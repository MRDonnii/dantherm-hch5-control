import { useCallback, useEffect, useState } from "react";
import { Send } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import type { Lang } from "../lib/i18n";
import { useSession } from "../lib/session";

export interface MailSettings {
  enabled: boolean;
  host: string;
  port: number;
  security: "starttls" | "ssl" | "none";
  username: string;
  password_set: boolean;
  from_address: string;
  from_name: string;
  recipients: string[];
  alerts_enabled: boolean;
  alert_min_severity: "info" | "warning" | "critical";
  alert_resolved: boolean;
  alert_repeat_hours: number;
  password_reset_enabled: boolean;
  base_url: string;
  configured: boolean;
  log: { time: number; kind: string; subject: string; recipients: number; ok: boolean; error?: string | null }[];
}

/** Common providers. Values are the providers' public SMTP submission settings. */
const PRESETS: Record<string, { host: string; port: number; security: MailSettings["security"] }> = {
  gmail: { host: "smtp.gmail.com", port: 587, security: "starttls" },
  outlook: { host: "smtp-mail.outlook.com", port: 587, security: "starttls" },
  office365: { host: "smtp.office365.com", port: 587, security: "starttls" },
  icloud: { host: "smtp.mail.me.com", port: 587, security: "starttls" },
  one: { host: "send.one.com", port: 465, security: "ssl" },
};

