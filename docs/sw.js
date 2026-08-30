/* 교통 관제탑 - 서비스 워커
   화면 파일만 캐시합니다. 영상과 API 는 항상 서버에서 새로 받습니다. */

const CACHE = 'gwanje-static-1788119870';
const SHELL = [
  './',
  './index.html',
  './static/css/style.css',
  './static/js/main.js',
  './manifest.webmanifest',
  './static/icons/icon-192.png',
  './static/icons/icon-512.png',
  './data/videos.json',
  './data/places.json'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => Promise.allSettled(SHELL.map((u) => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 영상과 API 는 캐시하지 않습니다. (구간 요청이 깨지는 것을 막습니다)
  if (url.pathname.startsWith('/media/') ||
      url.pathname.startsWith('/api/') ||
      req.headers.has('range')) {
    return;
  }

  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('./')))
  );
});
