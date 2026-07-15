#!/usr/bin/env python
"""Parse a UVTT/.dd2vtt file into (image, wall_segments_in_pixels, grid_px).

UVTT: JSON with a base64 PNG under "image", grid size under
resolution.pixels_per_grid, and walls under "line_of_sight" as polylines in
GRID units (portals = doors). We return walls as pixel-coord segments — the
ground truth for measuring detection and for labelling training data.
"""
import json, base64
import numpy as np, cv2


def load(path):
    d = json.load(open(path))
    ppg = d["resolution"]["pixels_per_grid"]
    img_b64 = d["image"]
    arr = np.frombuffer(base64.b64decode(img_b64), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    segs = []
    for poly in d.get("line_of_sight", []):
        pts = [(p["x"] * ppg, p["y"] * ppg) for p in poly]
        for a, b in zip(pts, pts[1:]):
            segs.append((a[0], a[1], b[0], b[1]))
    doors = []
    for portal in d.get("portals", []):
        b = portal.get("bounds", [])
        if len(b) >= 2:
            doors.append((b[0]["x"] * ppg, b[0]["y"] * ppg, b[1]["x"] * ppg, b[1]["y"] * ppg))
    return {"image": img, "walls": segs, "doors": doors, "ppg": ppg,
            "size": (img.shape[1], img.shape[0]) if img is not None else None}


if __name__ == "__main__":
    import sys, os
    r = load(sys.argv[1])
    print(f"image {r['size']} ppg {r['ppg']} walls {len(r['walls'])} doors {len(r['doors'])}")
    ov = r["image"].copy()
    for x0, y0, x1, y1 in r["walls"]:
        cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 3)
    for x0, y0, x1, y1 in r["doors"]:
        cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (255, 128, 0), 4)
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/uvtt_overlay.png"
    cv2.imwrite(out, ov)
    print("overlay ->", out)
