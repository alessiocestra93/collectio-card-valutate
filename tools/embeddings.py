"""Firme visive (embedding) delle carte per il riconoscimento da foto.

Uso: python tools/embeddings.py <data_dir> <cache_dir> <model.onnx> [Gioco ...]

- Per ogni carta del catalogo con immagine calcola la firma con lo stesso
  modello (DINOv2 small, ONNX) che l'app usa sul telefono.
- La cache (cache_dir/emb_<Gioco>/) conserva le firme già calcolate:
  ogni notte si calcolano solo le carte nuove.
- Scrive data/emb_<Gioco>.bin (int8, n x D) e data/emb_<Gioco>.json (ids).

Preparazione immagine (identica al JavaScript dell'app):
  ritaglio interno [5%,95%] x [4%,96%] -> 224x224 -> RGB/255 -> normalizzazione ImageNet
"""
import io, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import urllib.request

import numpy as np
from PIL import Image
import onnxruntime as ort

SIZE = 224
INNER = (0.05, 0.04, 0.95, 0.96)
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def prep(im: Image.Image):
    im = im.convert("RGB")
    w, h = im.size
    box = (int(round(w * INNER[0])), int(round(h * INNER[1])), int(round(w * INNER[2])), int(round(h * INNER[3])))
    a = np.asarray(im.crop(box).resize((SIZE, SIZE), Image.BILINEAR), dtype=np.float32) / 255.0
    a = (a - MEAN) / STD
    return a.transpose(2, 0, 1)


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


class Embedder:
    def __init__(self, model):
        so = ort.SessionOptions()
        self.s = ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])
        self.inp = self.s.get_inputs()[0].name
        self.outs = [o.name for o in self.s.get_outputs()]

    def __call__(self, batch):
        res = self.s.run(None, {self.inp: np.stack(batch).astype(np.float32)})
        named = dict(zip(self.outs, res))
        if "pooler_output" in named:
            v = named["pooler_output"]
        else:
            v = res[0]
            if v.ndim == 3:
                v = v[:, 0]
        v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6)
        return v


def run(data_dir, cache_dir, model, game):
    cat_path = os.path.join(data_dir, f"{game}.json")
    if not os.path.exists(cat_path) or not image_url(game, "x"):
        return
    cat = json.load(open(cat_path))
    rows = [r for r in cat["p"] if len(r) > 6 and r[6]]
    cdir = os.path.join(cache_dir, f"emb_{game}")
    os.makedirs(cdir, exist_ok=True)
    ppath, vpath = os.path.join(cdir, "paths.json"), os.path.join(cdir, "vecs.npy")
    cache = {}
    if os.path.exists(ppath) and os.path.exists(vpath):
        paths = json.load(open(ppath)); vecs = np.load(vpath)
        if len(paths) == len(vecs):
            cache = {p: vecs[i] for i, p in enumerate(paths)}
    bad = set(json.load(open(os.path.join(cdir, "bad.json")))) if os.path.exists(os.path.join(cdir, "bad.json")) else set()
    todo = sorted({r[6] for r in rows} - set(cache) - bad)
    print(game, "carte con immagine:", len(rows), "in cache:", len(cache), "da calcolare:", len(todo), flush=True)

    emb = Embedder(model)
    D = None

    def save():
        ps = list(cache.keys())
        if ps:
            np.save(vpath, np.stack([cache[p] for p in ps]).astype(np.int8))
            json.dump(ps, open(ppath, "w"))
        json.dump(sorted(bad), open(os.path.join(cdir, "bad.json"), "w"))

    def load(path):
        b = fetch(image_url(game, path))
        if not b:
            return path, None
        try:
            return path, prep(Image.open(io.BytesIO(b)))
        except Exception:
            return path, None

    t0 = time.time(); done = 0; buf = []

    def flush():
        nonlocal buf
        if not buf:
            return
        v = emb([x for _, x in buf])
        q = np.clip(np.round(v * 127), -127, 127).astype(np.int8)
        for (p, _), row in zip(buf, q):
            cache[p] = row
        buf = []

    with ThreadPoolExecutor(max_workers=24) as ex:
        for path, arr in ex.map(load, todo):
            done += 1
            if arr is None:
                bad.add(path)
            else:
                buf.append((path, arr))
                if len(buf) >= 32:
                    flush()
            if done % 2000 == 0:
                flush(); save()
                print(f"  {done}/{len(todo)} in {time.time()-t0:.0f}s", flush=True)
    flush(); save()

    ids, vs = [], []
    for r in rows:
        v = cache.get(r[6])
        if v is None:
            continue
        ids.append(r[0]); vs.append(v)
    if not vs:
        return
    M = np.stack(vs).astype(np.int8)
    M.tofile(os.path.join(data_dir, f"emb_{game}.bin"))
    json.dump({"n": len(ids), "d": int(M.shape[1]), "ids": ids, "size": SIZE}, open(os.path.join(data_dir, f"emb_{game}.json"), "w"), separators=(",", ":"))
    print(game, "firme scritte:", len(ids), "dimensione:", M.shape, f"{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    data_dir, cache_dir, model = sys.argv[1:4]
    games = sys.argv[4:] or ["Pokemon"]
    for g in games:
        run(data_dir, cache_dir, model, g)
