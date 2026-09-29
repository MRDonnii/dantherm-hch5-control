import { useCallback, useEffect, useState } from "react";
import { Copy, Eye, EyeOff, KeyRound, RefreshCw } from "lucide-react";
import { postJson, requestJson } from "../lib/api";
import { useSession } from "../lib/session";

interface Integration {
  configured: boolean;
  source: "webui" | "installer" | "none";
  hint: string | null;
  created_at: number | null;
  created_by: string | null;
  port: number;
  address: string | null;
}

async function copyText(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(value); return true; }
  } catch { /* fall back below */ }
  // Plain http on the local network is not a secure context; use a hidden text field.
  const area = document.createElement("textarea");
  area.value = value; area.setAttribute("readonly", ""); area.style.position = "fixed"; area.style.opacity = "0";
  document.body.appendChild(area); area.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  document.body.removeChild(area);
  return ok;
}

/** Address and API token Home Assistant needs for the controller API. */
export function IntegrationTokenCard() {
  const { auth } = useSession();
  const [info, setInfo] = useState<Integration | null>(null);
  const [token, setToken] = useState("");
  const [shown, setShown] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setInfo(await requestJson<Integration>("/api/integration")); }
    catch (error) { setNotice(`Kunne ikke hente API-oplysninger: ${error instanceof Error ? error.message : "?"}`); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const csrf = auth.csrf ?? undefined;
  const reveal = async () => {
    if (shown) { setShown(false); return; }
    setBusy(true);
    try { const result = await postJson<{ token: string }>("/api/integration/token/reveal", {}, csrf); setToken(result.token); setShown(true); }
    catch (error) { setNotice(`Fejl: ${error instanceof Error ? error.message : "?"}`); }
    finally { setBusy(false); }
  };
  const generate = async () => {
    if (!window.confirm("Generér en ny API-nøgle?\n\nDen gamle nøgle holder op med at virke med det samme, så Home Assistant-integrationen skal have den nye nøgle, før den kan styre anlægget igen.")) return;
    setBusy(true);
    try {
      const result = await postJson<Integration & { token: string }>("/api/integration/token/generate", {}, csrf);
      setToken(result.token); setShown(true); setInfo(i => i ? { ...i, ...result } : i);
      setNotice("Ny nøgle genereret. Kopiér den ind i Home Assistant-integrationen.");
    } catch (error) { setNotice(`Fejl: ${error instanceof Error ? error.message : "?"}`); }
    finally { setBusy(false); }
  };
  const copy = async (value: string, what: string) => setNotice(await copyText(value) ? `${what} er kopieret.` : `Kunne ikke kopiere. Markér ${what.toLowerCase()} og kopiér selv.`);

  const here = `${window.location.protocol}//${window.location.hostname}:${info?.port ?? window.location.port}`;
  const pi = info?.address ? `http://${info.address}:${info.port}` : null;
  const addresses = [...new Set([here, pi].filter(Boolean) as string[])];
  const source = info?.source === "webui"
    ? `Genereret i WebUI ${info.created_at ? new Date(info.created_at * 1000).toLocaleString("da-DK", { dateStyle: "short", timeStyle: "short" }) : ""}${info.created_by ? ` af ${info.created_by}` : ""}`
    : info?.source === "installer" ? "Fra installationen (gateway.env)" : "Ingen nøgle endnu";

  return <article className="surface panel-card panel-span-2 integration-card">
    <div className="pro-card-head compact"><div><h2>Forbindelse fra Home Assistant</h2><p>Det Home Assistant-integrationen skal bruge for at styre anlægget</p></div><KeyRound size={20}/></div>
    <div className="integration-fields">
      <div className="integration-field">
        <span>Controllerens adresse</span>
        {addresses.map(address => <div key={address} className="integration-value"><code>{address}</code><button type="button" className="icon-button" aria-label={`Kopiér ${address}`} title="Kopiér" onClick={() => void copy(address, "Adressen")}><Copy size={15}/></button></div>)}
        <small>Port {info?.port ?? "—"} bruges til styring. Rå data fra bussen ligger på port 4196.</small>
      </div>
      <div className="integration-field">
        <span>API-nøgle</span>
        <div className="integration-value">
          <code className={shown ? "" : "masked"}>{shown && token ? token : info?.configured ? `•••••••••••••••••••• ${info.hint ?? ""}` : "Ingen nøgle"}</code>
          {info?.configured && <button type="button" className="icon-button" disabled={busy} aria-label={shown ? "Skjul nøglen" : "Vis nøglen"} title={shown ? "Skjul" : "Vis"} onClick={() => void reveal()}>{shown ? <EyeOff size={15}/> : <Eye size={15}/>}</button>}
          {shown && token && <button type="button" className="icon-button" aria-label="Kopiér nøglen" title="Kopiér" onClick={() => void copy(token, "Nøglen")}><Copy size={15}/></button>}
        </div>
        <small>{source}</small>
      </div>
    </div>
    <div className="diag-actions">
      <button type="button" className="secondary-action" disabled={busy} onClick={() => void generate()}><RefreshCw size={14}/>{info?.configured ? "Generér ny nøgle" : "Generér nøgle"}</button>
      {notice && <span className="settings-inline-notice" role="status">{notice}</span>}
    </div>
    <p className="settings-help">I Home Assistant: indtast adressen og API-nøglen i HCH5-integrationens indstillinger. Nøglen giver fuld styring af anlægget, så del den kun med Home Assistant. Genererer du en ny, holder den gamle op med at virke med det samme.</p>
  </article>;
}
