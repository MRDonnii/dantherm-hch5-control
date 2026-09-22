import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, RefreshCw, Rocket, ShieldCheck } from "lucide-react";
import { ApiError, postJson, requestJson } from "../lib/api";

type Channel = "stable" | "beta";

interface AuthStatus { csrf?: string | null; }
interface UpdateState {
  running?: boolean;
  channel?: Channel | null;
  started_at?: number | null;
  finished_at?: number | null;
  progress?: number;
  phase?: string;
  detail?: string;
  last_error?: string | null;
}
interface UpdateInfo {
  ok?: boolean;
  channel?: Channel;
  current_version?: string;
  current_build?: string;
  available_version?: string;
  available_build?: string | null;
  published_at?: string | null;
  update_available?: boolean;
  update?: UpdateState;
  message?: string;
  error?: string;
}

function shortBuild(value?: string | null) {
  if (!value || value === "unknown") return "—";
  return value.slice(0, 8);
}
function clamp(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : 0;
}
function phaseLabel(value?: string) {
  const labels: Record<string, string> = {
    idle: "Klar", starting: "Starter", checking: "Kontrollerer", preparing: "Forbereder", downloading: "Downloader",
    extracting: "Pakker ud", validating: "Validerer", installing: "Installerer", verifying: "Verificerer", complete: "Færdig", failed: "Fejlet",
  };
  return labels[value ?? ""] ?? value ?? "Klar";
}

