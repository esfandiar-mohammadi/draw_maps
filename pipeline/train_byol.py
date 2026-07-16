#!/usr/bin/env python
"""BYOL self-supervised pretraining of a ResNet-50 backbone on the (licensed,
local-only) Drakkenheim maps, to adapt HEAT's backbone to the painted-map
domain before supervised fine-tuning.

BYOL is the CNN-native analogue of I-JEPA: an online net + predictor regress the
LATENT projection of an EMA target net across two views; no negatives. (I-JEPA's
token-dropping is ViT-specific; HEAT's backbone is a resnet50, so we use the
same predict-in-latent-space / EMA-target idea in the form that fits a CNN.)
Output weights load straight into HEAT's ResNetBackbone.base_model.
"""
import os, sys, math, random, argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models, transforms
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DEV = "cuda"


class TwoViews(torch.utils.data.Dataset):
    def __init__(self, files, length):
        self.files, self.length = files, length
        self.aug = transforms.Compose([
            transforms.RandomResizedCrop(224, scale=(0.3, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomApply([transforms.ColorJitter(0.4, 0.4, 0.2, 0.1)], p=0.8),
            transforms.RandomGrayscale(p=0.2),
            transforms.RandomApply([transforms.GaussianBlur(23, (0.1, 2.0))], p=0.5),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    def __len__(self):
        return self.length

    def __getitem__(self, i):
        rng = random.Random(i * 2654435761 % 2**31)
        img = None
        while img is None:
            try:
                img = Image.open(rng.choice(self.files)).convert("RGB")
            except Exception:
                img = None
        return self.aug(img), self.aug(img)


def mlp(i, h, o):
    return nn.Sequential(nn.Linear(i, h), nn.BatchNorm1d(h), nn.ReLU(inplace=True), nn.Linear(h, o))


class BYOL(nn.Module):
    def __init__(self, proj_dim=256, hid=4096):
        super().__init__()
        self.backbone = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V2)
        self.backbone.fc = nn.Identity()
        self.projector = mlp(2048, hid, proj_dim)
        self.predictor = mlp(proj_dim, hid, proj_dim)
        self.t_backbone = models.resnet50()
        self.t_backbone.fc = nn.Identity()
        self.t_projector = mlp(2048, hid, proj_dim)
        self._sync(0.0)
        for p in list(self.t_backbone.parameters()) + list(self.t_projector.parameters()):
            p.requires_grad = False

    @torch.no_grad()
    def _sync(self, m):
        for tp, op in zip(self.t_backbone.parameters(), self.backbone.parameters()):
            tp.data.mul_(m).add_(op.data, alpha=1 - m)
        for tp, op in zip(self.t_projector.parameters(), self.projector.parameters()):
            tp.data.mul_(m).add_(op.data, alpha=1 - m)
        for tb, ob in zip(self.t_backbone.buffers(), self.backbone.buffers()):
            tb.data.copy_(ob.data)
        for tb, ob in zip(self.t_projector.buffers(), self.projector.buffers()):
            tb.data.copy_(ob.data)

    def _one(self, v1, v2):
        p = self.predictor(self.projector(self.backbone(v1)))
        with torch.no_grad():
            z = self.t_projector(self.t_backbone(v2))
        return 2 - 2 * (F.normalize(p, dim=-1) * F.normalize(z, dim=-1)).sum(-1)

    def forward(self, v1, v2):
        return (self._one(v1, v2) + self._one(v2, v1)).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssl", default="corpus/drakkenheim_split/ssl_images.txt")
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--out", default="pipeline/models/resnet50_byol.pt")
    ap.add_argument("--smoke", type=int, default=0)
    a = ap.parse_args()

    files = [l.strip() for l in open(a.ssl) if l.strip()]
    print(f"SSL images: {len(files)}", flush=True)
    dl = torch.utils.data.DataLoader(TwoViews(files, a.bs * a.steps), batch_size=a.bs,
                                     num_workers=8, drop_last=True, shuffle=False, pin_memory=True)
    model = BYOL().to(DEV)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=1e-6)

    def lr_at(s):
        if s < a.warmup:
            return a.lr * s / max(1, a.warmup)
        t = (s - a.warmup) / max(1, a.steps - a.warmup)
        return 1e-6 + 0.5 * (a.lr - 1e-6) * (1 + math.cos(math.pi * t))

    step, run = 0, 0.0
    model.train()
    for v1, v2 in dl:
        v1, v2 = v1.to(DEV, non_blocking=True), v2.to(DEV, non_blocking=True)
        for g in opt.param_groups:
            g["lr"] = lr_at(step)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            loss = model(v1, v2)
        opt.zero_grad(); loss.backward(); opt.step()
        m = 0.996 + (1.0 - 0.996) * min(1.0, step / a.steps)
        model._sync(m)
        run += loss.item(); step += 1
        if step % 50 == 0:
            print(f"step {step}/{a.steps}  loss {run/50:.4f}  lr {lr_at(step):.2e}", flush=True); run = 0.0
        if a.smoke and step >= a.smoke:
            print("SMOKE OK", flush=True); return
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    torch.save(model.backbone.state_dict(), a.out)
    print(f"saved BYOL resnet50 backbone -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
