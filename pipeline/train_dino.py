#!/usr/bin/env python
"""Fine-tune DINOv2 ViT-g/14 as a wall+junction segmentation backbone.

Backbone frozen EXCEPT the last 4 transformer blocks (+ final norm); a small
decoder head maps patch tokens -> 2 channels (wall footprint, junction heatmap).
Reuses the donjon+real data pipeline, clDice connectivity loss and node-sparsity
regularisation from train_graph.
"""
import os, sys, glob, random, argparse
import numpy as np, cv2, torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_seg import augment, IMEAN, ISTD, soft_cldice
from train_graph import junction_map
import segmentation_models_pytorch as smp

DEV = "cuda"
SZ = 252  # 18 x 14 (DINOv2 patch size 14)


class DinoSeg(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = torch.hub.load("facebookresearch/dinov2", "dinov2_vitg14")
        d = self.backbone.embed_dim
        self.head = nn.Sequential(
            nn.Conv2d(d, 256, 3, padding=1), nn.GroupNorm(16, 256), nn.GELU(),
            nn.Conv2d(256, 128, 3, padding=1), nn.GroupNorm(16, 128), nn.GELU(),
            nn.Conv2d(128, 2, 1))

    def set_finetune_last4(self):
        for p in self.backbone.parameters():
            p.requires_grad = False
        for blk in self.backbone.blocks[-4:]:
            for p in blk.parameters():
                p.requires_grad = True
        for p in self.backbone.norm.parameters():
            p.requires_grad = True

    def forward(self, x):
        B, _, H, W = x.shape
        f = self.backbone.forward_features(x)["x_norm_patchtokens"]  # B,N,d
        gh, gw = H // 14, W // 14
        f = f.transpose(1, 2).reshape(B, -1, gh, gw)
        y = self.head(f)
        return F.interpolate(y, (H, W), mode="bilinear", align_corners=False)


def to_tensor2(img, m):
    img = cv2.resize(img, (SZ, SZ)); m = cv2.resize(m, (SZ, SZ), interpolation=cv2.INTER_NEAREST)
    x = (cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    wall = (m > 127).astype(np.float32); junc = junction_map(wall)
    return torch.from_numpy(x.transpose(2, 0, 1)), torch.from_numpy(np.stack([wall, junc]))


class DS(torch.utils.data.Dataset):
    def __init__(self, files, length, train=True):
        self.files, self.length, self.train = files, length, train
    def __len__(self): return self.length if self.train else len(self.files)
    def __getitem__(self, i):
        rng = random.Random(i * 2654435761 % 2**31) if self.train else random.Random(i)
        f = self.files[rng.randrange(len(self.files))] if self.train else self.files[i]
        img = cv2.imread(f); m = cv2.imread(f.replace("images", "masks"), 0)
        if self.train:
            img, m = augment(img, m, rng)
        return to_tensor2(img, m)


def dice(pred, y, eps=1e-6):
    p = (pred > 0.5).float(); inter = (p * y).sum((1, 2, 3))
    return ((2 * inter + eps) / (p.sum((1, 2, 3)) + y.sum((1, 2, 3)) + eps)).mean().item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="corpus/donjon/base"); ap.add_argument("--real", default="corpus/real")
    ap.add_argument("--real_mul", type=int, default=65); ap.add_argument("--samples", type=int, default=60000)
    ap.add_argument("--epochs", type=int, default=5); ap.add_argument("--bs", type=int, default=8)
    ap.add_argument("--node_reg", type=float, default=0.02)
    ap.add_argument("--donjon_cap", type=int, default=8000)
    ap.add_argument("--backbone_init", default="",
                    help="path to a JEPA-adapted ViT-g state_dict to load into the backbone")
    ap.add_argument("--out", default="pipeline/models/wall_dino_vitg.pt")
    a = ap.parse_args()
    files = sorted(glob.glob(f"{a.data}/images/*.png")); random.seed(0); random.shuffle(files)
    files = files[:a.donjon_cap]   # cap donjon so real painted data keeps a high share
    nval = max(20, int(0.1 * len(files))); va, tr = files[:nval], files[nval:]
    real = []
    for rd in a.real.split(","):     # comma-separated real tile dirs (like train_graph)
        rd = rd.strip()
        if rd:
            real += sorted(glob.glob(f"{rd}/images/*.png"))
    tr = tr + real * a.real_mul; random.shuffle(tr)
    print(f"donjon {len(files)} + real {len(real)}x{a.real_mul} -> {len(tr)} train "
          f"({100*len(real)*a.real_mul//max(1,len(tr))}% real)", flush=True)
    model = DinoSeg().to(DEV)
    if a.backbone_init:
        miss = model.backbone.load_state_dict(torch.load(a.backbone_init, map_location=DEV), strict=False)
        print(f"loaded JEPA backbone {a.backbone_init} (missing {len(miss.missing_keys)}, "
              f"unexpected {len(miss.unexpected_keys)})", flush=True)
    model.set_finetune_last4()
    n = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"DINOv2 ViT-g last-4 + head: {n/1e6:.1f}M trainable / "
          f"{sum(p.numel() for p in model.parameters())/1e9:.2f}B total", flush=True)
    per = a.samples // a.epochs
    dl = torch.utils.data.DataLoader(DS(tr, per), batch_size=a.bs, shuffle=True, num_workers=8, drop_last=True)
    vdl = torch.utils.data.DataLoader(DS(va, 0, train=False), batch_size=a.bs, num_workers=2)
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=2e-4)
    bce = nn.BCEWithLogitsLoss(); dloss = smp.losses.DiceLoss(mode="binary")
    best = 0
    for ep in range(1, a.epochs + 1):
        model.train()
        for x, y in dl:
            x, y = x.to(DEV), y.to(DEV); opt.zero_grad()
            out = model(x); wl = torch.sigmoid(out[:, :1]); jl = torch.sigmoid(out[:, 1:])
            loss = (bce(out[:, :1], y[:, :1]) + dloss(out[:, :1], y[:, :1]) + 0.4 * soft_cldice(wl, y[:, :1])
                    + bce(out[:, 1:], y[:, 1:]) + a.node_reg * jl.mean())
            loss.backward(); opt.step()
        model.eval(); d = 0; nb = 0
        with torch.no_grad():
            for x, y in vdl:
                d += dice(torch.sigmoid(model(x.to(DEV))[:, :1]), y.to(DEV)[:, :1]); nb += 1
        d /= max(nb, 1); print(f"epoch {ep}/{a.epochs}  wall val Dice={d:.3f}", flush=True)
        if d >= best:
            best = d; torch.save(model.state_dict(), a.out)
    print(f"best Dice={best:.3f}; saved {a.out}")


if __name__ == "__main__":
    main()