export function UpdatesPage() {
  const [csrf, setCsrf] = useState("");
  const [channel, setChannel] = useState<Channel>("beta");
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Henter versionsstatus…");
  const mounted = useRef(true);

  useEffect(() => () => { mounted.current = false; }, []);

  const action = useCallback(async (actionName: string, target?: string) => {
    return postJson<UpdateInfo>("/api/admin/action", { action: actionName, target }, csrf);
  }, [csrf]);

  const refresh = useCallback(async (selected?: Channel) => {
    const wanted = selected ?? channel;
    setBusy(true);
    try {
      const auth = await requestJson<AuthStatus>("/api/auth/status", { timeoutMs: 3500 });
      const token = auth.csrf ?? "";
      if (mounted.current) setCsrf(token);
      const result = await postJson<UpdateInfo>("/api/admin/action", { action: "check_update", target: wanted }, token);
      if (!mounted.current) return;
      setInfo(result);
      if (result.channel) setChannel(result.channel);
      setMessage(result.update_available ? "En nyere build er klar." : "Denne kanal er opdateret.");
    } catch (error) {
      if (!mounted.current) return;
      setMessage(error instanceof ApiError ? error.message : "Kunne ikke hente versionsstatus");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, [channel]);

  useEffect(() => { void refresh("beta"); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function chooseChannel(next: Channel) {
    if (busy || next === channel) return;
    setBusy(true);
    setMessage(`Skifter til ${next === "beta" ? "Beta" : "Stable"}…`);
    try {
      await action("set_update_channel", next);
      setChannel(next);
      await refresh(next);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Kunne ikke gemme kanal");
      setBusy(false);
    }
  }

  async function installUpdate() {
    if (busy) return;
    setBusy(true);
    setMessage("Opdateringen er startet. Controlleren fortsætter, mens den nye build valideres…");
    setInfo(current => ({
      ...current,
      update: { ...current?.update, running: true, progress: 2, phase: "starting", detail: "Forbereder sikker opdatering…", last_error: null },
    }));
    try {
      await action("install_update", channel);
    } catch (error) {
      setBusy(false);
      setMessage(error instanceof ApiError ? error.message : "Kunne ikke starte opdateringen");
      return;
    }

    const started = Date.now();
    const timer = window.setInterval(async () => {
      if (!mounted.current) return window.clearInterval(timer);
      try {
        const auth = await requestJson<AuthStatus>("/api/auth/status", { timeoutMs: 2500 });
        const token = auth.csrf ?? csrf;
        const local = await postJson<UpdateInfo>("/api/admin/action", { action: "get_update_status" }, token);
        if (!mounted.current) return;
        setInfo(current => ({ ...current, ...local, update: local.update ?? current?.update }));
        if (local.update?.last_error) {
          window.clearInterval(timer);
          setBusy(false);
          setMessage(`Opdatering rullet tilbage: ${local.update.last_error}`);
          return;
        }
        if (!local.update?.running && clamp(local.update?.progress) >= 100) {
          window.clearInterval(timer);
          setMessage("Opdateringen er installeret. Kontrollerer den nye build…");
          window.setTimeout(async () => {
            try {
              const final = await postJson<UpdateInfo>("/api/admin/action", { action: "check_update", target: channel }, token);
              setInfo(final);
            } catch {}
            window.location.reload();
          }, 1200);
          return;
        }
      } catch {
        // Gateway/admin kan genstarte kortvarigt. Fortsæt polling.
      }
      if (Date.now() - started > 180_000) {
        window.clearInterval(timer);
        setBusy(false);
        setMessage("Opdateringen tager længere tid end forventet. Tryk Kontroller igen om lidt.");
      }
    }, 1200);
  }

  const progress = clamp(info?.update?.progress);
  const running = info?.update?.running === true;
  const detail = info?.update?.detail ?? (running ? "Installerer…" : message);

  return (
    <section className="page-view page-enter">
      <header className="page-hero">
        <div>
          <span className="eyebrow">OPDATERINGER</span>
          <h1>Software og kanal</h1>
          <p>Beta bruges som live udviklingskanal. Updateren validerer build, controller, auth og services før den accepterer en ny version.</p>
        </div>
        <span className={`status-chip${info?.update_available ? "" : " muted"}`}>
          {info?.update_available ? <RefreshCw size={14} /> : <CheckCircle2 size={14} />}
          {info?.update_available ? " Update klar" : " Opdateret"}
        </span>
      </header>

      <div className="overview-grid-v2">
        <article className="surface control-card-v2">
          <div className="section-head compact">
            <div><span className="eyebrow">KANAL</span><h2>Stable eller Beta</h2></div>
            <ShieldCheck size={22} />
          </div>
          <div className="segmented-v2" role="group" aria-label="Opdateringskanal">
            <button type="button" className={channel === "stable" ? "active" : ""} onClick={() => void chooseChannel("stable")} disabled={busy}>Stable</button>
            <button type="button" className={channel === "beta" ? "active" : ""} onClick={() => void chooseChannel("beta")} disabled={busy}>Beta</button>
          </div>
          <div className="control-summary">
            <span>Installeret</span>
            <strong>{info?.current_version ?? "—"}</strong>
            <small>Build {shortBuild(info?.current_build)}</small>
          </div>
          <div className="control-summary">
            <span>Tilgængelig</span>
            <strong>{info?.available_version ?? "—"}</strong>
            <small>Build {shortBuild(info?.available_build)}</small>
          </div>
        </article>

        <aside className="control-column">
          <article className="surface quick-card">
            <div className="quick-icon green"><Rocket size={20}/></div>
            <div><span>Status</span><strong>{message}</strong></div>
            <button type="button" onClick={() => void refresh()} disabled={busy}>Kontroller</button>
          </article>
          <article className="surface control-card-v2">
            <div className="section-head compact"><div><span className="eyebrow">FAILSAFE</span><h2>Installer næste build</h2></div></div>
            <p>Den valgte kanal gemmes på Pi’en. Ved fejl ruller updateren applikationsfilerne tilbage og holder controlleren i sikker drift.</p>
            <div className="update-progress-panel" aria-live="polite">
              <div className="update-progress-meta"><strong>{detail}</strong><span>{Math.round(progress)}%</span></div>
              <div className="update-progress-track"><i style={{ width: `${progress}%` }}/></div>
              <div className="update-stage">{phaseLabel(info?.update?.phase)}</div>
            </div>
            {info?.update?.last_error && <div className="control-notice error">{info.update.last_error}</div>}
            <button type="button" className="primary-action" onClick={() => void installUpdate()} disabled={busy || running || !info?.update_available}>
              {running ? "Installerer…" : busy ? "Arbejder…" : info?.update_available ? "Opdater nu" : "Ingen update"}
            </button>
          </article>
        </aside>
      </div>
    </section>
  );
}
