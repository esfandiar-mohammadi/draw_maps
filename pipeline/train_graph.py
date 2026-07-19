#!/usr/bin/env python
"""Learn a PLANAR GRAPH of walls: 2-channel output
  ch0 = wall footprint (as before, gives edges + thickness)
  ch1 = JUNCTION heatmap (nodes: corners, T/X junctions, endpoints)
plus a node-count regulariser (L1 sparsity on predicted junctions) so the graph
uses FEW nodes (long edges). Reuses train_seg's data/augmentation.
"""
import os, sys, glob, random, argparse
import numpy as np, cv2, torch
import torch.nn as nn
import segmentation_models_pytorch as smp
from skimage.morphology import skeletonize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_seg import (augment, IMEAN, ISTD, SZ, DEV, soft_cldice,
                       set_finetune_last8, dice)

N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def junction_map(mask_bin):
    """Nodes = skeleton pixels with degree != 2 (endpoints + junctions), but
    CLUSTERED so a branchy thick-mask skeleton yields few clean nodes (one per
    cluster). Prunes short spurs first."""
    sk = skeletonize(mask_bin > 0).astype(np.uint8)
    H, W = sk.shape
    raw = np.zeros((H, W), np.uint8)
    ys, xs = np.where(sk)
    for y, x in zip(ys, xs):
        d = sum(1 for dy, dx in N8 if 0 <= y + dy < H and 0 <= x + dx < W and sk[y + dy, x + dx])
        if d != 2:
            raw[y, x] = 1
    # cluster nearby junction pixels -> one node per connected blob
    blobs = cv2.dilate(raw, np.ones((5, 5), np.uint8))
    n, _, _, cents = cv2.connectedComponentsWithStats(blobs, 8)
    jm = np.zeros((H, W), np.float32)
    for cx, cy in cents[1:]:
        cv2.circle(jm, (int(round(cx)), int(round(cy))), 3, 1.0, -1)
    return jm


def to_tensor2(img, m):
    x = (cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - IMEAN) / ISTD
    wall = (m > 127).astype(np.float32)
    junc = junction_map(wall)
    y = np.stack([wall, junc])
    return torch.from_numpy(x.transpose(2, 0, 1)), torch.from_numpy(y)


class DS(torch.utils.data.Dataset):
    def __init__(self, files, length, train=True):
        self.files, self.length, self.train = files, length, train
    def __len__(self): return self.length if self.train else len(self.files)
    def __getitem__(self, i):
        rng = random.Random(i * 2654435761 % (2**31)) if self.train else random.Random(i)
        f = self.files[rng.randrange(len(self.files))] if self.train else self.files[i]
        img = cv2.imread(f); m = cv2.imread(f.replace("images", "masks"), 0)
        if self.train:
            img, m = augment(img, m, rng)
        else:
            img = cv2.resize(img, (SZ, SZ)); m = cv2.resize(m, (SZ, SZ), interpolation=cv2.INTER_NEAREST)
        return to_tensor2(img, m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="corpus/donjon/base")
    ap.add_argument("--real", default="corpus/real",
                    help="comma-separated real tile dirs (all oversampled by --real_mul)")
    ap.add_argument("--real_mul", type=int, default=65)
    ap.add_argument("--samples", type=int, default=120000)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--bs", type=int, default=48)
    ap.add_argument("--node_reg", type=float, default=0.02)
    ap.add_argument("--out", default="pipeline/models/wall_graph_unet.pt")
    ap.add_argument("--init", default="", help="checkpoint to warm-start from")
    a = ap.parse_args()
    files = sorted(glob.glob(f"{a.data}/images/*.png"))
    random.seed(0); random.shuffle(files)
    nval = max(20, int(0.1 * len(files))); va, tr = files[:nval], files[nval:]
    real = []
    for rd in a.real.split(","):
        rd = rd.strip()
        if rd:
            real += sorted(glob.glob(f"{rd}/images/*.png"))
    tr = tr + real * a.real_mul; random.shuffle(tr)
    per_epoch = a.samples // a.epochs
    print(f"donjon {len(files)} + real {len(real)}x{a.real_mul} -> {len(tr)} train "
          f"({100*len(real)*a.real_mul//max(1,len(tr))}% real); node_reg={a.node_reg}", flush=True)
    model = smp.Unet(encoder_name="resnet34", encoder_weights="imagenet", classes=2).to(DEV)
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location=DEV))
        print(f"warm-started from {a.init}", flush=True)
    set_finetune_last8(model)
    dl = torch.utils.data.DataLoader(DS(tr, per_epoch), batch_size=a.bs, shuffle=True,
                                     num_workers=8, drop_last=True, persistent_workers=True)
    vdl = torch.utils.data.DataLoader(DS(va, 0, train=False), batch_size=a.bs, num_workers=2)
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=6e-4)
    bce = nn.BCEWithLogitsLoss(); dloss = smp.losses.DiceLoss(mode="binary")
    best = 0
    for ep in range(1, a.epochs + 1):
        model.train()
        for x, y in dl:
            x, y = x.to(DEV), y.to(DEV)
            opt.zero_grad(); out = model(x)
            wall_l = torch.sigmoid(out[:, :1]); junc_l = torch.sigmoid(out[:, 1:])
            loss = (bce(out[:, :1], y[:, :1]) + dloss(out[:, :1], y[:, :1])
                    + 0.4 * soft_cldice(wall_l, y[:, :1])
                    + bce(out[:, 1:], y[:, 1:])
                    + a.node_reg * junc_l.mean())          # node-count sparsity reg
            loss.backward(); opt.step()
        model.eval(); dw = 0; nb = 0
        with torch.no_grad():
            for x, y in vdl:
                x, y = x.to(DEV), y.to(DEV)
                dw += dice(torch.sigmoid(model(x)[:, :1]), y[:, :1]); nb += 1
        dw /= max(nb, 1)
        print(f"epoch {ep}/{a.epochs}  wall val Dice={dw:.3f}", flush=True)
        if dw >= best:
            best = dw; torch.save(model.state_dict(), a.out)
    print(f"best wall Dice={best:.3f}; saved {a.out}")


if __name__ == "__main__":
    main()
