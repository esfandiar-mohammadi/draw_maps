#!/usr/bin/env python
"""Distill the DINO-FA teacher into a small CNN student (DISTILL_PLAN.md P1).

Student: smp U-Net MobileNetV3-L (~6.7M params), 2-channel head (wall
footprint, junction heatmap) — CPU/ONNX/ncnn-deployable on the target
hardware (Ryzen 3600 / RX 6600).

Data mix per sample (weighted random source):
  - teacher SOFT labels on unlabeled + FA-train full maps (distill_pseudolabel.py)
  - hard GT anchors: fa_tiles (in-scope anchor), corpus/real, donjon (capped)
Loss (soft-target compatible): BCE + MSE + 0.4*clDice on wall, BCE on junction
+ small junction-sparsity reg. Val: held-out fa_tiles split (same convention
as train_dino: first 10% of the sorted list), checkpoint on best wall Dice.
"""
import os, sys, glob, random, argparse
import numpy as np, cv2, torch
import torch.nn as nn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_seg import (IMEAN, ISTD, soft_cldice, color_jitter, add_random_grid,
                       paste_distractors)
from train_graph import junction_map
import segmentation_models_pytorch as smp

DEV = "cuda"
SZ = 256


def norm_img(img):
    x = (cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    return torch.from_numpy(x.transpose(2, 0, 1))


def geo_aug(img, wall, junc, rng, full_map):
    """Random square crop + flips/rot90 applied consistently to img and both
    (float 0..1) label maps; then photometric aug on the image only.
    full_map=True (pseudo work-res maps ~1024): crop 256..640 px so the wall
    scale matches native-resolution inference. False (small GT tiles): crop
    0.5..1.0 of the tile like train_seg."""
    h, w = img.shape[:2]
    if full_map:
        hi = min(min(h, w), 640); lo = min(256, hi)
        cs = rng.randint(lo, hi)
        y0 = rng.randint(0, h - cs); x0 = rng.randint(0, w - cs)
        img = img[y0:y0 + cs, x0:x0 + cs]
        wall = wall[y0:y0 + cs, x0:x0 + cs]; junc = junc[y0:y0 + cs, x0:x0 + cs]
    elif rng.random() < 0.7:
        cs = rng.randint(int(min(h, w) * 0.5), min(h, w))
        y0 = rng.randint(0, h - cs); x0 = rng.randint(0, w - cs)
        img = img[y0:y0 + cs, x0:x0 + cs]
        wall = wall[y0:y0 + cs, x0:x0 + cs]; junc = junc[y0:y0 + cs, x0:x0 + cs]
    img = cv2.resize(img, (SZ, SZ), interpolation=cv2.INTER_AREA)
    wall = cv2.resize(wall, (SZ, SZ), interpolation=cv2.INTER_LINEAR)
    junc = cv2.resize(junc, (SZ, SZ), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.5:
        img = img[:, ::-1]; wall = wall[:, ::-1]; junc = junc[:, ::-1]
    if rng.random() < 0.5:
        img = img[::-1]; wall = wall[::-1]; junc = junc[::-1]
    k = rng.randint(0, 3)
    img = np.rot90(img, k).copy(); wall = np.rot90(wall, k).copy(); junc = np.rot90(junc, k).copy()
    img = paste_distractors(img, (wall * 255).astype(np.uint8), rng)
    img = color_jitter(img, rng)
    img = add_random_grid(img, rng)
    return img, wall, junc


class MixDS(torch.utils.data.Dataset):
    """Per-sample weighted source mixing: pseudo (soft) vs hard-GT dirs."""
    def __init__(self, pseudo_files, hard_groups, length):
        # hard_groups: list of (files, weight); pseudo weight is the remainder
        self.pseudo = pseudo_files
        self.groups = [(f, w) for f, w in hard_groups if f]
        self.length = length

    def __len__(self):
        return self.length

    def __getitem__(self, i):
        rng = random.Random(i * 2654435761 % 2**31)
        r = rng.random(); acc = 0.0; pick = None
        for files, wgt in self.groups:
            acc += wgt
            if r < acc:
                pick = files; break
        full_map = pick is None
        if full_map:  # pseudo branch
            f = self.pseudo[rng.randrange(len(self.pseudo))]
            img = cv2.imread(f)
            soft = cv2.imread(f.replace("/images/", "/soft/"))
            wall = soft[:, :, 0].astype(np.float32) / 255
            junc = soft[:, :, 1].astype(np.float32) / 255
        else:
            f = pick[rng.randrange(len(pick))]
            img = cv2.imread(f)
            m = cv2.imread(f.replace("images", "masks"), 0)
            wall = (m > 127).astype(np.float32)
            junc = junction_map(wall)
        img, wall, junc = geo_aug(img, wall, junc, rng, full_map)
        return norm_img(img), torch.from_numpy(np.stack([wall, junc]))


class ValDS(torch.utils.data.Dataset):
    def __init__(self, files):
        self.files = files

    def __len__(self):
        return len(self.files)

    def __getitem__(self, i):
        f = self.files[i]
        img = cv2.resize(cv2.imread(f), (SZ, SZ), interpolation=cv2.INTER_AREA)
        m = cv2.resize(cv2.imread(f.replace("images", "masks"), 0), (SZ, SZ),
                       interpolation=cv2.INTER_NEAREST)
        wall = (m > 127).astype(np.float32)
        return norm_img(img), torch.from_numpy(np.stack([wall, junction_map(wall)]))


def dice(pred, y, eps=1e-6):
    p = (pred > 0.5).float(); inter = (p * y).sum((1, 2, 3))
    return ((2 * inter + eps) / (p.sum((1, 2, 3)) + y.sum((1, 2, 3)) + eps)).mean().item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pseudo", default="corpus/distill_pl")
    ap.add_argument("--fa_tiles", default="corpus/fa_tiles")
    ap.add_argument("--real", default="corpus/real")
    ap.add_argument("--donjon", default="corpus/donjon/base")
    ap.add_argument("--donjon_cap", type=int, default=8000)
    ap.add_argument("--w_fa", type=float, default=0.25)
    ap.add_argument("--w_real", type=float, default=0.15)
    ap.add_argument("--w_donjon", type=float, default=0.15)
    ap.add_argument("--samples", type=int, default=160000)
    ap.add_argument("--epochs", type=int, default=16)
    ap.add_argument("--bs", type=int, default=48)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--node_reg", type=float, default=0.02)
    ap.add_argument("--encoder", default="timm-mobilenetv3_large_100")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--amp", action="store_true", help="mixed-precision training (fp16 autocast + GradScaler)")
    ap.add_argument("--out", default="pipeline/models/wall_student_mbv3.pt")
    a = ap.parse_args()

    pseudo = sorted(glob.glob(f"{a.pseudo}/images/*.png"))
    fa = sorted(glob.glob(f"{a.fa_tiles}/images/*.png"))
    k = max(20, len(fa) // 10)
    fa_val, fa_tr = fa[:k], fa[k:]          # same split convention as train_dino
    real = sorted(glob.glob(f"{a.real}/images/*.png"))
    donjon = sorted(glob.glob(f"{a.donjon}/images/*.png"))
    random.seed(0); random.shuffle(donjon); donjon = donjon[:a.donjon_cap]
    w_pseudo = 1.0 - a.w_fa - a.w_real - a.w_donjon
    print(f"pseudo {len(pseudo)} ({w_pseudo:.2f}) + fa_tiles {len(fa_tr)} ({a.w_fa}) "
          f"+ real {len(real)} ({a.w_real}) + donjon {len(donjon)} ({a.w_donjon}); "
          f"val={len(fa_val)} FA-holdout tiles", flush=True)
    assert pseudo, "no pseudo-label pairs found — run distill_pseudolabel.py first"

    model = smp.Unet(a.encoder, encoder_weights="imagenet", classes=2).to(DEV)
    n = sum(p.numel() for p in model.parameters())
    print(f"student {a.encoder}: {n/1e6:.1f}M params (all trainable)", flush=True)

    per = a.samples // a.epochs
    ds = MixDS(pseudo, [(fa_tr, a.w_fa), (real, a.w_real), (donjon, a.w_donjon)], per)
    dl = torch.utils.data.DataLoader(ds, batch_size=a.bs, shuffle=True,
                                     num_workers=a.workers, drop_last=True,
                                     persistent_workers=True, prefetch_factor=4)
    vdl = torch.utils.data.DataLoader(ValDS(fa_val), batch_size=a.bs, num_workers=2)
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)
    bce = nn.BCEWithLogitsLoss(); mse = nn.MSELoss()
    scaler = torch.amp.GradScaler("cuda", enabled=a.amp)
    print(f"AMP={'on' if a.amp else 'off'} bs={a.bs} workers={a.workers}", flush=True)
    best = 0.0
    for ep in range(1, a.epochs + 1):
        model.train()
        for x, y in dl:
            x, y = x.to(DEV), y.to(DEV)
            opt.zero_grad()
            with torch.autocast("cuda", dtype=torch.float16, enabled=a.amp):
                out = model(x)
                wl = torch.sigmoid(out[:, :1]); jl = torch.sigmoid(out[:, 1:])
                loss = (bce(out[:, :1], y[:, :1]) + mse(wl, y[:, :1])
                        + 0.4 * soft_cldice(wl, y[:, :1])
                        + bce(out[:, 1:], y[:, 1:]) + a.node_reg * jl.mean())
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
        sched.step()
        model.eval(); d = 0; nb = 0
        with torch.no_grad():
            for x, y in vdl:
                d += dice(torch.sigmoid(model(x.to(DEV))[:, :1]), y.to(DEV)[:, :1]); nb += 1
        d /= max(nb, 1)
        print(f"epoch {ep}/{a.epochs}  wall val Dice={d:.3f}", flush=True)
        torch.save(model.state_dict(), a.out.replace(".pt", "_last.pt"))
        if d >= best:
            best = d; torch.save(model.state_dict(), a.out)
    print(f"best Dice={best:.3f}; saved {a.out}", flush=True)


if __name__ == "__main__":
    main()
