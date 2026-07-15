#!/usr/bin/env python
"""Fine-tune a pretrained U-Net to segment walls, on donjon-generated data.

Per direction:
- Train the LAST 8 LAYERS (output side): segmentation head + all 5 decoder
  blocks + the last two encoder stages (layer4, layer3). Rest frozen.
- GRID-INVARIANCE: randomly overlay synthetic grids (and leave some gridless) so
  the model never learns "grid line == wall".
- 200k training scale via on-the-fly augmentation over a few-thousand donjon base
  (crop/flip/rot/colour-jitter/grid), not 200k distinct server requests.
"""
import os, sys, glob, random, argparse
import numpy as np, cv2, torch
import torch.nn as nn
import segmentation_models_pytorch as smp

DEV = "cuda"
SZ = 256
IMEAN = np.array([0.485, 0.456, 0.406], np.float32)
ISTD = np.array([0.229, 0.224, 0.225], np.float32)


def add_random_grid(img, rng):
    if rng.random() < 0.45:
        return img
    h, w = img.shape[:2]
    cell = rng.randint(8, 40); off = rng.randint(0, cell)
    col = rng.choice([(0, 0, 0), (255, 255, 255), (60, 60, 60), (40, 30, 20), (90, 90, 110)])
    alpha = rng.uniform(0.08, 0.5)
    ov = img.copy()
    for x in range(off, w, cell):
        cv2.line(ov, (x, 0), (x, h), col, 1)
    for y in range(off, h, cell):
        cv2.line(ov, (0, y), (w, y), col, 1)
    return cv2.addWeighted(ov, alpha, img, 1 - alpha, 0)


def color_jitter(img, rng):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + rng.uniform(-12, 12)) % 180
    hsv[:, :, 1] *= rng.uniform(0.7, 1.3)
    hsv[:, :, 2] *= rng.uniform(0.7, 1.3)
    return cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)


def augment(img, m, rng):
    h, w = img.shape[:2]
    # random square crop (scale variety) then resize
    if rng.random() < 0.7:
        cs = rng.randint(int(min(h, w) * 0.5), min(h, w))
        y0 = rng.randint(0, h - cs); x0 = rng.randint(0, w - cs)
        img = img[y0:y0 + cs, x0:x0 + cs]; m = m[y0:y0 + cs, x0:x0 + cs]
    img = cv2.resize(img, (SZ, SZ), interpolation=cv2.INTER_AREA)
    m = cv2.resize(m, (SZ, SZ), interpolation=cv2.INTER_NEAREST)
    if rng.random() < 0.5:
        img = img[:, ::-1]; m = m[:, ::-1]
    if rng.random() < 0.5:
        img = img[::-1]; m = m[::-1]
    k = rng.randint(0, 3); img = np.rot90(img, k).copy(); m = np.rot90(m, k).copy()
    img = color_jitter(img, rng)
    img = add_random_grid(img, rng)
    return img, m


def to_tensor(img, m):
    x = (cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - IMEAN) / ISTD
    return torch.from_numpy(x.transpose(2, 0, 1)), torch.from_numpy((m > 127).astype(np.float32)[None])


class TrainDS(torch.utils.data.Dataset):
    def __init__(self, files, length):
        self.files = files; self.length = length
    def __len__(self): return self.length
    def __getitem__(self, i):
        rng = random.Random(i * 2654435761 % (2**31))
        f = self.files[rng.randrange(len(self.files))]
        img = cv2.imread(f); m = cv2.imread(f.replace("images", "masks"), 0)
        img, m = augment(img, m, rng)
        return to_tensor(img, m)


class ValDS(torch.utils.data.Dataset):
    def __init__(self, files): self.files = files
    def __len__(self): return len(self.files)
    def __getitem__(self, i):
        f = self.files[i]; img = cv2.imread(f); m = cv2.imread(f.replace("images", "masks"), 0)
        img = cv2.resize(img, (SZ, SZ)); m = cv2.resize(m, (SZ, SZ), interpolation=cv2.INTER_NEAREST)
        return to_tensor(img, m)


def set_finetune_last8(model):
    """Train the last 8 output-side layers: segmentation head + all 5 decoder
    blocks + the last two encoder stages (layer4, layer3). Rest frozen."""
    for p in model.parameters():
        p.requires_grad = False
    mods = [model.segmentation_head] + list(model.decoder.blocks)   # head + 5 decoder blocks
    for name in ["layer4", "layer3"]:                               # + last 2 encoder stages
        if hasattr(model.encoder, name):
            mods.append(getattr(model.encoder, name))
    for mod in mods:
        for p in mod.parameters():
            p.requires_grad = True
    n = sum(p.numel() for p in model.parameters() if p.requires_grad)
    tot = sum(p.numel() for p in model.parameters())
    print(f"training last-8 output layers: {n/1e6:.2f}M / {tot/1e6:.2f}M params")


