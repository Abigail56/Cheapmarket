// Rider app: offers -> accept -> confirm address -> start -> arrive -> code + photo -> done.
"use strict";

const session = new Session("cmd.rider");
let jobs = [];
let stopEvents = null, watchId = null, lastPing = 0, lastFix = null, ticker = null;
let liveState = "connecting", stopPoll = null, bell = null;
const maps = {};          // job id -> { map, pin, me }
const pendingPin = {};    // job id -> [lat, lng] the rider has dragged the pin to
const photos = {};        // job id -> Blob (downscaled)
const drafts = {};        // job id -> what's been typed, so a live refresh never wipes it
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
window.addEventListener("appinstalled", () => $("#install").classList.add("hidden"));

// iPhones have no install prompt: riders add the app from Safari's Share menu
const installed = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
if (isIos && !installed) {
  $("#install-text").textContent = "In Safari, tap the Share button, then “Add to Home Screen”.";
  $("#install-btn").classList.add("hidden");
  $("#install").classList.remove("hidden");
}

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
    $("#google-apply-done").textContent = `Using your Google account ${claims.email}. Now add your phone, vehicle and ID.`;
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
    } catch { toast("We couldn't read that photo. Please try again.", "error"); }
  };
}

$("#apply-form").onsubmit = async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  if (!idFiles.id_front || !idFiles.selfie) { toast("Please add a photo of your ID and one of your face", "error"); return; }
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
    toast("Sending. Photos can take a few seconds…");
    await session.api("/auth/rider-signup", { method: "POST", form });
    $("#email").value = $("#a-email").value.trim();
    $("#apply-form").reset();
    for (const k of Object.keys(idFiles)) delete idFiles[k];
    ["#p-idfront", "#p-idback", "#p-selfie"].forEach((id) => $(id).classList.add("hidden"));
    showOnly("#applied");
  } catch (err) { toast(err.message, "error"); } finally { btn.disabled = false; }
};
$("#done-close").onclick = () => $("#done").classList.add("hidden");
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
      showLogin(err.status === 403 ? "This account isn't set up for riding." : null);
      return;
    }
    toast(err.message, "error");
  }
  $("#login").classList.add("hidden");
  document.body.classList.remove("public");
  $("#app").classList.remove("hidden");
  $("#logout").classList.remove("hidden");
  $("#bell").classList.remove("hidden");
  bell ||= new Bell($("#bell"), session, {
    onOpen: (n) => showOrder(n.order_number, n.order_number ? `${n.order_number} isn't on your list any more.` : null),
  });
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
  document.body.classList.add("public");
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  if (message) toast(message, "error");
}

if (session.access) start(); else showLogin();

