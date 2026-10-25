// Rider app: offers -> accept -> confirm address -> start -> arrive -> code + photo -> done.
"use strict";

const session = new Session("cmd.rider");
let jobs = [];
let stopEvents = null, watchId = null, lastPing = 0, lastFix = null, ticker = null;
let liveState = "connecting", stopPoll = null;
const maps = {};          // job id -> { map, pin, me }
const pendingPin = {};    // job id -> [lat, lng] the rider has dragged the pin to
const photos = {};        // job id -> Blob (downscaled)
const PING_EVERY_MS = 15000;

// ---------------------------------------------------------------- boot
soundButton($("#sound"));
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/rider/sw.js", { scope: "/rider/" });

let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("#install").classList.remove("hidden");
});
$("#install-btn").onclick = async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  $("#install").classList.add("hidden");
};

$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await session.login($("#email").value.trim(), $("#password").value);
    Sound.unlock();  // the sign-in tap counts as permission to play sounds
    await start();
  } catch (err) { toast(err.message, "error"); }  // includes "your application is being reviewed"
};

// "Continue with Google" on the sign-in screen: existing riders only (never creates an account)
googleButton($("#google-login"), async (idToken) => {
  try {
    await session.google(idToken, false);
    Sound.unlock();
    await start();
  } catch (err) {
    toast(err.code === "google_no_account"
      ? "No rider account uses this Google account yet. Tap “Apply to ride with us”."
      : err.message, "error");
  }
}).then((shown) => $("#or-login").classList.toggle("hidden", !shown));

