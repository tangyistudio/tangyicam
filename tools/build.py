"""Reproducible public release. Only explicit --install changes local Blender installs."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tangyicam"
DIST = ROOT / "dist" / "releases"
PUBLIC_DOCS = ["RELEASE_README.md", "CHANGELOG.md", "PRIVACY.md", "TESTING.md"]
PUBLIC_TOOLS = ["build.py", "agent_client.py", "agent_host.py"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for relative, source in sorted(files):
            if source.suffix.lower() in {".pem", ".key", ".pfx", ".blend", ".mp4"}:
                raise RuntimeError("Private/production material cannot enter a release: " + relative)
            info = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, source.read_bytes())
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError("Archive CRC failed: " + bad)


def build():
    manifest = (SRC / "blender_manifest.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', manifest, re.M).group(1)
    for wheel in re.findall(r'"(\./wheels/[^"\n]+)"', manifest):
        if not (SRC / wheel).is_file():
            raise RuntimeError("Missing wheel: " + wheel)
    for name in ("LICENSE.txt", "THIRD_PARTY_NOTICES.md", "bin/mkcert.exe", "web/vendor/qrcode.min.js"):
        if not (SRC / name).is_file():
            raise RuntimeError("Missing release component: " + name)
    addon = [(p.relative_to(SRC).as_posix(), p) for p in SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    target = DIST / version
    target.mkdir(parents=True, exist_ok=True)
    installer = target / ("tangyicam-" + version + "-windows-x64.zip")
    archive(installer, addon)
    source_files = [("tangyicam/" + n, p) for n,p in addon]
    source_files += [("README.md", ROOT / "docs" / "RELEASE_README.md")]
    source_files += [("docs/" + n, ROOT / "docs" / n) for n in PUBLIC_DOCS]
    source_files += [("tools/" + n, ROOT / "tools" / n) for n in PUBLIC_TOOLS]
    source_files += [("tests/" + p.name, p) for p in (ROOT / "tests").iterdir() if p.suffix in {".py", ".mjs"}]
    source = target / ("tangyicam-" + version + "-source.zip")
    archive(source, source_files)
    artifacts = [{"name":p.name,"size":p.stat().st_size,"sha256":digest(p)} for p in (installer,source)]
    release = {"version":version,"channel":"release-candidate","platforms":["windows-x64"],
               "blender_test_targets":["4.5.10","5.1.2"],"phone_acceptance":"pending-iphone",
               "license":"GPL-3.0-or-later","artifacts":artifacts,
               "files":{n:digest(p) for n,p in addon}}
    (target / "release.json").write_text(json.dumps(release,indent=2)+"\n",encoding="utf-8")
    (target / "SHA256SUMS.txt").write_text("".join(x["sha256"]+"  "+x["name"]+"\n" for x in artifacts),encoding="ascii")
    print(json.dumps({"directory":str(target),"artifacts":artifacts},ensure_ascii=False))
    return installer


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--install",metavar="BLENDER_EXE",help="Explicitly install into this Blender executable")
    parser.add_argument("--no-install",action="store_true",help="Compatibility flag; building never installs by default")
    args=parser.parse_args()
    package=build()
    if args.install:
        subprocess.run([args.install,"--command","extension","install-file","-r","user_default","-e",str(package)],check=True)
