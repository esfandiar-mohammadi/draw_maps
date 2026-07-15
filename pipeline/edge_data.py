#!/usr/bin/env python
"""Turn (donjon image, wall mask) into a STRUCTURED grid-edge label.

The structured wall representation: for each grid cell, two booleans — is there a
wall on its TOP edge (H) and on its LEFT edge (V). This is the target the edge-
output model predicts; by construction it can only encode straight, grid-aligned,
connected wall segments.

Per-image cell size is detected from the mask (donjon's cell px varies).
"""
import numpy as np, cv2

CELL = 16  # canonical pixels per cell after resampling


def detect_cell(mask, pmin=5, pmax=40):
    """Detect (period, offx, offy) of the wall grid from the binary mask."""
    b = (mask > 127).astype(np.float32)
    def axis(proj):
        s = proj - proj.mean()
        ac = np.correlate(s, s, "full")[len(s) - 1:]
        pmax2 = min(pmax, len(s) // 3)
        cand = [(ac[p], p) for p in range(pmin, pmax2)]
        cand.sort(reverse=True)
        p0 = cand[0][1]
        for d in (2, 3):
            if ac[max(pmin, p0 // d)] >= 0.6 * ac[p0] and p0 // d >= pmin:
                p0 = p0 // d
        # phase: offset maximising line hits
        best, boff = -1, 0
        for off in range(p0):
            idx = np.arange(off, len(proj), p0)
            v = proj[idx].mean()
            if v > best:
                best, boff = v, off
        return p0, boff
    px, offx = axis(b.sum(0))
    py, offy = axis(b.sum(1))
    period = int(round((px + py) / 2))
    return period, offx % period, offy % period


def to_canonical(img, mask):
    """Resample so cell==CELL px, return canonical image, mask, and (ncx,ncy)."""
    period, offx, offy = detect_cell(mask)
    if period < 4:
        return None
    scale = CELL / period
    ci = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cm = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    ox, oy = int(round(offx * scale)), int(round(offy * scale))
    ci = ci[oy:, ox:]; cm = cm[oy:, ox:]
    ncy, ncx = ci.shape[0] // CELL, ci.shape[1] // CELL
    ci = ci[:ncy * CELL, :ncx * CELL]; cm = cm[:ncy * CELL, :ncx * CELL]
    return ci, cm, ncx, ncy


def edge_labels(cm, ncx, ncy, thick=3):
    """H[j,i]=wall on top edge of cell(i,j); V[j,i]=wall on left edge."""
    m = (cm > 127).astype(np.uint8)
    H = np.zeros((ncy, ncx), np.float32); V = np.zeros((ncy, ncx), np.float32)
    for j in range(ncy):
        yc = j * CELL
        for i in range(ncx):
            xc = i * CELL
            band_h = m[max(0, yc - thick):yc + thick + 1, xc:xc + CELL]
            band_v = m[yc:yc + CELL, max(0, xc - thick):xc + thick + 1]
            H[j, i] = 1.0 if band_h.mean() > 0.25 else 0.0
            V[j, i] = 1.0 if band_v.mean() > 0.25 else 0.0
    return H, V


def edges_to_segments(H, V, cell=CELL, ox=0, oy=0):
    """Structured edges -> straight connected wall segments (grid coords)."""
    ncy, ncx = H.shape
    segs = []
    for j in range(ncy):  # merge consecutive H in a row
        i = 0
        while i < ncx:
            if H[j, i] > 0.5:
                i0 = i
                while i < ncx and H[j, i] > 0.5:
                    i += 1
                segs.append((ox + i0 * cell, oy + j * cell, ox + i * cell, oy + j * cell))
            else:
                i += 1
    for i in range(ncx):  # merge consecutive V in a column
        j = 0
        while j < ncy:
            if V[j, i] > 0.5:
                j0 = j
                while j < ncy and V[j, i] > 0.5:
                    j += 1
                segs.append((ox + i * cell, oy + j0 * cell, ox + i * cell, oy + j * cell))
            else:
                j += 1
    return segs


if __name__ == "__main__":
    import glob, sys
    fs = sorted(glob.glob("corpus/donjon/base/images/*.png"))[:3]
    for k, f in enumerate(fs):
        img = cv2.imread(f); mask = cv2.imread(f.replace("images", "masks"), 0)
        r = to_canonical(img, mask)
        if r is None:
            print(f, "cell detect failed"); continue
        ci, cm, ncx, ncy = r
        H, V = edge_labels(cm, ncx, ncy)
        segs = edges_to_segments(H, V)
        ov = ci.copy()
        for x0, y0, x1, y1 in segs:
            cv2.line(ov, (x0, y0), (x1, y1), (0, 0, 255), 1)
        vis = np.hstack([ci, ov])
        cv2.imwrite(f"/tmp/claude-1000/-home-spark1admin-draw-maps/cf6b135d-83e9-476c-b084-95aff54a5c4c/scratchpad/edge_lbl_{k}.png", vis)
        print(f, f"cells {ncx}x{ncy}, edges H={int(H.sum())} V={int(V.sum())}")
