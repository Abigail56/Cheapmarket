// Customer tracking page: /track/<token>. No login; the token in the link is the key.
"use strict";

const token = decodeURIComponent(location.pathname.split("/").pop());
const anon = new Session("cmd.track");  // no tokens: public endpoints only
let liveState = "connecting";
let view = null, map = null, riderMarker = null, dropMarker = null, pinned = null, editing = false;

soundButton($("#sound"));

const STEPS = [
  ["pending", "We got your order"], ["confirmed", "Order confirmed"], ["rider", "A rider is on it"],
  ["out_for_delivery", "On the way to you"], ["arrived", "Rider at your door"], ["delivered", "Delivered"],
];
const STATUS_TEXT = {
  pending: "Received", confirmed: "Confirmed", packed: "Being packed", out_for_delivery: "On the way",
  arrived: "At your door", delivered: "Delivered", cancelled: "Cancelled",
};

async function load() {
  try {
    view = await anon.api(`/track/${encodeURIComponent(token)}`);
    $("#error").classList.add("hidden");
    $("#view").classList.remove("hidden");
    render();
  } catch (err) {
    $("#error").textContent = err.status === 404
      ? "We can't find this tracking link. Please check the text message we sent you."
      : "We can't load your order right now. We'll keep trying.";
    $("#error").classList.remove("hidden");
  }
}

function reached() {
  const d = view.delivery, s = view.status;
  const done = new Set(["pending"]);
  if (["confirmed", "packed", "out_for_delivery", "delivered"].includes(s)) done.add("confirmed");
  if (d && ["accepted", "en_route", "arrived", "delivered"].includes(d.status)) done.add("rider");
  const riding = !d || ["en_route", "arrived", "delivered"].includes(d.status);  // not while finding a new rider
  if (s === "delivered" || (s === "out_for_delivery" && riding)) done.add("out_for_delivery");
  if (d && ["arrived", "delivered"].includes(d.status)) done.add("arrived");
  if (s === "delivered") done.add("delivered");
  return done;
}

// What's happening, said the way a person would say it.
function story() {
  const d = view.delivery, name = d?.rider_name;
  if (view.status === "cancelled") return ["This order was cancelled", "If that's a surprise, please get in touch and we'll sort it out."];
  if (view.status === "delivered") return ["Your order has arrived", "Thanks for shopping with us. Enjoy!"];
  if (d?.status === "arrived") return [`${name || "Your rider"} is at your door`, "Please go and meet them."];
  if (d?.status === "failed" || (view.status === "out_for_delivery" && d?.status === "unassigned")) return ["There's been a delay", "We couldn't complete your delivery just now. We'll be in touch shortly to sort it out."];
  if (view.status === "out_for_delivery" && d?.status === "assigned") return ["We're finding you a new rider", "We'll let you know as soon as they're on it."];
  if (view.status === "out_for_delivery" && d?.status !== "accepted") return [`${name || "Your rider"} is on the way`, "You can follow them on the map below."];
  if (d?.status === "accepted") return [`${name || "A rider"} will bring your order`, "They may call to check your address before setting off."];
  if (view.status === "confirmed" || view.status === "packed") return ["We're getting your order ready", "We'll let you know as soon as a rider picks it up."];
  if (view.payment_method !== "cod" && view.payment_status !== "paid") return ["We're waiting for your payment", "We'll start on your order as soon as it comes through."];
  return ["We got your order", "We'll confirm it shortly."];
}

function timeAt(status) {
  const step = view.timeline.find((t) => t.status === status);
  return step ? new Date(step.at).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "";
}

function render() {
  const d = view.delivery;
  $("#number").textContent = view.order_number;
  const status = d?.status === "arrived" ? "arrived" : view.status;
  $("#status").textContent = STATUS_TEXT[status] || status;
  $("#status").className = `chip ${status}`;
  const [headline, lead] = story();
  $("#headline").textContent = headline;
  $("#lead").textContent = lead;

  if (view.status === "cancelled") {
    $("#steps").innerHTML = `<li class="now">Order cancelled<time>${esc(timeAt("cancelled"))}</time></li>`;
  } else {
    const done = reached();
    const next = STEPS.find(([k]) => !done.has(k))?.[0];
    $("#steps").innerHTML = STEPS.map(([k, label]) =>
      `<li class="${done.has(k) ? "done" : ""} ${k === next ? "now" : ""}"><span>${esc(label)}</span><time>${esc(timeAt(k))}</time></li>`).join("");
  }

  const pos = d?.rider_position;
  const eta = d?.status === "en_route" && d.eta_minutes;
  $("#eta").classList.toggle("hidden", !eta);
  if (eta) $("#eta").textContent = `About ${d.eta_minutes} min away`;

  // the delivery code: what to do with it, right when it matters
  const atDoor = d?.status === "arrived";
  $("#code-card").classList.toggle("hidden", !atDoor);
  if (atDoor) {
    $("#code-title").textContent = d.code_sent ? "Your delivery code is in your texts" : "Your delivery code is coming";
    $("#code-text").textContent = d.code_sent
      ? `Check your items first. When you're happy, type the 6-digit code on ${d.rider_name || "your rider"}'s phone to confirm you got your order.`
      : `${d.rider_name || "Your rider"} will send it in a moment. You'll type it on their phone once you have your items.`;
  }

  const photo = d?.proof_photo_url;
  $("#proof-card").classList.toggle("hidden", !photo);
  if (photo && $("#proof").getAttribute("src") !== photo) {
    $("#proof").src = photo;
    $("#proof-link").href = photo;
  }

  const showRider = d && d.rider_name && ["accepted", "en_route", "arrived"].includes(d.status);
  $("#rider-card").classList.toggle("hidden", !showRider);
  if (showRider) {
    $("#avatar").textContent = d.rider_name[0].toUpperCase();
    $("#rider-line").textContent = `${d.rider_name} is your rider`;
    $("#seen").textContent = pos ? (pos.updated_seconds_ago < 60 ? "Location updated just now" : `Location updated ${Math.floor(pos.updated_seconds_ago / 60)} min ago`) : "";
    $("#call").classList.toggle("hidden", !d.rider_phone);
    if (d.rider_phone) { $("#call").href = `tel:${d.rider_phone}`; $("#call").textContent = `Call ${d.rider_name}`; }
    drawMap();
  }

  const open = !["delivered", "cancelled"].includes(view.status);
  $("#address-card").classList.toggle("hidden", !open);
  $("#address").textContent = view.delivery_address;
  $("#landmark").textContent = [d?.landmark && `Landmark: ${d.landmark}`, d?.notes && `Note: ${d.notes}`].filter(Boolean).join(" · ");
  $("#address-form").classList.toggle("hidden", !view.can_edit_address);
  if (view.can_edit_address && !editing) {  // never overwrite what the customer is typing
    $("#lm").value = d?.landmark || "";
    $("#nt").value = d?.notes || "";
  }

  $("#items").textContent = view.items.map((i) => `${i.quantity} × ${i.name}`).join(", ");
  $("#total").textContent = naira(view.total);
  $("#payment").textContent = view.payment_method === "cod"
    ? (view.payment_status === "paid" ? "Paid on delivery" : "Pay your rider when it arrives")
    : (view.payment_status === "paid" ? "Paid, thank you" : "Waiting for payment");
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
    if (!riderMarker) riderMarker = L.marker(rider, { icon: dot("#1c7946", "🛵") }).addTo(map);
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
    toast("Got it. Tap Save to send your location.", "good");
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
    toast("Saved. Your rider will see this.", "good");
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

load();
adaptivePoll(load, () => liveState === "live");
