import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { postJson } from "../lib/api";
import type { Lang } from "../lib/i18n";
import { ROLE_NAMES, useSession } from "../lib/session";

/** The signed-in user's own account: e-mail, username, password and (admins) the login switch. */
export function AccountPanel({ lang }: { lang: Lang }) {
  const tr = (da: string, en: string) => lang === "da" ? da : en;
  const { auth, can, refresh } = useSession();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loginRequired, setLoginRequired] = useState(true);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setUsername(auth.username ?? "");
    setEmail(auth.email ?? "");
    setLoginRequired(auth.enabled !== false);
  }, [auth.username, auth.email, auth.enabled]);

  const save = async () => {
    if (password && password !== confirm) { setNotice(tr("De nye adgangskoder er ikke ens.", "The new passwords do not match.")); return; }
    if (!current) { setNotice(tr("Skriv din nuværende adgangskode for at gemme.", "Enter your current password to save.")); return; }
    setBusy(true); setNotice("");
    const renamed = username.trim() !== (auth.username ?? "");
    try {
      await postJson("/api/auth/settings", {
        current_password: current, username: username.trim(), password, email,
        ...(can("login_switch") ? { enabled: loginRequired } : {}),
      }, auth.csrf ?? undefined);
      setCurrent(""); setPassword(""); setConfirm("");
      if ((password || renamed) && auth.enabled !== false) {
        setNotice(tr("Gemt. Log ind igen med de nye oplysninger.", "Saved. Sign in again with the new details."));
        window.setTimeout(() => { window.location.href = "/login"; }, 1500);
        return;
      }
      setNotice(tr("Din konto er gemt.", "Your account has been saved."));
      await refresh();
    } catch (error) {
      setNotice(`${tr("Fejl", "Error")}: ${error instanceof Error ? error.message : "?"}`);
    } finally { setBusy(false); }
  };

  return <div className="account-panel">
    <div className="settings-summary">
      <span>{tr("Bruger", "User")}<strong>{auth.username ?? "—"}</strong></span>
      <span>{tr("Rolle", "Role")}<strong>{auth.role ? ROLE_NAMES[auth.role][lang] : "—"}</strong></span>
      <span>Login<strong>{auth.enabled === false ? tr("Deaktiveret", "Disabled") : tr("Aktiveret", "Enabled")}</strong></span>
      <span>{tr("Glemt adgangskode via mail", "Forgotten password by mail")}<strong>{auth.password_reset_available ? tr("Klar", "Ready") : tr("Ikke sat op", "Not set up")}</strong></span>
    </div>
    <h3 className="settings-subhead"><KeyRound size={15}/>{tr("Min konto", "My account")}</h3>
    <div className="settings-grid">
      <label>{tr("Brugernavn", "Username")}<input value={username} autoComplete="username" onChange={e => setUsername(e.target.value)}/></label>
      <label>{tr("E-mail", "E-mail")}<input type="email" value={email} autoComplete="email" onChange={e => setEmail(e.target.value)} placeholder="navn@eksempel.dk"/><small className="settings-field-help">{tr("Bruges til at sende et link, hvis du glemmer adgangskoden.", "Used to send a link if you forget your password.")}</small></label>
      <label>{tr("Ny adgangskode", "New password")}<input type="password" value={password} autoComplete="new-password" minLength={10} onChange={e => setPassword(e.target.value)} placeholder={tr("Uændret", "Unchanged")}/></label>
      <label>{tr("Gentag ny adgangskode", "Repeat new password")}<input type="password" value={confirm} autoComplete="new-password" onChange={e => setConfirm(e.target.value)}/></label>
      {can("login_switch") && <label className="check-row"><input type="checkbox" checked={loginRequired} onChange={e => setLoginRequired(e.target.checked)}/> {tr("Kræv login for at bruge WebUI", "Require login to use the WebUI")}</label>}
      {can("login_switch") && !loginRequired && <p className="settings-warning">{tr("Uden login har alle på netværket fuld administratoradgang.", "Without login everyone on the network has full administrator access.")}</p>}
      <label>{tr("Nuværende adgangskode", "Current password")}<input type="password" value={current} autoComplete="current-password" onChange={e => setCurrent(e.target.value)}/></label>
    </div>
    <div className="diag-actions"><button className="primary-action" type="button" disabled={busy} onClick={() => void save()}>{busy ? tr("Gemmer…", "Saving…") : tr("Gem min konto", "Save my account")}</button>{notice && <span className="settings-inline-notice" role="status">{notice}</span>}</div>
  </div>;
}
