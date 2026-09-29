export type HaLinkState = "online" | "offline" | "bad_token" | "waiting" | "never";

export interface HaLink {
  state: HaLinkState | null;
  required: boolean;
  age: number | null;
  rejectedAt: number | null;
  rejectedIp: string | null;
}

export function readHaLink(data: Record<string, unknown>): HaLink {
  const state = data.ha_link_state;
  return {
    state: state === "online" || state === "offline" || state === "bad_token" || state === "waiting" || state === "never" ? state : null,
    required: data.ha_link_required === true,
    age: typeof data.ha_link_age_seconds === "number" ? data.ha_link_age_seconds : null,
    rejectedAt: typeof data.ha_link_rejected_at === "number" ? data.ha_link_rejected_at : null,
    rejectedIp: typeof data.ha_link_rejected_ip === "string" ? data.ha_link_rejected_ip : null,
  };
}

export function ago(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} sek siden`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min siden`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} timer siden` : `${Math.round(hours / 24)} dage siden`;
}

/** Short label, longer explanation and tone for the Home Assistant connection. */
export function haLinkText(link: HaLink): { label: string; detail: string; tone: "ok" | "warn" | "bad" | "muted" } {
  switch (link.state) {
    case "online": return { label: "Forbundet", detail: `Seneste kontakt ${ago(link.age)}`, tone: "ok" };
    case "bad_token": return { label: "Forkert API-nøgle", detail: `Home Assistant${link.rejectedIp ? ` (${link.rejectedIp})` : ""} bruger en nøgle, der ikke længere gælder. Kopiér den nye nøgle ind i integrationen.`, tone: "bad" };
    case "offline": return { label: "Ingen kontakt", detail: `Seneste kontakt ${ago(link.age)}${link.required ? ". Smart Auto kører på anlæggets egne følere." : "."}`, tone: link.required ? "bad" : "warn" };
    case "waiting": return { label: "Afventer", detail: "Controlleren er lige startet og venter på Home Assistant.", tone: "muted" };
    case "never": return { label: "Ikke forbundet", detail: link.required ? "Home Assistant har ikke kontaktet controlleren. Smart Auto kører på anlæggets egne følere." : "Home Assistant har ikke kontaktet controlleren siden start.", tone: link.required ? "bad" : "muted" };
    default: return { label: "Ukendt", detail: "", tone: "muted" };
  }
}