// ---------------------------------------------------------------- live events
function onEvent(type, data) {
  if (type === "delivery.assigned") { Sound.play("alert"); toast(`New delivery ${data.order_number || ""} for you. Have a look!`); }
  else if (type === "delivery.address_corrected") { Sound.play("alert"); toast("The customer changed their address. Please check it and confirm again."); }
  else if (type === "delivery.unassigned" || type === "delivery.expired") { Sound.play("info"); toast("That delivery has come off your list."); }
  else if (type === "order.status_changed" && data.status === "cancelled") { Sound.play("alert"); toast(`${data.order_number} was cancelled. Please don't deliver it.`, "error"); }
  else if (type === "delivery.geofence_overridden") { Sound.play("info"); toast("You're cleared to finish without the distance check."); }
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
  bell?.refresh().catch(() => {});
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
      $("#gps").textContent = `Location on, accurate to about ${Math.round(p.coords.accuracy)} m`;
      for (const id in maps) moveMe(id);
      if (Date.now() - lastPing > PING_EVERY_MS) {
        lastPing = Date.now();
        session.api("/rider/location", { method: "POST", json: {
          latitude: lastFix.latitude, longitude: lastFix.longitude, accuracy: lastFix.accuracy } }).catch(() => {});
      }
    }, (e) => {
      $("#gps").textContent = e.code === 1 ? "Your location is blocked. Please allow it in your browser settings." : "Looking for your location…";
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
    el.textContent = left ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left to accept` : "Time's up";
  });
}

const STATUS_TEXT = {
  assigned: "New offer", accepted: "Check the address", en_route: "On the way",
  arrived: "Hand it over", delivered: "Delivered", failed: "Couldn't deliver", cancelled: "Cancelled",
};
const STAGES = [["assigned", "Accept"], ["accepted", "Address"], ["en_route", "Ride"], ["arrived", "Hand over"]];

function render() {
  for (const id in maps) { maps[id].map.remove(); delete maps[id]; }
  $("#empty").classList.toggle("hidden", jobs.length > 0);
  $("#jobs").innerHTML = jobs.map(card).join("");
  for (const job of jobs) wire(job);
  tick();
}

function progress(job) {
  const at = STAGES.findIndex(([k]) => k === job.status);
  if (at < 0) return "";
  return `<div class="progress" role="img" aria-label="Step ${at + 1} of ${STAGES.length}: ${esc(STAGES[at][1])}">${STAGES.map(([, label], i) =>
    `<div class="${i < at ? "done" : i === at ? "now" : ""}">${esc(label)}</div>`).join("")}</div>`;
}

function firstName(job) { return String(job.customer_name || "the customer").split(" ")[0]; }

function card(job) {
  const items = job.items.map((i) => `${esc(i.quantity)} × ${esc(i.name)}`).join(", ");
  const cash = job.collect_cash != null
    ? `<div class="banner cash">Collect ${naira(job.collect_cash)} in cash</div>` : "";
  const changed = job.customer_changed_address
    ? `<div class="banner warn">${esc(firstName(job))} changed the address. Please check it and confirm again.</div>` : "";
  return `
  <article class="card" id="job-${job.id}" data-order="${esc(job.order_number)}">
    <div class="between"><h2>${esc(job.order_number)}</h2><span class="chip ${esc(job.status)}">${esc(STATUS_TEXT[job.status] || job.status)}</span></div>
    ${progress(job)}
    ${job.status === "assigned" ? `<p class="countdown offer-time" data-deadline="${esc(job.accept_deadline)}"></p>` : ""}
    ${cash}${changed}
    <p class="who">${esc(job.customer_name)}</p>
    ${job.customer_phone ? `<p class="place"><a href="tel:${esc(job.customer_phone)}">Call ${esc(job.customer_phone)}</a></p>` : ""}
    <p class="place">${esc(job.delivery_address)}</p>
    ${job.landmark ? `<p class="muted place">Landmark: ${esc(job.landmark)}</p>` : ""}
    ${job.notes ? `<p class="muted place">Note: ${esc(job.notes)}</p>` : ""}
    <p class="muted">${items} · ${naira(job.total)}</p>
    ${steps(job)}
  </article>`;
}

function callButton(job, label, cls = "") {
  return job.customer_phone ? `<a class="btn ${cls}" href="tel:${esc(job.customer_phone)}" data-call>${esc(label)}</a>` : "";
}

function stepBlock(no, done, title, body) {
  return `<div class="step ${done ? "done" : ""}"><div class="step-no">${done ? ICONS.check : no}</div>
    <div class="step-body"><h3>${esc(title)}</h3>${body}</div></div>`;
}

function steps(job) {
  const who = esc(firstName(job));
  switch (job.status) {
    case "assigned":
      return `<div class="row mt"><button data-act="accept">Accept delivery</button><button class="secondary" data-act="decline">I can't take it</button></div>`;
    case "accepted":
      return `
        ${stepBlock(1, job.address_confirmed, "Check the address", `
          <p class="muted">Call ${who}, then drag the pin to their door. Your delivery code will only work close to this pin.</p>
          <div class="map" data-map></div>
          <button class="secondary small" data-act="pin-here">I'm at the address, use my location</button>
          <label>Landmark</label><input data-field="landmark" maxlength="255" value="${esc(job.landmark || "")}" placeholder="Blue gate, opposite the church">
          <label>Note</label><input data-field="notes" maxlength="500" value="${esc(job.notes || "")}" placeholder="Call at the gate">
          <button class="full ${job.address_confirmed ? "secondary" : ""}" data-act="confirm">${job.address_confirmed ? "Update the address" : "Confirm address"}</button>`)}
        ${stepBlock(2, false, "Off you go", `
          <button class="full" data-act="start" ${job.address_confirmed ? "" : "disabled"}>Start the ride</button>
          <button class="quiet full" data-act="decline">I can't take it</button>`)}`;
    case "en_route":
      return `
        <div class="map" data-map></div>
        ${callButton(job, `Call ${firstName(job)}`, "secondary full")}
        <div class="row mt">
          ${job.dropoff_latitude != null ? `<a class="btn secondary" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${job.dropoff_latitude},${job.dropoff_longitude}">Get directions</a>` : ""}
          <button data-act="arrive">I've arrived</button>
        </div>
        <button class="quiet full mt" data-act="fail">I can't deliver this</button>`;
    case "arrived": {
      const hasPhoto = !!photos[job.id];
      return `
        <div class="call-box">
          <h3>Let ${who} know you're here</h3>
          <p class="muted">We've texted them too, but a quick call gets them to the door faster.</p>
          ${callButton(job, `Call ${firstName(job)} now`, "full")}
        </div>
        ${stepBlock(1, !!job.code_sent_at, `Text ${firstName(job)} their code`, `
          <p class="muted">We'll send a 6-digit code to their phone. You won't see it, and that's on purpose.</p>
          <button class="full ${job.code_sent_at ? "secondary" : ""}" data-act="send-code">${job.code_sent_at ? "Send the code again" : "Send delivery code"}</button>`)}
        ${stepBlock(2, hasPhoto, "Snap the delivery", `
          <p class="muted">Take a clear photo of the items with ${who} or at their door.</p>
          <label class="photo-tile ${hasPhoto ? "has-photo" : ""}" data-tile>
            <input class="visually-hidden" type="file" accept="image/*" capture="environment" data-photo aria-label="Take a photo of the delivery">
            <img class="photo-preview ${hasPhoto ? "" : "hidden"}" data-preview alt="Your delivery photo">
            <span class="retake ${hasPhoto ? "" : "hidden"}" data-retake>Retake</span>
            <span data-prompt class="${hasPhoto ? "hidden" : ""}" style="display:contents">${ICONS.camera}Open camera<small>A photo is required</small></span>
          </label>`)}
        ${stepBlock(3, false, `Pass your phone to ${firstName(job)}`, `
          <div class="handover-note">${who}: check your items, then type the code from your text message here.</div>
          <label for="code-${job.id}" class="visually-hidden">Delivery code</label>
          <input id="code-${job.id}" class="code-input mt" data-field="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" placeholder="······">
          <button class="full" data-act="complete">Confirm delivery</button>`)}
        <button class="quiet full mt" data-act="fail">I can't deliver this</button>`;
    }
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

  // what's been typed survives a live refresh
  const draft = (drafts[job.id] ||= {});
  root.querySelectorAll("[data-field]").forEach((input) => {
    const name = input.dataset.field;
    if (draft[name] !== undefined) input.value = draft[name];
    input.oninput = () => { draft[name] = input.value; };
  });

  const mapEl = $("[data-map]", root);
  if (mapEl && window.L) setupMap(job, mapEl);

  on("accept", async () => { await act(job, "accept"); Sound.play("good"); toast(`It's yours. Give ${firstName(job)} a call to check the address.`, "good"); await load(); });
  on("decline", async () => {
    const reason = await ask({ title: "Can't take this one?", text: "No problem, we'll find another rider. Want to tell us why? (optional)", input: true, placeholder: "My bike needs fixing", ok: "Pass on it", cancel: "Keep it" });
    if (reason === null) return;
    await act(job, "decline", { reason: reason || null });
    toast("Thanks for letting us know."); await load();
  });
  on("pin-here", async () => {
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    pendingPin[job.id] = [p.latitude, p.longitude];
    maps[job.id]?.pin.setLatLng(pendingPin[job.id]);
    maps[job.id]?.map.setView(pendingPin[job.id], 17);
  });
  on("confirm", async () => {
    const pin = pendingPin[job.id] || (job.dropoff_latitude != null ? [job.dropoff_latitude, job.dropoff_longitude] : null);
    if (!pin) { toast("Please move the pin to their door first.", "error"); return; }
    await act(job, "confirm-address", { latitude: pin[0], longitude: pin[1], landmark: field("landmark"), notes: field("notes") });
    delete pendingPin[job.id];
    delete draft.landmark; delete draft.notes;
    toast("Address confirmed. You're good to go.", "good"); await load();
  });
  on("start", async () => { await act(job, "start"); toast(`Ride safe. ${firstName(job)} can follow you on the map now.`, "good"); await load(); });
  on("arrive", async () => {
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    await act(job, "arrive", p); toast(`You're there. Give ${firstName(job)} a call, then send their code.`, "good"); await load();
  });
  on("send-code", async () => {
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    const r = await act(job, "send-code", p);
    toast(`Code sent. It works for ${r.expires_in_minutes} minutes.`, "good"); await load();
  });
  on("complete", async () => {
    const code = field("code");
    if (!photos[job.id]) { toast("Please take the delivery photo first.", "error"); return; }
    if (!/^\d{6}$/.test(code || "")) { toast(`Ask ${firstName(job)} to type the 6-digit code from their text.`, "error"); return; }
    const p = await here().catch((e) => { toast(e.message, "error"); throw e; });
    const form = new FormData();
    form.append("code", code);
    form.append("latitude", p.latitude);
    form.append("longitude", p.longitude);
    form.append("photo", photos[job.id], "handover.jpg");
    await act(job, "complete", undefined, { form });
    delete photos[job.id];
    delete drafts[job.id];
    Sound.play("good");
    $("#done-title").textContent = "Delivered. Nice work!";
    $("#done-text").textContent = `${job.order_number} is done. ${job.collect_cash != null ? `Remember to hand in the ${naira(job.collect_cash)} cash. ` : ""}Thanks for getting it there safely.`;
    $("#done").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
    await load();
  });
  on("fail", async () => {
    const reason = await ask({ title: "What happened?", text: "We'll let the office know, and they'll tell you what to do next.", input: true, minLength: 3, placeholder: "I've called twice and there's no answer", ok: "Send", cancel: "Go back" });
    if (!reason) return;
    await act(job, "fail", { reason });
    toast("Thanks. The office has been told."); await load();
  });

  const photoInput = $("[data-photo]", root);
  if (photoInput) {
    const img = $("[data-preview]", root);
    if (photos[job.id]) img.src = URL.createObjectURL(photos[job.id]);  // keep it across redraws
    photoInput.onchange = async () => {
      const file = photoInput.files[0];
      if (!file) return;
      try {
        photos[job.id] = await shrink(file);
        render();  // ticks the step and shows the photo
      } catch { toast("We couldn't read that photo. Please try again.", "error"); }
    };
  }
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
  const me = L.marker(lastFix ? [lastFix.latitude, lastFix.longitude] : start, { icon: dot("#1c7946", "me") });
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
    alertsBanner(iphone ? "To get alerts when the app is closed, tap Share, then “Add to Home Screen”, and open the app from there."
                        : "", false);
    return;
  }
  if (!pushKey) {
    const info = await session.api("/rider/push/key");
    if (!info.enabled) { alertsBanner("", false); return; }
    pushKey = info.public_key;
  }
  if (Notification.permission === "denied") {
    alertsBanner("Alerts are blocked. Allow notifications for this site in your browser settings so offers can reach you.", false);
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
    alertsBanner("Alerts are off, so you'll only hear about new deliveries while the app is open.", false);
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
  subscribePush().catch((e) => toast(`We couldn't turn on alerts: ${e.message}`, "error"));
};

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("message", (e) => {
    const { type, msg } = e.data || {};
    if (type === "push") { Sound.play("alert"); if (msg?.title) toast(msg.title); load().catch(() => {}); }
    else if (type === "refresh") load().catch(() => {});
    else if (type === "resubscribe") setupPush(true).catch(() => {});
  });
}
