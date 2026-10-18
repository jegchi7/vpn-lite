#!/usr/bin/env python3
"""Package authored source, bundled policy lists and deployment scripts."""
import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
version = json.loads((root / "release.json").read_text())["version"]
destination = root.parent / "dist"
destination.mkdir(exist_ok=True)
archive = destination / ("RU-Foreign-VPN-" + version + ".zip")
included = {"gateway", "templates", "static", "scripts", "systemd", "data", "docs"}
top = {"README.md", "LICENSE", "AGENTS.md", ".gitignore", "requirements.in", "requirements.lock", "release.json", "setup.example.toml", "vendor/README.md"}
files = sorted(p for p in root.rglob("*") if p.is_file() and (p.parts[len(root.parts)] in included or p.relative_to(root).as_posix() in top) and "__pycache__" not in p.parts and p.suffix != ".pyc")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    hashes = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        z.write(path, "ru-foreign-vpn-" + version + "/" + relative)
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + relative)
    z.writestr("ru-foreign-vpn-" + version + "/SHA256SUMS", "\n".join(hashes) + "\n")
print(str(archive))
print(str(len(files)) + " files; " + str(archive.stat().st_size) + " bytes")
