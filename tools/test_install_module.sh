#!/usr/bin/env bash
# Regression test for install.sh's Foundry-module stage (stage 2), including the
# Foundry-in-Docker paths. Uses REAL containers (image: alpine) with a
# foundry-looking process + real volumes; each case builds a throwaway "repo" so
# .install_state stays isolated and the real repo is never touched.
#
#   bash tools/test_install_module.sh
#
# Requirements: docker usable by the current user, the alpine image (pulled
# automatically), unzip. Cases: named volume (docker cp), writable bind mount,
# bind mount owned by uid 421, outdated/polluted copy, no-Docker-access pause +
# resume, uninstall, --foundry-data, unwritable dir via sudo (simulated), no
# Foundry present, --status.
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root
T="$(mktemp -d /tmp/wac-test.XXXXXX)"
export HOME="$T/home"; mkdir -p "$HOME"          # so a real Foundry install on this box cannot influence the tests
PASS=0; FAIL=0
say() { printf '\n\033[1m### %s\033[0m\n' "$*"; }
chk() { if eval "$2"; then printf '  ✓ %s\n' "$1"; PASS=$((PASS+1)); else printf '  ✗ %s\n' "$1"; FAIL=$((FAIL+1)); fi; }

mkrepo() {  # mkrepo <name> → echoes path
  local r="$T/$1"; mkdir -p "$r/pipeline" "$r/foundry_module"
  cp "$SRC/install.sh" "$r/"; : > "$r/pipeline/wall_service.py"
  cp "$SRC/foundry_module/wall-annotation-companion.zip" "$r/foundry_module/"
  printf '%s\n' "$r"
}
ZIPVER="$(unzip -p "$SRC/foundry_module/wall-annotation-companion.zip" module.json | grep -oE '"version"[^,}]*' | head -1)"
echo "zip version field: $ZIPVER"

# a container whose process looks like Foundry (matches the pgrep pattern) and
# whose cgroup is a docker cgroup (so pid_in_container() sees it)
FOUNDRY_CMD='set -- resources/app/main.js --dataPath=/data; while :; do sleep 3; done'
cleanup() {
  docker rm -f wac-t1-foundryvtt wac-t2-foundry wac-t3-foundry >/dev/null 2>&1
  docker run --rm -v "$T/fdata3:/d" alpine sh -c 'rm -rf /d/* /d/.??*' >/dev/null 2>&1
  docker volume rm wac_t1_data >/dev/null 2>&1
  chmod -R u+w "$T" 2>/dev/null
  rm -rf "$T"
}
trap cleanup EXIT

# ═══ T1: named volume (root-only on the host) → install THROUGH docker ═══════
say "T1  named volume → docker cp path"
docker volume create wac_t1_data >/dev/null
docker run --rm -v wac_t1_data:/data alpine sh -c 'mkdir -p /data/Data/modules /data/Data/worlds /data/Config' >/dev/null
docker run -d --name wac-t1-foundryvtt -v wac_t1_data:/data alpine sh -c "$FOUNDRY_CMD" >/dev/null
R="$(mkrepo r1)"; out="$(cd "$R" && bash install.sh --module-only 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0"                      "[ $rc -eq 0 ]"
chk "mode recorded = docker"      "[ \"\$(cat $R/.install_state/chosen.modmode)\" = docker ]"
chk "container recorded"          "[ \"\$(cat $R/.install_state/chosen.container)\" = wac-t1-foundryvtt ]"
chk "module.json inside container has our id" \
    "docker exec wac-t1-foundryvtt cat /data/Data/modules/wall-annotation-companion/module.json | grep -q '\"id\": *\"wall-annotation-companion\"'"
chk "scripts/module.js inside container" \
    "docker exec wac-t1-foundryvtt test -f /data/Data/modules/wall-annotation-companion/scripts/module.js"
chk "reports 'restart the container'" "echo \"\$out\" | grep -q 'restart wac-t1-foundryvtt'"
chk "says browser talks to the service (no port exposure needed)" \
    "echo \"\$out\" | grep -qi 'browser'"
