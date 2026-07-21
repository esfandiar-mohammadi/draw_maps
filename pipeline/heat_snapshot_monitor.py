"""Overnight monitor: evaluate each new HEAT in-scope snapshot on the 32 held-out
in-scope maps (CPU, so it never contends with GPU training) and append a summary
line (mean + buildings/caves split) to corpus/results/heat_snapshot_summary.txt.

Runs detached (setsid) so it survives /clear. Reads ep-numbered snapshots
(checkpoint_ep*.pth) which training never overwrites; a snapshot caught mid-write
just fails this round and is retried next round (self-healing). Exits once training
has ended AND all present snapshots (plus checkpoint_best) are evaluated.

Launch:
  cd /home/spark1admin/draw_maps
  setsid bash -c '.venv/bin/python -u pipeline/heat_snapshot_monitor.py \
    > corpus/results/heat_snapshot_monitor.log 2>&1' &
"""
import subprocess, os, time, glob

BASE = "/home/spark1admin/draw_maps"
os.chdir(BASE)
CKDIR = f"{BASE}/vendor/heat/checkpoints/ckpts_heat_fa_inscope"
OUT = f"{BASE}/corpus/results/heat_snapshot_evals"
SUM = f"{BASE}/corpus/results/heat_snapshot_summary.txt"
V = f"{BASE}/.venv/bin/python"
os.makedirs(OUT, exist_ok=True)

inscope = set(open("corpus/fa_test_inscope.txt").read().split())
build = set(open("corpus/fa_test_buildings.txt").read().split())
caves = set(open("corpus/fa_test_caves.txt").read().split())


def note(m):
    line = f"{time.strftime('%F %T')}  {m}"
    with open(SUM, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def training_alive():
    return subprocess.run(["pgrep", "-f", r"train\.py.*s3d_floorplan"],
                          capture_output=True).returncode == 0


def eval_ckpt(ckpt, log):
    env = dict(os.environ, HEAT_EVAL_DEV="cpu", OMP_NUM_THREADS="8")
    with open(log, "w") as f:
        subprocess.run([V, "-u", "pipeline/heat_eval_uvtt.py", "--ckpt", ckpt,
                        "--image_size", "256", "--fa_test",
                        "--fa_list", "corpus/fa_test_inscope.txt", "--per_map"],
                       stdout=f, stderr=subprocess.STDOUT, env=env)
    txt = open(log).read()
    if "MEAN HEAT" not in txt:
        return None
    f1 = {}
    for line in txt.splitlines():
        if "HEAT  P=" in line:
            parts = line.split()
            fv = [p for p in parts if p.startswith("F1=")]
            if fv:
                f1[parts[0]] = float(fv[0][3:])
    mean = lambda s: (sum(v for k, v in f1.items() if k in s) /
                      max(1, len([k for k in f1 if k in s])))
    return len(f1), mean(inscope), mean(build), mean(caves)


def process(ckpt, tag):
    log = f"{OUT}/{tag}.log"
    if os.path.exists(log) and "MEAN HEAT" in open(log).read():
        return  # already done
    note(f"evaluating {tag} ...")
    r = eval_ckpt(ckpt, log)
    if r is None:
        note(f"{tag}: eval incomplete (snapshot maybe mid-write) — will retry")
        return
    n, m, b, c = r
    note(f"{tag}: n={n} mean={m:.3f} buildings={b:.3f} caves={c:.3f}   [best so far vs DINO 0.728]")


note("=== monitor started ===")
for _ in range(3000):
    for ck in sorted(glob.glob(f"{CKDIR}/checkpoint_ep*.pth"),
                     key=lambda p: int(p.split("_ep")[1].split(".")[0])):
        ep = os.path.basename(ck).replace("checkpoint_ep", "").replace(".pth", "")
        process(ck, f"ep{ep}")
    if not training_alive():
        best = f"{CKDIR}/checkpoint_best.pth"
        if os.path.exists(best):
            process(best, "best")
        note("=== training ended; all snapshots evaluated; monitor exiting ===")
        break
    time.sleep(300)
