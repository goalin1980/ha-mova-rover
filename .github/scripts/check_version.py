"""Verify that the Python and manifest integration versions remain identical."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
manifest = json.loads(
    (ROOT / "custom_components/mova_rover/manifest.json").read_text(encoding="utf-8")
)
tree = ast.parse((ROOT / "custom_components/mova_rover/const.py").read_text(encoding="utf-8"))
python_version = None
for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "INTEGRATION_VERSION":
                python_version = ast.literal_eval(node.value)

if manifest.get("version") != python_version:
    print(f"Version mismatch: manifest={manifest.get('version')!r}, Python={python_version!r}")
    sys.exit(1)

print(f"Version is consistent: {python_version}")
