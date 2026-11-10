#!/bin/sh
# Rebuild tts.skill (the portable install artifact) from the tts/ folder.
# Run after ANY edit to the skill.
set -e
cd "$(dirname "$0")/.."
rm -f tts.skill
if command -v zip >/dev/null 2>&1; then
    zip -r tts.skill tts -x "*/__pycache__/*" "*.pyc" "*.DS_Store"
else
    python3 - <<'EOF'
import pathlib
import zipfile

root = pathlib.Path("tts")
with zipfile.ZipFile("tts.skill", "w", zipfile.ZIP_DEFLATED) as z:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        info = zipfile.ZipInfo.from_file(path, path.as_posix())
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
        z.writestr(info, path.read_bytes())
EOF
fi
echo "rebuilt tts.skill:"
if command -v unzip >/dev/null 2>&1; then
    unzip -l tts.skill
fi
