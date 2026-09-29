"""Optional e-mail service: SMTP settings, alarm mails and password reset mails.

Settings live in a 0600 JSON file next to the login store. The SMTP password
is never returned to the browser. Sending runs in a background thread so a
slow or unreachable mail server never blocks the WebUI or the controller.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import threading
import time
from collections import deque
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from webui_auth import EMAIL_RE

LOG = logging.getLogger("hch5-mail")

SECURITY_MODES = ("starttls", "ssl", "none")
SEVERITIES = ("info", "warning", "critical")
DEFAULTS = {
    "enabled": False,
    "host": "",
    "port": 587,
    "security": "starttls",
    "username": "",
    "password": "",
    "from_address": "",
    "from_name": "HCH5 Control",
    "recipients": [],
    "alerts_enabled": True,
    "alert_min_severity": "warning",
    "alert_resolved": True,
    "alert_repeat_hours": 24,
    "password_reset_enabled": True,
    "base_url": "",
}
# Extra alarm raised by the mail monitor itself (the diagnostics engine does
# not treat an HCP4 takeover as an alarm because it is a normal safety path).
HCP4_ALARM = {"code": "hcp4_master", "severity": "warning",
              "text": "HCP4-panelet har overtaget styringen; Pi'ens skrivninger er sat på pause"}
HCP4_DELAY = 120


class MailError(Exception):
    pass


def _clean_address(value: object) -> str:
    value = str(value or "").strip()
    if value and (len(value) > 254 or not EMAIL_RE.match(value)):
        raise ValueError(f"Ugyldig e-mailadresse: {value}")
    return value


class MailService:
    def __init__(self, path="/var/lib/dantherm-hch5-ha/webui-mail.json", *, smtp_factory=None):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.log: deque[dict] = deque(maxlen=30)
        self._smtp_factory = smtp_factory

    # ------------------------------------------------------------- settings
    def load(self) -> dict:
        data = dict(DEFAULTS)
        try:
            stored = json.loads(self.path.read_text())
            if isinstance(stored, dict):
                data.update({key: stored[key] for key in DEFAULTS if key in stored})
        except (OSError, ValueError):
            pass
        return data

    def public(self) -> dict:
        data = self.load()
        data["password_set"] = bool(data.pop("password"))
        data["configured"] = self.configured(data)
        data["log"] = list(self.log)
        return data

    @staticmethod
    def configured(data: dict | None = None) -> bool:
        return bool(data and data.get("enabled") and data.get("host") and data.get("from_address"))

    def ready(self) -> bool:
        return self.configured(self.load())

    def update(self, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise ValueError("Ugyldige mailindstillinger")
        with self.lock:
            data = self.load()
            for key in ("enabled", "alerts_enabled", "alert_resolved", "password_reset_enabled"):
                if key in patch:
                    data[key] = patch[key] is True
            if "host" in patch:
                host = str(patch["host"] or "").strip()
                if len(host) > 253 or any(ch.isspace() for ch in host):
                    raise ValueError("Ugyldig SMTP-server")
                data["host"] = host
            if "port" in patch:
                try:
                    port = int(patch["port"])
                except (TypeError, ValueError) as error:
                    raise ValueError("Ugyldig port") from error
                if not 1 <= port <= 65535:
                    raise ValueError("Ugyldig port")
                data["port"] = port
            if "security" in patch:
                if patch["security"] not in SECURITY_MODES:
                    raise ValueError("Ukendt krypteringstype")
                data["security"] = patch["security"]
            if "username" in patch:
                data["username"] = str(patch["username"] or "").strip()[:254]
            if patch.get("clear_password") is True:
                data["password"] = ""
            elif patch.get("password"):
                data["password"] = str(patch["password"])[:512]
            if "from_address" in patch:
                data["from_address"] = _clean_address(patch["from_address"])
            if "from_name" in patch:
                data["from_name"] = str(patch["from_name"] or "").replace("\r", " ").replace("\n", " ").strip()[:80]
            if "recipients" in patch:
                raw = patch["recipients"]
                items = raw if isinstance(raw, list) else str(raw or "").replace(";", ",").replace("\n", ",").split(",")
                recipients = []
                for item in items:
                    address = _clean_address(item)
                    if address and address.lower() not in (r.lower() for r in recipients):
                        recipients.append(address)
                if len(recipients) > 20:
                    raise ValueError("Højst 20 modtagere")
                data["recipients"] = recipients
            if "alert_min_severity" in patch:
                if patch["alert_min_severity"] not in SEVERITIES:
                    raise ValueError("Ukendt alvorlighed")
                data["alert_min_severity"] = patch["alert_min_severity"]
            if "alert_repeat_hours" in patch:
                try:
                    hours = int(patch["alert_repeat_hours"])
                except (TypeError, ValueError) as error:
                    raise ValueError("Ugyldigt gentagelsesinterval") from error
                data["alert_repeat_hours"] = max(0, min(hours, 24 * 14))
            if "base_url" in patch:
                url = str(patch["base_url"] or "").strip().rstrip("/")
                if url and not (url.startswith("http://") or url.startswith("https://")) or any(ch.isspace() for ch in url):
                    raise ValueError("Adressen skal starte med http:// eller https://")
                data["base_url"] = url[:200]
            if data["enabled"] and (not data["host"] or not data["from_address"]):
                raise ValueError("Udfyld SMTP-server og afsenderadresse for at slå mail til")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)
        return self.public()

    # --------------------------------------------------------------- sending
    def _record(self, kind: str, subject: str, recipients: list[str], ok: bool, error: str | None = None) -> None:
        self.log.appendleft({"time": time.time(), "kind": kind, "subject": subject,
                             "recipients": len(recipients), "ok": ok, "error": error})

    def _connect(self, data: dict):
        if self._smtp_factory:
            return self._smtp_factory(data)
        context = ssl.create_default_context()
        if data["security"] == "ssl":
            client = smtplib.SMTP_SSL(data["host"], int(data["port"]), timeout=15, context=context)
        else:
            client = smtplib.SMTP(data["host"], int(data["port"]), timeout=15)
            client.ehlo()
            if data["security"] == "starttls":
                client.starttls(context=context)
                client.ehlo()
        if data.get("username"):
            client.login(data["username"], data.get("password", ""))
        return client

    def send_now(self, recipients: list[str], subject: str, body: str, *, kind: str = "mail") -> None:
        data = self.load()
        if not self.configured(data):
            raise MailError("Mailservicen er ikke sat op")
        recipients = [r for r in recipients if r]
        if not recipients:
            raise MailError("Ingen modtagere")
        message = EmailMessage()
        message["From"] = formataddr((data.get("from_name") or "HCH5 Control", data["from_address"]))
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=data["from_address"].rsplit("@", 1)[-1])
        message.set_content(body)
        try:
            client = self._connect(data)
            try:
                client.send_message(message)
            finally:
                try:
                    client.quit()
                except Exception:
                    pass
        except (OSError, smtplib.SMTPException) as error:
            text = str(error) or error.__class__.__name__
            self._record(kind, subject, recipients, False, text[:200])
            LOG.warning("Mail '%s' could not be sent: %s", subject, text)
            raise MailError(f"Mail kunne ikke sendes: {text}") from error
        self._record(kind, subject, recipients, True)

    def send_async(self, recipients: list[str], subject: str, body: str, *, kind: str = "mail") -> None:
        def worker():
            try:
                self.send_now(recipients, subject, body, kind=kind)
            except MailError:
                pass
        threading.Thread(target=worker, name="hch5-mail", daemon=True).start()

    def send_test(self, recipients: list[str] | None = None) -> None:
        targets = recipients or self.load().get("recipients") or []
        self.send_now(targets, "HCH5 Control: testmail",
                      "Dette er en testmail fra HCH5 Control.\n\n"
                      "Mailservicen virker, og alarmer samt links til nulstilling af adgangskode kan sendes.\n",
                      kind="test")

    def send_password_reset(self, email: str, username: str, link: str) -> None:
        body = (
            f"Hej {username}\n\n"
            "Der er bedt om at nulstille adgangskoden til HCH5 Control.\n"
            f"Åbn linket inden for 30 minutter for at vælge en ny adgangskode:\n\n{link}\n\n"
            "Har du ikke bedt om det, kan du se bort fra denne mail. Din adgangskode er uændret.\n"
        )
        self.send_async([email], "HCH5 Control: nulstil adgangskode", body, kind="reset")


class AlarmMailer:
    """Watches the controller snapshot and mails new and resolved alarms."""

    def __init__(self, mail: MailService, snapshot, *, interval: float = 30.0, site_name: str = "HCH5"):
        self.mail = mail
        self.snapshot = snapshot
        self.interval = interval
        self.site_name = site_name
        self.sent: dict[str, float] = {}
        self.known: dict[str, dict] = {}
        self.hcp4_since: float | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def current_alarms(self, state: dict, now: float) -> dict[str, dict]:
        alarms = {a["code"]: a for a in state.get("diagnostics_alarms") or [] if isinstance(a, dict) and a.get("code")}
        if state.get("hardware_control_state") == "paused_hcp4_master":
            self.hcp4_since = self.hcp4_since or now
            if now - self.hcp4_since >= HCP4_DELAY:
                alarms[HCP4_ALARM["code"]] = dict(HCP4_ALARM, since=int(self.hcp4_since))
        else:
            self.hcp4_since = None
        return alarms

    def check(self, now: float | None = None) -> list[tuple[str, dict]]:
        """Return and mail the (event, alarm) pairs that should notify now."""
        now = time.time() if now is None else now
        settings = self.mail.load()
        try:
            state = self.snapshot() or {}
        except Exception:  # the monitor must never take anything down
            LOG.exception("Alarm monitor could not read controller state")
            return []
        alarms = self.current_alarms(state, now)
        if not (settings.get("alerts_enabled", True) and self.mail.configured(settings) and settings.get("recipients")):
            # Nothing is delivered; start fresh once mail is switched on.
            self.known, self.sent = alarms, {}
            return []
        threshold = SEVERITIES.index(settings.get("alert_min_severity", "warning"))
        repeat = float(settings.get("alert_repeat_hours") or 0) * 3600
        events: list[tuple[str, dict]] = []
        for code, alarm in alarms.items():
            severity = alarm.get("severity")
            if severity not in SEVERITIES or SEVERITIES.index(severity) < threshold:
                continue
            last = self.sent.get(code)
            if last is None or (repeat and now - last >= repeat):
                events.append(("raised" if code not in self.known else "reminder", alarm))
                self.sent[code] = now
        for code, alarm in list(self.known.items()):
            if code not in alarms:
                if code in self.sent and settings.get("alert_resolved", True):
                    events.append(("resolved", alarm))
                self.sent.pop(code, None)
        self.known = alarms
        if events:
            self.mail.send_async(list(settings["recipients"]), self._subject(events), self._body(events, state), kind="alarm")
        return events

    def _subject(self, events):
        raised = [a for kind, a in events if kind != "resolved"]
        if raised:
            worst = max(raised, key=lambda a: SEVERITIES.index(a.get("severity", "info")))
            label = {"critical": "KRITISK", "warning": "Advarsel", "info": "Info"}.get(worst.get("severity"), "Alarm")
            return f"{self.site_name}: {label} – {worst.get('text', worst.get('code'))}"[:180]
        return f"{self.site_name}: alarm løst"

    def _body(self, events, state):
        lines = [f"HCH5 Control på {state.get('system_hostname') or 'Raspberry Pi'} melder:", ""]
        titles = {"raised": "NY ALARM", "reminder": "STADIG AKTIV", "resolved": "LØST"}
        for kind, alarm in events:
            since = alarm.get("since")
            when = time.strftime("%d-%m-%Y %H:%M", time.localtime(since)) if since else "—"
            lines.append(f"[{titles[kind]}] {alarm.get('text', alarm.get('code'))}")
            lines.append(f"    kode: {alarm.get('code')} · alvor: {alarm.get('severity', '—')} · siden: {when}")
        lines += ["", f"Aktiv styring: {state.get('hardware_control_state') or '—'}",
                  f"Tilstand: {state.get('mode') or '—'}", "",
                  "Mailen er sendt automatisk. Indstillingerne findes under Indstillinger → Mail."]
        base = self.mail.load().get("base_url")
        if base:
            lines.append(f"{base}/#/diagnostics")
        return "\n".join(lines) + "\n"

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()

        def run():
            while not self.stop_event.wait(self.interval):
                self.check()

        self.thread = threading.Thread(target=run, name="hch5-alarm-mail", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
