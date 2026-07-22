"""Teacher pseudo-labeling for the CNN-student distillation (DISTILL_PLAN.md P1).

Runs the DINO-FA teacher in its exact multi-scale eval protocol (scales
768/1024/1536 fused at ref long edge 1024 — the 0.728 operating point) over
(a) unlabeled full maps (corpus/distill_unlabeled.txt) and (b) the FA in-scope
TRAIN maps (corpus/distill_fa_train.txt; never fa_test/outscope), and stores
(work-res image, soft wall+junction) pairs the student regresses on.

Output: OUT/images/<slug>.png  (BGR, ref-res)
        OUT/soft/<slug>.png    (u8 3ch: ch0=wall*255, ch1=junc*255, ch2=0)

Resumable: existing soft/<slug>.png are skipped. Tile inference is BATCHED
(unlike graph_eval_dino.predict) so a full map takes ~1-2 s on GPU.
"""
import os, sys, re, argparse
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2, torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graph_eval_dino as G
from train_seg import IMEAN, ISTD
from train_dino import SZ
from uvtt import load as load_uvtt


def predict_batched(work, tile=SZ, bs=16):
    """Same tiling/averaging as graph_eval_dino.predict, but batched forwards."""
    H, W = work.shape[:2]
    wall = np.zeros((H, W), np.float32); junc = np.zeros((H, W), np.float32)
    cnt = np.zeros((H, W), np.float32)
    xs = sorted(set(list(range(0, max(1, W - tile) + 1, tile)) + [max(0, W - tile)]))
    ys = sorted(set(list(range(0, max(1, H - tile) + 1, tile)) + [max(0, H - tile)]))
    coords, batch = [], []
    for y in ys:
        for x in xs:
            crop = work[y:y + tile, x:x + tile]
            ch, cw = crop.shape[:2]
            c = cv2.resize(crop, (tile, tile))
            xx = (cv2.cvtColor(c, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
            coords.append((y, x, ch, cw)); batch.append(xx.transpose(2, 0, 1))
    for i in range(0, len(batch), bs):
        xb = torch.from_numpy(np.stack(batch[i:i + bs])).to(G.DEV)
        with torch.no_grad():
            out = torch.sigmoid(G.model()(xb)).cpu().numpy()
        for (y, x, ch, cw), o in zip(coords[i:i + bs], out):
            wall[y:y + ch, x:x + cw] += cv2.resize(o[0], (tile, tile))[:ch, :cw]
            junc[y:y + ch, x:x + cw] += cv2.resize(o[1], (tile, tile))[:ch, :cw]
            cnt[y:y + ch, x:x + cw] += 1
    return wall / np.maximum(cnt, 1), junc / np.maximum(cnt, 1)


def ms_predict_batched(img, scales, ref_long=1024, bs=16):
    H0, W0 = img.shape[:2]
    rsc = min(1.0, ref_long / max(H0, W0))
    RW, RH = round(W0 * rsc), round(H0 * rsc)
    wsum = np.zeros((RH, RW), np.float32); jsum = np.zeros((RH, RW), np.float32)
    for s in scales:
        sc = min(1.0, s / max(H0, W0))
        work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        w, j = predict_batched(work, bs=bs)
        wsum += cv2.resize(w, (RW, RH))
        jsum += cv2.resize(j, (RW, RH))
    return wsum / len(scales), jsum / len(scales), rsc


def slugify(path):
    s = os.path.splitext(os.path.relpath(path, "corpus"))[0]
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:150]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="pipeline/models/wall_dino_fa_inscope.pt")
    ap.add_argument("--scales", default="768,1024,1536")
    ap.add_argument("--ref_long", type=int, default=1024)
    ap.add_argument("--unlabeled", default="corpus/distill_unlabeled.txt")
    ap.add_argument("--fa_train", default="corpus/distill_fa_train.txt")
    ap.add_argument("--out", default="corpus/distill_pl")
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="smoke test: only N maps")
    a = ap.parse_args()
    G.CKPT = a.ckpt
    scales = [int(x) for x in a.scales.split(",")]
    os.makedirs(f"{a.out}/images", exist_ok=True); os.makedirs(f"{a.out}/soft", exist_ok=True)

    jobs = []  # (slug, kind, path)
    if a.fa_train and os.path.exists(a.fa_train):
        for ln in open(a.fa_train):
            s = ln.strip()
            if s:
                jobs.append(("fa_" + re.sub(r"[^A-Za-z0-9_-]+", "_", s), "uvtt",
                             os.path.join("corpus/fa", s + ".dd2vtt")))
    if a.unlabeled and os.path.exists(a.unlabeled):
        for ln in open(a.unlabeled):
            p = ln.strip()
            if p:
                jobs.append((slugify(p), "img", p))
    if a.limit:
        jobs = jobs[:a.limit]
    todo = [(s, k, p) for s, k, p in jobs
            if not os.path.exists(f"{a.out}/soft/{s}.png")]
    print(f"{len(jobs)} maps total, {len(todo)} to label "
          f"(scales={scales}, ref={a.ref_long}, ckpt={a.ckpt})", flush=True)

    def load(job):
        slug, kind, path = job
        if kind == "uvtt":
            try:
                img = load_uvtt(path)["image"]
            except Exception as e:
                print(f"SKIP {slug}: uvtt load failed ({e})", flush=True); img = None
        else:
            img = cv2.imread(path)
        return slug, img

    done = 0
    with ThreadPoolExecutor(3) as ex:
        for slug, img in ex.map(load, todo):
            if img is None:
                print(f"SKIP unreadable: {slug}", flush=True)
                continue
            try:
                wall, junc, _ = ms_predict_batched(img, scales, a.ref_long, a.bs)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                print(f"OOM on {slug}, retrying bs=4", flush=True)
                try:
                    wall, junc, _ = ms_predict_batched(img, scales, a.ref_long, 4)
                except torch.cuda.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    print(f"SKIP {slug}: OOM twice", flush=True)
                    continue
            RH, RW = wall.shape
            wimg = cv2.resize(img, (RW, RH), interpolation=cv2.INTER_AREA)
            soft = np.zeros((RH, RW, 3), np.uint8)
            soft[:, :, 0] = np.clip(wall * 255, 0, 255).astype(np.uint8)
            soft[:, :, 1] = np.clip(junc * 255, 0, 255).astype(np.uint8)
            cv2.imwrite(f"{a.out}/images/{slug}.png", wimg)
            cv2.imwrite(f"{a.out}/soft/{slug}.png", soft)
            done += 1
            if done % 20 == 0:
                print(f"labeled {done}/{len(todo)}", flush=True)
    print(f"DONE: labeled {done}/{len(todo)} -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
