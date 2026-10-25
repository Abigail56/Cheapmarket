// Admin live board: who needs a rider, what's on the road, where the riders are, with sound.
"use strict";

const session = new Session("cmd.admin");
let board = null, map = null, stopEvents = null, ticker = null;
let liveState = "connecting", stopPoll = null;
const riderMarkers = {};   // delivery id -> marker
const dropMarkers = {};

const STATUS_TEXT = {
  assigned: "Waiting for rider to accept", accepted: "Accepted: confirming address",
  en_route: "On the way", arrived: "At the door",
};

const ID_TYPES = { nin: "NIN", drivers_licence: "Driver's licence", voters_card: "Voter's card", passport: "Passport" };
const ID_CHECK = {
  pending: ["⏳ Checking ID…", "assigned"],
  verified: ["✅ ID verified", "delivered"],
  review: ["⚠️ Needs a close look", "arrived"],
  failed: ["❌ ID not found", "failed"],
  manual: ["🔎 Check ID by hand", "accepted"],
  error: ["⚠️ Check didn't run", "unassigned"],
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
  "order.placed": ["good", (d) => `New order ${d.order_number} (${naira(d.total)})`],
  "delivery.accepted": ["info", (d) => `${d.rider_name} accepted a delivery`],
  "delivery.declined": ["alert", (d) => `${d.rider_name} declined ${d.order_number}${d.reason ? `: ${d.reason}` : ""}. Reassign it.`],
  "delivery.expired": ["alert", () => "A rider didn't answer in time. Reassign the order."],
  "delivery.code_wrong": ["alert", (d) => `Wrong delivery code entered (${d.attempts} tries)`],
  "delivery.failed": ["alert", (d) => `Delivery ${d.order_number} failed: ${d.reason}`],
  "delivery.delivered": ["good", (d) => `${d.order_number} delivered by ${d.rider_name}`],
  "delivery.address_corrected": ["info", () => "A customer corrected their address"],
  "delivery.started": ["info", () => "A rider started a journey"],
  "delivery.arrived": ["info", () => "A rider arrived at the customer"],
  "rider.applied": ["alert", (d) => `New rider application: ${d.full_name} (${d.vehicle_type}${d.area ? `, ${d.area}` : ""})`],
  "rider.approved": ["info", (d) => `${d.full_name} approved as a rider`],
  "rider.id_checked": ["info", (d) => `ID check for ${d.full_name}: ${(ID_CHECK[d.status] || [d.status])[0]}`],
};

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
    showLogin(err.status === 403 ? "Only admins can open the live board." : err.message);
    return;
  }
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  $("#logout").classList.remove("hidden");
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
}

// ---------------------------------------------------------------- events
let reloadTimer = null;
function onEvent(type, data) {
  if (type === "rider.location") { moveRider(data); return; }
  const rule = SOUNDS[type];
  if (rule) {
    Sound.play(rule[0]);
    feed(rule[1](data), rule[0]);
  } else if (type === "order.status_changed") {
    feed(`${data.order_number}: ${data.previous} → ${data.status}`, "info");
  }
  clearTimeout(reloadTimer);  // several events often arrive together: one reload
  reloadTimer = setTimeout(() => load().catch(() => {}), 300);
}

function feed(text, kind) {
  $("#feed-empty")?.remove();
  const el = document.createElement("div");
  el.className = kind === "info" ? "" : kind;
  el.textContent = `${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })} · ${text}`;
  $("#feed").prepend(el);
  while ($("#feed").children.length > 100) $("#feed").lastChild.remove();
}

// ---------------------------------------------------------------- render
function count(id, n) { const el = $(id); el.textContent = n; el.classList.toggle("zero", !n); }

