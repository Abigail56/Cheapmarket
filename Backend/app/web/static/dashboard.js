// Admin live board: who needs a rider, what's on the road, where the riders are, with sound.
"use strict";

const session = new Session("cmd.admin");
let board = null, map = null, stopEvents = null, ticker = null, bell = null;
let liveState = "connecting", stopPoll = null;
const riderMarkers = {};   // delivery id -> marker
const dropMarkers = {};

const STATUS_TEXT = {
  assigned: "Waiting for an answer", accepted: "Checking the address",
  en_route: "On the way", arrived: "At the door",
};

const ID_TYPES = { nin: "NIN", drivers_licence: "Driver's licence", voters_card: "Voter's card", passport: "Passport" };
const ID_CHECK = {
  pending: ["Checking their ID…", "assigned"],
  verified: ["ID verified", "delivered"],
  review: ["ID needs a closer look", "arrived"],
  failed: ["ID not found", "failed"],
  manual: ["Please check this ID yourself", "accepted"],
  error: ["ID check didn't run", "unassigned"],
};
const DOC_NAMES = { id_front: "ID front", id_back: "ID back", selfie: "Selfie" };
const docUrls = {};  // document id -> blob: URL (fetched once with the admin token)

// ID documents need the admin's token, so they're fetched (not <img src>) and shown as
// blob URLs. Each fetch is recorded in the audit log on the server.
async function loadDoc(appId, btn) {
  const id = btn.dataset.doc;
  if (!docUrls[id]) {
    const r = await fetch(`${API}/admin/rider-applications/${appId}/documents/${id}`,
                          { headers: { Authorization: `Bearer ${session.access}` } });
    if (!r.ok) throw new Error(`Could not load the document (${r.status})`);
    docUrls[id] = URL.createObjectURL(await r.blob());
  }
  return docUrls[id];
}

// which events chime, and how
const SOUNDS = {
  "order.placed": ["good", (d) => `New order ${d.order_number} for ${naira(d.total)}`],
  "delivery.assigned": ["quiet", (d) => `${d.order_number} was offered to ${d.rider_name}`],
  "delivery.address_confirmed": ["quiet", (d) => `${d.rider_name} confirmed the address for ${d.order_number}`],
  "delivery.code_sent": ["quiet", (d) => `${d.rider_name} sent the delivery code for ${d.order_number}`],
  "delivery.accepted": ["info", (d) => `${d.rider_name} accepted ${d.order_number || "a delivery"}`],
  "delivery.declined": ["alert", (d) => `${d.rider_name} can't take ${d.order_number}${d.reason ? `: ${d.reason}` : ""}. It needs a new rider.`],
  "delivery.expired": ["alert", (d) => `No answer on ${d.order_number || "an offer"}. It needs a new rider.`],
  "delivery.code_wrong": ["alert", (d) => `Wrong delivery code on ${d.order_number || "an order"} (${d.attempts} so far)`],
  "delivery.failed": ["alert", (d) => `${d.order_number} couldn't be delivered: ${d.reason}`],
  "delivery.delivered": ["good", (d) => `${d.rider_name} delivered ${d.order_number}`],
  "delivery.address_corrected": ["info", (d) => `The customer updated the address for ${d.order_number || "an order"}`],
  "delivery.started": ["info", (d) => `${d.rider_name} set off with ${d.order_number}`],
  "delivery.arrived": ["info", (d) => `${d.rider_name} arrived with ${d.order_number}`],
  "rider.applied": ["alert", (d) => `${d.full_name} wants to ride with us (${d.vehicle_type}${d.area ? `, ${d.area}` : ""})`],
  "rider.approved": ["info", (d) => `${d.full_name} is now a rider`],
  "rider.id_checked": ["info", (d) => `${d.full_name}: ${(ID_CHECK[d.status] || [d.status])[0]}`],
};

const STATUS_WORDS = { pending: "new", confirmed: "confirmed", packed: "packed", out_for_delivery: "on the way", delivered: "delivered", cancelled: "cancelled" };
const PAY_WORDS = { cod: "Pay on delivery", card: "Card", transfer: "Bank transfer" };

soundButton($("#sound"));

