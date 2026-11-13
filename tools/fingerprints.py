"""Calcola le "impronte" visive delle carte per il riconoscimento da foto.

Uso: python tools/fingerprints.py <data_dir> <cache_dir> [--debug-ids id1,id2,...]

- Legge data/<Gioco>.json (catalogo dell'app) e, per le carte con immagine,
  scarica l'immagine e calcola l'impronta.
- La cache (cache_dir/<Gioco>.json) conserva le impronte già calcolate:
  ogni notte si calcolano solo le carte nuove.
- Scrive data/fp_<Gioco>.json per l'app.

Impronta (identica al codice JavaScript dell'app):
  ritaglio interno della carta [5%,95%] x [4%,96%]
  -> 128x128 (media a blocchi) -> scala di grigi
  -> 32x32 (media 4x4) -> DCT 2D -> 8x8 coefficienti -> 64 bit (sopra/sotto la mediana)
  + colore 4x4 RGB (media a blocchi 32x32 del 128x128) = 48 byte
"""
import base64, io, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import urllib.request

import numpy as np
from PIL import Image

N = 32
_k = np.arange(N)
DCT = np.sqrt(2.0 / N) * np.cos(np.pi * (2 * _k[None, :] + 1) * _k[:, None] / (2 * N))
DCT[0, :] = np.sqrt(1.0 / N)

INNER = (0.05, 0.04, 0.95, 0.96)  # x0, y0, x1, y1


def fingerprint(im: Image.Image):
    im = im.convert("RGB")
    w, h = im.size
    box = (int(round(w * INNER[0])), int(round(h * INNER[1])), int(round(w * INNER[2])), int(round(h * INNER[3])))
    a = np.asarray(im.crop(box).resize((128, 128), Image.BOX), dtype=np.float64)
    gray = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    g32 = gray.reshape(32, 4, 32, 4).mean(axis=(1, 3))
    d = DCT @ g32 @ DCT.T
    blk = d[:8, :8].flatten()
    med = np.median(blk[1:])
    bits = (blk > med).astype(np.uint8)
    hb = np.packbits(bits).tobytes()  # 8 byte
    col = a.reshape(4, 32, 4, 32, 3).mean(axis=(1, 3)).round().clip(0, 255).astype(np.uint8).tobytes()  # 48 byte (riga, colonna, rgb)
    return hb + col


def fetch(url, tries=3):
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "collectio-card-valutate/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return r.read()
        except Exception:
            time.sleep(1 + t)
    return None


def image_url(game, path):
    if game == "Pokemon":
        return f"https://assets.tcgdex.net/{path}/low.webp"
    return None


def run(data_dir, cache_dir, game, debug_ids=()):
    cat_path = os.path.join(data_dir, f"{game}.json")
    if not os.path.exists(cat_path):
        return
    cat = json.load(open(cat_path))
    rows = [r for r in cat["p"] if len(r) > 6 and r[6]]
    os.makedirs(cache_dir, exist_ok=True)
    cpath = os.path.join(cache_dir, f"{game}.json")
    cache = json.load(open(cpath)) if os.path.exists(cpath) else {}
    todo = [r for r in rows if r[6] not in cache]
    print(game, "carte con immagine:", len(rows), "in cache:", len(rows) - len(todo), "da calcolare:", len(todo), flush=True)

    def work(r):
        b = fetch(image_url(game, r[6]))
        if not b:
            return r[6], None
        try:
            return r[6], base64.b64encode(fingerprint(Image.open(io.BytesIO(b)))).decode()
        except Exception:
            return r[6], None

    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=32) as ex:
        for path, fp in ex.map(work, todo):
            done += 1
            if fp:
                cache[path] = fp
            else:
                cache.setdefault(path, "")  # immagine non disponibile: non riprovare ogni notte
            if done % 2000 == 0:
                print(f"  {done}/{len(todo)} in {time.time()-t0:.0f}s", flush=True)
                json.dump(cache, open(cpath, "w"))
    json.dump(cache, open(cpath, "w"))

    ids, hs, cs = [], bytearray(), bytearray()
    for r in rows:
        fp = cache.get(r[6])
        if not fp:
            continue
        raw = base64.b64decode(fp)
        ids.append(r[0]); hs += raw[:8]; cs += raw[8:56]
    out = {"n": len(ids), "ids": ids, "h": base64.b64encode(bytes(hs)).decode(), "c": base64.b64encode(bytes(cs)).decode()}
    json.dump(out, open(os.path.join(data_dir, f"fp_{game}.json"), "w"), separators=(",", ":"))
    print(game, "impronte scritte:", len(ids), flush=True)

    if debug_ids:
        os.makedirs("debug_img", exist_ok=True)
        want = set(int(x) for x in debug_ids)
        for r in rows:
            if r[0] in want:
                b = fetch(image_url(game, r[6]))
                if b:
                    open(f"debug_img/{r[0]}.webp", "wb").write(b)


if __name__ == "__main__":
    data_dir, cache_dir = sys.argv[1], sys.argv[2]
    dbg = []
    if "--debug-ids" in sys.argv:
        dbg = sys.argv[sys.argv.index("--debug-ids") + 1].split(",")
    for g in ["Pokemon"]:
        run(data_dir, cache_dir, g, dbg)
