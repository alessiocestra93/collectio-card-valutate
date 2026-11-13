// Ponte CardTrader per Collectio Card Valutate.
// Il token resta qui come segreto (CT_TOKEN), mai nel sito.
const ALLOWED = ["/games", "/expansions", "/blueprints/export", "/marketplace/products"];
const ORIGINS = ["https://alessiocestra93.github.io"];

export default {
  async fetch(req, env, ctx) {
    const origin = req.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0],
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "*",
      "Vary": "Origin",
    };
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    const url = new URL(req.url);
    if (req.method !== "GET" || !ALLOWED.includes(url.pathname))
      return new Response("non permesso", { status: 403, headers: cors });
    if (!env.CT_TOKEN) return new Response("manca CT_TOKEN", { status: 500, headers: cors });

    // espansioni e carte cambiano poco: cache 12 ore; prezzi: 2 minuti
    const ttl = url.pathname === "/marketplace/products" ? 120 : 43200;
    const cache = caches.default;
    const key = new Request(url.toString());
    let res = await cache.match(key);
    if (!res) {
      const up = await fetch("https://api.cardtrader.com/api/v2" + url.pathname + url.search, {
        headers: { Authorization: "Bearer " + env.CT_TOKEN },
      });
      res = new Response(up.body, up);
      res.headers.set("Cache-Control", "public, max-age=" + ttl);
      if (up.ok) ctx.waitUntil(cache.put(key, res.clone()));
    }
    const out = new Response(res.body, res);
    for (const [k, v] of Object.entries(cors)) out.headers.set(k, v);
    return out;
  },
};
