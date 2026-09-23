"""Per-user HTTPS setup. Never installs a root into the computer trust store."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile

MKCERT_SHA256 = "d2660b50a9ed59eada480750561c96abc2ed4c9a38c6a24d93e30e0977631398"


def data_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "TangyiCam"


def default_cert_dir():
    return str(data_dir() / "certs")


def certificate_status(folder, address):
    folder = Path(folder)
    if not all((folder / name).is_file() for name in ("server.pem", "server-key.pem", "rootCA.pem")):
        return False, "尚未建立連線憑證，請按「首次設定／更新憑證」"
    try:
        cert = ssl._ssl._test_decode_cert(str(folder / "server.pem"))
        import time
        if ssl.cert_time_to_seconds(cert["notAfter"]) < time.time() + 86400:
            return False, "憑證即將到期，請更新憑證"
        names = {v for kind, v in cert.get("subjectAltName", ()) if kind in ("IP Address", "DNS")}
        if address not in names:
            return False, "電腦 IP 已變更，請按「首次設定／更新憑證」"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(folder / "server.pem"), str(folder / "server-key.pem"))
        return True, "憑證可用"
    except (OSError, ValueError, ssl.SSLError):
        return False, "憑證無法讀取，請更新憑證"


def create_certificate(folder, address):
    import ipaddress
    ipaddress.ip_address(address)
    executable = Path(__file__).parent / "bin" / "mkcert.exe"
    if os.name != "nt":
        raise RuntimeError("此發布版本支援 Windows x64")
    if not executable.is_file() or hashlib.sha256(executable.read_bytes()).hexdigest() != MKCERT_SHA256:
        raise RuntimeError("憑證工具校驗失敗，請重新下載完整 TangyiCam 安裝包")
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    # Each installation owns its own CA; the private root never enters the web directory.
    ca_dir = data_dir() / "private-ca"
    ca_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CAROOT=str(ca_dir))
    with tempfile.TemporaryDirectory(prefix="tc-cert-", dir=folder) as temporary:
        stage = Path(temporary)
        cmd = [str(executable), "-cert-file", str(stage / "server.pem"), "-key-file",
               str(stage / "server-key.pem"), address, "localhost", "127.0.0.1", "::1"]
        result = subprocess.run(cmd, env=env, capture_output=True, timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError("憑證建立失敗，請確認資料夾可寫入與防毒軟體允許 mkcert")
        shutil.copy2(ca_dir / "rootCA.pem", stage / "rootCA.pem")
        ok, message = certificate_status(stage, address)
        if not ok:
            raise RuntimeError(message)
        for name in ("server.pem", "server-key.pem", "rootCA.pem"):
            os.replace(stage / name, folder / name)
    return "憑證已建立；接著啟動攝影機並在 iPhone 安裝一次公開根憑證"
