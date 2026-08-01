#!/usr/bin/env bash
#
# The one stage-1 path a container cannot exercise: `systemctl --user` with a
# REAL user session bus (unit written → enabled → started → self-test → removed).
# Runs on any box that has a user session; pacman is stubbed so the Arch-only
# steps pass, everything else is the genuine code path.
#
#   bash tools/test_install_systemd.sh
#
# Side effects are contained and undone: a scratch repo under /tmp, a user unit
# named wall-service.service on a NON-default port, both removed by
# `install.sh --uninstall` at the end. Any linger state it turns on is restored.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${TEST_PORT:-8188}"
T="$(mktemp -d /tmp/wac-systemd.XXXXXX)"
PASS=0; FAIL=0
say() { printf '\n\033[1m### %s\033[0m\n' "$*"; }
chk() { if eval "$2"; then printf '  ✓ %s\n' "$1"; PASS=$((PASS+1)); else printf '  ✗ %s\n' "$1"; FAIL=$((FAIL+1)); fi; }

systemctl --user show-environment >/dev/null 2>&1 || {
  echo "REFUSING: no user session bus here — this test needs one (that is its point)"; exit 2; }

LINGER_BEFORE="$(loginctl show-user "$(id -un)" 2>/dev/null | grep '^Linger=' || echo Linger=unknown)"
cleanup() {
  (cd "$T/repo" 2>/dev/null && bash install.sh --uninstall >/dev/null 2>&1) || true
  systemctl --user stop wall-service.service >/dev/null 2>&1 || true
  systemctl --user disable wall-service.service >/dev/null 2>&1 || true
  rm -f "$HOME/.config/systemd/user/wall-service.service"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  [ "$LINGER_BEFORE" = "Linger=no" ] && loginctl disable-linger "$(id -un)" >/dev/null 2>&1
  rm -rf "$T"
}
trap cleanup EXIT

say "scratch repo (tracked files) + stubbed pacman so the Arch-only steps pass"
mkdir -p "$T/repo" "$T/stub"
(cd "$REPO" && git ls-files -z | tar --null -T - -cf -) | tar x -C "$T/repo"
ln -s "$REPO/.venv" "$T/repo/.venv"                       # reuse the dev venv, deps are the same
mkdir -p "$T/repo/pipeline/models"
ln -sf "$REPO/pipeline/models/wall_student_convnext_tiny.onnx" "$T/repo/pipeline/models/"
cat > "$T/stub/pacman" <<'EOF'
#!/bin/sh
# every package "installed"; nothing else is asked of pacman in this test
case "${1:-}" in -Qq) exit 0;; -Si) exit 0;; esac
exit 0
EOF
chmod +x "$T/stub/pacman"

say "running install.sh --no-module (real systemd user session, port $PORT)"
out="$(cd "$T/repo" && PATH="$T/stub:$PATH" bash install.sh --no-module --port "$PORT" 2>&1)"; rc=$?
echo "$out" | grep -E '✓|✗|!|Service runs' | sed 's/^/    | /'

chk "install.sh exited 0"                 "[ $rc -eq 0 ]"
chk "took the systemd path (not the fallback)" "[ \"\$(cat $T/repo/.install_state/chosen.svcmode 2>/dev/null)\" = systemd ]"
chk "unit file exists"                    "[ -f $HOME/.config/systemd/user/wall-service.service ]"
chk "systemd reports it active"           "systemctl --user is-active wall-service.service | grep -q '^active'"
chk "systemd reports it enabled"          "systemctl --user is-enabled wall-service.service | grep -qE 'enabled|static'"
chk "service answers on the chosen port"  "curl -fsS --max-time 5 http://127.0.0.1:$PORT/health | grep -q '\"status\": *\"ok\"'"
chk "self-test ran a real detection"      "echo \"\$out\" | grep -qE 'live detection works: [0-9]+ walls'"
chk "summary points at systemctl"         "echo \"\$out\" | grep -q 'systemctl --user status|restart|stop wall-service.service'"
chk "unit survives a restart by systemd"  "systemctl --user restart wall-service.service && sleep 4 && curl -fsS --max-time 5 http://127.0.0.1:$PORT/health | grep -q ok"

say "re-run must verify the running unit and change nothing"
out2="$(cd "$T/repo" && PATH="$T/stub:$PATH" bash install.sh --no-module --port "$PORT" 2>&1)"; rc2=$?
chk "re-run exits 0"                      "[ $rc2 -eq 0 ]"
chk "re-run skips the unit step"          "echo \"\$out2\" | grep -q 'systemd user service (already done, verified)'"
chk "re-run skips 'service running'"      "echo \"\$out2\" | grep -q 'service running (already done, verified)'"

say "uninstall must stop and remove the unit"
out3="$(cd "$T/repo" && bash install.sh --uninstall 2>&1)"
chk "uninstall exits 0"                   "[ \$? -eq 0 ]"
chk "unit file removed"                   "[ ! -f $HOME/.config/systemd/user/wall-service.service ]"
chk "service no longer answers"           "! curl -fsS --max-time 3 http://127.0.0.1:$PORT/health >/dev/null 2>&1"
chk "systemd no longer knows the unit"    "! systemctl --user is-active wall-service.service 2>/dev/null | grep -q '^active'"

printf '\n\033[1m== %d passed, %d failed ==\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