function riderOptions(current) {
  return board.riders.map((r) =>
    `<option value="${esc(r.id)}" ${r.id === current ? "selected" : ""}>${esc(r.name)}${r.busy ? " (busy)" : ""}</option>`).join("");
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
      <div class="row"><strong>${esc(a.full_name)}</strong><span class="muted">${esc(ago(a.applied_at))}</span></div>
      <div class="muted">${esc(a.vehicle_type)}${a.plate_number ? ` · ${esc(a.plate_number)}` : ""}${a.area ? ` · ${esc(a.area)}` : ""}</div>
      <div class="muted">${a.phone ? `<a href="tel:${esc(a.phone)}">${esc(a.phone)}</a> · ` : ""}${esc(a.email)}</div>
      ${a.note ? `<div class="muted">“${esc(a.note)}”</div>` : ""}
      ${a.id_type ? `<div class="muted">🪪 ${esc(ID_TYPES[a.id_type] || a.id_type)}: <strong>${esc(a.id_number || "")}</strong></div>` : ""}
      <div class="row" style="margin-top:6px">
        <span class="chip ${esc((ID_CHECK[a.id_check_status] || [])[1] || "")}">${esc((ID_CHECK[a.id_check_status] || [a.id_check_status])[0])}</span>
        ${a.id_face_match != null ? `<span class="muted">Face ${esc(Math.round(a.id_face_match))}%</span>` : ""}
        ${a.id_name_match != null ? `<span class="muted">Name ${esc(a.id_name_match)}%</span>` : ""}
      </div>
      ${a.id_record_name ? `<div class="muted">Name on record: <strong>${esc(a.id_record_name)}</strong></div>` : ""}
      ${(a.id_check_reasons || []).length ? `<ul class="reasons">${a.id_check_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      <div class="docs">${(a.documents || []).map((d) => `
        <button type="button" class="doc" data-doc="${esc(d.id)}" data-type="${esc(d.content_type)}" title="${esc(DOC_NAMES[d.kind] || d.kind)}">
          ${d.content_type === "application/pdf" ? "📄 PDF" : "Loading…"}<span>${esc(DOC_NAMES[d.kind] || d.kind)}</span>
        </button>`).join("")}</div>
      <div class="row" style="margin-top:8px">
        <button class="small" data-approve data-check="${esc(a.id_check_status)}">Approve</button>
        <button class="small secondary" data-recheck>Check again</button>
        <button class="small danger" data-reject>Reject</button>
      </div>
    </div>`).join("");
  count("#n-waiting", board.needs_rider.length);
  count("#n-active", board.active.length);
  const noRiders = !board.riders.length;
  $("#waiting").innerHTML = board.needs_rider.length ? board.needs_rider.map((o) => `
    <div class="item" data-order="${esc(o.order_number)}">
      <div class="row"><strong>${esc(o.order_number)}</strong><span class="muted">${esc(ago(o.placed_at))}</span></div>
      <div class="muted">${esc(o.customer_name)} · ${naira(o.total)} · ${esc(o.payment_method.toUpperCase())}</div>
      <div class="muted">${esc(o.delivery_address)}</div>
      <div class="row" style="margin-top:8px">
        <select data-rider ${noRiders ? "disabled" : ""}>${noRiders ? "<option>No active riders</option>" : riderOptions()}</select>
        <button class="small" data-assign ${noRiders ? "disabled" : ""}>Assign</button>
      </div>
    </div>`).join("") : `<p class="muted">Nothing waiting. 🎉</p>`;

  $("#active").innerHTML = board.active.length ? board.active.map(({ delivery: d, ...a }) => `
    <div class="item" data-delivery="${esc(d.id)}" data-order="${esc(a.order_number)}">
      <div class="row"><strong>${esc(a.order_number)}</strong><span class="chip ${esc(d.status)}">${esc(STATUS_TEXT[d.status] || d.status)}</span></div>
      <div class="muted">🛵 ${esc(a.rider_name)}${a.rider_phone ? ` · <a href="tel:${esc(a.rider_phone)}">${esc(a.rider_phone)}</a>` : ""}</div>
      <div class="muted">${esc(a.customer_name)} · ${esc(a.delivery_address)}</div>
      ${d.status === "assigned" ? `<div class="countdown" data-deadline="${esc(d.accept_deadline)}"></div>` : ""}
      ${d.status === "accepted" && !d.address_confirmed_at ? `<div class="muted">Address not confirmed yet</div>` : ""}
      ${d.last_location_at ? `<div class="muted">Last GPS ${esc(ago(d.last_location_at))}</div>` : ""}
      ${d.code_sent_at ? `<div class="muted">Delivery code sent ${esc(ago(d.code_sent_at))}</div>` : ""}
      ${d.geofence_override_at ? `<div class="muted">Location check waived: ${esc(d.geofence_override_reason)}</div>` : ""}
      <div class="row" style="margin-top:8px">
        <select data-rider>${riderOptions(d.rider_id)}</select><button class="small secondary" data-assign>Reassign</button>
        ${["accepted", "en_route", "arrived"].includes(d.status) && !d.geofence_override_at
          ? `<button class="small secondary" data-override>Waive location check</button>` : ""}
      </div>
    </div>`).join("") : `<p class="muted">No deliveries on the road.</p>`;

  $("#riders").textContent = `${board.riders.length} active rider(s), ${board.riders.filter((r) => r.busy).length} busy`;
  document.querySelectorAll(".item[data-order]").forEach((el) => {
    const sel = $("[data-rider]", el);
    if (!sel) return;
    if (picked[el.dataset.order]) { sel.value = picked[el.dataset.order]; sel.dataset.touched = "1"; }
    sel.addEventListener("change", () => { sel.dataset.touched = "1"; });
  });
  wire();
  drawMap();
  tick();
}

