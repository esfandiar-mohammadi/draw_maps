#!/usr/bin/env python
"""Harvest Forgotten-Adventures battlemaps into .dd2vtt ground-truth files.

FA_Battlemaps (github.com/Forgotten-Adventures/FA_Battlemaps) is a public repo
of Foundry v13 scenes with hand-placed walls. The images themselves live behind
api.forgotten-adventures.net:
  GET /api/v1/battlemaps/list                      -> [{id,name,access,...}]
  GET /api/v1/battlemaps/list-files/<id>?userId=   -> {files:{images:[...]}}
  GET /api/v1/battlemaps/get-file/<id>/<path>?userId=<uid> -> {url: signed S3}
Free maps (access=="Free") work with an empty userId; Premium maps need a real
Patreon userId (obtained via the module's OAuth; 401 otherwise).

Walls come from the repo scene JSON (packs/_source/maps/<slug>.json): each wall
is {"c":[x1,y1,x2,y2], "door":0|1|2, ...} in PADDED canvas pixels. Foundry pads
the scene by `padding` on each side, rounded up to the grid:
    pad = ceil(padding * dim / grid) * grid
so image_pixel = canvas_coord - (pad_x, pad_y). The merged *_BG.webp has pixel
dims == scene width/height (scale 1.0), verified on tomb-of-horrors.

Output: corpus/fa/<slug>.dd2vtt  (base64 image, long edge capped; walls as
2-point polylines in grid units; doors as portals) — consumed unchanged by
uvtt.load / dd2vtt_to_heat.py.
"""
import os
import json
import math
import base64
import argparse
import re
import glob
import urllib.parse
import urllib.request

import numpy as np
import cv2

API = "https://api.forgotten-adventures.net"
REPO_SRC = None  # set from args: FA_Battlemaps/packs/_source/maps


def http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "draw_maps-harvest"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url, timeout=60):
    st, body = http_get(url, timeout)
    if st != 200:
        return st, None
    return st, json.loads(body)


def norm_name(s):
    """Normalise a map name for matching: lowercase, collapse ws, drop ws
    before '[', strip punctuation to spaces."""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace(" [", "[")
    return s


def scene_name(d):
    return norm_name(d.get("name", ""))


