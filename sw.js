// Collectio: tiene salvati sul telefono i file pesanti (lettore, modello, firme)
// così ogni apertura dell'app è immediata, anche dopo aver chiuso il browser.
const STATIC = "collectio-static-v1";   // file che non cambiano (lettore, modello)
const DATA = "collectio-data-v1";       // cataloghi e firme: si usano subito e si aggiornano dietro le quinte
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (![STATIC, DATA].includes(k)) await caches.delete(k);
  await self.clients.claim();
})()));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  const p = u.pathname;
  if (/\/(vendor|models|ocr|assets)\//.test(p)) e.respondWith(cacheFirst(e.request));
  else if (/\/data\//.test(p)) e.respondWith(staleWhileRevalidate(e.request, e));
  else e.respondWith(networkFirst(e.request));
});
async function cacheFirst(req) {
  const c = await caches.open(STATIC);
  const hit = await c.match(req, { ignoreSearch: true });
  if (hit) return hit;
  const r = await fetch(req);
  if (r.ok) c.put(req, r.clone());
  return r;
}
async function staleWhileRevalidate(req, e) {
  const c = await caches.open(DATA);
  const hit = await c.match(req, { ignoreSearch: true });
  const net = fetch(req).then(r => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => null);
  if (hit) { e.waitUntil(net); return hit; }
  return (await net) || new Response("", { status: 504 });
}
async function networkFirst(req) {
  const c = await caches.open(DATA);
  try {
    const r = await fetch(req, { cache: "no-store" });
    if (r.ok) c.put(req, r.clone());
    return r;
  } catch (err) {
    const hit = await c.match(req, { ignoreSearch: true });
    if (hit) return hit;
    throw err;
  }
}
