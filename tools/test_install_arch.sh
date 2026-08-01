#!/usr/bin/env bash
#
# Run install.sh's SERVICE half (stage 1) for real inside an Arch container:
# pacman transactions, venv creation, wheel resolution, the port/threads choice,
# starting the service and the end-to-end self-test. None of that can run on the
# Ubuntu dev box, so it was previously only reasoned about.
#
#   bash tools/test_install_arch.sh [--keep] [--download] [--presync]
#
#   --keep      leave the container running for poking around afterwards
#   --download  do NOT pre-place the model; let install.sh fetch it (122 MB)
#   --presync   run `pacman -Sy` first (a normal, up-to-date box); without it the
#               image's stale db forces install.sh's -Syu fallback path
#
# CAVEAT 1: this is Arch Linux ARM (aarch64), not Arch x86_64 — the flow, the
# pacman transactions and the pip resolution are real, but wheel availability
# for the target's x86_64 Python can still differ.
# CAVEAT 2: run this in the FOREGROUND. A detached/background run gets killed
# during the last (longest) scenario, which then reports nothing; that is an
# environment quirk of this dev box, not an installer fault — the scenario was
# verified separately by running it directly against a prepared container.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${ARCH_IMAGE:-menci/archlinuxarm:base}"
NAME="wac-arch-test"
KEEP=0; DOWNLOAD=0; PRESYNC=0
while [ $# -gt 0 ]; do
  case "$1" in
    --keep) KEEP=1; shift;;
    --download) DOWNLOAD=1; shift;;
    --presync) PRESYNC=1; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
PASS=0; FAIL=0
say() { printf '\n\033[1m### %s\033[0m\n' "$*"; }
chk() { if eval "$2"; then printf '  ✓ %s\n' "$1"; PASS=$((PASS+1)); else printf '  ✗ %s\n' "$1"; FAIL=$((FAIL+1)); fi; }
dex() { docker exec "$NAME" bash -lc "$1"; }

cleanup() { [ "$KEEP" -eq 1 ] || docker rm -f "$NAME" >/dev/null 2>&1; }
trap cleanup EXIT

say "starting $IMAGE"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" "$IMAGE" sleep infinity >/dev/null || { echo "cannot start container"; exit 1; }

# Ship the TRACKED files with WORKING-TREE content: same file set a fresh clone
# gets (no .venv, no corpus, no untracked junk), but including edits that are not
# committed yet — otherwise every iteration would test the previous commit.
say "installing a pristine copy of the repo (tracked files, working-tree content)"
dex 'mkdir -p /root/draw_maps'
(cd "$REPO" && git ls-files -z | tar --null -T - -cf -) | docker exec -i "$NAME" tar x -C /root/draw_maps
chk "install.sh present in the clone" "docker exec $NAME test -f /root/draw_maps/install.sh"
chk "module zip present in the clone"  "docker exec $NAME test -f /root/draw_maps/foundry_module/wall-annotation-companion.zip"

if [ "$DOWNLOAD" -eq 0 ]; then
  say "pre-placing the model (skip the 122 MB download; that path is verified separately)"
  dex 'mkdir -p /root/draw_maps/pipeline/models'
  docker cp "$REPO/pipeline/models/wall_student_convnext_tiny.onnx" \
            "$NAME:/root/draw_maps/pipeline/models/" >/dev/null
fi
[ "$PRESYNC" -eq 1 ] && { say "pacman -Sy (simulating an up-to-date box)"; dex 'pacman -Sy --noconfirm' >/dev/null 2>&1 || true; }

say "running install.sh --no-module (systemd --user does not exist in a container)"
set +e
docker exec "$NAME" bash -lc 'cd /root/draw_maps && timeout 3000 bash install.sh --no-module --no-service 2>&1' \
  | tee /tmp/wac-arch-install.log | tail -40