def build_repo_index(src_dir):
    idx = {}
    for f in glob.glob(os.path.join(src_dir, "*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if "walls" not in d:
            continue
        idx[scene_name(d)] = f
    return idx


def pad_offset(d):
    g = d["grid"]["size"]
    pad = d.get("padding", 0) or 0
    px = math.ceil(pad * d["width"] / g) * g
    py = math.ceil(pad * d["height"] / g) * g
    return px, py, g


def pick_bg_candidates(files_json):
    """Ranked list of single-file full-map candidates (largest first). FA uses
    several conventions for the flattened battlemap:
      - '<name>_BG.webp' / 'fungicavernbg.webp'   (merged, no digit)
      - '<name>_Gridless_<W>x<H>_200ppi.webp' / '<name>-bare-gridless-...'
        (the flattened full battlemap — many Premium maps only ship this)
    Split-quadrant maps ('...BG1.webp') expose no such file -> empty list, and
    the caller composites from scene tiles. We return several candidates so the
    caller can skip a near-black one and try the next."""
    imgs = files_json.get("files", {}).get("images", [])
    maps = [f for f in imgs if "/maps/" in f["path"].lower()
            and f["path"].lower().endswith(".webp")]
    cands = []
    for f in maps:
        name = f["path"].split("/")[-1].lower()
        if re.search(r"bg\.webp$", name) or "gridless" in name:
            cands.append(f)
    return sorted(cands, key=lambda f: -f["size"])


def pick_bg_file(files_json):
    c = pick_bg_candidates(files_json)
    return c[0] if c else None


# filename keywords that mark a tile as a NON-base overlay (roofs/canopies/
# shadows/doors/props) — excluded when compositing the base map, because for
# wall ground-truth we want the GM view with every wall visible, not occluded.
_OVERLAY_KW = ("fg", "canopy", "shadow", "roof", "door", "tower", "cell",
               "top", "mist", "blur", "overlay", "light", "_fx", "grid",
               "cloud", "fog", "water_reflection")


def _tile_src(t):
    tx = t.get("texture") or {}
    return tx.get("src") or ""


def _is_base_tile(t):
    src = _tile_src(t)
    name = src.split("/")[-1].lower()
    if "/maps/" not in src.lower():
        return False
    if not name.endswith((".webp", ".png", ".jpg", ".jpeg")):
        return False
    if any(k in name for k in _OVERLAY_KW):
        return False
    if (t.get("elevation") or 0) > 0 or t.get("hidden"):
        return False
    occ = (t.get("occlusion") or {}).get("mode")
    if occ not in (None, 0):
        return False
    return True


def compose_base_image(scene, bmid, uid, px, py):
    """Reconstruct the base map (scene width x height, 1px == 1 canvas unit)
    by alpha-compositing the scene's base tiles (BG quadrants etc.), skipping
    occluding overlays. Returns BGR uint8 or None."""
    tiles = [t for t in scene.get("tiles", []) if _is_base_tile(t)]
    if not tiles:
        return None
    W, H = int(scene["width"]), int(scene["height"])
    canvas = np.zeros((H, W, 3), np.uint8)
    tiles.sort(key=lambda t: (t.get("sort") or 0, t.get("elevation") or 0))
    placed = 0
    for t in tiles:
        url = sign_url(bmid, _tile_src(t), uid)
        if not url:
            continue
        st, raw = http_get(url, timeout=240)
        if st != 200:
            continue
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
        if im is None:
            continue
        tw, th = max(1, round(t["width"])), max(1, round(t["height"]))
        im = cv2.resize(im, (tw, th), interpolation=cv2.INTER_AREA)
        ox, oy = round(t["x"] - px), round(t["y"] - py)
        # destination window clipped to canvas
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(W, ox + tw), min(H, oy + th)
        if x1 <= x0 or y1 <= y0:
            continue
        sub = im[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        if sub.ndim == 3 and sub.shape[2] == 4:
            rgb = sub[:, :, :3].astype(np.float32)
            a = (sub[:, :, 3:4].astype(np.float32)) / 255.0
            dst = canvas[y0:y1, x0:x1].astype(np.float32)
            canvas[y0:y1, x0:x1] = (a * rgb + (1 - a) * dst).astype(np.uint8)
        else:
            if sub.ndim == 2:
                sub = cv2.cvtColor(sub, cv2.COLOR_GRAY2BGR)
            canvas[y0:y1, x0:x1] = sub[:, :, :3]
        placed += 1
    return canvas if placed else None


def sign_url(bmid, path, uid):
    q = urllib.parse.quote(path, safe="")
    url = f"{API}/api/v1/battlemaps/get-file/{bmid}/{q}?userId={uid}"
    st, j = get_json(url)
    if st != 200 or not j or "url" not in j:
        return None
    return j["url"]


def to_dd2vtt(img, walls_px, doors_px, grid, max_edge):
    """img BGR, walls/doors in ORIGINAL image pixels, grid px per square.
    Downscale so long edge <= max_edge; grid coords are scale-invariant."""
    H, W = img.shape[:2]
    s = min(1.0, max_edge / max(W, H))
    if s < 1.0:
        img = cv2.resize(img, (round(W * s), round(H * s)), interpolation=cv2.INTER_AREA)
    ppg = grid * s  # keeps gridcoord*ppg == original_pixel*s
    los = [[{"x": x0 / grid, "y": y0 / grid}, {"x": x1 / grid, "y": y1 / grid}]
           for (x0, y0, x1, y1) in walls_px]
    portals = [{"bounds": [{"x": x0 / grid, "y": y0 / grid},
                            {"x": x1 / grid, "y": y1 / grid}],
                "closed": True} for (x0, y0, x1, y1) in doors_px]
    ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 90])
    b64 = base64.b64encode(buf.tobytes()).decode()
    return {
        "format": 0.3,
        "resolution": {"map_origin": {"x": 0, "y": 0},
                       "map_size": {"x": img.shape[1] / ppg, "y": img.shape[0] / ppg},
                       "pixels_per_grid": ppg},
        "line_of_sight": los,
        "portals": portals,
        "image": b64,
    }


def slug_of(name):
    s = norm_name(name).replace("[", "-").replace("]", "").replace("x", "x")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="path to FA_Battlemaps checkout")
    ap.add_argument("--out", default="corpus/fa")
    ap.add_argument("--userid", default="", help="Patreon userId for Premium maps")
    ap.add_argument("--access", default="Free", choices=["Free", "Premium", "all"])
    ap.add_argument("--max_edge", type=int, default=2048)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--overlays", type=int, default=6, help="render N overlays")
    args = ap.parse_args()

    src = os.path.join(args.repo, "packs", "_source", "maps")
    assert os.path.isdir(src), src
    os.makedirs(args.out, exist_ok=True)
    ov_dir = os.path.join(args.out, "_overlays")
    os.makedirs(ov_dir, exist_ok=True)

    print("indexing repo scenes ...", flush=True)
    idx = build_repo_index(src)
    print(f"  {len(idx)} scenes with walls", flush=True)

    st, lst = get_json(f"{API}/api/v1/battlemaps/list")
    assert st == 200, f"list failed {st}"
    if args.access != "all":
        lst = [m for m in lst if m.get("access") == args.access]
    print(f"  {len(lst)} battlemaps (access={args.access})", flush=True)

    done = miss_repo = miss_file = err = 0
    n_ov = 0
    for i, m in enumerate(lst):
        if args.limit and done >= args.limit:
            break
        nm = norm_name(m["name"])
        jf = idx.get(nm)
        if not jf:
            miss_repo += 1
            print(f"  [skip:no-repo] {m['name']}", flush=True)
            continue
        slug = slug_of(m["name"])
        out_path = os.path.join(args.out, slug + ".dd2vtt")
        if os.path.exists(out_path):
            done += 1
            continue
        try:
            d = json.load(open(jf))
            px, py, g = pad_offset(d)
            # file manifest + signed url
            st, fj = get_json(f"{API}/api/v1/battlemaps/list-files/{m['id']}?userId={args.userid}")
            if st != 200 or not fj:
                miss_file += 1
                print(f"  [skip:list-files {st}] {m['name']}", flush=True)
                continue
            # Primary: a single full-map file (merged BG or flattened gridless).
            # Accept only if its aspect matches the scene AND it is not near-black
            # (some maps only ship a lightless/night variant, or the wrong file).
            # Try candidates largest-first; else composite base tiles; a near-
            # black result at every stage -> skip the map (never poison the set).
            def _black(im):
                return im is None or im.mean() < 8 or (im.max(axis=2) < 20).mean() > 0.97
            img = None
            via = None
            for bg in pick_bg_candidates(fj):
                url = sign_url(m["id"], bg["path"], args.userid)
                if not url:
                    continue
                st, raw = http_get(url, timeout=240)
                if st != 200:
                    continue
                cand = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if cand is None:
                    continue
                H, W = cand.shape[:2]
                sx, sy = W / d["width"], H / d["height"]
                if abs(sx - sy) <= 0.02 and not _black(cand):
                    img, via = cand, "single"
                    break
            if img is None:
                comp = compose_base_image(d, m["id"], args.userid, px, py)
                if comp is not None and not _black(comp):
                    img, via = comp, "composite"
            if img is None:
                miss_file += 1
                print(f"  [skip:no-usable-image] {m['name']}", flush=True)
                continue
            H, W = img.shape[:2]
            sx, sy = W / d["width"], H / d["height"]
            if abs(sx - sy) > 0.02:
                print(f"  [warn:scale sx={sx:.3f} sy={sy:.3f} via={via}] {m['name']}", flush=True)
            walls, doors = [], []
            for w in d.get("walls", []):
                c = w.get("c")
                if not c or len(c) < 4:
                    continue
                seg = ((c[0] - px) * sx, (c[1] - py) * sy,
                       (c[2] - px) * sx, (c[3] - py) * sy)
                if w.get("door", 0):
                    doors.append(seg)
                else:
                    walls.append(seg)
            g_img = g * sx  # pixels per grid square in the image
            dd = to_dd2vtt(img, walls, doors, g_img, args.max_edge)
            json.dump(dd, open(out_path, "w"))
            done += 1
            print(f"  [ok {done}] {slug}  walls={len(walls)} doors={len(doors)} img={W}x{H} via={via}", flush=True)
            if n_ov < args.overlays:
                ov = img.copy()
                for (x0, y0, x1, y1) in walls:
                    cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 6)
                for (x0, y0, x1, y1) in doors:
                    cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (255, 128, 0), 8)
                sc = 1400 / max(ov.shape[:2])
                ov = cv2.resize(ov, (int(ov.shape[1] * sc), int(ov.shape[0] * sc)))
                cv2.imwrite(os.path.join(ov_dir, slug + ".png"), ov)
                n_ov += 1
        except Exception as e:
            err += 1
            print(f"  [EXC] {m['name']}: {e}", flush=True)
            continue

    print(f"\nDONE  ok={done} no-repo={miss_repo} no-file={miss_file} err={err}", flush=True)


if __name__ == "__main__":
    main()
