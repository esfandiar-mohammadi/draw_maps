"""End-to-end service smoke test (no Foundry).

Takes wild .dd2vtt maps (embedded battlemap + GT walls, held out from training),
extracts the raw image, POSTs it to the running wall_service (/detect), and
renders an overlay: GREEN = ground-truth walls, RED = service-predicted walls.
This exercises the exact deployment path the Foundry module uses.
"""
import sys, json, base64, io, urllib.request
import numpy as np, cv2
sys.path.insert(0, "pipeline")
import uvtt

SERVICE = "http://127.0.0.1:8177/detect?scales=1024"


def post_image(png_bytes):
    req = urllib.request.Request(SERVICE, data=png_bytes,
                                 headers={"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main(paths):
    for path in paths:
        r = uvtt.load(path)
        img = r["image"]
        ppg = r["ppg"]
        h, w = img.shape[:2]
        # re-encode the embedded image as PNG bytes (what the module sends)
        ok, buf = cv2.imencode(".png", img)
        res = post_image(buf.tobytes())
        gt = r["walls"]
        pred = res["walls"]
        name = path.rsplit("/", 1)[-1].replace(".dd2vtt", "")
        print(f"{name:40s} {w}x{h} ppg={ppg}  GT={len(gt)} segs  "
              f"PRED={res['count']} segs  {res['elapsed_s']}s", flush=True)
        ov = img.copy()
        for x0, y0, x1, y1 in gt:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 255, 0), 3)
        for x0, y0, x1, y1 in pred:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        out = f"corpus/results/service_e2e_{name}.png"
        cv2.imwrite(out, ov)
        print(f"   overlay -> {out}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
