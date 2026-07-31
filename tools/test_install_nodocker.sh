#!/usr/bin/env bash
# Regression test: installing the Foundry module when Foundry runs in a
# container and we have NO access to the container runtime at all.
# A PATH stub makes `docker`/`podman` fail like a socket-permission denial,
# while the container (and its Foundry-looking process) is genuinely running.
#
#   bash tools/test_install_nodocker.sh
#
# Covers: host-path discovery via /proc/<pid>/mountinfo (bind mount, writable →
# no root, no docker), named volume (root-only → falls back to the pause with
# the --serve-module option), and --serve-module itself (patched manifest,
# reachable URL, download detection) with curl standing in for Foundry.
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d /tmp/wac-nodocker.XXXXXX)"; export HOME="$T/home"; mkdir -p "$HOME"
PASS=0; FAIL=0
say() { printf '\n\033[1m### %s\033[0m\n' "$*"; }
chk() { if eval "$2"; then printf '  ✓ %s\n' "$1"; PASS=$((PASS+1)); else printf '  ✗ %s\n' "$1"; FAIL=$((FAIL+1)); fi; }
mkrepo() { local r="$T/$1"; mkdir -p "$r/pipeline" "$r/foundry_module"
  cp "$SRC/install.sh" "$r/"; : > "$r/pipeline/wall_service.py"
  cp "$SRC/foundry_module/wall-annotation-companion.zip" "$r/foundry_module/"; printf '%s\n' "$r"; }
cleanup(){ docker rm -f wac-nd-bind wac-nd-vol >/dev/null 2>&1
           docker volume rm wac_nd_vol >/dev/null 2>&1; rm -rf "$T"; }
trap cleanup EXIT

# guard: a foreign Foundry-ish container would be discovered too and could win
if docker ps --format '{{.Names}} {{.Image}}' 2>/dev/null | grep -iE 'foundry|felddy' | grep -qv 'wac-nd-'; then
  echo "REFUSING TO RUN: another foundry-like container is running — it would be"
  echo "picked up by the discovery and make these results meaningless:"
  docker ps --format '  {{.Names}} ({{.Image}})' | grep -iE 'foundry|felddy'
  exit 2
fi

# a docker CLI that behaves like "you are not in the docker group"
mkdir -p "$T/stub"
cat > "$T/stub/docker" <<'EOF'
#!/bin/sh
echo "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock" >&2
exit 1
EOF
chmod +x "$T/stub/docker"
FOUNDRY_CMD='set -- resources/app/main.js --dataPath=/data; while :; do sleep 3; done'

# ═══ N1: bind mount I own → discovered via /proc, installed without docker ═══
say "N1  containerized Foundry, NO docker access, bind mount owned by me"
mkdir -p "$T/fdata/Data/modules" "$T/fdata/Config"
docker run -d --name wac-nd-bind -v "$T/fdata:/data" alpine sh -c "$FOUNDRY_CMD" >/dev/null
sleep 1
R="$(mkrepo r1)"
out="$(cd "$R" && PATH="$T/stub:$PATH" bash install.sh --module-only 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0 (no pause needed)"        "[ $rc -eq 0 ]"
chk "found the volume host path"      "echo \"\$out\" | grep -q '$T/fdata/Data/modules'"
chk "mode = host"                     "[ \"\$(cat $R/.install_state/chosen.modmode)\" = host ]"
chk "module.json really installed"    "grep -q '\"id\": *\"wall-annotation-companion\"' $T/fdata/Data/modules/wall-annotation-companion/module.json"
chk "module.js really installed"      "[ -f $T/fdata/Data/modules/wall-annotation-companion/scripts/module.js ]"
chk "no sudo/root was involved"       "! echo \"\$out\" | grep -qi 'root'"
chk "no docker command succeeded"     "! echo \"\$out\" | grep -q 'docker cp'"
docker rm -f wac-nd-bind >/dev/null 2>&1

# ═══ N2: named volume (root-only) + no docker → pause, offering serve-module ═
say "N2  containerized Foundry, NO docker access, named volume (root-only)"
docker volume create wac_nd_vol >/dev/null
docker run --rm -v wac_nd_vol:/data alpine sh -c 'mkdir -p /data/Data/modules /data/Config' >/dev/null
docker run -d --name wac-nd-vol -v wac_nd_vol:/data alpine sh -c "$FOUNDRY_CMD" >/dev/null
sleep 1
R2="$(mkrepo r2)"
out2="$(cd "$R2" && PATH="$T/stub:$PATH" bash install.sh --module-only 2>&1)"; rc2=$?
echo "$out2" | sed 's/^/    | /'
chk "paused with exit 4"              "[ $rc2 -eq 4 ]"
chk "offers --serve-module route"     "echo \"\$out2\" | grep -q -- '--serve-module'"
chk "says it needs neither docker nor root" "echo \"\$out2\" | grep -qi 'neither'"
chk "still offers the docker-group route"   "echo \"\$out2\" | grep -q 'usermod -aG docker'"

# ═══ N3: --serve-module — Foundry installs it itself ════════════════════════
say "N3  --serve-module (curl stands in for Foundry's installer)"
R3="$(mkrepo r3)"
( cd "$R3" && PATH="$T/stub:$PATH" bash install.sh --serve-module --serve-port 8391 > "$T/serve.out" 2>&1 ) &
SERVE_SH=$!
for i in $(seq 1 40); do grep -q "Manifest URL" "$T/serve.out" 2>/dev/null && break; sleep 0.5; done
URL="$(grep -oE 'http://[0-9.]+:[0-9]+/module.json' "$T/serve.out" | head -1)"
chk "printed a manifest URL"          "[ -n \"$URL\" ]"
chk "URL is not localhost (container must reach it)" "! echo \"$URL\" | grep -q '127.0.0.1'"
MJ="$(curl -fsS --max-time 5 "$URL" 2>/dev/null)"
chk "manifest is served"              "[ -n \"\$MJ\" ]"
chk "manifest has a download URL"     "echo \"\$MJ\" | grep -q '\"download\".*\\.zip'"
chk "manifest has a manifest URL"     "echo \"\$MJ\" | grep -q '\"manifest\".*module.json'"
chk "manifest keeps our module id"    "echo \"\$MJ\" | grep -q '\"id\": *\"wall-annotation-companion\"'"
DL="$(echo "$MJ" | python3 -c 'import json,sys;print(json.load(sys.stdin)["download"])')"
chk "the zip is downloadable"         "curl -fsS -o $T/got.zip --max-time 20 '$DL' && unzip -p $T/got.zip module.json | grep -q wall-annotation-companion"
for i in $(seq 1 40); do grep -q "downloaded the module archive" "$T/serve.out" 2>/dev/null && break; sleep 0.5; done
wait $SERVE_SH; rc3=$?
echo "  --- serve output (tail) ---"; tail -8 "$T/serve.out" | sed 's/^/    | /'
chk "detected the manifest fetch"     "grep -q 'fetched the manifest' $T/serve.out"
chk "detected the zip download"       "grep -q 'downloaded the module archive' $T/serve.out"
chk "exited 0 after the hand-off"     "[ $rc3 -eq 0 ]"
chk "http server stopped"             "! (exec 3<>/dev/tcp/127.0.0.1/8391) 2>/dev/null"

printf '\n\033[1m== %d passed, %d failed ==\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
