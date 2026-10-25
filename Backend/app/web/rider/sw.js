// Makes the rider app installable and opens it instantly. API calls always go to the
// network (deliveries must be live), only the app's own files are cached.
const CACHE = "cmd-rider-v2";
const SHELL = ["/rider/", "/rider/rider.js", "/static/common.js", "/static/common.css",
               "/rider/icon.svg", "/rider/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // network first so updates arrive, cache when offline
  e.respondWith(fetch(e.request).then((res) => {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(e.request, copy));
    return res;
  }).catch(() => caches.match(e.request)));
});

// ---------------------------------------------------------------- push alerts
// Arrives even when the app is closed. Browsers don't let a site pick the notification
// sound (the phone's own alert sound plays), so the alert stays on screen until tapped
// and vibrates hard. When the app is open on screen it plays its own sharp beep instead.
self.addEventListener("push", (e) => {
  let msg = {};
  try { msg = e.data ? e.data.json() : {}; } catch { msg = { body: e.data && e.data.text() }; }
  const title = msg.title || "Cheapmarketdeal Rider";
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const onScreen = wins.find((w) => w.visibilityState === "visible");
    if (onScreen) {
      onScreen.postMessage({ type: "push", msg });  // the open app beeps and refreshes
      return;
    }
    await self.registration.showNotification(title, {
      body: msg.body || "",
      tag: msg.tag || "rider",
      renotify: true,              // a repeat with the same tag alerts again
      requireInteraction: true,    // stays until the rider taps it
      silent: false,
      vibrate: [400, 100, 400, 100, 400, 100, 800],
      icon: "/rider/icon.svg",
      badge: "/rider/icon.svg",
      data: { url: msg.url || "/rider/" },
    });
  })());
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "/rider/", self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = wins.find((w) => w.url.startsWith(self.location.origin + "/rider"));
    if (open) { await open.focus(); open.postMessage({ type: "refresh" }); return; }
    await self.clients.openWindow(url);
  })());
});

// The browser can rotate a subscription; re-register it with the server.
self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil(self.clients.matchAll({ type: "window" }).then((wins) =>
    wins.forEach((w) => w.postMessage({ type: "resubscribe" }))));
});
