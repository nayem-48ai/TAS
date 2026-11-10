#!/bin/sh
# Rebuild tas.skill — the installable skill artifact for agents that take a
# single skill folder (e.g. Claude Desktop upload). The zip root contains a
# `tas/` folder so SKILL.md sits at tas/SKILL.md. Run after ANY edit.
set -e
cd "$(dirname "$0")/.."
rm -f tas.skill
if command -v zip >/dev/null 2>&1; then
    (cd skills && zip -r ../tas.skill tas -x "*/__pycache__/*" "*.pyc" "*.DS_Store") >/dev/null
else
    python3 - <<'PYEOF'
import pathlib
import zipfile

root = pathlib.Path("skills/tas")
with zipfile.ZipFile("tas.skill", "w", zipfile.ZIP_DEFLATED) as z:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        arc = path.relative_to(root.parent).as_posix()  # tas/...
        info = zipfile.ZipInfo.from_file(path, arc)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
        z.writestr(info, path.read_bytes())
PYEOF
fi
echo "rebuilt tas.skill:"
if command -v unzip >/dev/null 2>&1; then
    unzip -l tas.skill
fi