// ---------------------------------------------------------------- apply to ride
function showOnly(id) {
  for (const s of ["#login", "#apply", "#applied"]) $(s).classList.toggle("hidden", s !== id);
}
let googleApplyToken = null;
$("#show-apply").onclick = (e) => {
  e.preventDefault();
  showOnly("#apply");
  // fill name + email from Google (Google has verified the email); no password needed
  googleButton($("#google-apply"), (idToken) => {
    const claims = JSON.parse(atob(idToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    googleApplyToken = idToken;
    if (!$("#a-name").value) $("#a-name").value = claims.name || "";
    $("#email-fields").classList.add("hidden");
    $("#a-email").required = $("#a-password").required = false;
    $("#google-apply").classList.add("hidden");
    $("#google-apply-done").textContent = `✔ Using your Google account ${claims.email}. Now add your phone, vehicle and ID.`;
    $("#google-apply-done").classList.remove("hidden");
  }, { text: "signup_with" });
};
$("#back-to-login").onclick = () => showOnly("#login");
$("#applied-back").onclick = () => showOnly("#login");
// ID photos: shrink + re-encode (which also strips the GPS location phones hide in
// photos); PDFs go as they are.
const idFiles = {};
for (const [input, preview, field] of [["#a-idfront", "#p-idfront", "id_front"],
                                       ["#a-idback", "#p-idback", "id_back"],
                                       ["#a-selfie", "#p-selfie", "selfie"]]) {
  $(input).onchange = async () => {
    const file = $(input).files[0];
    delete idFiles[field];
    $(preview).classList.add("hidden");
    if (!file) return;
    try {
      if (file.type === "application/pdf") { idFiles[field] = file; toast("PDF added"); return; }
      idFiles[field] = await shrink(file);
      $(preview).src = URL.createObjectURL(idFiles[field]);
      $(preview).classList.remove("hidden");
    } catch { toast("Could not read that photo, try again", "error"); }
  };
}

$("#apply-form").onsubmit = async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  if (!idFiles.id_front || !idFiles.selfie) { toast("Add a photo of your ID and of your face", "error"); return; }
  btn.disabled = true;
  const form = new FormData();
  const add = (k, id) => { const v = $(id).value.trim(); if (v) form.append(k, v); };
  add("full_name", "#a-name"); add("phone", "#a-phone");
  if (googleApplyToken) form.append("google_id_token", googleApplyToken);
  else { add("email", "#a-email"); form.append("password", $("#a-password").value); }
  add("vehicle_type", "#a-vehicle"); add("id_type", "#a-idtype"); add("id_number", "#a-idnumber");
  add("plate_number", "#a-plate"); add("area", "#a-area"); add("note", "#a-note");
  for (const [field, blob] of Object.entries(idFiles)) {
    form.append(field, blob, blob.type === "application/pdf" ? `${field}.pdf` : `${field}.jpg`);
  }
  try {
    toast("Sending… (photos can take a few seconds)");
    await session.api("/auth/rider-signup", { method: "POST", form });
    $("#email").value = $("#a-email").value.trim();
    $("#apply-form").reset();
    for (const k of Object.keys(idFiles)) delete idFiles[k];
    ["#p-idfront", "#p-idback", "#p-selfie"].forEach((id) => $(id).classList.add("hidden"));
    showOnly("#applied");
  } catch (err) { toast(err.message, "error"); } finally { btn.disabled = false; }
};
$("#logout").onclick = async () => {
  await unsubscribePush().catch(() => {});  // this phone stops getting this rider's alerts
  session.logout();
  location.reload();
};

async function start() {
  try {
    await load();
  } catch (err) {
    if (err.status === 401 || err.status === 403) {
      session.logout();
      showLogin(err.status === 403 ? "This account is not a rider account." : null);
      return;
    }
    toast(err.message, "error");
  }
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#logout").classList.remove("hidden");
  stopEvents?.();
  stopEvents = liveEvents("/rider/events", onEvent, {
    session, onState: (s) => { liveState = s; $("#live").classList.toggle("live", s === "live"); },
  });
  clearInterval(ticker);
  ticker = setInterval(tick, 1000);
  stopPoll?.();
  stopPoll = adaptivePoll(load, () => liveState === "live");  // safety net if live events can't get through
  setupPush().catch((e) => console.warn("push setup", e));
}

function showLogin(message) {
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  if (message) toast(message, "error");
}

if (session.access) start(); else showLogin();

// ---------------------------------------------------------------- live events
function onEvent(type, data) {
  if (type === "delivery.assigned") { Sound.play("alert"); toast(`New delivery ${data.order_number || ""}: accept within 5 minutes`); }
  else if (type === "delivery.address_corrected") { Sound.play("alert"); toast("The customer changed the address. Check and confirm it again."); }
  else if (type === "delivery.unassigned" || type === "delivery.expired") { Sound.play("info"); toast("A delivery was taken off your list"); }
  else if (type === "order.status_changed" && data.status === "cancelled") { Sound.play("alert"); toast(`Order ${data.order_number} was cancelled. Stop this delivery.`, "error"); }
  else if (type === "delivery.geofence_overridden") { Sound.play("info"); toast("Admin waived the location check for this delivery"); }
  load().catch(() => {});
}

// ---------------------------------------------------------------- data
let lastRendered = "";
async function load() {
  jobs = await session.api("/rider/deliveries");
  // only redraw when something changed, so a refresh never wipes a code being typed
  const signature = JSON.stringify(jobs);
  if (signature !== lastRendered) { lastRendered = signature; render(); }
  syncGps();
}

async function act(job, step, body, { form } = {}) {
  try {
    const result = await session.api(`/rider/deliveries/${job.id}/${step}`, { method: "POST", json: body, form });
    return result;
  } catch (err) {
    toast(err.message, "error");
    if (err.status === 404 || err.code === "wrong_delivery_state") load().catch(() => {});
    throw err;
  }
}

async function here() {
  // a fix from the last 20 s is good enough; otherwise ask the GPS
  if (lastFix && Date.now() - lastFix.at < 20000) return lastFix;
  const p = await currentPosition();
  lastFix = { ...p, at: Date.now() };
  return lastFix;
}

// ---------------------------------------------------------------- GPS
// Watch position while there's an active delivery; send a ping every 15 s.
function syncGps() {
  const active = jobs.some((j) => ["accepted", "en_route", "arrived"].includes(j.status));
  if (active && watchId === null && navigator.geolocation) {
    watchId = navigator.geolocation.watchPosition((p) => {
      lastFix = { latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy, at: Date.now() };
      $("#gps").textContent = `📍 GPS on (±${Math.round(p.coords.accuracy)} m)`;
      for (const id in maps) moveMe(id);
      if (Date.now() - lastPing > PING_EVERY_MS) {
        lastPing = Date.now();
        session.api("/rider/location", { method: "POST", json: {
          latitude: lastFix.latitude, longitude: lastFix.longitude, accuracy: lastFix.accuracy } }).catch(() => {});
      }
    }, (e) => {
      $("#gps").textContent = e.code === 1 ? "⚠️ Location is blocked. Allow it in your browser settings." : "⚠️ Waiting for GPS…";
    }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 30000 });
  } else if (!active && watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
    $("#gps").textContent = "";
  }
}

