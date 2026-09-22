"use strict";
(() => {
  const params = new URLSearchParams(location.search);
  const embeddedTechnique = location.pathname.startsWith("/controller") && params.get("embedded") === "1";
  if (embeddedTechnique) document.documentElement.classList.add("embedded-technique");

  let pref = "system";
  try { pref = localStorage.getItem("hch5-theme-preference") || "system"; } catch (e) {}
  const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const resolved = pref === "dark" ? "dark" : pref === "light" ? "light" : systemDark ? "dark" : "light";
  document.documentElement.dataset.theme = resolved;
  try {
    if (localStorage.getItem("hch5-sidebar-collapsed") === "1") document.documentElement.classList.add("sidebar-collapsed");
  } catch (e) {}
  document.documentElement.classList.add("ui-prepaint");

  const style = document.createElement("style");
  style.textContent = `
    html.embedded-technique .topbar,
    html.embedded-technique .tabs { display:none !important; }
    html.embedded-technique body { min-height:100vh; background:var(--page-bg, transparent); }
    html.embedded-technique main,
    html.embedded-technique .controller-main {
      margin:0 !important;
      width:100% !important;
      max-width:none !important;
      padding:24px !important;
      min-height:100vh;
    }
    #technique-bridge.page { padding:0 !important; overflow:hidden; }
    #technique-bridge .technique-frame {
      display:block;
      width:100%;
      min-height:calc(100vh - 104px);
      height:calc(100vh - 104px);
      border:0;
      background:transparent;
    }
    body.sidebar-collapsed #technique-bridge .technique-frame { min-height:calc(100vh - 104px); }
    @media (max-width: 900px) {
      #technique-bridge .technique-frame { min-height:calc(100vh - 76px); height:calc(100vh - 76px); }
      html.embedded-technique main,
      html.embedded-technique .controller-main { padding:14px !important; }
    }
  `;
  document.head.append(style);

  // Keep the high-level visual layer independent from the legacy dashboard code.
  // It can therefore evolve quickly without changing controller semantics.
  const studioScript = document.createElement("script");
  studioScript.src = "/assets/studio.js";
  studioScript.async = false;
  document.head.append(studioScript);

  function navTabFromUrl(url) {
    if (url.pathname === "/controller" || url.pathname === "/controller.html") return "technique";
    if (url.pathname !== "/" && url.pathname !== "/index.html") return null;
    return url.searchParams.get("tab") || "overview";
  }

  function techniqueLink() {
    return document.querySelector('.tabs a[href="/controller"], .tabs a[href="/controller.html"]');
  }

  function ensureTechniqueBridge() {
    let host = document.getElementById("technique-bridge");
    if (host) return host;
    const main = document.querySelector("main");
    if (!main) return null;
    host = document.createElement("section");
    host.id = "technique-bridge";
    host.className = "page";
    host.setAttribute("aria-label", "Teknik");
    const frame = document.createElement("iframe");
    frame.className = "technique-frame";
    frame.title = "HCH5 Control · Teknik";
    frame.src = "/controller?embedded=1";
    frame.setAttribute("loading", "eager");
    host.append(frame);
    main.append(host);
    return host;
  }

  function setTechniqueNavActive(active) {
    const link = techniqueLink();
    if (link) {
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    if (active) document.querySelectorAll(".tabs button[data-tab]").forEach(button => button.classList.remove("active"));
  }

  function showTechnique() {
    const host = ensureTechniqueBridge();
    if (!host) return false;
    document.querySelectorAll("main > .page").forEach(page => page.classList.toggle("active", page === host));
    setTechniqueNavActive(true);
    return true;
  }

  function showDashboardTab(tab) {
    const host = document.getElementById("technique-bridge");
    if (host) host.classList.remove("active");
    setTechniqueNavActive(false);
    const button = document.querySelector(`.tabs button[data-tab="${CSS.escape(tab || "overview")}"]`)
      || document.querySelector('.tabs button[data-tab="overview"]');
    if (button) button.click();
    history.replaceState(null, "", "/");
  }

  addEventListener("message", event => {
    if (event.origin !== location.origin || !event.data || event.data.type !== "hch5-navigation") return;
    if (event.data.tab === "technique") showTechnique();
    else showDashboardTab(String(event.data.tab || "overview"));
  });

  addEventListener("DOMContentLoaded", () => {
    document.body.classList.toggle("sidebar-collapsed", document.documentElement.classList.contains("sidebar-collapsed"));

    if (embeddedTechnique) {
      document.addEventListener("click", event => {
        const anchor = event.target.closest?.("a[href]");
        if (!anchor) return;
        const url = new URL(anchor.href, location.href);
        if (url.origin !== location.origin) return;
        const tab = navTabFromUrl(url);
        if (!tab) return;
        event.preventDefault();
        parent.postMessage({ type: "hch5-navigation", tab }, location.origin);
      }, true);
      requestAnimationFrame(() => document.documentElement.classList.remove("ui-prepaint"));
      return;
    }

    document.addEventListener("click", event => {
      const anchor = event.target.closest?.("a[href]");
      if (anchor) {
        const url = new URL(anchor.href, location.href);
        if (url.origin === location.origin && (url.pathname === "/controller" || url.pathname === "/controller.html")) {
          event.preventDefault();
          showTechnique();
          history.replaceState(null, "", "/");
          return;
        }
      }
      const tabButton = event.target.closest?.(".tabs button[data-tab]");
      if (tabButton) setTechniqueNavActive(false);
    }, true);

    const requested = params.get("tab");
    if (location.pathname === "/" && (requested === "technique" || requested === "controller")) {
      showTechnique();
      history.replaceState(null, "", "/");
    } else if (location.pathname === "/" && requested) {
      // Keep one-shot deep links, but normal refreshes still begin on Overview.
      queueMicrotask(() => history.replaceState(null, "", "/"));
    }

    // Warm Technique in the background so the first click is instant and does
    // not replace the live dashboard document or briefly show disconnected.
    setTimeout(() => ensureTechniqueBridge(), 700);
    requestAnimationFrame(() => document.documentElement.classList.remove("ui-prepaint"));
  }, { once: true });
})();
