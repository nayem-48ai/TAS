#!/bin/sh
# Build both distribution artifacts from the repo root:
#   tts.skill  — installable skill folder (via scripts/build-skill.sh)
#   tts.zip    — full project backup / GitHub upload
# Works without the `zip` binary (uses Python's zipfile with Unix modes).
set -e
cd "$(dirname "$0")/.."
./scripts/build-skill.sh

python3 - <<'EOF'
import pathlib
import zipfile

root = pathlib.Path(".")
out = root / "tts.zip"
if out.exists():
    out.unlink()
skip_dirs = {"__pycache__", ".git", "out"}
skip_files = {"tts.zip"}
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if rel.as_posix() in skip_files:
            continue
        if path.suffix in (".pyc", ".pyo"):
            continue
        # Prefix entries with the repo folder name so extraction yields tts/.
        arc = (pathlib.Path("tts") / rel).as_posix()
        info = zipfile.ZipInfo.from_file(path, arc)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
        z.writestr(info, path.read_bytes())
print(f"wrote {out.resolve()}")
EOF

ls -lh tts.skill tts.zip