function tick() {
  document.querySelectorAll("[data-deadline]").forEach((el) => {
    const left = Math.max(0, Math.round((new Date(el.dataset.deadline) - Date.now()) / 1000));
    el.textContent = left ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} for the rider to accept` : "No answer: will come back here";
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
      } catch { btn.firstChild.textContent = "⚠️"; }
    }
  });
  document.querySelectorAll("[data-approve]").forEach((btn) => {
    btn.onclick = async () => {
      const item = btn.closest(".item");
      const status = btn.dataset.check;
      const warning = status === "verified" ? ""
        : `\n\n⚠️ Their ID is NOT verified (${(ID_CHECK[status] || [status])[0].replace(/^\S+ /, "")}). Make sure you've checked the ID photo against the selfie and details yourself.`;
      if (!confirm(`Approve ${$("strong", item).textContent} as a rider? They'll be able to sign in and take deliveries.${warning}`)) return;
      btn.disabled = true;
      try {
        await session.api(`/admin/rider-applications/${item.dataset.app}/approve`, { method: "POST" });
        toast("Approved. They've been sent an SMS.", "good");
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
      } catch (err) { toast(err.message, "error"); btn.disabled = false; btn.textContent = "Check again"; }
    };
  });
  document.querySelectorAll("[data-reject]").forEach((btn) => {
    btn.onclick = async () => {
      const item = btn.closest(".item");
      const reason = prompt("Reason (the applicant will see this by SMS):", "We're not taking new riders in your area right now.");
      if (!reason || reason.trim().length < 3) return;
      try {
        await session.api(`/admin/rider-applications/${item.dataset.app}/reject`, { method: "POST", json: { reason: reason.trim() } });
        toast("Rejected. They've been sent an SMS.");
        await load();
      } catch (err) { toast(err.message, "error"); }
    };
  });
  document.querySelectorAll("[data-assign]").forEach((btn) => {
    btn.onclick = async () => {
      const item = btn.closest(".item");
      const riderId = $("[data-rider]", item).value;
      btn.disabled = true;
      try {
        await session.api(`/admin/orders/${encodeURIComponent(item.dataset.order)}/assign-rider`, { method: "POST", json: { rider_id: riderId } });
        toast("Offered to the rider. They have 5 minutes to accept.", "good");
        await load();
      } catch (err) { toast(err.message, "error"); } finally { btn.disabled = false; }
    };
  });
  document.querySelectorAll("[data-override]").forEach((btn) => {
    btn.onclick = async () => {
      const reason = prompt("Why waive the location check? (e.g. called the customer, rider is at the gate)");
      if (!reason || reason.trim().length < 3) return;
      try {
        await session.api(`/admin/deliveries/${btn.closest(".item").dataset.delivery}/override-location`, { method: "POST", json: { reason: reason.trim() } });
        toast("Location check waived (recorded in the audit log)", "good");
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
      if (!riderMarkers[d.id]) riderMarkers[d.id] = L.marker(ll, { icon: dot("#1f8a4c", "🛵") }).addTo(map);
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
    riderMarkers[id] = L.marker([data.latitude, data.longitude], { icon: dot("#1f8a4c", "🛵") }).addTo(map);
  }
}
