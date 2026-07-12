// Service worker for The Hustle - only handles Web Push. No offline
// caching (the game is server-authoritative and needs a live connection
// anyway), so this stays deliberately minimal.

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let data = {title: 'The Hustle', body: 'Something happened.', url: '/'};
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (e) { /* fall back to defaults above */ }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: './icons/icon-192.png',
      badge: './badges/first_blood.png',
      data: {url: data.url || '/'},
      vibrate: [120, 60, 120],
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({type: 'window', includeUncontrolled: true}).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
