"""Build compact per-game card catalogs for the Valutatore app.

Usage: python3 build.py <srcdir> <tcgdex_dir> <outdir>
srcdir holds p{N}.json (singles), ns{N}.json (non-singles), pg{N}.json (price guide).
"""
import json, os, re, sys, glob, html
from collections import Counter, defaultdict

SRC, TCGDEX, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
GAMES = {6: "Pokemon", 18: "OnePiece", 13: "DragonBallSuper", 1: "Magic", 3: "YuGiOh", 19: "Lorcana"}

SUFFIX = re.compile(r"\b(booster|box|display|pack|deck|bundle|tin|case|collection|starter|set|kit|blister|elite|trainer|premium|prerelease|sleeved|jumbo|draft|play|collector|set|commander|theme|gift|bundle|binder|checklane|build|battle|sealed)\b.*$", re.I)

def norm(t):
    return re.sub(r"\s+", " ", t).strip()

def expansion_names(ns_path):
    """Guess expansion names from sealed product names (word-level common prefix)."""
    try:
        prods = json.load(open(ns_path))["products"]
    except Exception:
        return {}
    by = defaultdict(list)
    for p in prods:
        if p.get("idExpansion"):
            by[p["idExpansion"]].append(p["name"])
    out = {}
    for e, names in by.items():
        if len(names) >= 2:
            ws = [n.split() for n in names]
            pref = []
            for col in zip(*ws):
                if all(c == col[0] for c in col):
                    pref.append(col[0])
                else:
                    break
            cand = " ".join(pref)
        else:
            cand = ""
        if len(cand) < 3:
            # most common stripped name
            c = Counter(norm(SUFFIX.sub("", n)) for n in names)
            cand = c.most_common(1)[0][0] if c else ""
        cand = re.sub(r"[\s:\-–|]+$", "", cand)
        if len(cand) >= 3:
            out[e] = html.unescape(cand)
    return out

# ---------- TCGdex (Pokémon) ----------
def block(src, key):
    m = re.search(key + r"\s*:\s*\{([^{}]*)\}", src)
    if not m:
        m2 = re.search(key + r'\s*:\s*["\']([^"\']*)["\']', src)
        return {"en": m2.group(1)} if m2 else {}
    return {k: (a or b) for k, a, b in re.findall(r"""(\w[\w-]*)\s*:\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""", m.group(1))}

SETS = {}
def load_set(path):
    if path in SETS:
        return SETS[path]
    info = {}
    try:
        s = open(path, encoding="utf-8").read()
        info["name"] = block(s, "name")
        mid = re.search(r"""\bid\s*:\s*["']([^"']+)["']""", s)
        info["id"] = mid.group(1) if mid else ""
        ab = re.search(r"abbreviations\s*:\s*\{([^}]*)\}", s)
        info["abbr"] = (re.findall(r'official\s*:\s*["\']([^"\']+)["\']', ab.group(1)) or [""])[0] if ab else ""
        cm = re.search(r"thirdParty\s*:\s*\{[^}]*cardmarket\s*:\s*(\d+)", s)
        info["cm"] = int(cm.group(1)) if cm else 0
        cc = re.search(r"official\s*:\s*(\d+)", s[s.find("cardCount"):] if "cardCount" in s else "")
        info["count"] = cc.group(1) if cc else ""
    except Exception:
        pass
    SETS[path] = info
    return info

