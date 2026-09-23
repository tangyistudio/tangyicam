"""Release security integration tests against a temporary loopback-only server."""
import base64
import http.client
import importlib
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("tangyicam")
package.__path__ = [str(ROOT / "tangyicam")]
sys.modules["tangyicam"] = package
from tangyicam import security, server, setup


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.p = security.Pairing(clock=lambda: self.now)

    def test_code_single_use_session_expiry_and_reset(self):
        code = self.p.code
        token, error = self.p.pair(code, "a")
        self.assertIsNone(error)
        self.assertTrue(self.p.valid(token))
        self.assertNotEqual(self.p.code, code)
        self.assertIsNone(self.p.pair(code, "a")[0])
        self.now += security.SESSION_SECONDS + 1
        self.assertFalse(self.p.valid(token))
        self.p.rotate()
        token, _ = self.p.pair(self.p.code, "a")
        self.p.rotate()
        self.assertFalse(self.p.valid(token))

    def test_attempt_limit_and_expired_code(self):
        bad = "000000" if self.p.code != "000000" else "111111"
        for _ in range(6): self.p.pair(bad,"a")
        self.assertEqual(self.p.pair(self.p.code,"a")[1],"too_many_attempts")
        self.now += 61
        self.assertIsNone(self.p.pair(self.p.code,"a")[1])
        self.now += 601
        self.assertEqual(self.p.pair(self.p.code,"a")[1],"expired_code")

    def test_non_ascii_pairing_code_is_rejected(self):
        self.assertEqual(self.p.pair("一二三四五六", "a")[1], "invalid_code")

    def test_global_limit_is_bounded(self):
        for n in range(30): self.p.pair("BAD",str(n))
        self.assertEqual(self.p.pair(self.p.code,"other")[1],"too_many_attempts")
        self.assertEqual(len(self.p.attempts),30)

    def test_control_input_is_finite_bounded_and_known(self):
        for value in ({"q":[0,0,0,0]},{"mx":float("nan")},{"lens":float("inf")},{"key":{"cmd":"exec"}},{"seq":True},{"q":[1,0,0]},{"exec":"bad"}):
            self.assertIsNone(security.validate_control(value))
        self.assertEqual(security.validate_control({"mx":999})["mx"],4)
        self.assertEqual(security.validate_control({"q":[2,0,0,0]})["q"],[1,0,0,0])


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="tc-security-")
        cls.folder = Path(cls.temp.name)
        previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(cls.folder)
        try: setup.create_certificate(cls.folder / "certs","127.0.0.1")
        finally:
            if previous is None: os.environ.pop("LOCALAPPDATA",None)
            else: os.environ["LOCALAPPDATA"] = previous
        certs = cls.folder / "certs"
        cls.srv = server.TCServer(str(ROOT / "tangyicam" / "web"),str(certs / "server.pem"),
            str(certs / "server-key.pem"),str(certs / "rootCA.pem"),0,0,"127.0.0.1","127.0.0.1")
        cls.messages=[]
        cls.srv.on_message=lambda client,obj: cls.messages.append(obj)
        cls.srv.shots_provider=lambda:{"shots":[{"id":"sample","title":"Private shot"}]}
        assert cls.srv.start(),cls.srv.error
        cls.context=ssl.create_default_context(cafile=str(certs / "rootCA.pem"))
        cls.origin="https://127.0.0.1:%d" % cls.srv.https_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.srv.reset_pairing()
        self.srv.pairing.attempts.clear()
        self.messages.clear()

    def request(self,path,method="GET",data=None,token=None,secure=True,origin=None,headers=None):
        conn=(http.client.HTTPSConnection("127.0.0.1",self.srv.https_port,context=self.context,timeout=5)
              if secure else http.client.HTTPConnection("127.0.0.1",self.srv.http_port,timeout=5))
        hs=dict(headers or {})
        if token: hs["Cookie"]="tc_session="+token
        if method=="POST": hs.update({"Content-Type":"application/json","Origin":origin or (self.origin if secure else "http://127.0.0.1:%d" % self.srv.http_port)})
        conn.request(method,path,None if data is None else json.dumps(data),hs)
        r=conn.getresponse();body=r.read();result=(r.status,dict(r.getheaders()),body)
        conn.close();return result

    def pair(self):
        status,headers,body=self.request("/pair","POST",{"code":self.srv.pairing.code})
        self.assertEqual(status,200,body)
        cookie=headers["Set-Cookie"]
        for flag in ("HttpOnly","Secure","SameSite=Strict"): self.assertIn(flag,cookie)
        return cookie.split(";",1)[0].split("=",1)[1]

    def ws(self,token=None,origin=None):
        sock=self.context.wrap_socket(socket.create_connection(("127.0.0.1",self.srv.https_port),timeout=3),server_hostname="127.0.0.1")
        key=base64.b64encode(os.urandom(16)).decode()
        headers=["GET /ws HTTP/1.1","Host: 127.0.0.1:%d"%self.srv.https_port,"Upgrade: websocket","Connection: Upgrade","Sec-WebSocket-Version: 13","Sec-WebSocket-Key: "+key,"Origin: "+(origin or self.origin)]
        if token: headers.append("Cookie: tc_session="+token)
        sock.sendall(("\r\n".join(headers)+"\r\n\r\n").encode())
        data=b""
        while b"\r\n\r\n" not in data: data+=sock.recv(4096)
        return sock,int(data.split(b" ")[1])

    def test_private_endpoints_require_pairing_and_https(self):
        for path in ("/state","/shots.json","/ws"):
            self.assertEqual(self.request(path)[0],401)
            self.assertEqual(self.request(path,secure=False)[0],403)
        self.assertEqual(self.request("/pair","POST",{"code":self.srv.pairing.code},secure=False)[0],403)
        self.assertEqual(self.request("/bootstrap.json",secure=False)[0],200)
        self.assertEqual(self.request("/ca.pem",secure=False)[0],200)

    def test_origins_hosts_and_file_allowlist(self):
        self.assertEqual(self.request("/pair","POST",{"code":self.srv.pairing.code},origin="https://evil.example")[0],403)
        self.assertEqual(self.request("/local-info",headers={"Host":"evil.example"})[0],403)
        for path in ("/../server-key.pem","/server-key.pem","/private-ca/rootCA-key.pem","/C:/Windows/win.ini"):
            self.assertEqual(self.request(path)[0],404)
        fake=object.__new__(server._Handler);fake.client_address=("192.168.1.77",1000)
        self.assertFalse(fake._local())

    def test_pairing_cookie_and_revocation(self):
        token=self.pair()
        status,_,body=self.request("/state",token=token)
        self.assertEqual(status,200)
        self.assertNotIn("code",json.loads(body))
        self.assertEqual(self.request("/shots.json",token=token)[0],200)
        self.assertEqual(self.request("/unpair","POST",token=token)[0],200)
        self.assertEqual(self.request("/state",token=token)[0],401)

    def test_admin_csrf_and_revoke(self):
        token=self.pair()
        self.assertEqual(self.request("/local/rotate","POST",secure=False)[0],403)
        self.assertEqual(self.request("/local/rotate","POST",secure=False,headers={"X-TangyiCam-Admin":self.srv.pairing.admin_token})[0],200)
        self.assertFalse(self.srv.pairing.valid(token))

    def test_websocket_auth_origin_control_lease_and_message(self):
        sock,status=self.ws();self.assertEqual(status,401);sock.close()
        token=self.pair()
        sock,status=self.ws(token,"https://evil.example");self.assertEqual(status,403);sock.close()
        sock,status=self.ws(token);self.assertEqual(status,101)
        other=self.pair()
        second,status=self.ws(other);self.assertEqual(status,409);second.close()
        payload=json.dumps({"seq":0,"mx":0.5,"rec":True}).encode();mask=os.urandom(4)
        sock.sendall(bytes([0x81,0x80|len(payload)])+mask+bytes(v^mask[i%4] for i,v in enumerate(payload)))
        limit=time.monotonic()+2
        while not self.messages and time.monotonic()<limit: time.sleep(.01)
        self.assertEqual(self.messages[-1]["mx"],0.5)
        replacement,status=self.ws(token);self.assertEqual(status,101)
        replacement.close();sock.close()

    def test_incomplete_tls_handshake_does_not_block_other_clients(self):
        stalled = socket.create_connection(("127.0.0.1", self.srv.https_port), timeout=2)
        try:
            self.assertEqual(self.request("/bootstrap.json")[0], 200)
        finally:
            stalled.close()

    def test_plain_http_cannot_expose_app_or_sessions(self):
        for path in ("/","/app.js","/manifest.webmanifest"):
            self.assertEqual(self.request(path,secure=False)[0],403)
        status,headers,body=self.request("/qr",secure=False)
        self.assertEqual(status,200)
        self.assertNotIn(b"cdnjs",body)
        self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])


if __name__=="__main__": unittest.main(verbosity=2)