# idempotent re-run
out2="$(cd "$R" && bash install.sh --module-only 2>&1)"; rc2=$?
chk "re-run exit 0"               "[ $rc2 -eq 0 ]"
chk "re-run skips (verified)"     "echo \"\$out2\" | grep -q 'already done, verified'"
# stale copy must be replaced, not merged
docker exec wac-t1-foundryvtt sh -c 'echo junk > /data/Data/modules/wall-annotation-companion/STALE' >/dev/null
docker exec wac-t1-foundryvtt sh -c "sed -i 's|\"version\": *\"[^\"]*\"|\"version\": \"0.0.1\"|' /data/Data/modules/wall-annotation-companion/module.json"
out3="$(cd "$R" && bash install.sh --module-only 2>&1)"; rc3=$?
chk "outdated version is repaired" "[ $rc3 -eq 0 ] && docker exec wac-t1-foundryvtt cat /data/Data/modules/wall-annotation-companion/module.json | grep -q '$(echo "$ZIPVER" | grep -oE '[0-9.]+')'"
chk "stale file removed (not merged)" "! docker exec wac-t1-foundryvtt test -f /data/Data/modules/wall-annotation-companion/STALE"

# ═══ T4: containerized Foundry, but no access to the runtime → PAUSE ════════
say "T4  containerized Foundry + no docker access → pause with instructions"
mkdir -p "$T/stub"
cat > "$T/stub/docker" <<'EOF'
#!/bin/sh
echo "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock" >&2
exit 1
EOF
chmod +x "$T/stub/docker"
R4="$(mkrepo r4)"
out4="$(cd "$R4" && PATH="$T/stub:$PATH" bash install.sh --module-only 2>&1)"; rc4=$?
echo "$out4" | sed 's/^/    | /'
chk "exit code 4 (paused, not failed)" "[ $rc4 -eq 4 ]"
chk "detected the container cgroup"    "echo \"\$out4\" | grep -q 'running inside a container'"
chk "tells usermod -aG docker"         "echo \"\$out4\" | grep -q 'usermod -aG docker'"
chk "tells to log out / newgrp"        "echo \"\$out4\" | grep -qi 'log out' && echo \"\$out4\" | grep -q 'newgrp docker'"
chk "offers sudo -v alternative"       "echo \"\$out4\" | grep -q 'sudo -v'"
chk "offers --foundry-data alternative" "echo \"\$out4\" | grep -q -- '--foundry-data'"
chk "offers --no-module alternative"   "echo \"\$out4\" | grep -q -- '--no-module'"
chk "tells how to resume"              "echo \"\$out4\" | grep -q 'bash install.sh'"
chk "blocked marker written"           "[ -f $R4/.install_state/blocked ]"
chk "nothing installed yet"            "[ ! -f $R4/.install_state/chosen.modmode ]"
# ═══ T6: resume the paused install once access exists ═══════════════════════
say "T6  resume after the pause (access now granted)"
out6="$(cd "$R4" && bash install.sh --module-only 2>&1)"; rc6=$?
chk "exit 0"                      "[ $rc6 -eq 0 ]"
chk "says it resumes"             "echo \"\$out6\" | grep -q 'resuming after'"
chk "blocked marker cleared"      "[ ! -f $R4/.install_state/blocked ]"
chk "module now inside container" "docker exec wac-t1-foundryvtt test -f /data/Data/modules/wall-annotation-companion/module.json"

# ═══ T10: uninstall in docker mode must clean the CONTAINER, not the host ═══
say "T10 uninstall (docker mode)"
out10="$(cd "$R" && bash install.sh --uninstall 2>&1)"; rc10=$?
echo "$out10" | sed 's/^/    | /'
chk "exit 0"                       "[ $rc10 -eq 0 ]"
chk "module gone inside container" "! docker exec wac-t1-foundryvtt test -e /data/Data/modules/wall-annotation-companion"
chk "container itself untouched"   "docker inspect -f '{{.State.Running}}' wac-t1-foundryvtt | grep -q true"
docker rm -f wac-t1-foundryvtt >/dev/null 2>&1

# ═══ T2: bind mount writable by me → plain host copy ════════════════════════
say "T2  bind mount owned by me → host file copy"
mkdir -p "$T/fdata2/Data/modules" "$T/fdata2/Config"
docker run -d --name wac-t2-foundry -v "$T/fdata2:/data" alpine sh -c "$FOUNDRY_CMD" >/dev/null
R2="$(mkrepo r2)"; out="$(cd "$R2" && bash install.sh --module-only 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0"                    "[ $rc -eq 0 ]"
chk "mode = host"               "[ \"\$(cat $R2/.install_state/chosen.modmode)\" = host ]"
chk "files on the host volume"  "[ -f $T/fdata2/Data/modules/wall-annotation-companion/scripts/module.js ]"
chk "correct id on disk"        "grep -q '\"id\": *\"wall-annotation-companion\"' $T/fdata2/Data/modules/wall-annotation-companion/module.json"
docker rm -f wac-t2-foundry >/dev/null 2>&1