// ---------------------------------------------------------------- render
let lastNag = 0;
function tick() {
  // an unanswered offer keeps beeping (every 12 s) while the app is open
  if (jobs.some((j) => j.status === "assigned") && document.visibilityState === "visible"
      && Date.now() - lastNag > 12000) {
    lastNag = Date.now();
    Sound.play("alert");
  }
  document.querySelectorAll("[data-deadline]").forEach((el) => {
    const left = Math.max(0, Math.round((new Date(el.dataset.deadline) - Date.now()) / 1000));
    el.textContent = left ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left to accept` : "Time is up";
  });
}

const STATUS_TEXT = {
  assigned: "New offer", accepted: "Accepted: check the address", en_route: "On the way",
  arrived: "Arrived: hand over", delivered: "Delivered", failed: "Failed", cancelled: "Cancelled",
};

function render() {
  for (const id in maps) { maps[id].map.remove(); delete maps[id]; }
  $("#empty").classList.toggle("hidden", jobs.length > 0);
  $("#jobs").innerHTML = jobs.map(card).join("");
  for (const job of jobs) wire(job);
  tick();
}

function card(job) {
  const items = job.items.map((i) => `${esc(i.quantity)} × ${esc(i.name)}`).join(", ");
  const cash = job.collect_cash != null
    ? `<div class="banner cash">💵 Collect ${naira(job.collect_cash)} cash on delivery</div>` : "";
  const changed = job.customer_changed_address
    ? `<div class="banner warn">The customer changed the address. Check it and confirm again.</div>` : "";
  return `
  <article class="card" id="job-${job.id}">
    <div class="row"><h2>${esc(job.order_number)}</h2><span class="chip ${esc(job.status)}">${esc(STATUS_TEXT[job.status] || job.status)}</span></div>
    ${job.status === "assigned" ? `<p class="countdown" data-deadline="${esc(job.accept_deadline)}"></p>` : ""}
    ${cash}${changed}
    <p><strong>${esc(job.customer_name)}</strong>${job.customer_phone ? ` · <a href="tel:${esc(job.customer_phone)}">📞 ${esc(job.customer_phone)}</a>` : ""}</p>
    <p>${esc(job.delivery_address)}</p>
    ${job.landmark ? `<p class="muted">Landmark: ${esc(job.landmark)}</p>` : ""}
    ${job.notes ? `<p class="muted">Notes: ${esc(job.notes)}</p>` : ""}
    <p class="muted">${items} · ${naira(job.total)}</p>
    ${steps(job)}
  </article>`;
}

function steps(job) {
  switch (job.status) {
    case "assigned":
      return `<div class="row"><button data-act="accept">Accept</button><button class="secondary" data-act="decline">Decline</button></div>`;
    case "accepted":
      return `
        <h3>1. Confirm the address</h3>
        <p class="muted">Call the customer, then drag the pin to their exact door (or tap “I'm at the address”). The delivery code only works near this pin.</p>
        <div class="map" data-map></div>
        <div class="row"><button class="secondary small" data-act="pin-here">📍 Pin my current location</button></div>
        <label>Landmark</label><input data-field="landmark" maxlength="255" value="${esc(job.landmark || "")}" placeholder="e.g. Blue gate opposite the church">
        <label>Notes for delivery</label><input data-field="notes" maxlength="500" value="${esc(job.notes || "")}" placeholder="e.g. Call when at the gate">
        <div class="row" style="margin-top:12px"><button data-act="confirm">${job.address_confirmed ? "✔ Address confirmed: update" : "Confirm address"}</button></div>
        <h3>2. Go</h3>
        <div class="row"><button data-act="start" ${job.address_confirmed ? "" : "disabled"}>Start journey</button><button class="secondary" data-act="decline">Decline</button></div>`;
    case "en_route":
      return `
        <div class="map" data-map></div>
        <div class="row">
          ${job.dropoff_latitude != null ? `<a class="btn secondary" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${job.dropoff_latitude},${job.dropoff_longitude}">🧭 Navigate</a>` : ""}
          <button data-act="arrive">I've arrived</button>
        </div>
        <div class="row" style="margin-top:10px"><button class="danger small" data-act="fail">Can't deliver</button></div>`;
    case "arrived":
      return `
        <h3>1. Send the code</h3>
        <p class="muted">The customer gets a 6-digit code by SMS. Ask them to read it to you once they have their items.</p>
        <button class="secondary" data-act="send-code">${job.code_sent_at ? "Resend delivery code" : "📩 Send delivery code"}</button>
        <h3>2. Take a photo of the handover</h3>
        <input type="file" accept="image/*" capture="environment" data-photo>
        <img class="photo-preview hidden" data-preview alt="Handover photo">
        <h3>3. Enter the code</h3>
        <input class="code-input" data-field="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="••••••">
        <div class="row" style="margin-top:12px"><button data-act="complete">Complete delivery</button></div>
        <div class="row" style="margin-top:10px"><button class="danger small" data-act="fail">Can't deliver</button></div>`;
    default:
      return "";
  }
}

// ---------------------------------------------------------------- wiring
function wire(job) {
  const root = $(`#job-${job.id}`);
  const field = (name) => $(`[data-field="${name}"]`, root)?.value.trim() || null;
  const on = (name, fn) => root.querySelectorAll(`[data-act="${name}"]`).forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      try { await fn(); } catch { /* toast already shown */ } finally { b.disabled = false; }
    };
  });

  const mapEl = $("[data-map]", root);
  if (mapEl && window.L) setupMap(job, mapEl);

  on("accept", async () => { await act(job, "accept"); Sound.play("good"); toast("Accepted. Call the customer and confirm the address.", "good"); await load(); });
  on("decline", async () => {
    const reason = prompt("Why are you declining? (optional)");
    if (reason === null) return;
    await act(job, "decline", { reason: reason || null });
    toast("Declined"); await load();
  });
  on("pin-here", async () => {
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    pendingPin[job.id] = [p.latitude, p.longitude];
    maps[job.id]?.pin.setLatLng(pendingPin[job.id]);
    maps[job.id]?.map.setView(pendingPin[job.id], 17);
  });
  on("confirm", async () => {
    const pin = pendingPin[job.id] || (job.dropoff_latitude != null ? [job.dropoff_latitude, job.dropoff_longitude] : null);
    if (!pin) { toast("Drop the pin on the customer's door first (drag it, or pin your location)", "error"); return; }
    await act(job, "confirm-address", { latitude: pin[0], longitude: pin[1], landmark: field("landmark"), notes: field("notes") });
    delete pendingPin[job.id];
    toast("Address confirmed", "good"); await load();
  });
  on("start", async () => { await act(job, "start"); toast("Journey started. The customer can now follow you live.", "good"); await load(); });
  on("arrive", async () => {
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    await act(job, "arrive", p); toast("Arrived. Send the delivery code.", "good"); await load();
  });
  on("send-code", async () => {
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    const r = await act(job, "send-code", p);
    toast(`Code sent to the customer (valid ${r.expires_in_minutes} min)`, "good"); await load();
  });
  on("complete", async () => {
    const code = field("code");
    if (!/^\d{6}$/.test(code || "")) { toast("Enter the 6-digit code the customer reads to you", "error"); return; }
    if (!photos[job.id]) { toast("Take a photo of the handover first", "error"); return; }
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    const form = new FormData();
    form.append("code", code);
    form.append("latitude", p.latitude);
    form.append("longitude", p.longitude);
    form.append("photo", photos[job.id], "handover.jpg");
    await act(job, "complete", undefined, { form });
    delete photos[job.id];
    Sound.play("good"); toast("Delivered! 🎉", "good"); await load();
  });
  on("fail", async () => {
    const reason = prompt("What went wrong? (e.g. customer not reachable)");
    if (!reason || reason.trim().length < 3) return;
    await act(job, "fail", { reason: reason.trim() });
    toast("Reported. The admin will decide what happens next."); await load();
  });

  const photoInput = $("[data-photo]", root);
  if (photoInput && photos[job.id]) {  // keep a photo already taken across redraws
    const img = $("[data-preview]", root);
    img.src = URL.createObjectURL(photos[job.id]);
    img.classList.remove("hidden");
  }
  if (photoInput) photoInput.onchange = async () => {
    const file = photoInput.files[0];
    if (!file) return;
    try {
      photos[job.id] = await shrink(file);
      const img = $("[data-preview]", root);
      img.src = URL.createObjectURL(photos[job.id]);
      img.classList.remove("hidden");
    } catch { toast("Could not read that photo, try again", "error"); }
  };
}

