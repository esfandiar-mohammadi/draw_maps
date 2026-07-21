"""Inference-only wall drawing on UNLABELED images (no GT needed).
Reuses the fine-tuned DINOv2 ViT-g DinoSeg predictor + planar graph build,
draws overlays. Runs on CPU by default to avoid clobbering GPU training.
"""
import os, sys, glob, json, base64, io, time, argparse
import numpy as np, cv2, torch
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_dino import DinoSeg, SZ
from train_seg import IMEAN, ISTD
import graph_infer

Image.MAX_IMAGE_PIXELS = None
DEV = os.environ.get("SHOWCASE_DEV", "cpu")
CKPT = os.environ.get("SHOWCASE_CKPT", "pipeline/models/wall_dino_fa_inscope.pt")
_m = None


def model():
    global _m
    if _m is None:
        m = DinoSeg().to(DEV)
        m.load_state_dict(torch.load(CKPT, map_location=DEV))
        m.eval(); _m = m
    return _m


def load_image(path):
    """Return BGR uint8 image from png/jpg or a dd2vtt/uvtt embedded base64."""
    if path.lower().endswith((".dd2vtt", ".uvtt", ".df2vtt")):
        d = json.load(open(path))
        im = Image.open(io.BytesIO(base64.b64decode(d["image"]))).convert("RGB")
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    return cv2.imread(path)


def predict(work, tile=SZ):
    H, W = work.shape[:2]
    wall = np.zeros((H, W), np.float32); junc = np.zeros((H, W), np.float32); cnt = np.zeros((H, W), np.float32)
    xs = sorted(set(list(range(0, max(1, W - tile) + 1, tile)) + [max(0, W - tile)]))
    ys = sorted(set(list(range(0, max(1, H - tile) + 1, tile)) + [max(0, H - tile)]))
    for y in ys:
        for x in xs:
            crop = work[y:y + tile, x:x + tile]; ch, cw = crop.shape[:2]
            c = cv2.resize(crop, (tile, tile))
            xx = (cv2.cvtColor(c, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
            with torch.no_grad():
                out = torch.sigmoid(model()(torch.from_numpy(xx.transpose(2, 0, 1))[None].to(DEV)))[0].cpu().numpy()
            wall[y:y + ch, x:x + cw] += cv2.resize(out[0], (tile, tile))[:ch, :cw]
            junc[y:y + ch, x:x + cw] += cv2.resize(out[1], (tile, tile))[:ch, :cw]
            cnt[y:y + ch, x:x + cw] += 1
    return wall / np.maximum(cnt, 1), junc / np.maximum(cnt, 1)


def infer_map(path, long_edge=1024):
    img = load_image(path)
    if img is None:
        return None
    H0, W0 = img.shape[:2]
    sc = min(1.0, long_edge / max(H0, W0))
    work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
    wall, junc = predict(work)
    nodes, edges = graph_infer.build_graph(wall, junc)
    ov = (work * 0.5).astype(np.uint8)
    for a, b, t in edges:
        cv2.line(ov, tuple(map(int, nodes[a])), tuple(map(int, nodes[b])), (0, 0, 255), 2)
    for (x, y) in nodes:
        cv2.circle(ov, (int(x), int(y)), 2, (0, 255, 255), -1)
    return work, ov, len(edges)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="text file: one image path per line")
    ap.add_argument("--out", default="corpus/results/showcase")
    ap.add_argument("--long_edge", type=int, default=1024)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    paths = [l.strip() for l in open(a.list) if l.strip()]
    if a.limit:
        paths = paths[:a.limit]
    print(f"device={DEV} ckpt={CKPT} n={len(paths)}", flush=True)
    for i, p in enumerate(paths):
        t0 = time.time()
        r = infer_map(p, a.long_edge)
        if r is None:
            print(f"[{i}] SKIP (unreadable) {p}", flush=True); continue
        work, ov, ne = r
        base = os.path.splitext(os.path.basename(p))[0]
        cv2.imwrite(os.path.join(a.out, f"{i:02d}_{base}.png"), ov)
        print(f"[{i}] {base[:42]:44} edges={ne:4d}  {time.time()-t0:5.1f}s", flush=True)


if __name__ == "__main__":
    main()