rc=${PIPESTATUS[0]}
set -e
echo
chk "install.sh exited 0"                  "[ $rc -eq 0 ]"
chk "pacman step reported success"         "grep -qE '✓ system packages' /tmp/wac-arch-install.log"
chk "venv built"                           "docker exec $NAME test -x /root/draw_maps/.venv/bin/python"
chk "onnxruntime importable in the venv"   "docker exec $NAME /root/draw_maps/.venv/bin/python -c 'import onnxruntime' >/dev/null 2>&1"
chk "opencv importable in the venv"        "docker exec $NAME /root/draw_maps/.venv/bin/python -c 'import cv2' >/dev/null 2>&1"
chk "skimage.skeletonize importable"       "docker exec $NAME /root/draw_maps/.venv/bin/python -c 'from skimage.morphology import skeletonize' >/dev/null 2>&1"
chk "service answers /health"              "docker exec $NAME bash -lc 'curl -fsS --max-time 5 http://127.0.0.1:\$(cat /root/draw_maps/.install_state/chosen.port)/health' | grep -q '\"status\": *\"ok\"'"
chk "health names the ConvNeXt model"      "docker exec $NAME bash -lc 'curl -fsS --max-time 5 http://127.0.0.1:\$(cat /root/draw_maps/.install_state/chosen.port)/health' | grep -q convnext"
chk "self-test detected walls"             "grep -qE 'live detection works: [0-9]+ walls' /tmp/wac-arch-install.log"
chk "threads kept ~20% of cores free"      "t=\$(docker exec $NAME cat /root/draw_maps/.install_state/chosen.threads 2>/dev/null); n=\$(docker exec $NAME nproc); [ -n \"\$t\" ] && [ \"\$t\" -le \"\$n\" ]"
chk "state recorded for every stage-1 step" "docker exec $NAME bash -lc 'for s in sanity pacman model venv pydeps config running selftest; do test -f /root/draw_maps/.install_state/step.\$s || exit 1; done'"

say "re-run must be a no-op (every step verified and skipped)"
out2="$(docker exec "$NAME" bash -lc 'cd /root/draw_maps && bash install.sh --no-module --no-service 2>&1')"; rc2=$?
chk "re-run exits 0"                       "[ $rc2 -eq 0 ]"
chk "re-run skips the model step"          "echo \"\$out2\" | grep -q 'model file (already done, verified)'"
chk "re-run skips the venv step"           "echo \"\$out2\" | grep -q 'python virtualenv (already done, verified)'"
chk "re-run does not rebuild anything"     "! echo \"\$out2\" | grep -qE 'downloading|rebuilding|installing packages'"

say "self-healing: delete the venv, re-run, it must repair itself"
dex 'rm -rf /root/draw_maps/.venv' >/dev/null
out3="$(docker exec "$NAME" bash -lc 'cd /root/draw_maps && timeout 1800 bash install.sh --no-module --no-service 2>&1')"
chk "repaired the venv"                    "docker exec $NAME test -x /root/draw_maps/.venv/bin/python"
chk "service healthy again"                "docker exec $NAME bash -lc 'curl -fsS --max-time 5 http://127.0.0.1:\$(cat /root/draw_maps/.install_state/chosen.port)/health' | grep -q ok"

say "systemd path: no session bus in a container → must fall back, not fail"
# also stop the service from the previous scenario: otherwise it still answers on
# the port, verify_running passes, and do_running (the branch under test) is skipped
dex 'pkill -f wall_service.py; rm -rf /root/draw_maps/.install_state /root/draw_maps/.venv' >/dev/null 2>&1
sleep 2
out4="$(docker exec "$NAME" bash -lc 'cd /root/draw_maps && timeout 2400 bash install.sh --no-module 2>&1')"; rc4=$?
echo "$out4" | grep -E "systemd|background|✓ service running|✗" | head -6 | sed 's/^/    | /'
chk "install still succeeds without systemd" "[ $rc4 -eq 0 ]"
chk "wrote the systemd user unit file"       "docker exec $NAME test -f /root/.config/systemd/user/wall-service.service"
chk "unit points at the venv python"         "docker exec $NAME grep -q '/root/draw_maps/.venv/bin/python pipeline/wall_service.py' /root/.config/systemd/user/wall-service.service"
chk "unit carries the ConvNeXt model + thr"  "docker exec $NAME grep -qE 'wall_student_convnext_tiny.onnx .*--wall_thr 0.5' /root/.config/systemd/user/wall-service.service"
chk "explained the fallback to the user"     "echo \"\$out4\" | grep -qi 'systemd --user is not reachable'"
chk "told them what to run after login"      "echo \"\$out4\" | grep -q 'systemctl --user enable --now wall-service.service'"
chk "service is up anyway"                   "echo \"\$out4\" | grep -q 'live detection works'"

printf '\n\033[1m== %d passed, %d failed ==\033[0m\n' "$PASS" "$FAIL"
echo "full installer log: /tmp/wac-arch-install.log"
[ "$FAIL" -eq 0 ]