def tcgdex_map():
    res = {}  # idProduct -> dict
    exp_names = {}
    for root in ("data", "data-asia"):
        for f in glob.glob(os.path.join(TCGDEX, root, "*", "*", "*.ts")):
            try:
                s = open(f, encoding="utf-8").read()
            except Exception:
                continue
            ids = [int(x) for x in re.findall(r"cardmarket\s*:\s*(\d+)", s)]
            if not ids:
                continue
            ctmap = {}
            for blk in re.findall(r"thirdParty\s*:\s*\{([^}]*)\}", s):
                cm_ = re.search(r"cardmarket\s*:\s*(\d+)", blk); ct_ = re.search(r"cardtrader\s*:\s*(\d+)", blk)
                if cm_ and ct_:
                    ctmap[int(cm_.group(1))] = int(ct_.group(1))
            setpath = os.path.dirname(f) + ".ts"
            st = load_set(setpath)
            nm = block(s, "name")
            num = os.path.splitext(os.path.basename(f))[0]
            sname = st.get("name", {})
            sen = sname.get("en") or sname.get("ja") or next(iter(sname.values()), "")
            if st.get("cm") and sname.get("en"):
                exp_names[st["cm"]] = sname["en"]
            serie = load_set(os.path.dirname(setpath) + ".ts")
            sid = os.path.basename(os.path.dirname(setpath)) if root == "data-asia" else serie.get("id", "")
            img = ("ja/" if root == "data-asia" else "en/") + "/".join([sid, st.get("id", ""), num]) if sid and st.get("id") else ""
            for i in ids:
                res.setdefault(i, {
                    "img": img,
                    "en": nm.get("en", ""), "it": nm.get("it", ""), "ja": nm.get("ja", ""),
                    "set": sen, "setit": sname.get("it", ""), "abbr": st.get("abbr", "") or (st.get("id", "") if root == "data-asia" else ""),
                    "num": num, "count": st.get("count", ""), "ct": ctmap.get(i, 0),
                })
    return res, exp_names

def build(gid, slug, tdx=None, tdx_exp=None):
    prods = json.load(open(f"{SRC}/p{gid}.json"))
    created = prods.get("createdAt", "")[:10]
    prods = prods["products"]
    trend, low = {}, {}
    try:
        for g in json.load(open(f"{SRC}/pg{gid}.json"))["priceGuides"]:
            t = g.get("trend") or g.get("avg") or g.get("low")
            if t:
                trend[g["idProduct"]] = round(t, 2)
            if g.get("low"):
                low[g["idProduct"]] = round(g["low"], 2)
    except Exception:
        pass
    exps = expansion_names(f"{SRC}/ns{gid}.json")
    if tdx_exp:
        exps.update({k: v for k, v in tdx_exp.items()})
    if tdx:
        ab = defaultdict(Counter)
        for p in prods:
            d = tdx.get(p["idProduct"])
            if d and d["abbr"] and p.get("idExpansion"):
                ab[p["idExpansion"]][d["abbr"]] += 1
        for e, c in ab.items():
            a = c.most_common(1)[0][0]
            exps[e] = (exps.get(e, "") + " · " + a) if exps.get(e) else a
    rows, used_exp = [], set()
    matched = 0
    for p in prods:
        pid, name, e = p["idProduct"], html.unescape(p["name"]), p.get("idExpansion") or 0
        extra = ""
        if tdx and pid in tdx:
            d = tdx[pid]
            matched += 1
            num = d["num"] + (("/" + d["count"]) if d["count"] and d["num"].isdigit() else "")
            setlabel = (exps.get(e, "").split(" · ")[0]) or d["set"]
            name = f"{name} — {setlabel} {num}".strip()
            extra = " ".join(x for x in [d["it"], d["setit"], d["set"] if d["set"] != setlabel else "", d["abbr"], d["abbr"] + d["num"], d["num"]] if x)
            if setlabel:
                used_exp.add(e)
        row = [pid, name, e]
        t = trend.get(pid)
        row.append(t if t is not None else 0)
        ct = tdx[pid]["ct"] if (tdx and pid in tdx) else 0
        img = tdx[pid]["img"] if (tdx and pid in tdx) else ""
        if extra or ct or img:
            row.append(extra)
        if ct or img:
            row.append(ct)
        lo = low.get(pid)
        if img or lo:
            while len(row) < 6:
                row.append("" if len(row) == 4 else 0)
            row.append(img)
        if lo:
            row.append(lo)
        rows.append(row)
        if e in exps:
            used_exp.add(e)
    out = {"g": slug, "d": created, "e": {str(k): v for k, v in exps.items() if k in used_exp}, "p": rows}
    path = f"{OUT}/{slug}.json"
    json.dump(out, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    print(slug, len(rows), "prodotti,", len(out["e"]), "espansioni,", "tcgdex:", matched, "->", os.path.getsize(path) // 1024, "KB")

if __name__ == "__main__":
    tdx, tdx_exp = tcgdex_map()
    print("tcgdex ids", len(tdx), "sets", len(tdx_exp))
    for gid, slug in GAMES.items():
        if gid == 6:
            build(gid, slug, tdx, tdx_exp)
        else:
            build(gid, slug)
