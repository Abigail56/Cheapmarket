// Shared by the rider app, the tracking page and the admin dashboard. No build step, no framework.
"use strict";

const API = "/api/v1";

// Anything that came from a user (names, addresses, notes) goes through esc() before innerHTML.
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function $(sel, root = document) { return root.querySelector(sel); }

function naira(amount) {
  return amount == null ? "" : "₦" + Number(amount).toLocaleString("en-NG", { maximumFractionDigits: 2 });
}

function ago(iso) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

let toastTimer;
function toast(message, kind = "info") {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), kind === "error" ? 6000 : 3500);
}

// ---------------------------------------------------------------- auth + fetch
// Tokens live in localStorage under one key per app, so the rider and admin can be
// logged in on the same device without clashing.
class Session {
  constructor(key) { this.key = key; }
  get tokens() {
    try { return JSON.parse(localStorage.getItem(this.key)) || null; } catch { return null; }
  }
  set tokens(value) {
    try {
      if (value) localStorage.setItem(this.key, JSON.stringify(value));
      else localStorage.removeItem(this.key);
    } catch { /* private mode: stays logged in for this page only */ }
    this._memory = value;
  }
  get access() { return (this.tokens || this._memory || {}).access_token; }

  async login(email, password) {
    const r = await fetch(`${API}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errorText(body, "Could not log in"));
    this.tokens = body;
  }

  async refresh() {
    const t = this.tokens || this._memory;
    if (!t?.refresh_token) return false;
    const r = await fetch(`${API}/auth/refresh`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: t.refresh_token }),
    });
    if (!r.ok) { this.tokens = null; return false; }
    this.tokens = await r.json();
    return true;
  }

  logout() { this.tokens = null; }

  // sign in with a Google ID token; create=false only signs existing accounts in
  async google(idToken, create) {
    const r = await fetch(`${API}/auth/google`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_token: idToken, create_account: create }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(errorText(body, "Google sign-in failed")); e.code = body?.error?.code; throw e; }
    this.tokens = body;
    return body.user;
  }

  // fetch with the access token; on 401 refresh once and retry
  async api(path, { method = "GET", json, form, retry = true } = {}) {
    const headers = {};
    if (this.access) headers.Authorization = `Bearer ${this.access}`;
    let body;
    if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
    if (form) body = form;
    const r = await fetch(API + path, { method, headers, body });
    if (r.status === 401 && retry && await this.refresh()) {
      return this.api(path, { method, json, form, retry: false });
    }
    if (r.status === 204) return null;
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(errorText(data, `Request failed (${r.status})`));
      err.status = r.status;
      err.code = data?.error?.code;
      throw err;
    }
    return data;
  }
}

function errorText(body, fallback) {
  if (body?.error?.message) return body.error.message;
  if (Array.isArray(body?.detail)) return body.detail.map((d) => d.msg).join("; ");
  return body?.detail || fallback;
}

// ---------------------------------------------------------------- Google sign-in
// Renders Google's own "Continue with Google" button into `el` (nothing if the server has
// no Google client ID). `onToken(idToken)` gets Google's signed ID token, which the server
// verifies itself.
let googleConfig;
async function googleButton(el, onToken, { text = "continue_with" } = {}) {
  googleConfig ??= fetch(`${API}/auth/config`).then((r) => r.json()).catch(() => ({}));
  const { google_client_id: clientId } = await googleConfig;
  if (!clientId) return false;
  if (!window.google?.accounts?.id) {
    await new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client";
      s.async = true;
      s.onload = ok;
      s.onerror = () => fail(new Error("Could not load Google sign-in"));
      document.head.appendChild(s);
    });
  }
  google.accounts.id.initialize({
    client_id: clientId,
    callback: (resp) => onToken(resp.credential),
    ux_mode: "popup",
    use_fedcm_for_prompt: true,
  });
  el.classList.remove("hidden");
  google.accounts.id.renderButton(el, {
    theme: "outline", size: "large", shape: "pill", text, width: Math.min(el.clientWidth || 320, 400),
  });
  return true;
}

// ---------------------------------------------------------------- live events
// Server-sent events read with fetch (not EventSource) so the Authorization header
// can be sent instead of putting the token in the URL. Reconnects on its own.
// The line only counts as "live" once data actually flows: some networks and tunnels
// accept the connection but hold the stream back. A watchdog drops a line that goes
// silent (the server sends a heartbeat every 15 s), and pages poll fast until it's live.
function liveEvents(path, onEvent, { session, onState } = {}) {
  let stopped = false, lastId = null, delay = 1000, ctrl = null;
  const SILENCE_MS = 40000;
  async function run() {
    while (!stopped) {
      ctrl = new AbortController();
      let watchdog = setTimeout(() => ctrl.abort(), SILENCE_MS);
      const feed = () => { clearTimeout(watchdog); watchdog = setTimeout(() => ctrl.abort(), SILENCE_MS); };
      try {
        onState?.("connecting");
        const headers = { Accept: "text/event-stream" };
        if (session?.access) headers.Authorization = `Bearer ${session.access}`;
        if (lastId) headers["Last-Event-ID"] = lastId;
        const r = await fetch(API + path, { headers, signal: ctrl.signal, cache: "no-store" });
        if (r.status === 401 && session && await session.refresh()) { clearTimeout(watchdog); continue; }
        if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "", flowing = false;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          feed();
          if (!flowing) { flowing = true; delay = 1000; onState?.("live"); }
          buffer += decoder.decode(value, { stream: true });
          let cut;
          while ((cut = buffer.indexOf("\n\n")) >= 0) {
            const block = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);
            const msg = { event: "message", data: "" };
            for (const line of block.split("\n")) {
              if (line.startsWith("event: ")) msg.event = line.slice(7);
              else if (line.startsWith("data: ")) msg.data += line.slice(6);
              else if (line.startsWith("id: ")) lastId = line.slice(4);
            }
            if (msg.data) {
              try { onEvent(msg.event, JSON.parse(msg.data)); } catch (e) { console.error(e); }
            }
          }
        }
      } catch (e) {
        if (stopped) return;
      } finally {
        clearTimeout(watchdog);
      }
      onState?.("reconnecting");
      await new Promise((ok) => setTimeout(ok, delay));
      delay = Math.min(delay * 2, 15000);
    }
  }
  run();
  return () => { stopped = true; ctrl?.abort(); };
}

// Refresh on a timer: every 30 s while live events flow, every 5 s when they don't
// (so a blocked stream costs a few seconds, not half a minute).
function adaptivePoll(fn, isLive) {
  let timer;
  const loop = async () => {
    try { await fn(); } catch { /* next round */ }
    timer = setTimeout(loop, isLive() ? 30000 : 5000);
  };
  timer = setTimeout(loop, isLive() ? 30000 : 5000);
  return () => clearTimeout(timer);
}

// ---------------------------------------------------------------- sound
// Browsers only allow sound after the user has tapped something, so each page shows an
// "Enable sound" button once. The tones are generated, no audio files needed.
const Sound = {
  ctx: null,
  out: null,
  get enabled() { try { return localStorage.getItem("cmd.sound") !== "off"; } catch { return true; } },
  unlock() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      // compressor + make-up gain: as loud as the device volume allows, without crackling
      this.comp = this.ctx.createDynamicsCompressor();
      this.comp.threshold.value = -12; this.comp.knee.value = 0; this.comp.ratio.value = 20;
      this.comp.attack.value = 0.001; this.comp.release.value = 0.05;
      this.out = this.ctx.createGain();
      this.out.gain.value = 1.3;  // make-up gain: peaks just under full scale (no crackle)
      this.comp.connect(this.out).connect(this.ctx.destination);
    }
    this.wake();
    try { localStorage.setItem("cmd.sound", "on"); } catch {}
    return this.ctx.state !== "closed";
  },
  // Phones suspend web audio when the screen locks or the app is in the background.
  // Wake it whenever we're back on screen and before every alert, or alerts go silent.
  wake() {
    if (this.ctx && this.ctx.state !== "running" && this.ctx.state !== "closed") this.ctx.resume().catch(() => {});
  },
  ready() { return !!this.ctx && this.ctx.state !== "closed"; },

  // Siren: two slightly detuned sawtooth waves swept up and down, like an emergency siren.
  //   alert: long "wail" sweeps then a fast "yelp" (~3.5 s): new offer, declined, wrong code...
  //   good:  short fast yelp (~1 s): new order, delivered
  //   info:  one quick rising whoop
  SIRENS: {
    alert: [{ low: 650, high: 1550, period: 1.0, cycles: 2 }, { low: 750, high: 1650, period: 0.25, cycles: 6 }],
    good: [{ low: 900, high: 1750, period: 0.2, cycles: 5 }],
    info: [{ low: 800, high: 1600, period: 0.7, cycles: 0.5 }],
  },
  play(kind = "alert") {
    if (!this.ready() || !this.enabled) return;
    this.wake();
    const parts = this.SIRENS[kind] || this.SIRENS.alert;
    const start = this.ctx.currentTime + 0.03;
    const length = parts.reduce((t, p) => t + p.period * p.cycles, 0);
    const env = this.ctx.createGain();
    env.gain.setValueAtTime(0, start);
    env.gain.linearRampToValueAtTime(0.9, start + 0.02);
    env.gain.setValueAtTime(0.9, start + length - 0.06);
    env.gain.linearRampToValueAtTime(0, start + length);
    env.connect(this.comp);
    for (const detune of [-8, 8]) {
      const osc = this.ctx.createOscillator();
      osc.type = "sawtooth";
      osc.detune.value = detune;
      let t = start;
      osc.frequency.setValueAtTime(parts[0].low, t);
      for (const p of parts) {
        for (let c = 0; c < p.cycles; c += 0.5) {  // half a cycle = one sweep up or down
          const up = Math.round(c * 2) % 2 === 0;
          t += p.period / 2;
          osc.frequency.linearRampToValueAtTime(up ? p.high : p.low, t);
        }
      }
      osc.connect(env);
      osc.start(start);
      osc.stop(start + length + 0.02);
    }
    if (kind === "alert" && navigator.vibrate) navigator.vibrate([600, 150, 600, 150, 600, 150, 1200]);
  },
};

// back on screen (screen unlocked, app reopened): make sure sound still works
document.addEventListener("visibilitychange", () => { if (!document.hidden) Sound.wake(); });
["touchstart", "pointerdown", "keydown"].forEach((ev) =>
  document.addEventListener(ev, () => Sound.wake(), { passive: true, capture: true }));

function soundButton(container) {
  const btn = document.createElement("button");
  btn.className = "sound-btn";
  btn.type = "button";
  const paint = () => {
    btn.textContent = Sound.ready() ? "🔔 Test siren" : "🔕 Enable sound";
    btn.title = Sound.ready() ? "Sound alerts are on" : "Tap so new orders and alerts can make a sound";
    btn.classList.toggle("off", !Sound.ready());
  };
  btn.onclick = () => { Sound.unlock(); setTimeout(() => { paint(); Sound.play("alert"); }, 50); };
  paint();
  container.appendChild(btn);
  return btn;
}

// ---------------------------------------------------------------- maps
const MAP_TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const LAGOS = [6.5244, 3.3792];

function makeMap(el, center = LAGOS, zoom = 12) {
  const map = L.map(el, { zoomControl: true }).setView(center, zoom);
  L.tileLayer(MAP_TILES, { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
  return map;
}

function dot(color, label) {
  return L.divIcon({
    className: "map-dot",
    html: `<span style="background:${color}">${esc(label || "")}</span>`,
    iconSize: [28, 28], iconAnchor: [14, 14],
  });
}

function currentPosition(options = {}) {
  return new Promise((ok, fail) => {
    if (!navigator.geolocation) return fail(new Error("This device has no GPS / location support"));
    navigator.geolocation.getCurrentPosition(
      (p) => ok({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy }),
      (e) => fail(new Error(e.code === 1 ? "Allow location access to continue" : "Could not get your location; try again outside")),
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 5000, ...options });
  });
}
