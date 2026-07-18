"use strict";

/* Cache tĩnh tối thiểu cho app shell — không bao giờ cache /api/*. */

const CACHE_NAME = "bnn-shell-v19";
const SHELL_URLS = ["/", "/app.css", "/app.js", "/manifest.webmanifest", "/icon.svg"];

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
  // Dashboard cán bộ luôn lấy bản mới nhất — tránh CSS/JS cũ dính cache khi đang chỉnh sửa
  if (url.pathname.startsWith("/officer")) return;

  // Dashboard cán bộ thay đổi thường xuyên và không tự nạp app.js của PWA chính.
  // Ưu tiên mạng để tránh trả index/JS/CSS cũ; cache chỉ dùng khi thực sự offline.
  if (url.pathname.startsWith("/officer")) {
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