# ═══ T3: bind mount owned by the container's uid → route through docker ════
say "T3  bind mount owned by Foundry's container uid (421) → docker cp, no sudo"
mkdir -p "$T/fdata3"
docker run --rm -v "$T/fdata3:/data" alpine sh -c 'mkdir -p /data/Data/modules /data/Config; chown -R 421:421 /data' >/dev/null
docker run -d --name wac-t3-foundry -v "$T/fdata3:/data" alpine sh -c "$FOUNDRY_CMD" >/dev/null
chk "host dir really not writable by me" "[ ! -w $T/fdata3/Data/modules ]"
R3="$(mkrepo r3)"; out="$(cd "$R3" && bash install.sh --module-only 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0"                     "[ $rc -eq 0 ]"
chk "mode = docker (no sudo)"    "[ \"\$(cat $R3/.install_state/chosen.modmode)\" = docker ]"
chk "no sudo was needed"         "! echo \"\$out\" | grep -qi 'root privileges needed'"
chk "files landed in the volume" "[ -f $T/fdata3/Data/modules/wall-annotation-companion/module.json ]"
chk "owned by Foundry's uid 421" "[ \"\$(stat -c %u $T/fdata3/Data/modules/wall-annotation-companion/module.json)\" = 421 ]"
docker rm -f wac-t3-foundry >/dev/null 2>&1

# ═══ T7: --foundry-data, no container involved at all ══════════════════════
say "T7  --foundry-data (explicit path, Docker never touched)"
mkdir -p "$T/fdata7/Data/modules" "$T/fdata7/Config"
R7="$(mkrepo r7)"
out="$(cd "$R7" && PATH="$T/stub:$PATH" bash install.sh --module-only --foundry-data "$T/fdata7" 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0 even with a broken docker CLI" "[ $rc -eq 0 ]"
chk "mode = host"                "[ \"\$(cat $R7/.install_state/chosen.modmode)\" = host ]"
chk "installed at the given path" "[ -f $T/fdata7/Data/modules/wall-annotation-companion/module.json ]"

# ═══ T8: host dir not writable, no container → sudo path (simulated root) ══
say "T8  unwritable host dir, no container → root path (sudo simulated)"
mkdir -p "$T/fdata8/Data/modules"; chmod a-w "$T/fdata8/Data/modules"
mkdir -p "$T/stub2"
cat > "$T/stub2/sudo" <<'EOF'
#!/bin/bash
# fake root: -n true → ok; otherwise loosen the target dir, then run the command
[ "$1" = "-n" ] && shift && { [ "$1" = "true" ] && exit 0; }
[ "$1" = "-v" ] && exit 0
for a in "$@"; do case "$a" in /*) d="$a";; esac; done
chmod -R u+w "$(dirname "${d:-/tmp}")" 2>/dev/null
echo "FAKEROOT: $*" >&2
"$@"
EOF
chmod +x "$T/stub2/sudo"
R8="$(mkrepo r8)"
out="$(cd "$R8" && PATH="$T/stub2:$T/stub:$PATH" bash install.sh --module-only --foundry-data "$T/fdata8" 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0"                       "[ $rc -eq 0 ]"
chk "noticed it is not writable"   "echo \"\$out\" | grep -q 'not writable by'"
chk "used the root path"           "grep -q FAKEROOT $R8/.install_state/install.log"
chk "files installed"              "[ -f $T/fdata8/Data/modules/wall-annotation-companion/module.json ]"

# ═══ T9: no Foundry anywhere → skip with a recipe, do not fail ═════════════
say "T9  no Foundry on this box → skip module, exit 0"
R9="$(mkrepo r9)"
out="$(cd "$R9" && bash install.sh --module-only 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0 (module is not critical)" "[ $rc -eq 0 ]"
chk "explains the manual route"       "echo \"\$out\" | grep -q 'unzip'"
chk "offers --docker-container"       "echo \"\$out\" | grep -q -- '--docker-container'"

# ═══ T11: --status lists the two new steps ════════════════════════════════
say "T11 --status"
out="$(cd "$R7" && bash install.sh --status 2>&1)"; rc=$?
echo "$out" | sed 's/^/    | /'
chk "exit 0"                    "[ $rc -eq 0 ]"
chk "lists the location step"   "echo \"\$out\" | grep -q 'Foundry install location'"
chk "lists the module step"     "echo \"\$out\" | grep -q 'Foundry module files'"

printf '\n\033[1m== %d passed, %d failed ==\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
