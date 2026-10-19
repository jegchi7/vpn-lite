#!/usr/bin/env python3
"""Pinned dependency acquisition/build; also usable on a separate Linux PC/WSL."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "release.json").read_text())
VENDOR = ROOT / "vendor"
DOWNLOADS = VENDOR / "downloads"


def command(argv, env=None):
    subprocess.run([str(x) for x in argv], check=True, env=env)


def asset(key):
    item = MANIFEST["assets"][key]
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    path = DOWNLOADS / item["filename"]
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".part")
        try:
            with urllib.request.urlopen(item["url"], timeout=45) as response, temporary.open("wb") as target:
                shutil.copyfileobj(response, target)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit("SHA256 mismatch: " + path.name + "; файл не используется")
    return path


def unpack(archive, destination):
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")
    children = list(destination.iterdir())
    return children[0] if len(children) == 1 and children[0].is_dir() else destination


def build(arch, role, offline):
    machine_arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    output = VENDOR / ("linux-" + arch) / "bin" if offline else ROOT / "bin"
    output.mkdir(parents=True, exist_ok=True)
    for name, binary in [("sing_box", "sing-box")] + ([("caddy", "caddy")] if role == "ru" else []):
        archive = asset(name + "_" + arch)
        with tempfile.TemporaryDirectory() as tmp:
            source = unpack(archive, Path(tmp))
            shutil.copy2(source / binary, output / binary)
            if (source / "libcronet.so").exists():
                # The selected transports do not use Naive/Cronet.
                pass
    if role == "ru":
        prebuilt = VENDOR / ("linux-" + arch) / "bin"
        hashes = VENDOR / ("linux-" + arch) / "built-sha256.json"
        if not offline and hashes.exists():
            expected = json.loads(hashes.read_text())
            for name in ["amneziawg-go", "awg"]:
                data = (prebuilt / name).read_bytes()
                if hashlib.sha256(data).hexdigest() != expected.get(name):
                    raise SystemExit("Повреждён локальный бинарник " + name)
                shutil.copy2(prebuilt / name, output / name)
        else:
            if machine_arch != arch:
                raise SystemExit("Сборку AWG tools выполняйте на Linux/WSL нужной архитектуры")
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                go_dir, awg_dir, tools_dir = base / "go", base / "awg", base / "tools"
                for folder in [go_dir, awg_dir, tools_dir]:
                    folder.mkdir()
                go_root = unpack(asset("go_" + arch), go_dir)
                source = unpack(asset("awg_go"), awg_dir)
                tools = unpack(asset("awg_tools"), tools_dir)
                env = os.environ.copy()
                env.update(GOROOT=str(go_root), GOTOOLCHAIN="local", CGO_ENABLED="0", GOOS="linux", GOARCH=arch)
                env["PATH"] = str(go_root / "bin") + ":" + env.get("PATH", "")
                command([go_root / "bin/go", "build", "-C", source, "-mod=readonly", "-trimpath", "-ldflags=-s -w", "-o", output / "amneziawg-go", "."], env)
                command(["make", "-C", tools / "src", "WITH_WGQUICK=no", "WITH_SYSTEMDUNITS=no"])
                # Upstream builds 'wg'; its install target names it 'awg'.
                shutil.copy2(tools / "src/wg", output / "awg")
        for path in output.iterdir():
            path.chmod(0o755)
        if offline:
            hashes.write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}, indent=2))
    if offline:
        wheels = VENDOR / "wheels"
        wheels.mkdir(exist_ok=True)
        import sys
        command([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--dest", wheels, "-r", ROOT / "requirements.lock"])
    print("Dependencies prepared for linux-" + arch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=["amd64", "arm64"], default={"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine()))
    parser.add_argument("--role", choices=["ru", "foreign"], default="ru")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not args.arch:
        parser.error("Укажите --arch")
    build(args.arch, args.role, args.offline)
