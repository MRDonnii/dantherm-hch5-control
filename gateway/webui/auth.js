"use strict";
const $ = s => document.querySelector(s);
const params = new URLSearchParams(location.search);
const token = params.get("token") || "";
let mode = { "/setup": "setup", "/forgot": "forgot", "/reset": "reset" }[location.pathname] || "login";

function show(id, visible) { const el = $(id); el.hidden = !visible; el.querySelectorAll("input").forEach(input => { input.disabled = !visible; }); }
function message(text, ok = false) { $("#message").textContent = text; $("#message").classList.toggle("ok", ok); }

function render(resetAvailable) {
  show("#username-row", mode !== "reset");
  show("#password-row", mode !== "forgot");
  show("#confirm-row", mode === "setup" || mode === "reset");
  show("#remember-row", mode === "login" || mode === "setup");
  $("#forgot-link").hidden = !(mode === "login" && resetAvailable);
  $("#login-link").hidden = mode === "login" || mode === "setup";
  $("#password").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("#username").minLength = mode === "forgot" ? 1 : 3;
  if (mode === "setup") {
    $("#auth-title").textContent = "Opret første bruger";
    $("#auth-intro").textContent = "Opret administratoren af HCH5 Control. Adgangskoden gemmes kun som et saltet hash på Raspberry Pi. Flere brugere og teknikere kan oprettes bagefter under Indstillinger → Brugere.";
    $("#submit").textContent = "Opret administrator";
  } else if (mode === "forgot") {
    $("#auth-title").textContent = "Glemt adgangskode";
    $("#auth-intro").textContent = "Skriv dit brugernavn eller din e-mailadresse. Har brugeren en e-mail tilknyttet, sendes et link til at vælge en ny adgangskode.";
    $("#username-label").textContent = "Brugernavn eller e-mail";
    $("#username").autocomplete = "username email";
    $("#submit").textContent = "Send link";
  } else if (mode === "reset") {
    $("#auth-title").textContent = "Vælg ny adgangskode";
    $("#auth-intro").textContent = "Linket gælder i 30 minutter og kan kun bruges én gang.";
    $("#password-label").textContent = "Ny adgangskode";
    $("#submit").textContent = "Gem ny adgangskode";
  }
}

async function responseJson(response) { try { return await response.json(); } catch (_error) { return {}; } }
function networkMessage() { return "Kunne ikke kontakte HCH5 Control. Kontroller gateway-service."; }

async function status() {
  try {
    const r = await fetch("/api/auth/status");
    const s = await responseJson(r);
    if (!r.ok) throw Error(s.error || "Kunne ikke hente login-status");
    if (!s.configured) mode = "setup";
    else if (mode === "setup") mode = "login";
    if (s.authenticated && mode !== "reset") { location.replace("/"); return; }
    render(s.password_reset_available === true);
    if (mode === "reset") {
      const check = await responseJson(await fetch(`/api/auth/reset/check?token=${encodeURIComponent(token)}`));
      if (!check.valid) { message("Linket er udløbet eller allerede brugt. Bed om et nyt."); $("#submit").disabled = true; }
    }
  } catch (error) {
    console.error("HCH5 Control auth status failed", error);
    message(error instanceof TypeError ? networkMessage() : error.message);
  }
}

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const p = await responseJson(r);
  if (!r.ok) throw Error(p.error || `Handlingen mislykkedes (HTTP ${r.status})`);
  return p;
}

render(false);
$("#auth-form").addEventListener("submit", async e => {
  e.preventDefault();
  const username = $("#username").value.trim(), password = $("#password").value, remember = $("#remember")?.checked === true;
  if ((mode === "setup" || mode === "reset") && password !== $("#confirm").value) { message("Adgangskoderne er ikke ens"); return; }
  $("#submit").disabled = true;
  try {
    if (mode === "forgot") {
      await post("/api/auth/forgot", { identifier: username });
      message("Hvis brugeren findes og har en e-mailadresse, er der nu sendt et link. Tjek også spam-mappen.", true);
      return;
    }
    if (mode === "reset") {
      await post("/api/auth/reset", { token, password });
      message("Adgangskoden er skiftet. Du kan nu logge ind.", true);
      setTimeout(() => location.replace("/login"), 1800);
      return;
    }
    await post(mode === "setup" ? "/api/auth/setup" : "/api/auth/login", { username, password, remember });
    location.replace("/");
  } catch (error) {
    console.error("HCH5 Control authentication failed", error);
    message(error instanceof TypeError ? networkMessage() : error.message);
    $("#submit").disabled = false;
  }
});
status();