$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await session.login($("#email").value.trim(), $("#password").value);
    Sound.unlock();
    await start();
  } catch (err) { toast(err.message, "error"); }
};
$("#logout").onclick = () => { session.logout(); location.reload(); };

// existing admins only: Google never creates or upgrades an account here
googleButton($("#google-login"), async (idToken) => {
  try {
    await session.google(idToken, false);
    Sound.unlock();
    await start();
  } catch (err) {
    toast(err.code === "google_no_account" ? "No admin account uses this Google account." : err.message, "error");
  }
}).then((shown) => $("#or-login").classList.toggle("hidden", !shown));

async function start() {
  try {
    await load();
  } catch (err) {
    session.logout();
    showLogin(err.status === 403 ? "This page is just for admins." : err.message);
    return;
  }
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#logout").classList.remove("hidden");
  $("#bell").classList.remove("hidden");
  bell ||= new Bell($("#bell"), session, {
    onOpen: (n) => showOrder(n.order_number, n.order_number ? `${n.order_number} isn't on the board any more.` : null),
  });
  stopEvents?.();
  stopEvents = liveEvents("/admin/events", onEvent, {
    session, onState: (s) => { liveState = s; $("#live").classList.toggle("live", s === "live"); },
  });
  clearInterval(ticker);
  ticker = setInterval(tick, 1000);
  stopPoll?.();
  stopPoll = adaptivePoll(load, () => liveState === "live");
}

function showLogin(message) {
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  if (message) toast(message, "error");
}

if (session.access) start(); else showLogin();

async function load() {
  board = await session.api("/admin/deliveries/board");
  render();
  OrderAlarm.sync(board.new_orders || []);
  bell?.refresh().catch(() => {});
}

// ---------------------------------------------------------------- events
let reloadTimer = null;
function onEvent(type, data) {
  if (type === "rider.location") { moveRider(data); return; }
  const rule = SOUNDS[type];
  if (rule) {
    if (type === "order.placed") OrderAlarm.add(data);  // rings until someone stops it
    else if (rule[0] !== "quiet") Sound.play(rule[0]);
    feed(rule[1](data), rule[0]);
  } else if (type === "order.status_changed" && !["out_for_delivery", "delivered"].includes(data.status)) {  // these have their own line above
    feed(`${data.order_number} is now ${STATUS_WORDS[data.status] || data.status}`, "info");
  }
  clearTimeout(reloadTimer);  // several events often arrive together: one reload
  reloadTimer = setTimeout(() => load().catch(() => {}), 300);
}

function feed(text, kind) {
  $("#feed-empty")?.remove();
  const el = document.createElement("div");
  el.className = kind === "info" ? "" : kind;
  el.textContent = `${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · ${text}`;
  $("#feed").prepend(el);
  while ($("#feed").children.length > 100) $("#feed").lastChild.remove();
}

// ---------------------------------------------------------------- render
function count(id, n) { const el = $(id); el.textContent = n; el.classList.toggle("zero", !n); }
function stat(id, n, hot) { $(`${id} b`).textContent = n; $(id).classList.toggle("hot", !!(hot && n)); }

function riderOptions(current) {
  return board.riders.map((r) =>
    `<option value="${esc(r.id)}" ${r.id === current ? "selected" : ""}>${esc(r.name)}${r.busy ? " (on a delivery)" : ""}</option>`).join("");
}