// Phone photos are often 5-10 MB: shrink to <=1600 px JPEG before upload.
function shrink(file, maxSide = 1600) {
  return new Promise((ok, fail) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((b) => (b ? ok(b) : fail(new Error("encode"))), "image/jpeg", 0.82);
      URL.revokeObjectURL(img.src);
    };
    img.onerror = fail;
    img.src = URL.createObjectURL(file);
  });
}

// ---------------------------------------------------------------- maps
function setupMap(job, el) {
  const drop = job.dropoff_latitude != null ? [job.dropoff_latitude, job.dropoff_longitude] : null;
  const start = pendingPin[job.id] || drop || (lastFix ? [lastFix.latitude, lastFix.longitude] : LAGOS);
  const map = makeMap(el, start, drop || lastFix ? 16 : 12);
  const editable = job.status === "accepted";
  const pin = L.marker(start, { draggable: editable, icon: dot("#b42318", "🏠") }).addTo(map);
  if (editable) pin.on("dragend", () => { const ll = pin.getLatLng(); pendingPin[job.id] = [ll.lat, ll.lng]; });
  const me = L.marker(lastFix ? [lastFix.latitude, lastFix.longitude] : start, { icon: dot("#1f8a4c", "me") });
  if (lastFix) me.addTo(map);
  maps[job.id] = { map, pin, me, drop: editable ? null : drop, fitted: false };
  moveMe(job.id);
  setTimeout(() => map.invalidateSize(), 50);
}