export function MailPanel({ lang }: { lang: Lang }) {
  const tr = (da: string, en: string) => lang === "da" ? da : en;
  const { auth, refresh } = useSession();
  const csrf = auth.csrf ?? undefined;
  const [mail, setMail] = useState<MailSettings | null>(null);
  const [form, setForm] = useState<Partial<MailSettings>>({});
  const [recipients, setRecipients] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const apply = (next: MailSettings) => { setMail(next); setForm(next); setRecipients((next.recipients ?? []).join(", ")); };
  const load = useCallback(async () => {
    try { apply(await requestJson<MailSettings>("/api/mail")); }
    catch (error) { setNotice(`${tr("Kunne ikke hente mailindstillinger", "Could not load mail settings")}: ${error instanceof Error ? error.message : "?"}`); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const set = <K extends keyof MailSettings>(key: K, value: MailSettings[K]) => setForm(v => ({ ...v, [key]: value }));
  const save = async () => {
    setBusy(true); setNotice("");
    try {
      const next = await postJson<MailSettings>("/api/mail/settings", {
        enabled: form.enabled === true, host: form.host ?? "", port: Number(form.port) || 587, security: form.security ?? "starttls",
        username: form.username ?? "", ...(password ? { password } : {}), from_address: form.from_address ?? "", from_name: form.from_name ?? "",
        recipients, alerts_enabled: form.alerts_enabled === true, alert_min_severity: form.alert_min_severity ?? "warning",
        alert_resolved: form.alert_resolved === true, alert_repeat_hours: Number(form.alert_repeat_hours) || 0,
        password_reset_enabled: form.password_reset_enabled === true, base_url: form.base_url ?? "",
      }, csrf);
      apply(next); setPassword(""); setNotice(tr("Mailindstillinger gemt.", "Mail settings saved.")); await refresh();
    } catch (error) {
      setNotice(`${tr("Fejl", "Error")}: ${error instanceof Error ? error.message : "?"}`);
    } finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setNotice(tr("Sender testmail…", "Sending test mail…"));
    try {
      const result = await postJson<{ mail: MailSettings }>("/api/mail/test", {}, csrf);
      setMail(result.mail); setNotice(tr("Testmail sendt. Tjek indbakken (og spam).", "Test mail sent. Check the inbox (and spam)."));
    } catch (error) {
      setNotice(`${tr("Fejl", "Error")}: ${error instanceof Error ? error.message : "?"}`);
      void load();
    } finally { setBusy(false); }
  };

  if (!mail) return <p className="settings-help">{notice || tr("Henter…", "Loading…")}</p>;
  return <div className="mail-panel">
    <div className="settings-summary">
      <span>{tr("Mailservice", "Mail service")}<strong>{mail.configured ? tr("Aktiv", "Active") : tr("Ikke sat op", "Not set up")}</strong></span>
      <span>{tr("Alarmmails", "Alarm mails")}<strong>{mail.configured && mail.alerts_enabled && mail.recipients.length ? `${mail.recipients.length} ${tr("modtager(e)", "recipient(s)")}` : tr("Fra", "Off")}</strong></span>
      <span>{tr("Glemt adgangskode", "Forgotten password")}<strong>{mail.configured && mail.password_reset_enabled ? tr("Via mail", "By mail") : tr("Fra", "Off")}</strong></span>
    </div>

    <h3 className="settings-subhead">{tr("SMTP-server", "SMTP server")}</h3>
    <div className="settings-grid">
      <label className="check-row"><input type="checkbox" checked={form.enabled === true} onChange={e => set("enabled", e.target.checked)}/> {tr("Slå mailservicen til", "Enable the mail service")}</label>
      <label>{tr("Udbyder (udfylder server og port)", "Provider (fills in server and port)")}<select value="" onChange={e => { const p = PRESETS[e.target.value]; if (p) setForm(v => ({ ...v, ...p })); }}>
        <option value="">{tr("Vælg…", "Choose…")}</option><option value="gmail">Gmail</option><option value="outlook">Outlook.com / Hotmail</option><option value="office365">Microsoft 365</option><option value="icloud">iCloud</option><option value="one">one.com</option>
      </select></label>
      <label>{tr("SMTP-server", "SMTP server")}<input value={form.host ?? ""} placeholder="smtp.eksempel.dk" onChange={e => set("host", e.target.value)}/></label>
      <label>Port<input type="number" min="1" max="65535" value={form.port ?? 587} onChange={e => set("port", Number(e.target.value))}/></label>
      <label>{tr("Kryptering", "Encryption")}<select value={form.security ?? "starttls"} onChange={e => set("security", e.target.value as MailSettings["security"])}>
        <option value="starttls">STARTTLS (587)</option><option value="ssl">SSL/TLS (465)</option><option value="none">{tr("Ingen (kun lokalt relæ)", "None (local relay only)")}</option>
      </select></label>
      <label>{tr("Brugernavn", "Username")}<input value={form.username ?? ""} autoComplete="off" onChange={e => set("username", e.target.value)}/></label>
      <label>{tr("Adgangskode", "Password")}<input type="password" autoComplete="new-password" value={password} placeholder={mail.password_set ? tr("Gemt – skriv for at ændre", "Stored – type to change") : ""} onChange={e => setPassword(e.target.value)}/><small className="settings-field-help">{tr("Gmail, Outlook og iCloud kræver en app-adgangskode, når totrinsbekræftelse er slået til.", "Gmail, Outlook and iCloud need an app password when two-step verification is on.")}</small></label>
      <label>{tr("Afsenderadresse", "From address")}<input type="email" value={form.from_address ?? ""} placeholder="hch5@eksempel.dk" onChange={e => set("from_address", e.target.value)}/></label>
      <label>{tr("Afsendernavn", "From name")}<input value={form.from_name ?? ""} onChange={e => set("from_name", e.target.value)}/></label>
    </div>

    <h3 className="settings-subhead">{tr("Fejlmeddelelser", "Fault notifications")}</h3>
    <div className="settings-grid">
      <label className="check-row"><input type="checkbox" checked={form.alerts_enabled === true} onChange={e => set("alerts_enabled", e.target.checked)}/> {tr("Send mail ved alarmer", "Send mail on alarms")}</label>
      <label>{tr("Modtagere", "Recipients")}<input value={recipients} placeholder="ejer@eksempel.dk, service@firma.dk" onChange={e => setRecipients(e.target.value)}/><small className="settings-field-help">{tr("Adskil med komma. F.eks. husets ejer og serviceteknikeren.", "Separate with commas. E.g. the home owner and the service technician.")}</small></label>
      <label>{tr("Send ved", "Send for")}<select value={form.alert_min_severity ?? "warning"} onChange={e => set("alert_min_severity", e.target.value as MailSettings["alert_min_severity"])}>
        <option value="critical">{tr("Kun kritiske fejl (fx ingen forbindelse til anlægget)", "Critical faults only (e.g. no connection to the unit)")}</option>
        <option value="warning">{tr("Advarsler og kritiske fejl", "Warnings and critical faults")}</option>
        <option value="info">{tr("Alt, også information (fx filter)", "Everything, including information (e.g. filter)")}</option>
      </select></label>
      <label>{tr("Gentag hvis stadig aktiv", "Repeat while still active")}<input type="number" min="0" max="336" value={form.alert_repeat_hours ?? 24} onChange={e => set("alert_repeat_hours", Number(e.target.value))}/><span>{tr("timer", "hours")}</span><small className="settings-field-help">{tr("0 = kun én mail pr. alarm.", "0 = only one mail per alarm.")}</small></label>
      <label className="check-row"><input type="checkbox" checked={form.alert_resolved === true} onChange={e => set("alert_resolved", e.target.checked)}/> {tr("Send også mail, når en alarm er løst", "Also mail when an alarm clears")}</label>
      <p className="settings-help">{tr("Alarmerne er de samme som på Diagnostik-siden: ingen RS485-forbindelse, frostrisiko, lav genvinding, bypass der ikke lukker, eftervarme uden effekt, manglende 1-Wire-føler og tilstoppet filter – samt når HCP4-panelet overtager styringen.", "The alarms are the same as on the Diagnostics page: no RS485 connection, frost risk, low recovery, bypass not closing, afterheat without effect, missing 1-Wire sensor and clogged filter – and when the HCP4 panel takes over control.")}</p>
    </div>

    <h3 className="settings-subhead">{tr("Nulstilling af adgangskode", "Password reset")}</h3>
    <div className="settings-grid">
      <label className="check-row"><input type="checkbox" checked={form.password_reset_enabled === true} onChange={e => set("password_reset_enabled", e.target.checked)}/> {tr("Vis \"Glemt adgangskode?\" på login-siden", "Show \"Forgot password?\" on the sign-in page")}</label>
      <label>{tr("WebUI-adresse i links", "WebUI address in links")}<input value={form.base_url ?? ""} placeholder="http://192.168.1.50:8080" onChange={e => set("base_url", e.target.value)}/><small className="settings-field-help">{tr("Tom = Pi'ens egen IP-adresse. Brugere skal have en e-mail på deres konto.", "Empty = the Pi's own IP address. Users need an e-mail on their account.")}</small></label>
    </div>

    <div className="diag-actions">
      <button className="primary-action" type="button" disabled={busy} onClick={() => void save()}>{busy ? tr("Gemmer…", "Saving…") : tr("Gem mailindstillinger", "Save mail settings")}</button>
      <button className="secondary-action" type="button" disabled={busy || !mail.configured || !mail.recipients.length} onClick={() => void test()}><Send size={14}/>{tr("Send testmail", "Send test mail")}</button>
      {notice && <span className="settings-inline-notice" role="status">{notice}</span>}
    </div>

    {mail.log.length > 0 && <>
      <h3 className="settings-subhead">{tr("Seneste mails", "Recent mails")}</h3>
      <div className="settings-table-wrap"><table className="settings-table">
        <thead><tr><th>{tr("Tid", "Time")}</th><th>{tr("Type", "Type")}</th><th>{tr("Emne", "Subject")}</th><th>Status</th></tr></thead>
        <tbody>{mail.log.map((entry, index) => <tr key={index}>
          <td>{new Date(entry.time * 1000).toLocaleString(lang === "da" ? "da-DK" : "en-GB", { dateStyle: "short", timeStyle: "short" })}</td>
          <td>{({ alarm: tr("Alarm", "Alarm"), test: "Test", reset: tr("Nulstilling", "Reset") } as Record<string, string>)[entry.kind] ?? entry.kind}</td>
          <td>{entry.subject}</td>
          <td className={entry.ok ? "mail-ok" : "mail-failed"} title={entry.error ?? undefined}>{entry.ok ? tr("Sendt", "Sent") : `${tr("Fejlede", "Failed")}: ${entry.error ?? ""}`}</td>
        </tr>)}</tbody>
      </table></div>
    </>}
  </div>;
}
