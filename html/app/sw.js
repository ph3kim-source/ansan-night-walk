/* 안산 밤길 — 설치형 웹앱 저장소(service worker, 수정사항 #31)
   앱 파일(화면 · 자료 · 아이콘 · Leaflet)을 저장해 인터넷이 끊겨도 앱이 열리게 한다.
   지도 바탕(OpenStreetMap · 브이월드 타일)은 저장하지 않는다 — 타일 이용 정책 · 용량.
   363322b17b 은 build_app.py 가 만들 때마다 바꿔 넣는다 → 새 판이 올라가면 예전 저장분을 지운다. */
const VERSION = "363322b17b";
const CACHE = "ansan-night-" + VERSION;
const SHELL = ["./", "./index.html", "./app.css", "./app.js", "./data.js", "./manifest.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/icon-maskable-512.png", "./icons/apple-touch-icon.png",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k.startsWith("ansan-night-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const u = new URL(e.request.url);
  if (/tile\.openstreetmap\.org$|vworld\.kr$/.test(u.hostname)) return;          // 지도 바탕은 그때그때 받는다
  e.respondWith(caches.match(e.request, {ignoreSearch: true}).then(r => r || fetch(e.request)));
});
