// Customer tracking page: /track/<token>. No login; the token in the link is the key.
"use strict";

const token = decodeURIComponent(location.pathname.split("/").pop());
const anon = new Session("cmd.track");  // no tokens: public endpoints only
let liveState = "connecting";
let view = null, map = null, riderMarker = null, dropMarker = null, pinned = null, editing = false;

const STEPS = [
  ["pending", "Order placed"], ["confirmed", "Confirmed"], ["rider", "Rider assigned"],
  ["out_for_delivery", "On the way"], ["arrived", "Rider has arrived"], ["delivered", "Delivered"],
];
const STATUS_TEXT = {
  pending: "Placed", confirmed: "Confirmed", packed: "Being packed", out_for_delivery: "On the way",
  delivered: "Delivered", cancelled: "Cancelled",
};

async function load() {
  try {
    view = await anon.api(`/track/${encodeURIComponent(token)}`);
    $("#error").classList.add("hidden");
    $("#view").classList.remove("hidden");
    render();
  } catch (err) {
    $("#error").textContent = err.status === 404 ? "We couldn't find this tracking link. Check the SMS we sent you." : err.message;
    $("#error").classList.remove("hidden");
  }
}

function reached() {
  const d = view.delivery, s = view.status;
  const done = new Set(["pending"]);
  if (["confirmed", "packed", "out_for_delivery", "delivered"].includes(s)) done.add("confirmed");
  if (d && !["unassigned"].includes(d.status) && d.rider_name) done.add("rider");
  if (["out_for_delivery", "delivered"].includes(s)) done.add("out_for_delivery");
  if (d && ["arrived", "delivered"].includes(d.status)) done.add("arrived");
  if (s === "delivered") done.add("delivered");
  return done;
}

function render() {
  const d = view.delivery;
  $("#number").textContent = view.order_number;
  const status = d?.status === "arrived" ? "arrived" : view.status;
  $("#status").textContent = d?.status === "arrived" ? "Rider has arrived" : (STATUS_TEXT[view.status] || view.status);
  $("#status").className = `chip ${status}`;

  if (view.status === "cancelled") {
    $("#steps").innerHTML = `<li class="now">This order was cancelled</li>`;
  } else {
    const done = reached();
    const next = STEPS.find(([k]) => !done.has(k))?.[0];
    $("#steps").innerHTML = STEPS.map(([k, label]) =>
      `<li class="${done.has(k) ? "done" : ""} ${k === next ? "now" : ""}">${esc(label)}</li>`).join("");
  }

  const pos = d?.rider_position;
  $("#eta").classList.toggle("hidden", !(d && (d.eta_minutes || d.status === "arrived")));
  if (d?.status === "arrived") { $("#eta-text").textContent = "Your rider is at the door"; $("#seen").textContent = "They'll ask for the code we texted you."; }
  else if (d?.eta_minutes) { $("#eta-text").textContent = `About ${d.eta_minutes} min away`; $("#seen").textContent = pos ? `Updated ${pos.updated_seconds_ago}s ago` : ""; }

  const showRider = d && d.rider_name && ["accepted", "en_route", "arrived", "delivered"].includes(d.status);
  $("#rider-card").classList.toggle("hidden", !showRider);
  if (showRider) {
    $("#rider-line").textContent = d.status === "delivered" ? `Delivered by ${d.rider_name}` : `${d.rider_name} is your rider`;
    $("#call").classList.toggle("hidden", !d.rider_phone);
    if (d.rider_phone) $("#call").href = `tel:${d.rider_phone}`;
    drawMap();
  }

  $("#address-card").classList.remove("hidden");
  $("#address").textContent = view.delivery_address;
  $("#landmark").textContent = [d?.landmark && `Landmark: ${d.landmark}`, d?.notes && `Notes: ${d.notes}`].filter(Boolean).join(" · ");
  const form = $("#address-form");
  form.classList.toggle("hidden", !view.can_edit_address);
  if (view.can_edit_address && !editing) {  // never overwrite what the customer is typing
    $("#lm").value = d?.landmark || "";
    $("#nt").value = d?.notes || "";
  }

  $("#items").textContent = view.items.map((i) => `${i.quantity} × ${i.name}`).join(", ");
  $("#total").textContent = naira(view.total);
  $("#payment").textContent = view.payment_method === "cod"
    ? (view.payment_status === "paid" ? "Paid on delivery" : "Pay the rider on delivery")
    : (view.payment_status === "paid" ? "Paid" : "Awaiting payment");
}

function drawMap() {
  if (!window.L) return;
  const d = view.delivery;
  const drop = d.dropoff ? [d.dropoff.latitude, d.dropoff.longitude] : null;
  const rider = d.rider_position ? [d.rider_position.latitude, d.rider_position.longitude] : null;
  $("#map").classList.toggle("hidden", !drop && !rider);
  if (!drop && !rider) return;
  if (!map) map = makeMap($("#map"), rider || drop, 15);
  if (drop) {
    if (!dropMarker) dropMarker = L.marker(drop, { icon: dot("#b42318", "🏠") }).addTo(map);
    else dropMarker.setLatLng(drop);
  }
  if (rider) {
    if (!riderMarker) riderMarker = L.marker(rider, { icon: dot("#1f8a4c", "🛵") }).addTo(map);
    else riderMarker.setLatLng(rider);
  }
  const pts = [drop, rider].filter(Boolean);
  if (pts.length === 2) map.fitBounds(pts, { padding: [40, 40], maxZoom: 16 });
  setTimeout(() => map.invalidateSize(), 50);
}

$("#address-form").addEventListener("input", () => { editing = true; });

$("#pin-me").onclick = async () => {
  try {
    const p = await currentPosition();
    pinned = [p.latitude, p.longitude];
    toast("Location added. Press Save to send it.", "good");
  } catch (err) { toast(err.message, "error"); }
};

$("#address-form").onsubmit = async (e) => {
  e.preventDefault();
  const body = { landmark: $("#lm").value.trim() || null, notes: $("#nt").value.trim() || null };
  if (pinned) Object.assign(body, { latitude: pinned[0], longitude: pinned[1] });
  try {
    view = await anon.api(`/track/${encodeURIComponent(token)}/address`, { method: "POST", json: body });
    pinned = null;
    editing = false;
    render();
    toast("Saved. Your rider will see it.", "good");
  } catch (err) { toast(err.message, "error"); }
};

liveEvents(`/track/${encodeURIComponent(token)}/events`, (type, data) => {
  if (type === "rider.location" && view?.delivery) {
    view.delivery.rider_position = { latitude: data.latitude, longitude: data.longitude, updated_seconds_ago: 0 };
    if (data.eta_minutes) view.delivery.eta_minutes = data.eta_minutes;
    render();
    return;
  }
  if (type === "delivery.arrived") Sound.play("alert");
  load();
}, { onState: (s) => { liveState = s; $("#live").classList.toggle("live", s === "live"); } });

document.addEventListener("click", () => Sound.unlock(), { once: true });
load();
adaptivePoll(load, () => liveState === "live");