function render() {
  // keep riders the admin has already picked in the dropdowns
  const picked = {};
  document.querySelectorAll(".item[data-order]").forEach((el) => {
    const sel = $("[data-rider]", el);
    if (sel && document.activeElement === sel || sel?.dataset.touched) picked[el.dataset.order] = sel.value;
  });
  const apps = board.applications || [];
  $("#apps-card").classList.toggle("hidden", !apps.length);
  count("#n-apps", apps.length);
  $("#apps").innerHTML = apps.map((a) => `
    <div class="item" data-app="${esc(a.id)}">
      <div class="row top"><strong>${esc(a.full_name)}</strong><span class="muted">${esc(ago(a.applied_at))}</span></div>
      <div class="muted">${esc(a.vehicle_type)}${a.plate_number ? ` · ${esc(a.plate_number)}` : ""}${a.area ? ` · ${esc(a.area)}` : ""}</div>
      <div class="muted">${a.phone ? `<a href="tel:${esc(a.phone)}">${esc(a.phone)}</a> · ` : ""}${esc(a.email)}</div>
      ${a.note ? `<div class="muted">“${esc(a.note)}”</div>` : ""}
      ${a.id_type ? `<div class="muted">${esc(ID_TYPES[a.id_type] || a.id_type)}: <strong>${esc(a.id_number || "")}</strong></div>` : ""}
      <div class="row" style="margin-top:6px">
        <span class="chip ${esc((ID_CHECK[a.id_check_status] || [])[1] || "")}">${esc((ID_CHECK[a.id_check_status] || [a.id_check_status])[0])}</span>
        ${a.id_face_match != null ? `<span class="muted">Face match ${esc(Math.round(a.id_face_match))}%</span>` : ""}
        ${a.id_name_match != null ? `<span class="muted">Name match ${esc(a.id_name_match)}%</span>` : ""}
      </div>
      ${a.id_record_name ? `<div class="muted">Name on record: <strong>${esc(a.id_record_name)}</strong></div>` : ""}
      ${(a.id_check_reasons || []).length ? `<ul class="reasons">${a.id_check_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      <div class="docs">${(a.documents || []).map((d) => `
        <button type="button" class="doc" data-doc="${esc(d.id)}" data-type="${esc(d.content_type)}" title="${esc(DOC_NAMES[d.kind] || d.kind)}">
          ${d.content_type === "application/pdf" ? "PDF" : "Loading…"}<span>${esc(DOC_NAMES[d.kind] || d.kind)}</span>
        </button>`).join("")}</div>
      <div class="row" style="margin-top:8px">
        <button class="small" data-approve data-check="${esc(a.id_check_status)}">Approve</button>
        <button class="small secondary" data-recheck>Check ID again</button>
        <button class="small danger" data-reject>Say no</button>
      </div>
    </div>`).join("");
  const newOrders = board.new_orders || [];
  count("#n-new", newOrders.length);
  count("#n-waiting", board.needs_rider.length);
  count("#n-active", board.active.length);
  stat("#s-new", newOrders.length, true);
  stat("#s-waiting", board.needs_rider.length, true);
  stat("#s-active", board.active.length);
  stat("#s-free", board.riders.filter((r) => !r.busy).length);
  $("#new-orders").innerHTML = newOrders.length ? newOrders.map((o) => `
    <div class="item" data-order="${esc(o.order_number)}">
      <div class="row top"><strong>${esc(o.order_number)}</strong><span class="muted">${esc(ago(o.placed_at))}</span></div>
      <div class="muted">${esc(o.customer_name)} · ${naira(o.total)} · ${esc(PAY_WORDS[o.payment_method] || o.payment_method)}</div>
      <div class="muted">${esc(o.delivery_address)}</div>
      <div class="row mt">${orderAction(o)}</div>
    </div>`).join("") : `<p class="muted">No new orders right now.</p>`;
  const noRiders = !board.riders.length;
  $("#waiting").innerHTML = board.needs_rider.length ? board.needs_rider.map((o) => `
    <div class="item" data-order="${esc(o.order_number)}">
      <div class="row top"><strong>${esc(o.order_number)}</strong><span class="muted">${esc(ago(o.placed_at))}</span></div>
      <div class="muted">${esc(o.customer_name)} · ${naira(o.total)} · ${esc(PAY_WORDS[o.payment_method] || o.payment_method)}</div>
      <div class="muted">${esc(o.delivery_address)}</div>
      ${o.failure_reason ? `<div class="banner bad">Last try failed: ${esc(o.failure_reason)}</div>` : ""}
      <div class="row" style="margin-top:8px">
        <select data-rider ${noRiders ? "disabled" : ""}>${noRiders ? "<option>No riders available</option>" : riderOptions()}</select>
        <button class="small" data-assign ${noRiders ? "disabled" : ""}>Offer to rider</button>
        ${o.failure_reason ? `<button class="small danger" data-cancel>Cancel order</button>` : ""}
      </div>
    </div>`).join("") : `<p class="muted">Every order has a rider.</p>`;

  $("#active").innerHTML = board.active.length ? board.active.map(({ delivery: d, ...a }) => `
    <div class="item" data-delivery="${esc(d.id)}" data-order="${esc(a.order_number)}">
      <div class="row top"><strong>${esc(a.order_number)}</strong><span class="chip ${esc(d.status)}">${esc(STATUS_TEXT[d.status] || d.status)}</span></div>
      <div class="muted">${esc(a.rider_name)}${a.rider_phone ? ` · <a href="tel:${esc(a.rider_phone)}">${esc(a.rider_phone)}</a>` : ""}</div>
      ${journey(d)}
      <div class="muted">${esc(a.customer_name)}${a.customer_phone ? ` · <a href="tel:${esc(a.customer_phone)}">Call ${esc(a.customer_phone)}</a>` : ""}</div>
      <div class="muted">${esc(a.delivery_address)}</div>
      ${d.status === "assigned" ? `<div class="countdown" data-deadline="${esc(d.accept_deadline)}"></div>` : ""}
      ${d.status === "accepted" && !d.address_confirmed_at ? `<div class="muted">Hasn't confirmed the address yet</div>` : ""}
      ${d.last_location_at ? `<div class="muted">Location seen ${esc(ago(d.last_location_at))}</div>` : ""}
      ${d.code_sent_at ? `<div class="muted">Customer got their code ${esc(ago(d.code_sent_at))}</div>` : ""}
      ${d.geofence_override_at ? `<div class="muted">Distance check waived: ${esc(d.geofence_override_reason)}</div>` : ""}
      <div class="row" style="margin-top:8px">
        <select data-rider>${riderOptions(d.rider_id)}</select><button class="small secondary" data-assign>Change rider</button>
        ${["accepted", "en_route", "arrived"].includes(d.status) && !d.geofence_override_at
          ? `<button class="small secondary" data-override>Waive distance check</button>` : ""}
      </div>
    </div>`).join("") : `<p class="muted">Nobody is out on a delivery.</p>`;

  const delivered = board.delivered || [];
  $("#delivered").innerHTML = delivered.length ? delivered.map((x) => `
    <div class="proof-tile" data-order="${esc(x.order_number)}">
      ${x.proof_photo_url ? `<a href="${esc(x.proof_photo_url)}" target="_blank" rel="noopener"><img src="${esc(x.proof_photo_url)}" alt="Delivery photo for ${esc(x.order_number)}" loading="lazy"></a>` : `<div class="no-photo">No photo</div>`}
      <strong>${esc(x.order_number)}</strong>${esc(x.customer_name)}<br>${x.rider_name ? `by ${esc(x.rider_name)}, ` : ""}${esc(ago(x.delivered_at))}
    </div>`).join("") : `<p class="muted">Nothing delivered yet.</p>`;

  const busyRiders = board.riders.filter((r) => r.busy).length;
  $("#riders").textContent = board.riders.length
    ? `${board.riders.length} ${board.riders.length === 1 ? "rider" : "riders"}, ${busyRiders} out on a delivery`
    : "No riders yet.";
  document.querySelectorAll(".item[data-order]").forEach((el) => {
    const sel = $("[data-rider]", el);
    if (!sel) return;
    if (picked[el.dataset.order]) { sel.value = picked[el.dataset.order]; sel.dataset.touched = "1"; }
    sel.addEventListener("change", () => { sel.dataset.touched = "1"; });
  });
  // a card whose delivery just moved on gets a brief highlight
  for (const { delivery: d, order_number: n } of board.active) {
    if (lastStatus[d.id] && lastStatus[d.id] !== d.status) showFlash(n);
    lastStatus[d.id] = d.status;
  }
  wire();
  drawMap();
  tick();
}

// Where a delivery has got to, with the time of each step.
const JOURNEY = [["assigned_at", "Offered"], ["accepted_at", "Accepted"], ["started_at", "On the way"], ["arrived_at", "Arrived"], ["code_sent_at", "Code sent"]];
function journey(d) {
  const reached = JOURNEY.filter(([k]) => d[k]).length;
  return `<ol class="journey" aria-label="Delivery progress">${JOURNEY.map(([k, label], i) => `
    <li class="${i < reached - 1 ? "done" : i === reached - 1 ? "now" : ""}"><b>${esc(label)}</b>${d[k] ? esc(new Date(d[k]).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })) : ""}</li>`).join("")}</ol>`;
}

// The next step depends on how they're paying.
function orderAction(o) {
  if (o.payment_method === "transfer" && o.payment_status !== "paid") {
    return `<button class="small" data-paid>I've seen the transfer</button>`;
  }
  if (o.payment_method === "card" && o.payment_status !== "paid") {
    return `<span class="muted">Waiting for the customer's card payment. This confirms itself.</span>`;
  }
  return `<button class="small" data-confirm>Confirm order</button>`;
}

const lastStatus = {};
function showFlash(orderNumber) {
  const el = document.querySelector(`#active [data-order="${CSS.escape(orderNumber)}"]`);
  el?.classList.add("flash");
}

function tick() {
  document.querySelectorAll("[data-deadline]").forEach((el) => {
    const left = Math.max(0, Math.round((new Date(el.dataset.deadline) - Date.now()) / 1000));
    el.textContent = left ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left for the rider to answer` : "No answer. This will come back to you.";
  });
}

function wire() {
  document.querySelectorAll("[data-doc]").forEach(async (btn) => {
    const appId = btn.closest(".item").dataset.app;
    btn.onclick = async () => {
      try { window.open(await loadDoc(appId, btn), "_blank", "noopener"); }
      catch (err) { toast(err.message, "error"); }
    };
    if (btn.dataset.type !== "application/pdf") {
      try {
        const url = await loadDoc(appId, btn);
        btn.innerHTML = `<img src="${url}" alt=""><span>${esc(btn.title)}</span>`;
      } catch { btn.firstChild.textContent = "Couldn't load"; }
    }
  });
  document.querySelectorAll("[data-approve]").forEach((btn) => {
    btn.onclick = async () => {
      const item = btn.closest(".item");
      const status = btn.dataset.check;
      const warning = status === "verified" ? ""
        : ` Their ID isn't verified yet (${(ID_CHECK[status] || [status])[0]}), so please compare the ID photo with the selfie first.`;
      const yes = await ask({ title: `Approve ${$("strong", item).textContent}?`,
                              text: `They'll be able to sign in and take deliveries.${warning}`, ok: "Approve" });
      if (!yes) return;
      btn.disabled = true;
      try {
        await session.api(`/admin/rider-applications/${item.dataset.app}/approve`, { method: "POST" });
        toast("Approved. We've texted them the good news.", "good");
        await load();
      } catch (err) { toast(err.message, "error"); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-recheck]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = "Checking…";
      try {
        const r = await session.api(`/admin/rider-applications/${btn.closest(".item").dataset.app}/check-id`, { method: "POST" });
        toast((ID_CHECK[r.id_check_status] || [r.id_check_status])[0], r.id_check_status === "verified" ? "good" : "info");
        await load();
      } catch (err) { toast(err.message, "error"); btn.disabled = false; btn.textContent = "Check ID again"; }
    };
  });
  document.querySelectorAll("[data-reject]").forEach((btn) => {
    btn.onclick = async () => {
      const item = btn.closest(".item");
      const reason = await ask({ title: "What should we tell them?", text: "They'll get this by text.", input: true, minLength: 3,
                                 value: "We're not taking new riders in your area right now.", ok: "Send" });
      if (!reason) return;
      try {
        await session.api(`/admin/rider-applications/${item.dataset.app}/reject`, { method: "POST", json: { reason } });
        toast("Done. We've let them know.");
        await load();
      } catch (err) { toast(err.message, "error"); }
    };
  });
  document.querySelectorAll("[data-cancel]").forEach((btn) => {
    btn.onclick = async () => {
      const n = btn.closest(".item").dataset.order;
      const yes = await ask({ title: `Cancel ${n}?`, text: "The stock goes back on the shelf and the customer is told. If they've already paid, they'll need a refund.", ok: "Cancel order", cancel: "Keep it", danger: true });
      if (!yes) return;
      btn.disabled = true;
      try {
        await session.api(`/admin/orders/${encodeURIComponent(n)}/status`, { method: "PATCH", json: { status: "cancelled", note: "Cancelled after a failed delivery" } });
        toast("Cancelled. We've told the customer.");
        await load();
      } catch (err) { toast(err.message, "error"); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-confirm]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await session.api(`/admin/orders/${encodeURIComponent(btn.closest(".item").dataset.order)}/status`, { method: "PATCH", json: { status: "confirmed" } });
        toast("Confirmed. We've told the customer.", "good");
        await load();
      } catch (err) { toast(err.message, "error"); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-paid]").forEach((btn) => {
    btn.onclick = async () => {
      const n = btn.closest(".item").dataset.order;
      const yes = await ask({ title: `Has the money for ${n} arrived?`, text: "This marks the order as paid and confirms it.", ok: "Yes, it's paid" });
      if (!yes) return;
      btn.disabled = true;
      try {
        await session.api(`/admin/orders/${encodeURIComponent(n)}/mark-paid`, { method: "POST", json: { note: "Transfer seen, confirmed on the live board" } });
        toast("Paid and confirmed.", "good");
        await load();
      } catch (err) { toast(err.message, "error"); btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-assign]").forEach((btn) => {
    btn.onclick = async () => {
      const item = btn.closest(".item");
      const riderId = $("[data-rider]", item).value;
      btn.disabled = true;
      try {
        await session.api(`/admin/orders/${encodeURIComponent(item.dataset.order)}/assign-rider`, { method: "POST", json: { rider_id: riderId } });
        toast("Offer sent. They have 5 minutes to answer.", "good");
        await load();
      } catch (err) { toast(err.message, "error"); } finally { btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-override]").forEach((btn) => {
    btn.onclick = async () => {
      const reason = await ask({ title: "Waive the distance check?", text: "Only do this if you know the rider is really there. We'll keep your reason on record.",
                                 input: true, minLength: 3, placeholder: "I called the customer, the rider is at their gate", ok: "Waive it" });
      if (!reason) return;
      try {
        await session.api(`/admin/deliveries/${btn.closest(".item").dataset.delivery}/override-location`, { method: "POST", json: { reason } });
        toast("Done. The rider can finish now.", "good");
        await load();
      } catch (err) { toast(err.message, "error"); }
    };
  });
}

// ---------------------------------------------------------------- map
function drawMap() {
  if (!window.L) return;
  if (!map) map = makeMap($("#map"));
  const live = new Set();
  const points = [];
  for (const { delivery: d, ...a } of board.active) {
    live.add(d.id);
    if (d.last_latitude != null) {
      const ll = [d.last_latitude, d.last_longitude];
      points.push(ll);
      if (!riderMarkers[d.id]) riderMarkers[d.id] = L.marker(ll, { icon: dot("#1c7946", "🛵") }).addTo(map);
      riderMarkers[d.id].setLatLng(ll).bindTooltip(`${a.rider_name} · ${a.order_number}`);
    }
    if (d.dropoff_latitude != null) {
      const ll = [d.dropoff_latitude, d.dropoff_longitude];
      points.push(ll);
      if (!dropMarkers[d.id]) dropMarkers[d.id] = L.marker(ll, { icon: dot("#b42318", "🏠") }).addTo(map);
      dropMarkers[d.id].setLatLng(ll).bindTooltip(`${a.customer_name} · ${a.order_number}`);
    }
  }
  for (const id of Object.keys(riderMarkers)) if (!live.has(id)) { riderMarkers[id].remove(); delete riderMarkers[id]; }
  for (const id of Object.keys(dropMarkers)) if (!live.has(id)) { dropMarkers[id].remove(); delete dropMarkers[id]; }
  if (points.length && !map._fitted) { map.fitBounds(points, { padding: [40, 40], maxZoom: 15 }); map._fitted = true; }
  setTimeout(() => map.invalidateSize(), 50);
}

function moveRider(data) {
  const id = String(data.delivery_id);
  if (riderMarkers[id]) riderMarkers[id].setLatLng([data.latitude, data.longitude]);
  else if (board?.active.some((a) => String(a.delivery.id) === id)) {
    riderMarkers[id] = L.marker([data.latitude, data.longitude], { icon: dot("#1c7946", "🛵") }).addTo(map);
  }
}
