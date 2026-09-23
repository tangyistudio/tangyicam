# -*- coding: utf-8 -*-
"""TangyiCam 的網路層：一個 HTTPS 伺服器同時做三件事。

1. 靜態檔：手機頁（web/）與 PC 的 QR 頁。
2. WebSocket（/ws）：手機 → 姿態 JSON；Blender → 預覽 JPEG（二進位）與遙測 JSON。
3. 另開一個純 HTTP 埠（預設 8080）只為了讓 iPhone 抓 rootCA.pem 裝憑證——
   憑證裝好之前 HTTPS 進不來，這是唯一的入口。

全部只用標準庫（http.server、ssl、socket、hashlib）。WebSocket 依 RFC 6455
自己拆幀，不用 websockets 套件——Blender 的 Python 沒有它，而我們不想為了
一個握手多帶一個 wheel。

執行緒模型：
- 每個連線一條讀取執行緒（handler 本身），解析幀後呼叫 on_message(client, dict)。
- 每個連線一條寫入執行緒，從 queue 取資料送出。影像用「只留最新一張」的槽，
  文字用一般佇列——網路慢的時候丟舊畫面，不排隊。
- Blender 主執行緒只呼叫 broadcast_*()，永遠不會被網路卡住。
"""

import base64
import hashlib
import http.server
import json
import mimetypes
import os
import queue
import socket
import ssl
import struct
import threading
import time
import urllib.parse
import hmac
import ipaddress
from http.cookies import SimpleCookie

from .security import Pairing, COOKIE_NAME, SESSION_SECONDS, validate_control

WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---------------------------------------------------------------------------
# WebSocket 用戶端
# ---------------------------------------------------------------------------
class WSClient:
    def __init__(self, conn, addr, role="phone"):
        self.conn = conn
        self.addr = addr
        self.role = role
        self.alive = True
        self.connected_at = time.time()
        self.last_rx = time.time()
        self._text_q = queue.Queue(maxsize=32)
        self._video_lock = threading.Lock()
        self._video = None  # 最新一張 JPEG；舊的直接被蓋掉
        self._video_evt = threading.Event()
        self._send_lock = threading.Lock()
        self._io_lock = threading.Lock()  # One OpenSSL operation per connection.
        self.last_error = ""
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()

    # ---- 送出 --------------------------------------------------------------
    def send_text(self, obj):
        if self.alive:
            try:
                self._text_q.put_nowait(json.dumps(obj, ensure_ascii=False))
            except queue.Full:
                self.close()
                return
            self._video_evt.set()

    def send_video(self, jpeg_bytes):
        if not self.alive:
            return
        with self._video_lock:
            self._video = jpeg_bytes
        self._video_evt.set()

    def _write_loop(self):
        while self.alive:
            self._video_evt.wait(timeout=0.5)
            self._video_evt.clear()
            try:
                while True:
                    try:
                        text = self._text_q.get_nowait()
                    except queue.Empty:
                        break
                    self._send_frame(0x1, text.encode("utf-8"))
                with self._video_lock:
                    frame, self._video = self._video, None
                if frame is not None:
                    self._send_frame(0x2, frame)
            except Exception:
                self.close()
                return

    def _send_frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header += struct.pack(">H", n)
        else:
            header.append(127)
            header += struct.pack(">Q", n)
        with self._send_lock, self._io_lock:
            self.conn.settimeout(0.5)
            self.conn.sendall(bytes(header) + payload)

    def pong(self, payload):
        try:
            self._send_frame(0xA, payload)
        except Exception:
            self.close()

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self._video_evt.set()
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass

    # ---- 讀取（在 handler 執行緒裡跑）----------------------------------------
    def read_frame(self):
        """回傳 (opcode, payload)；連線結束回傳 (None, None)。"""
        head = self._recv_exact(2)
        if head is None:
            return None, None
        b0, b1 = head
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        if not (b0 & 0x80) or (b0 & 0x70) or not masked or opcode not in (1, 8, 9, 10):
            return None, None
        n = b1 & 0x7F
        if n == 126:
            ext = self._recv_exact(2)
            if ext is None:
                return None, None
            n = struct.unpack(">H", ext)[0]
        elif n == 127:
            ext = self._recv_exact(8)
            if ext is None:
                return None, None
            n = struct.unpack(">Q", ext)[0]
        if n > 4096 or (opcode >= 8 and n > 125):
            return None, None
        mask = None
        if masked:
            mask = self._recv_exact(4)
            if mask is None:
                return None, None
        payload = self._recv_exact(n) if n else b""
        if payload is None:
            return None, None
        if mask:
            payload = bytes(payload[i] ^ mask[i % 4] for i in range(n)) if n < 512 else _unmask(payload, mask)
        return opcode, payload

    def _recv_exact(self, n):
        buf = bytearray()
        deadline = time.monotonic() + 15
        while len(buf) < n:
            try:
                with self._io_lock:
                    self.conn.settimeout(0.01)
                    chunk = self.conn.recv(n - len(buf))
            except (socket.timeout, TimeoutError):
                if not self.alive or time.monotonic() >= deadline:
                    return None
                time.sleep(0.001)  # Let the writer acquire the shared TLS lock.
                continue
            except Exception:
                return None
            if not chunk:
                return None
            buf += chunk
        return bytes(buf)


