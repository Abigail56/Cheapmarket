// New-order alarm on the admin dashboard: rings until someone stops it, on every tab of the page.
// The board is checked as well as the live events, so an order placed while the connection
// dropped or the page was closed still rings. Stopped orders are remembered on this device.
"use strict";

const OrderAlarm = (() => {
  const RING_EVERY_MS = 5000;  // the "alert" siren lasts about 3.5 seconds
  const STORE_KEY = "cmd.alarm.stopped";
  const pending = new Map();   // order number -> { order_number, total, payment_method }
  let timer = null;

  let stopped = [];
  try { stopped = JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch { /* private mode: this page only */ }
  function remember(numbers) {
    stopped = [...stopped, ...numbers].slice(-300);
    try { localStorage.setItem(STORE_KEY, JSON.stringify(stopped)); } catch { /* as above */ }
  }

  function paint() {
    const banner = $("#order-alarm");
    banner.classList.toggle("hidden", !pending.size);
    if (!pending.size) return;
    const orders = [...pending.values()];
    if (orders.length > 1) {
      $("#order-alarm-text").textContent = `${orders.length} new orders are waiting`;
    } else {
      const [o] = orders;
      const waiting = o.payment_method === "card" ? " (card payment not finished yet)" : "";
      $("#order-alarm-text").textContent = `New order ${o.order_number} · ${naira(o.total)} · ${PAY_WORDS[o.payment_method] || o.payment_method}${waiting}`;
    }
  }

  function ringing() {
    if (pending.size && !timer) {
      Sound.play("alert");
      timer = setInterval(() => Sound.play("alert"), RING_EVERY_MS);
    } else if (!pending.size && timer) {
      clearInterval(timer);
      timer = null;
    }
    paint();
  }

  function add(order) {
    if (!order?.order_number || stopped.includes(order.order_number)) return;
    pending.set(order.order_number, order);
    ringing();
  }

  // Called with the board's new orders each time it loads
  function sync(newOrders) {
    const onBoard = new Set(newOrders.map((o) => o.order_number));
    // Someone dealt with it. A card order also leaves the list by itself once paid, and that one should keep ringing.
    for (const [number, o] of pending) {
      if (!onBoard.has(number) && o.payment_method !== "card") pending.delete(number);
    }
    newOrders.forEach(add);
    ringing();
  }

  function stop() {
    remember([...pending.keys()]);
    pending.clear();
    ringing();
  }

  // Browsers keep a page silent until it's clicked, so say so rather than failing quietly
  function soundNote() {
    const note = $("#alarm-sound-note");
    const text = !Sound.enabled ? "The order alarm is muted. Tap the speaker at the top to turn it back on."
      : Sound.ctx?.state !== "running" ? "Click anywhere on this page to turn on the order alarm." : "";
    note.textContent = text;
    note.classList.toggle("hidden", !text);
  }

  $("#order-alarm-stop").onclick = () => {
    stop();
    showView("deliveries");
    $("#new-orders").scrollIntoView({ behavior: "smooth", block: "center" });
  };
  setInterval(soundNote, 1000);
  soundNote();

  return { add, sync, stop };
})();
