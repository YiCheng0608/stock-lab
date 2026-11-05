#!/usr/bin/env bash
# The CJK font for the CI verify job's screenshots (Issue #489).
#
#   bash tools/verify/install_fonts.sh --cache <dir> --log <file>
#
# The runner has no CJK font; without one the screenshots show boxes (the text checks do not
# care). On 2026-11-04 the bare `apt-get update && apt-get install fonts-noto-cjk` took 12 to
# over 15 minutes three times and the job hit its 15-minute limit. So:
#
# 1. <dir>/fonts-noto-cjk.tar (the package's files, restored by actions/cache) is unpacked
#    onto / when present; apt is not touched.
# 2. Otherwise apt-get update and apt-get install each run under `timeout` and are retried;
#    after an install the package's files go into the tarball for actions/cache to save.
# 3. A command that runs out of time is stopped; the script prints which one, how long it ran,
#    the last lines of its output and the apt/dpkg/http processes still running, and exits 1
#    instead of waiting for the job to be cancelled.
#
# Every command's output goes to <file> (uploaded with the verify artifact); the step log gets
# one line per command with its seconds. Limits in seconds, overridable for the tests in
# tools/ci/test_checks.py (VerifyFonts): VERIFY_FONTS_UPDATE_TIMEOUT (60),
# VERIFY_FONTS_INSTALL_TIMEOUT (120), VERIFY_FONTS_RESTORE_TIMEOUT (60), VERIFY_FONTS_ATTEMPTS
# (2). The worst case, 2 x (60 + 120) + 60 + 60 seconds, stays inside the step's 10 minutes.

set -u -o pipefail

PKG=fonts-noto-cjk
UPDATE_TIMEOUT=${VERIFY_FONTS_UPDATE_TIMEOUT:-60}
INSTALL_TIMEOUT=${VERIFY_FONTS_INSTALL_TIMEOUT:-120}
RESTORE_TIMEOUT=${VERIFY_FONTS_RESTORE_TIMEOUT:-60}
ATTEMPTS=${VERIFY_FONTS_ATTEMPTS:-2}
# A stalled connection is retried by apt itself well before the command's own limit.
APT_OPTS=(-o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 -o Acquire::Retries=2 -o DPkg::Lock::Timeout=30)

cache='' log=''
while [ $# -gt 0 ]; do
  case "$1" in
    --cache) cache=${2:-}; shift 2 ;;
    --log) log=${2:-}; shift 2 ;;
    *) echo "usage: install_fonts.sh --cache <dir> --log <file>" >&2; exit 64 ;;
  esac
done
if [ -z "$cache" ] || [ -z "$log" ]; then
  echo "usage: install_fonts.sh --cache <dir> --log <file>" >&2
  exit 64
fi
mkdir -p "$cache" "$(dirname "$log")"
tarball="$cache/$PKG.tar"

note() {
  printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*" | tee -a "$log"
}

diagnose() {
  echo "---- 診斷：$log（含 apt 輸出）最後 40 行"
  tail -n 40 "$log"
  echo "---- 還在跑的 apt／dpkg／http 行程"
  if command -v ps > /dev/null; then
    # By program name (apt's download methods are .../apt/methods/http and https), not by
    # command line, which would also match this script's callers.
    ps -eo pid,etimes,comm,args | awk 'NR == 1 || $3 ~ /^(apt|apt-get|dpkg|http|https|gpgv)$/ { print; n++ } END { if (n < 2) print "（沒有）" }'
  else
    echo "（沒有 ps）"
  fi
  echo "---- apt 來源"
  grep -rhoE 'https?://[^ ]+' /etc/apt/sources.list /etc/apt/sources.list.d 2> /dev/null | sort -u || true
}

# run <seconds> <label> <command...>: the command's output goes to the log only.
run() {
  local limit=$1 label=$2 started=$SECONDS status took
  shift 2
  note "開始：$label（上限 $limit 秒）：$*"
  timeout --kill-after=5 "$limit" "$@" >> "$log" 2>&1
  status=$?
  took=$((SECONDS - started))
  if [ "$status" -eq 0 ]; then
    note "完成：$label（$took 秒）"
    return 0
  fi
  if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
    note "逾時：$label 跑了 $took 秒仍未結束（上限 $limit 秒），已中止"
  else
    note "失敗：$label exit $status（$took 秒）"
  fi
  diagnose
  return 1
}

have_font() {
  fc-list ':lang=zh-tw' family 2> /dev/null | grep -q 'Noto Sans CJK'
}

if have_font; then
  note "字型已在 runner 上"
  exit 0
fi
if [ -s "$tarball" ]; then
  if run "$RESTORE_TIMEOUT" "從快取還原 $PKG" sudo tar -xf "$tarball" -C / \
    && run "$RESTORE_TIMEOUT" "fc-cache" sudo fc-cache -f \
    && have_font; then
    note "字型就緒（快取）"
    exit 0
  fi
  note "快取還原後仍沒有 Noto Sans CJK，改用 apt"
fi

installed=''
for attempt in $(seq 1 "$ATTEMPTS"); do
  run "$UPDATE_TIMEOUT" "apt-get update（第 $attempt／$ATTEMPTS 次）" \
    sudo apt-get "${APT_OPTS[@]}" update || continue
  run "$INSTALL_TIMEOUT" "apt-get install $PKG（第 $attempt／$ATTEMPTS 次）" \
    sudo apt-get "${APT_OPTS[@]}" install -y --no-install-recommends "$PKG" || continue
  installed=1
  break
done
if [ -z "$installed" ]; then
  echo "::error title=verify fonts::$PKG 試了 $ATTEMPTS 次都沒裝好，見上方診斷與 $log"
  exit 1
fi
if ! have_font; then
  note "裝完 $PKG 仍找不到 Noto Sans CJK"
  diagnose
  echo "::error title=verify fonts::裝完 $PKG 仍找不到 Noto Sans CJK"
  exit 1
fi

# The package's files and links (not its directories), relative to / for tar -C /.
list="$cache/files.txt"
dpkg -L "$PKG" | while IFS= read -r path; do
  if [ -f "$path" ] || [ -L "$path" ]; then printf '%s\n' "${path#/}"; fi
done > "$list"
if [ -s "$list" ] && tar -C / -cf "$tarball.partial" -T "$list" >> "$log" 2>&1; then
  mv "$tarball.partial" "$tarball"
  note "已寫入快取 $tarball（$(wc -l < "$list") 個檔）"
else
  rm -f "$tarball.partial"
  note "沒寫成快取（下次仍走 apt）"
fi
rm -f "$list"
note "字型就緒（apt）"
