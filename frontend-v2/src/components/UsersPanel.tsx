import { useCallback, useEffect, useState } from "react";
import { Mail, Pencil, Trash2, UserPlus } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import type { Lang } from "../lib/i18n";
import { ROLE_NAMES, useSession, type Role } from "../lib/session";

export interface UserRow {
  username: string;
  role: Role;
  email: string;
  disabled: boolean;
  expires_at: number | null;
  expired: boolean;
  created_at?: number | null;
  last_login?: number | null;
}

type Draft = { username: string; role: Role; email: string; password: string; confirm: string; expires: string; disabled: boolean };
const EMPTY: Draft = { username: "", role: "user", email: "", password: "", confirm: "", expires: "", disabled: false };

/** "2026-10-31" → end of that local day in epoch seconds. */
export function dateToEpoch(value: string): number | null {
  if (!value) return null;
  const time = new Date(`${value}T23:59:59`).getTime();
  return Number.isFinite(time) ? Math.floor(time / 1000) : null;
}
export function epochToDate(value: number | null | undefined): string {
  if (!value) return "";
  const d = new Date(value * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const ROLE_HELP: Record<Role, { da: string; en: string }> = {
  admin: { da: "Alt – også brugere, mail og om login er slået til.", en: "Everything – including users, mail and whether login is required." },
  technician: { da: "Alt teknisk: avancerede indstillinger, følere, diagnostik, sniffer, opdateringer, genstart og mail. Ikke brugere.", en: "Everything technical: advanced settings, sensors, diagnostics, sniffer, updates, restart and mail. Not users." },
  user: { da: "Daglig brug: tilstand, trin, boost, bypass, frikøling, pejs og eftervarme. Kan se historik.", en: "Daily use: mode, level, boost, bypass, free cooling, fireplace and afterheat. Can see history." },
};

export function UsersPanel({ lang }: { lang: Lang }) {
  const tr = (da: string, en: string) => lang === "da" ? da : en;
  const { auth } = useSession();
  const csrf = auth.csrf ?? undefined;
  const [users, setUsers] = useState<UserRow[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState<Draft>(EMPTY);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setUsers((await requestJson<{ users: UserRow[] }>("/api/users")).users ?? []); }
    catch (error) { setNotice(`${tr("Kunne ikke hente brugere", "Could not load users")}: ${error instanceof Error ? error.message : "?"}`); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const run = async (action: () => Promise<{ users?: UserRow[] } | unknown>, success: string) => {
    setBusy(true); setNotice("");
    try {
      const result = await action() as { users?: UserRow[] };
      if (result && Array.isArray(result.users)) setUsers(result.users);
      setNotice(success);
      return true;
    } catch (error) {
      setNotice(`${tr("Fejl", "Error")}: ${error instanceof Error ? error.message : "?"}`);
      return false;
    } finally { setBusy(false); }
  };

  const create = async () => {
    if (draft.password !== draft.confirm) { setNotice(tr("Adgangskoderne er ikke ens.", "The passwords do not match.")); return; }
    const ok = await run(() => postJson("/api/users/create", {
      username: draft.username.trim(), password: draft.password, role: draft.role, email: draft.email.trim(),
      expires_at: dateToEpoch(draft.expires),
    }, csrf), tr(`Brugeren ${draft.username.trim()} er oprettet.`, `User ${draft.username.trim()} was created.`));
    if (ok) setDraft(EMPTY);
  };
  const startEdit = (user: UserRow) => {
    setEditing(user.username);
    setEdit({ username: user.username, role: user.role, email: user.email, password: "", confirm: "", expires: epochToDate(user.expires_at), disabled: user.disabled });
  };
  const saveEdit = async () => {
    if (edit.password !== edit.confirm) { setNotice(tr("Adgangskoderne er ikke ens.", "The passwords do not match.")); return; }
    const ok = await run(() => postJson("/api/users/update", {
      username: edit.username, role: edit.role, email: edit.email.trim(), disabled: edit.disabled,
      expires_at: dateToEpoch(edit.expires), ...(edit.password ? { password: edit.password } : {}),
    }, csrf), tr("Ændringerne er gemt.", "The changes have been saved."));
    if (ok) setEditing(null);
  };
  const remove = async (user: UserRow) => {
    if (!window.confirm(tr(`Slet brugeren ${user.username}? Brugeren logges ud med det samme.`, `Delete user ${user.username}? They are signed out immediately.`))) return;
    await run(() => postJson("/api/users/delete", { username: user.username }, csrf), tr("Brugeren er slettet.", "The user has been deleted."));
  };
  const sendReset = async (user: UserRow) => {
    await run(() => postJson("/api/users/send-reset", { username: user.username }, csrf),
      tr(`Link til ny adgangskode er sendt til ${user.email}.`, `A new-password link was sent to ${user.email}.`));
  };

  const status = (user: UserRow) => {
    if (user.disabled) return tr("Deaktiveret", "Disabled");
    if (user.expired) return tr("Udløbet", "Expired");
    if (user.expires_at) return `${tr("Til", "Until")} ${new Date(user.expires_at * 1000).toLocaleDateString(lang === "da" ? "da-DK" : "en-GB")}`;
    return tr("Aktiv", "Active");
  };
  const when = (value?: number | null) => value ? new Date(value * 1000).toLocaleString(lang === "da" ? "da-DK" : "en-GB", { dateStyle: "short", timeStyle: "short" }) : "—";
  const roleSelect = (value: Role, onChange: (role: Role) => void, disabled = false) =>
    <select value={value} disabled={disabled} onChange={e => onChange(e.target.value as Role)}>
      {(["user", "technician", "admin"] as Role[]).map(role => <option key={role} value={role}>{ROLE_NAMES[role][lang]}</option>)}
    </select>;
  const self = (user: UserRow) => user.username.toLowerCase() === (auth.username ?? "").toLowerCase();

  return <div className="users-panel">
    <div className="role-cards">
      {(["admin", "technician", "user"] as Role[]).map(role => <div key={role}><strong>{ROLE_NAMES[role][lang]}</strong><span>{ROLE_HELP[role][lang]}</span></div>)}
    </div>

    <div className="settings-table-wrap">
      <table className="settings-table users-table">
        <thead><tr><th>{tr("Brugernavn", "Username")}</th><th>{tr("Rolle", "Role")}</th><th>{tr("E-mail", "E-mail")}</th><th>Status</th><th>{tr("Sidste login", "Last sign-in")}</th><th/></tr></thead>
        <tbody>{users.map(user => editing === user.username
          ? <tr key={user.username} className="is-editing"><td colSpan={6}>
            <div className="settings-grid">
              <label>{tr("Rolle", "Role")}{roleSelect(edit.role, role => setEdit(v => ({ ...v, role })), self(user))}</label>
              <label>{tr("E-mail", "E-mail")}<input type="email" value={edit.email} onChange={e => setEdit(v => ({ ...v, email: e.target.value }))}/></label>
              <label>{tr("Adgang udløber", "Access expires")}<input type="date" value={edit.expires} onChange={e => setEdit(v => ({ ...v, expires: e.target.value }))}/><small className="settings-field-help">{tr("Tom = ingen udløb.", "Empty = never expires.")}</small></label>
              <label className="check-row"><input type="checkbox" checked={edit.disabled} disabled={self(user)} onChange={e => setEdit(v => ({ ...v, disabled: e.target.checked }))}/> {tr("Deaktiveret", "Disabled")}</label>
              <label>{tr("Ny adgangskode", "New password")}<input type="password" autoComplete="new-password" value={edit.password} placeholder={tr("Uændret", "Unchanged")} onChange={e => setEdit(v => ({ ...v, password: e.target.value }))}/></label>
              <label>{tr("Gentag ny adgangskode", "Repeat new password")}<input type="password" autoComplete="new-password" value={edit.confirm} onChange={e => setEdit(v => ({ ...v, confirm: e.target.value }))}/></label>
            </div>
            <div className="diag-actions"><button className="primary-action" type="button" disabled={busy} onClick={() => void saveEdit()}>{tr("Gem", "Save")}</button><button className="secondary-action" type="button" onClick={() => setEditing(null)}>{tr("Annuller", "Cancel")}</button></div>
          </td></tr>
          : <tr key={user.username} className={user.disabled || user.expired ? "is-inactive" : undefined}>
            <td><strong>{user.username}</strong>{self(user) && <small className="users-self"> ({tr("dig", "you")})</small>}</td>
            <td>{ROLE_NAMES[user.role]?.[lang] ?? user.role}</td>
            <td>{user.email || "—"}</td>
            <td>{status(user)}</td>
            <td>{when(user.last_login)}</td>
            <td className="users-actions">
              <button className="icon-button" type="button" title={tr("Rediger", "Edit")} aria-label={tr("Rediger", "Edit")} onClick={() => startEdit(user)}><Pencil size={14}/></button>
              {user.email && <button className="icon-button" type="button" disabled={busy} title={tr("Send link til ny adgangskode", "Send new-password link")} aria-label={tr("Send link til ny adgangskode", "Send new-password link")} onClick={() => void sendReset(user)}><Mail size={14}/></button>}
              {!self(user) && <button className="icon-button" type="button" disabled={busy} title={tr("Slet", "Delete")} aria-label={tr("Slet", "Delete")} onClick={() => void remove(user)}><Trash2 size={14}/></button>}
            </td>
          </tr>)}</tbody>
      </table>
    </div>

    <h3 className="settings-subhead"><UserPlus size={15}/>{tr("Opret bruger", "Create user")}</h3>
    <div className="settings-grid">
      <label>{tr("Brugernavn", "Username")}<input value={draft.username} autoComplete="off" onChange={e => setDraft(v => ({ ...v, username: e.target.value }))}/></label>
      <label>{tr("Rolle", "Role")}{roleSelect(draft.role, role => setDraft(v => ({ ...v, role })))}</label>
      <label>{tr("E-mail (valgfri)", "E-mail (optional)")}<input type="email" value={draft.email} onChange={e => setDraft(v => ({ ...v, email: e.target.value }))}/><small className="settings-field-help">{tr("Giver mulighed for at nulstille adgangskoden via mail.", "Allows resetting the password by mail.")}</small></label>
      <label>{tr("Adgang udløber (valgfri)", "Access expires (optional)")}<input type="date" value={draft.expires} onChange={e => setDraft(v => ({ ...v, expires: e.target.value }))}/><small className="settings-field-help">{tr("Praktisk til en tekniker, der kun skal have adgang under et servicebesøg.", "Handy for a technician who only needs access during a service visit.")}</small></label>
      <label>{tr("Adgangskode", "Password")}<input type="password" autoComplete="new-password" minLength={10} value={draft.password} onChange={e => setDraft(v => ({ ...v, password: e.target.value }))}/><small className="settings-field-help">{tr("Mindst 10 tegn.", "At least 10 characters.")}</small></label>
      <label>{tr("Gentag adgangskode", "Repeat password")}<input type="password" autoComplete="new-password" value={draft.confirm} onChange={e => setDraft(v => ({ ...v, confirm: e.target.value }))}/></label>
    </div>
    <div className="diag-actions"><button className="primary-action" type="button" disabled={busy || !draft.username.trim() || draft.password.length < 10} onClick={() => void create()}><UserPlus size={15}/>{tr("Opret bruger", "Create user")}</button>{notice && <span className="settings-inline-notice" role="status">{notice}</span>}</div>
  </div>;
}