def dice(pred, y, eps=1e-6):
    p = (pred > 0.5).float(); inter = (p * y).sum((1, 2, 3))
    return ((2 * inter + eps) / (p.sum((1, 2, 3)) + y.sum((1, 2, 3)) + eps)).mean().item()


# --- clDice: connectivity-preserving loss (long, unbroken lines) -------------
import torch.nn.functional as F  # noqa: E402


def _soft_erode(x):
    return torch.min(-F.max_pool2d(-x, (3, 1), 1, (1, 0)),
                     -F.max_pool2d(-x, (1, 3), 1, (0, 1)))


def _soft_dilate(x):
    return F.max_pool2d(x, 3, 1, 1)


def _soft_open(x):
    return _soft_dilate(_soft_erode(x))


def soft_skel(x, iters=8):
    x1 = _soft_open(x)
    skel = F.relu(x - x1)
    for _ in range(iters):
        x = _soft_erode(x)
        x1 = _soft_open(x)
        d = F.relu(x - x1)
        skel = skel + F.relu(d - skel * d)
    return skel


def soft_cldice(pred, target, iters=8, eps=1e-5):
    """1 - clDice. Breaking a connected line lowers topology precision/sensitivity
    -> higher loss. Forces long, connected wall strokes."""
    sp, st = soft_skel(pred, iters), soft_skel(target, iters)
    tprec = (sp * target).sum((1, 2, 3)) / (sp.sum((1, 2, 3)) + eps)
    tsens = (st * pred).sum((1, 2, 3)) / (st.sum((1, 2, 3)) + eps)
    return (1 - 2 * tprec * tsens / (tprec + tsens + eps)).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="corpus/donjon/base")
    ap.add_argument("--real", default="corpus/real")
    ap.add_argument("--real_mul", type=int, default=20)
    ap.add_argument("--samples", type=int, default=200000)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--bs", type=int, default=48)
    a = ap.parse_args()
    files = sorted(glob.glob(f"{a.data}/images/*.png"))
    if len(files) < 50:
        files += sorted(glob.glob("corpus/donjon/dataset/images/*.png"))
    random.seed(0); random.shuffle(files)
    nval = max(20, int(0.1 * len(files))); va, tr = files[:nval], files[nval:]
    real = sorted(glob.glob(f"{a.real}/images/*.png"))
    # domain mixing: oversample the real painted tiles so they are ~1/3 of training
    tr = tr + real * a.real_mul
    random.shuffle(tr)
    per_epoch = a.samples // a.epochs
    print(f"donjon {len(files)} + real {len(real)}x{a.real_mul} -> {len(tr)} train "
          f"({100*len(real)*a.real_mul//max(1,len(tr))}% real) / {len(va)} donjon-val; "
          f"{a.samples} aug samples over {a.epochs} epochs", flush=True)
    model = smp.Unet(encoder_name="resnet34", encoder_weights="imagenet", classes=1).to(DEV)
    set_finetune_last8(model)
    dl = torch.utils.data.DataLoader(TrainDS(tr, per_epoch), batch_size=a.bs, shuffle=True,
                                     num_workers=8, drop_last=True, persistent_workers=True)
    vdl = torch.utils.data.DataLoader(ValDS(va), batch_size=a.bs, num_workers=2)
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=6e-4)
    bce = nn.BCEWithLogitsLoss(); dl_loss = smp.losses.DiceLoss(mode="binary")
    best = 0
    for ep in range(1, a.epochs + 1):
        model.train()
        for bi, (x, y) in enumerate(dl):
            x, y = x.to(DEV), y.to(DEV)
            opt.zero_grad(); out = model(x)
            pr = torch.sigmoid(out)
            loss = bce(out, y) + dl_loss(out, y) + 0.4 * soft_cldice(pr, y)  # + connectivity reg
            loss.backward(); opt.step()
        model.eval(); d = 0; nb = 0
        with torch.no_grad():
            for x, y in vdl:
                d += dice(torch.sigmoid(model(x.to(DEV))), y.to(DEV)); nb += 1
        d /= max(nb, 1)
        print(f"epoch {ep}/{a.epochs}  val Dice={d:.3f}", flush=True)
        if d >= best:
            best = d; torch.save(model.state_dict(), "pipeline/models/wall_seg_unet.pt")
    print(f"best val Dice={best:.3f}; saved pipeline/models/wall_seg_unet.pt")


if __name__ == "__main__":
    main()
