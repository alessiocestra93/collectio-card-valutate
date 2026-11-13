"""Prezzi minimi CardTrader Zero per carta e lingua (eseguito ogni notte su GitHub).

Uso: CARDTRADER_TOKEN=... python tools/cardtrader.py <data_dir>

Per ogni espansione dei giochi dell'app:
  - /blueprints/export?expansion_id=  -> blueprint -> ID Cardmarket
  - /marketplace/products?expansion_id=&language=XX -> inserzioni piu' economiche
Scrive data/ct_<Gioco>.json:
  {"d": data, "p": {"<idCardmarket>": [blueprint_id, {"it": [minNM, minQualsiasi], ...}]}}
dove i minimi sono in euro e considerano solo le inserzioni vendibili con CardTrader Zero.
"""
import json, os, sys, time, datetime, urllib.request, urllib.error

API = "https://api.cardtrader.com/api/v2"
TOKEN = os.environ.get("CARDTRADER_TOKEN", "").strip()
GAMES = {  # nome nell'app -> parole per riconoscere il gioco su CardTrader
    "Pokemon": ["pokemon", "pokémon"],
    "OnePiece": ["one piece"],
    "DragonBallSuper": ["dragon ball"],
    "Magic": ["magic"],
    "YuGiOh": ["yu-gi-oh", "yugioh"],
    "Lorcana": ["lorcana"],
}
LANGS = ["it", "en", "jp", "fr", "de", "es", "pt"]
NM = {"mint", "near mint"}
_last = [0.0]


def get(path, tries=5):
    for t in range(tries):
        wait = 0.12 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/json", "User-Agent": "collectio-card-valutate/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (t + 1))
                continue
            if e.code in (401, 403):
                raise SystemExit(f"CardTrader: token non valido o senza permessi (HTTP {e.code})")
            return None
        except Exception:
            time.sleep(2 * (t + 1))
    return None


def lang_of(props):
    for k, v in (props or {}).items():
        if k.endswith("language") and isinstance(v, str):
            return v.lower()
    return None


def price_eur(p):
    if isinstance(p.get("price"), dict) and p["price"].get("cents") is not None:
        cur = p["price"].get("currency", "EUR")
        return p["price"]["cents"] / 100.0, cur
    if p.get("price_cents") is not None:
        return p["price_cents"] / 100.0, p.get("price_currency", "EUR")
    return None, None


def main(data_dir):
    if not TOKEN:
        print("CARDTRADER_TOKEN mancante: salto CardTrader")
        return
    info = get("/info")
    print("CardTrader /info:", json.dumps(info)[:200] if info else None)
    games = get("/games") or []
    if isinstance(games, dict):
        games = games.get("array") or games.get("games") or list(games.values())
    print("giochi CardTrader:", [(g.get("id"), g.get("name") or g.get("display_name")) for g in games])
    gid2app = {}
    for g in games:
        name = (g.get("display_name") or g.get("name") or "").lower()
        for app, keys in GAMES.items():
            if any(k in name for k in keys) and app not in gid2app.values():
                gid2app[g["id"]] = app
    print("abbinamento giochi:", gid2app)
    exps = get("/expansions") or []
    exps = [e for e in exps if e.get("game_id") in gid2app]
    print("espansioni da leggere:", len(exps))
    out = {app: {} for app in gid2app.values()}
    t0 = time.time()
    first_dump = True
    for n, e in enumerate(exps):
        app = gid2app[e["game_id"]]
        bps = get(f"/blueprints/export?expansion_id={e['id']}") or []
        bp2cm = {}
        for b in bps:
            ids = b.get("card_market_ids") or []
            if ids:
                bp2cm[b["id"]] = ids
        if not bp2cm:
            continue
        mins = {}
        for lg in LANGS:
            prods = get(f"/marketplace/products?expansion_id={e['id']}&language={lg}")
            if not isinstance(prods, dict):
                continue
            if first_dump and prods:
                k0 = next(iter(prods))
                print("esempio inserzione:", json.dumps((prods[k0] or [None])[0])[:600])
                first_dump = False
            for bid, items in prods.items():
                try:
                    bid = int(bid)
                except ValueError:
                    continue
                if bid not in bp2cm:
                    continue
                for p in items or []:
                    if not p.get("can_sell_via_hub"):
                        continue
                    pl = lang_of(p.get("properties_hash"))
                    if pl and pl[:2] != lg[:2] and not (lg == "jp" and pl in ("ja", "jp")):
                        continue
                    eur, cur = price_eur(p)
                    if eur is None or (cur and cur != "EUR"):
                        continue
                    cond = str((p.get("properties_hash") or {}).get("condition", "")).lower()
                    m = mins.setdefault(bid, {}).setdefault(lg, [None, None])
                    if cond in NM and (m[0] is None or eur < m[0]):
                        m[0] = round(eur, 2)
                    if m[1] is None or eur < m[1]:
                        m[1] = round(eur, 2)
        for bid, cms in bp2cm.items():
            for cm in cms:
                out[app][str(cm)] = [bid, mins.get(bid, {})]
        if (n + 1) % 100 == 0:
            print(f"  {n+1}/{len(exps)} espansioni, {time.time()-t0:.0f}s", flush=True)
    day = datetime.date.today().isoformat()
    for app, p in out.items():
        json.dump({"d": day, "p": p}, open(os.path.join(data_dir, f"ct_{app}.json"), "w"), separators=(",", ":"))
        withp = sum(1 for v in p.values() if v[1])
        print(app, "carte collegate:", len(p), "con prezzo CT Zero:", withp)


if __name__ == "__main__":
    main(sys.argv[1])
