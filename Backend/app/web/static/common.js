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
  const when = new Date(iso);
  const s = Math.max(0, Math.round((Date.now() - when.getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  const time = when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (when.toDateString() === new Date().toDateString()) return time;
  if (when.toDateString() === new Date(Date.now() - 86400000).toDateString()) return `Yesterday, ${time}`;
  return `${when.toLocaleDateString([], { day: "numeric", month: "short" })}, ${time}`;
}

const ICONS = {
  bell: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10.3 21a2 2 0 0 0 3.4 0"/></svg>',
  soundOn: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/></svg>',
  soundOff: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/></svg>',
  camera: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  eye: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7"/><circle cx="12" cy="12" r="3"/></svg>',
  eyeOff: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7"/><circle cx="12" cy="12" r="3"/><path d="m3 3 18 18"/></svg>',
  check: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
};

// A friendly question box. Resolves to the typed text ("" if nothing was typed), to true
// when there's no text box, or to null if they backed out.
function ask({ title, text = "", input = false, placeholder = "", value = "", minLength = 0, ok = "OK", cancel = "Not now", danger = false }) {
  return new Promise((resolve) => {
    const box = document.createElement("dialog");
    box.className = "ask";
    box.innerHTML = `<form method="dialog">
      <h2>${esc(title)}</h2>${text ? `<p>${esc(text)}</p>` : ""}
      ${input ? `<textarea rows="2" maxlength="255" placeholder="${esc(placeholder)}" ${minLength ? `minlength="${minLength}" required` : ""}>${esc(value)}</textarea>` : ""}
      <div class="row"><button type="button" class="secondary" data-no>${esc(cancel)}</button>
      <button type="submit" class="${danger ? "danger" : ""}" value="yes">${esc(ok)}</button></div></form>`;
    document.body.appendChild(box);
    const field = $("textarea", box);
    let answer = null;
    $("[data-no]", box).onclick = () => box.close();
    $("form", box).onsubmit = () => { answer = field ? field.value.trim() : true; };
    box.addEventListener("close", () => { box.remove(); resolve(answer); });
    box.showModal();
  });
}

// ---------------------------------------------------------------- notification bell
// The saved list of what happened (the server keeps it, so nothing is missed while away).
// refresh() is called whenever a live event arrives and on each page poll.
class Bell {
  constructor(mount, session, { onOpen } = {}) {
    this.session = session;
    this.onOpen = onOpen;
    this.items = [];
    this.unread = null;  // null until the first load, so old alerts don't "ring" on opening
    this.baseTitle = document.title;
    mount.classList.add("bell");
    mount.innerHTML = `
      <button type="button" class="icon-btn" data-toggle aria-haspopup="true" aria-expanded="false" aria-label="Notifications">
        ${ICONS.bell}<span class="bell-badge hidden" data-badge></span>
      </button>
      <div class="bell-panel hidden" data-panel>
        <div class="bell-head"><span>Notifications</span><button type="button" class="quiet small" data-all>Mark all as read</button></div>
        <div class="bell-list" data-list></div>
      </div>`;
    this.root = mount;
    this.button = $("[data-toggle]", mount);
    this.panel = $("[data-panel]", mount);
    this.button.onclick = () => this.toggle();
    $("[data-all]", mount).onclick = () => this.markAll();
    document.addEventListener("click", (e) => { if (!mount.contains(e.target)) this.toggle(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") this.toggle(false); });
    this.refresh().catch(() => {});
  }

  toggle(open = this.panel.classList.contains("hidden")) {
    this.panel.classList.toggle("hidden", !open);
    this.button.setAttribute("aria-expanded", String(open));
    if (open) this.refresh().catch(() => {});
  }

  async refresh() {
    const data = await this.session.api("/notifications");
    const ring = this.unread !== null && data.unread > this.unread;
    this.items = data.items;
    this.unread = data.unread;
    this.paint();
    if (ring) {
      this.button.classList.remove("bell-ring");
      void this.button.offsetWidth;  // restart the little shake
      this.button.classList.add("bell-ring");
    }
  }

  paint() {
    const badge = $("[data-badge]", this.root);
    badge.textContent = this.unread > 99 ? "99+" : this.unread;
    badge.classList.toggle("hidden", !this.unread);
    this.button.setAttribute("aria-label", this.unread ? `Notifications, ${this.unread} unread` : "Notifications");
    document.title = this.unread ? `(${this.unread}) ${this.baseTitle}` : this.baseTitle;
    $("[data-all]", this.root).classList.toggle("hidden", !this.unread);
    const list = $("[data-list]", this.root);
    list.innerHTML = this.items.length ? this.items.map((n) => `
      <button type="button" class="bell-item ${n.read_at ? "" : "unread"}" data-id="${esc(n.id)}">
        <strong>${esc(n.title)}</strong><span>${esc(n.body)}</span><time>${esc(ago(n.created_at))}</time>
      </button>`).join("") : `<div class="empty"><strong>You're all caught up</strong>New alerts will show up here.</div>`;
    list.querySelectorAll("[data-id]").forEach((el) => { el.onclick = () => this.open(el.dataset.id); });
  }

  async open(id) {
    const item = this.items.find((n) => n.id === id);
    if (!item) return;
    this.toggle(false);
    if (!item.read_at) {
      item.read_at = new Date().toISOString();
      this.unread = Math.max(0, this.unread - 1);
      this.paint();
      this.session.api(`/notifications/${id}/read`, { method: "POST" }).catch(() => {});
    }
    this.onOpen?.(item);
  }

  async markAll() {
    this.items.forEach((n) => { n.read_at ||= new Date().toISOString(); });
    this.unread = 0;
    this.paint();
    await this.session.api("/notifications/read-all", { method: "POST" }).catch(() => {});
  }
}

// Scroll to the card for an order and flash it, so a bell tap lands somewhere useful.
function showOrder(orderNumber, missing) {
  const el = orderNumber && document.querySelector(`[data-order="${CSS.escape(orderNumber)}"]`);
  if (!el) { if (missing) toast(missing); return; }
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash");
  void el.offsetWidth;
  el.classList.add("flash");
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
// sound button in the header. The tones are generated, no audio files needed.
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
    return this.ctx.state !== "closed";
  },
  setEnabled(on) { try { localStorage.setItem("cmd.sound", on ? "on" : "off"); } catch {} },
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
// Browsers allow sound only after a tap, so the first tap anywhere switches it on (unless muted).
// A tap on the sound button is left to the button itself.
["touchstart", "pointerdown", "keydown", "click"].forEach((ev) =>
  document.addEventListener(ev, (e) => {
    if (e.target.closest?.("[data-sound]")) return;
    if (Sound.enabled) Sound.unlock();
    Sound.wake();
  }, { passive: true, capture: true }));

// The mute button. Muting is remembered on this device, through sign-outs and reloads.
function soundButton(container) {
  const btn = document.createElement("button");
  btn.className = "icon-btn";
  btn.type = "button";
  btn.dataset.sound = "";
  const paint = () => {
    const on = Sound.enabled;
    btn.innerHTML = on ? ICONS.soundOn : ICONS.soundOff;
    const label = !on ? "Alarm is muted. Tap to turn it back on."
      : Sound.ready() ? "Alarm is on. Tap to mute it." : "Tap anywhere to allow the alarm";
    btn.title = label;
    btn.setAttribute("aria-label", label);
    btn.setAttribute("aria-pressed", String(!on));
    btn.classList.toggle("off", !on);
  };
  btn.onclick = () => {
    const needsPermission = Sound.enabled && !Sound.ready();
    if (Sound.enabled && !needsPermission) {
      Sound.setEnabled(false);
      toast("Alarm muted. You'll still see alerts on screen.");
    } else {
      Sound.setEnabled(true);
      Sound.unlock();
      setTimeout(() => Sound.play("info"), 50);  // a short sound, so you know it works
      toast("Alarm is on.", "good");
    }
    paint();
  };
  paint();
  for (const ev of ["pointerup", "keyup"]) document.addEventListener(ev, () => setTimeout(paint, 100), { passive: true });
  container.appendChild(btn);
  return btn;
}

// Every password box gets an eye button to check what's been typed.
function addPasswordEyes() {
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    const wrap = document.createElement("div");
    wrap.className = "pw-wrap";
    input.replaceWith(wrap);
    wrap.appendChild(input);
    const eye = document.createElement("button");
    eye.type = "button";
    eye.className = "icon-btn pw-eye";
    const paint = () => {
      const shown = input.type === "text";
      eye.innerHTML = shown ? ICONS.eyeOff : ICONS.eye;
      eye.setAttribute("aria-label", shown ? "Hide password" : "Show password");
      eye.setAttribute("aria-pressed", String(shown));
    };
    eye.onclick = () => { input.type = input.type === "text" ? "password" : "text"; paint(); };
    // hidden again on sending, so browsers offer to save it as a password
    input.form?.addEventListener("submit", () => { input.type = "password"; paint(); });
    paint();
    wrap.appendChild(eye);
  });
}
addPasswordEyes();

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