function moveMe(id) {
  const m = maps[id];
  if (!m || !lastFix) return;
  m.me.setLatLng([lastFix.latitude, lastFix.longitude]);
  if (!m.map.hasLayer(m.me)) m.me.addTo(m.map);
  if (m.drop && !m.fitted) {  // on the way: once, zoom to show both me and the door
    m.map.fitBounds([m.drop, [lastFix.latitude, lastFix.longitude]], { padding: [30, 30], maxZoom: 16 });
    m.fitted = true;
  }
}

// ---------------------------------------------------------------- push alerts
// Web push so offers arrive while the app is closed. Needs: the server's VAPID key,
// notification permission, and (on iPhone) the app installed to the home screen.
let pushKey = null;

function b64ToBytes(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

function alertsBanner(text, button) {
  $("#alerts").classList.toggle("hidden", !text);
  if (text) $("#alerts-text").textContent = text;
  $("#alerts-btn").classList.toggle("hidden", !button);
}

async function setupPush(force = false) {
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (!supported) {
    const iphone = /iphone|ipad/i.test(navigator.userAgent);
    alertsBanner(iphone ? "To get delivery alerts when the app is closed, tap Share → “Add to Home Screen”, then open the app from there."
                        : "", false);
    return;
  }
  if (!pushKey) {
    const info = await session.api("/rider/push/key");
    if (!info.enabled) { alertsBanner("", false); return; }
    pushKey = info.public_key;
  }
  if (Notification.permission === "denied") {
    alertsBanner("Alerts are blocked. Allow notifications for this site in your browser settings to get offers when the app is closed.", false);
    return;
  }
  if (Notification.permission === "default" && !force) {
    alertsBanner("Turn on alerts so new deliveries reach you even when this app is closed.", true);
    return;
  }
  await subscribePush();
}

async function subscribePush() {
  const reg = await navigator.serviceWorker.ready;
  if (Notification.permission !== "granted" && await Notification.requestPermission() !== "granted") {
    alertsBanner("Alerts were not allowed. You'll only hear offers while the app is open.", false);
    return;
  }
  let sub = await reg.pushManager.getSubscription();
  const key = b64ToBytes(pushKey);
  if (sub && sub.options?.applicationServerKey) {
    const current = new Uint8Array(sub.options.applicationServerKey);
    if (current.length !== key.length || current.some((b, i) => b !== key[i])) {
      await sub.unsubscribe();  // server keys changed: start over
      sub = null;
    }
  }
  sub = sub || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await session.api("/rider/push/subscribe", { method: "POST", json: sub.toJSON() });
  alertsBanner("", false);
}

async function unsubscribePush() {
  if (!("serviceWorker" in navigator)) return;
  const reg = await navigator.serviceWorker.getRegistration("/rider/");
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await session.api("/rider/push/unsubscribe", { method: "POST", json: { endpoint: sub.endpoint } }).catch(() => {});
  await sub.unsubscribe();
}

$("#alerts-btn").onclick = () => {
  Sound.unlock();
  subscribePush().catch((e) => toast(`Could not turn on alerts: ${e.message}`, "error"));
};

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("message", (e) => {
    const { type, msg } = e.data || {};
    if (type === "push") { Sound.play("alert"); if (msg?.title) toast(msg.title); load().catch(() => {}); }
    else if (type === "refresh") load().catch(() => {});
    else if (type === "resubscribe") setupPush(true).catch(() => {});
  });
}
