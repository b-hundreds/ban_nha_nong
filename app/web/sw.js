"use strict";

/* Cache tĩnh tối thiểu cho app shell — không bao giờ cache /api/*. */

const CACHE_NAME = "bnn-shell-v26";
const SHELL_URLS = [
  "/chat?app=v26",
  "/app.css?v=26",
  "/app.js?v=26",
  "/manifest.webmanifest",
  "/icon.svg",
];
const CHAT_SHELL_PATHS = new Set(["/chat", "/app.css", "/app.js"]);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/")) return; // luôn qua mạng, không cache dữ liệu động
  // Dashboard cán bộ luôn lấy bản mới nhất.
  if (url.pathname.startsWith("/officer")) return;

  // HTML/CSS/JS của chat phải network-first. Cache-first từng làm code trước
  // merge đè code mới: composer trôi khỏi viewport và thẻ liều bị ẩn.
  if (request.mode === "navigate" || CHAT_SHELL_PATHS.has(url.pathname)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
