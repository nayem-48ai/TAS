#!/bin/sh
# Self-test for the TTS skill. Offline by default; pass --online for a smoke
# synthesis + QA + JSON check (uses the free API).
set -u
export PYTHONDONTWRITEBYTECODE=1

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
S="$ROOT/tts/scripts/tts.py"
fail=0

ok() { printf 'ok   %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=1; }

run_ok() {
    desc="$1"; shift
    if "$@" >/dev/null 2>&1; then ok "$desc"; else bad "$desc"; fi
}

expect_code() {
    desc="$1"; expected="$2"; shift 2
    "$@" >/dev/null 2>&1
    actual=$?
    if [ "$actual" -eq "$expected" ]; then
        ok "$desc (exit $actual)"
    else
        bad "$desc (expected $expected, got $actual)"
    fi
}

if python3 -m py_compile "$S"; then ok "python compile"; else bad "python compile"; fi
run_ok "help" python3 "$S" --help
run_ok "version" python3 "$S" --version
run_ok "presets" python3 "$S" presets
expect_code "empty text -> validation" 3 python3 "$S" tts
expect_code "uid without voice -> validation" 3 python3 "$S" uid "x"
expect_code "unknown preset -> validation" 3 python3 "$S" tts "x" --preset nope
expect_code "missing verify file -> QA fail" 5 python3 "$S" verify /nonexistent.mp3

if [ "${1:-}" = "--online" ]; then
    tmp=$(mktemp -d)
    run_ok "online: languages" python3 "$S" languages
    run_ok "online: models" python3 "$S" models
    run_ok "online: synthesize" python3 "$S" tts "Self test." -l en -o "$tmp/selftest.mp3"
    run_ok "online: verify" python3 "$S" verify "$tmp/selftest.mp3"
    run_ok "online: json" python3 "$S" languages --json
    rm -rf "$tmp"
fi

if [ "$fail" -eq 0 ]; then
    echo "PASS"
else
    echo "FAILED"
fi
exit "$fail"