def _unmask(payload, mask):
    # 大封包用 int 位元運算一次做完，比逐 byte 快很多
    n = len(payload)
    full = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(full, "big")).to_bytes(n, "big")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TangyiCam/0.4"

    def setup(self):
        self.request.settimeout(10)
        if isinstance(self.request, ssl.SSLSocket):
            self.request.do_handshake()
        super().setup()

    def log_message(self, fmt, *args):
        pass  # Pairing codes/cookies must never appear in request logs.

    def _secure(self):
        return isinstance(self.connection, ssl.SSLSocket)

    def _host_ok(self, local=False):
        srv = self.server.tc
        port = srv.https_port if self._secure() else srv.http_port
        hosts = {"127.0.0.1", "localhost"} if local else {"127.0.0.1", "localhost", srv.lan_ip}
        return self.headers.get("Host", "").lower() in {"%s:%d" % (h, port) for h in hosts}

    def _local(self):
        return ipaddress.ip_address(self.client_address[0]).is_loopback and self._host_ok(local=True)

    def _same_origin(self):
        scheme = "https" if self._secure() else "http"
        return self._host_ok() and self.headers.get("Origin") == scheme + "://" + self.headers.get("Host", "")

    def _token(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else None
        except Exception:
            return None

    def _json(self, value, code=200, extra=None):
        return self._send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"),
                                "application/json; charset=utf-8", code, extra)

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "invalid_host"}, 403)
        srv = self.server.tc
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/qr", "/qr.html", "/qr.js", "/local-info", "/vendor/qrcode.min.js"):
            if not self._local():
                return self._json({"error": "computer_only"}, 403)
            if path == "/local-info":
                info = srv.info()
                info.update(srv.pairing.status())
                info["admin_token"] = srv.pairing.admin_token
                return self._json(info)
            path = "/qr.html" if path == "/qr" else path
        elif path == "/bootstrap.json":
            return self._json({"url": srv.url(), "fingerprint": srv.ca_fingerprint()})
        elif path == "/ca.pem":
            return self._send_file(srv.ca_path, "application/x-x509-ca-cert",
                                   extra={"Content-Disposition": 'attachment; filename="TangyiCam-rootCA.pem"'})
        elif path in ("/help", "/help.html", "/help.js", "/setup.css"):
            path = "/help.html" if path == "/help" else path
        elif not self._secure():
            return self._json({"error": "https_required"}, 403)
        elif path in ("/state", "/shots.json", "/ws"):
            token = self._token()
            if not srv.pairing.valid(token):
                return self._json({"error": "pairing_required"}, 401)
            if path == "/ws":
                return self._websocket(token)
            if path == "/state":
                return self._json(srv.info())
            return self._json(srv.shots_provider() if srv.shots_provider else {"fps": 24, "shots": []})
        path = "/index.html" if path in ("/", "") else path
        allowed = {"/index.html", "/app.js", "/style.css", "/manifest.webmanifest", "/help.html",
                   "/help.js", "/setup.css", "/qr.html", "/qr.js", "/vendor/qrcode.min.js"}
        if path not in allowed:
            return self._json({"error": "not_found"}, 404)
        full = os.path.join(srv.web_dir, path.lstrip("/"))
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if path.endswith(".js"):
            ctype = "application/javascript"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        return self._send_file(full, ctype)

    def do_POST(self):
        srv = self.server.tc
        if not self._same_origin():
            return self._json({"error": "invalid_origin"}, 403)
        path = urllib.parse.urlparse(self.path).path
        if path == "/local/rotate":
            if not self._local() or not hmac.compare_digest(self.headers.get("X-TangyiCam-Admin", ""), srv.pairing.admin_token):
                return self._json({"error": "computer_only"}, 403)
            srv.reset_pairing()
            return self._json({"ok": True})
        if not self._secure():
            return self._json({"error": "https_required"}, 403)
        if path == "/unpair":
            srv.pairing.revoke(self._token())
            for client in srv.clients():
                if not srv.pairing.valid(getattr(client, "token", None)):
                    client.close()
            return self._json({"ok": True}, extra={"Set-Cookie": COOKIE_NAME + "=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"})
        if path != "/pair":
            return self._json({"error": "not_found"}, 404)
        if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
            return self._json({"error": "json_required"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, OSError):
            return self._json({"error": "invalid_request"}, 400)
        token, error = srv.pairing.pair(data.get("code"), self.client_address[0])
        if error:
            return self._json({"error": error}, 429 if error == "too_many_attempts" else 400)
        cookie = "%s=%s; Path=/; Max-Age=%d; HttpOnly; Secure; SameSite=Strict" % (COOKIE_NAME, token, SESSION_SECONDS)
        return self._json({"ok": True}, extra={"Set-Cookie": cookie})

    def _send_file(self, full, ctype, extra=None):
        if not full or not os.path.isfile(full):
            return self._json({"error": "not_found"}, 404)
        with open(full, "rb") as f:
            data = f.read()
        return self._send_bytes(data, ctype, extra=extra)

    def _send_bytes(self, data, ctype, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self' wss://%s; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" % (self.headers.get("Host", "") if self._host_ok() else "localhost"))
        self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def _websocket(self, token):
        if not self._same_origin():
            return self._json({"error": "invalid_origin"}, 403)
        key = self.headers.get("Sec-WebSocket-Key", "")
        try:
            valid_key = len(base64.b64decode(key, validate=True)) == 16
        except Exception:
            valid_key = False
        if (self.headers.get("Upgrade", "").lower() != "websocket" or not valid_key or
                self.headers.get("Sec-WebSocket-Version") != "13"):
            return self._json({"error": "invalid_websocket"}, 400)
        srv = self.server.tc
        with srv._handshake_lock:
            active = srv.clients()
            if any(c.token != token for c in active):
                return self._json({"error": "controller_busy"}, 409)
            for c in active:
                c.close()  # Same browser reconnects; the old socket loses control.
            accept = base64.b64encode(hashlib.sha1(key.encode() + WS_MAGIC).digest()).decode()
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.wfile.flush()
            client = WSClient(self.connection, self.client_address)
            client.token = token
            srv.add_client(client)
        count, window = 0, time.monotonic()
        try:
            while client.alive and srv.running and srv.pairing.valid(token):
                opcode, payload = client.read_frame()
                if opcode is None or not srv.pairing.valid(token):
                    break
                client.last_rx = time.time()
                if opcode == 1:
                    now = time.monotonic()
                    if now - window >= 1:
                        count, window = 0, now
                    count += 1
                    if count > 180:
                        break
                    try:
                        obj = validate_control(json.loads(payload.decode("utf-8")))
                    except (ValueError, UnicodeError):
                        break
                    if obj is None:
                        break
                    if srv.on_message:
                        srv.on_message(client, obj)
                elif opcode == 8:
                    break
                elif opcode == 9:
                    client.pong(payload)
        except (OSError, ValueError):
            pass
        finally:
            client.close()
            srv.remove_client(client)
        self.close_connection = True


class _ThreadingHTTPS(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # TLS cancellation and incomplete requests are normal on mobile networks.
        pass


# ---------------------------------------------------------------------------
# 伺服器本體
# ---------------------------------------------------------------------------
class TCServer:
    def __init__(self, web_dir, cert_path, key_path, ca_path, https_port=8443, http_port=8080, bind_host="0.0.0.0", advertised_ip=None):
        self.bind_host = bind_host
        self.advertised_ip = advertised_ip
        self.web_dir = web_dir
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_path = ca_path
        self.https_port = https_port
        self.http_port = http_port
        self.on_message = None  # callable(client, dict)
        self.shots_provider = None  # callable() -> dict
        self.running = False
        self._https = None
        self._http = None
        self._threads = []
        self._clients = set()
        self._clients_lock = threading.Lock()
        self._handshake_lock = threading.Lock()
        self.pairing = Pairing()
        self.on_disconnect = None
        self.lan_ip = self.advertised_ip or detect_lan_ip()
        self.error = ""

    # ---- 生命週期 ------------------------------------------------------------
    def start(self):
        if self.running:
            return True
        self.error = ""
        self.lan_ip = self.advertised_ip or detect_lan_ip()
        self.pairing.rotate()
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(self.cert_path, self.key_path)
            self._https = _ThreadingHTTPS((self.bind_host, self.https_port), _Handler)
            self.https_port = self._https.server_address[1]
            self._https.tc = self
            self._https.socket = ctx.wrap_socket(self._https.socket, server_side=True, do_handshake_on_connect=False)
            self._http = _ThreadingHTTPS((self.bind_host, self.http_port), _Handler)
            self.http_port = self._http.server_address[1]
            self._http.tc = self
        except Exception as e:  # 埠被占、憑證壞
            self.error = str(e)
            for listener in (self._https, self._http):
                if listener is not None:
                    listener.server_close()
            self._https = self._http = None
            return False
        self.running = True
        for srv in (self._https, self._http):
            t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
            t.start()
            self._threads.append(t)
        return True

    def stop(self):
        self.running = False
        self.pairing.rotate()
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for c in clients:
            c.close()
        for srv in (self._https, self._http):
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except Exception:
                    pass
        self._https = self._http = None
        self._threads = []

    # ---- 用戶端 -------------------------------------------------------------
    def add_client(self, c):
        with self._clients_lock:
            self._clients.add(c)

    def remove_client(self, c):
        with self._clients_lock:
            self._clients.discard(c)
            empty = not any(client.alive for client in self._clients)
        if empty and self.on_disconnect:
            self.on_disconnect()

    def clients(self):
        with self._clients_lock:
            return [c for c in self._clients if c.alive]

    def phone_count(self):
        return len([c for c in self.clients() if c.role == "phone"])

    def broadcast_text(self, obj):
        for c in self.clients():
            c.send_text(obj)

    def broadcast_video(self, jpeg_bytes):
        for c in self.clients():
            if c.role == "phone":
                c.send_video(jpeg_bytes)

    def reset_pairing(self):
        self.pairing.rotate()
        for client in self.clients():
            client.close()
        if self.on_disconnect:
            self.on_disconnect()

    def ca_fingerprint(self):
        try:
            with open(self.ca_path, encoding="ascii") as handle:
                der = ssl.PEM_cert_to_DER_cert(handle.read())
            return hashlib.sha256(der).hexdigest().upper()
        except (OSError, ValueError):
            return ""

    # ---- 資訊 ---------------------------------------------------------------
    def url(self):
        return "https://%s:%d/" % (self.lan_ip, self.https_port)

    def help_url(self):
        return "http://%s:%d/help" % (self.lan_ip, self.http_port)

    def info(self):
        return {
            "running": self.running,
            "lan_ip": self.lan_ip,
            "url": self.url(),
            "help_url": self.help_url(),
            "phones": self.phone_count(),
            "error": self.error,
            "fingerprint": self.ca_fingerprint(),
        }


def detect_lan_ip():
    """不真的連出去，只借作業系統的路由表決定哪張網卡對外。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()
