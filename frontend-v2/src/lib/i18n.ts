import { useEffect, useState } from "react";

export type Lang = "da" | "en";
export const LANG_KEY = "hch5-v2-lang";

export function currentLang(): Lang {
  return localStorage.getItem(LANG_KEY) === "en" ? "en" : "da";
}

/** Language chosen under Settings → Interface; follows saves live. */
export function useLang(): Lang {
  const [lang, setLang] = useState<Lang>(currentLang);
  useEffect(() => {
    const update = () => setLang(currentLang());
    window.addEventListener("hch5-ui-preferences", update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener("hch5-ui-preferences", update);
      window.removeEventListener("storage", update);
    };
  }, []);
  return lang;
}
