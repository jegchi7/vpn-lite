#!/usr/bin/env python3
"""Package authored source, bundled policy lists and deployment scripts."""
import hashlib
import json
import os
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
version = json.loads((root / "release.json").read_text())["version"]
destination = root.parent / "dist"
destination.mkdir(exist_ok=True)
archive = destination / ("CHIMERA-" + version + ".zip")
included = {"gateway", "templates", "static", "scripts", "systemd", "data", "docs", "web"}
top = {"README.md", "LICENSE", "AGENTS.md", ".gitignore", "requirements.in", "requirements.lock", "release.json", "setup.example.toml", "vendor/README.md"}
files = []
for directory, folders, names in os.walk(root):
    folders[:] = [name for name in folders if name not in {".git", ".venv", "node_modules", "__pycache__"}]
    for name in names:
        p = Path(directory) / name
        relative = p.relative_to(root)
        if (relative.parts[0] in included or relative.as_posix() in top) and p.suffix != ".pyc":
            files.append(p)
files.sort()
hashes = [hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.relative_to(root).as_posix() for p in files]
(root / "SHA256SUMS").write_text("\n".join(hashes) + "\n")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for path in files:
        relative = path.relative_to(root).as_posix()
        z.write(path, "chimera-" + version + "/" + relative)
    z.writestr("chimera-" + version + "/SHA256SUMS", "\n".join(hashes) + "\n")
print(str(archive))
print(str(len(files)) + " files; " + str(archive.stat().st_size) + " bytes")
