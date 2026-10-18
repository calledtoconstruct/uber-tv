#!/usr/bin/python3
"""Logos and program listings are fetched only after every address is checked
(lib/mediafetch.py, bin/om-pg-epg, bin/om-pg-streamer):
/usr/bin/python3 tests/mediafetch.test.py

A private or special address is refused before anything is connected, a
redirect included. A public address is fetched, and so is one on the user's
own network, except YouTube's logos and media playlists, which stay on public
addresses. A login is sent only back to the same scheme, host and port. A
redirect that brings its own login uses that one, and the original is never
put in an error. Unpacked listings stop at 512 MB, and an xz dictionary
bigger than that is refused.
"""

import base64
import gzip
import http.server
import importlib.machinery
import importlib.util
import lzma
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, rel):
    path = os.path.join(ROOT, rel)
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


media = load("mediafetch", "lib/mediafetch.py")
epg = load("om_pg_epg", "bin/om-pg-epg")
streamer = load("om_pg_streamer", "bin/om-pg-streamer")

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


def raises(url, **kw):
    try:
        media.approve(url, **kw)
    except media.FetchError as e:
        return str(e)
    return ""


PUBLIC = "93.184.216.34"


def resolver_for(table):
    def resolver(host, port):
        if host not in table:
            raise AssertionError("looked up " + host)
        return list(table[host])
    return resolver


def response(status, headers, chunks):
    pending = list(chunks)

    def read(n):
        if not pending:
            return b""
        return pending.pop(0)

    return status, headers, read, lambda: None


# ---- addresses --------------------------------------------------------------

refused = ["127.0.0.1", "::1", "0.0.0.0", "169.254.169.254", "169.254.1.1", "100.64.0.1",
           "192.0.2.1", "192.0.0.1", "192.88.99.1", "198.18.0.1", "198.51.100.1", "203.0.113.1",
           "224.0.0.1", "240.0.0.1", "255.255.255.255", "fe80::1", "::ffff:127.0.0.1",
           "2002:7f00:1::", "2001:db8::1"]
for addr in refused:
    check("refused " + addr, not media.address_ok(addr, False) and not media.address_ok(addr, True))

for addr in ("10.0.0.1", "172.16.5.1", "192.168.1.1", "fc00::1", "fd12:3456::1"):
    check("own network " + addr, media.address_ok(addr, False) and not media.address_ok(addr, True))

for addr in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
    check("public " + addr, media.address_ok(addr, False) and media.address_ok(addr, True))

check("a mapped address spelled as the host is refused",
      "hides an IPv4" in raises("http://[::ffff:127.0.0.1]/x"))
check("an address written an unusual way is refused",
      "unusual" in raises("http://0x7f000001/x"))
check("a link-local name is refused before it is fetched",
      "wasn't reached" in raises("http://metadata.example/", resolver=resolver_for({"metadata.example": ["169.254.169.254"]})))
check("one private address beside a public one refuses the name",
      "wasn't reached" in raises("http://cdn.example/a", resolver=resolver_for({"cdn.example": [PUBLIC, "127.0.0.1"]})))
check("a home server is allowed",
      media.approve("http://10.0.0.1/x")["addr"] == "10.0.0.1")
check("a path with two slashes is sent as written",
      media.approve("http://cdn.example//epg.xml?x=1", resolver=resolver_for({"cdn.example": [PUBLIC]}))["target"]
      == "//epg.xml?x=1")
check("YouTube is not fetched from a home-network address",
      "wasn't reached" in raises("https://yt3.googleusercontent.com/a", public_only=True, https_only=True,
                                 resolver=resolver_for({"yt3.googleusercontent.com": ["10.0.0.1"]})))
check("a logo stays on YouTube's image servers",
      "isn't one of the servers" in raises("https://evil.example/a.jpg", hosts=streamer.LOGO_HOSTS, https_only=True,
                                           resolver=resolver_for({"evil.example": [PUBLIC]})))
check("http is refused where https is required", "isn't https" in raises("http://yt3.ggpht.com/a", https_only=True,
      hosts=streamer.LOGO_HOSTS, resolver=resolver_for({"yt3.ggpht.com": [PUBLIC]})))


# ---- redirects, and a login -------------------------------------------------

dialed = []


def scripted(steps):
    """steps: url -> (status, headers, body chunks). Records every address."""
    dialed.clear()

    def dialer(hop, auth, deadline, connect_timeout=None):
        dialed.append((hop["addr"], auth, hop["url"]))
        status, headers, chunks = steps[hop["url"]]
        return response(status, headers, chunks)

    return dialer


written = bytearray()


def take(chunk):
    written.extend(chunk)


written.clear()
kind = media.retrieve(
    "http://user:s3cret@cdn.example/a", take, 100, 5,
    resolver=resolver_for({"cdn.example": [PUBLIC], "other.example": [PUBLIC]}),
    dialer=scripted({
        "http://user:s3cret@cdn.example/a": (302, {"Location": "/b"}, [b"ignore-me"]),
        "http://user:s3cret@cdn.example/b": (302, {"Location": "http://other.example/c"}, []),
        "http://other.example/c": (200, {"Content-Type": "image/png", "Content-Length": "2"}, [b"ok"]),
    }))
check("a redirect on the same origin keeps the login, and another host does not",
      kind == "image/png" and bytes(written) == b"ok"
      and len(dialed) == 3 and dialed[0][0] == PUBLIC and dialed[1][1] == dialed[0][1]
      and dialed[0][1] and dialed[2][1] is None and dialed[2][0] == PUBLIC)
check("the redirect's own body is not the file", b"ignore-me" not in written)

def basic(user, password):
    return "Basic " + base64.b64encode((user + ":" + password).encode()).decode("ascii")


written.clear()
kind = media.retrieve(
    "http://user:s3cret@cdn.example/a", take, 100, 5,
    resolver=resolver_for({"cdn.example": [PUBLIC]}),
    dialer=scripted({
        "http://user:s3cret@cdn.example/a": (302, {"Location": "http://cdn.example/b"}, []),
        "http://cdn.example/b": (200, {"Content-Type": "text/plain", "Content-Length": "1"}, [b"k"]),
    }))
check("a redirect to the same origin keeps the login when the new link omits it",
      kind == "text/plain" and bytes(written) == b"k" and len(dialed) == 2
      and dialed[1][1] == basic("user", "s3cret") and "s3cret" not in dialed[1][2])

written.clear()
kind = media.retrieve(
    "http://user:s3cret@cdn.example/a", take, 100, 5,
    resolver=resolver_for({"cdn.example": [PUBLIC], "cdn2.example": [PUBLIC]}),
    dialer=scripted({
        "http://user:s3cret@cdn.example/a": (302, {"Location": "http://other:tok@cdn2.example/x"}, []),
        "http://other:tok@cdn2.example/x": (200, {"Content-Type": "text/plain", "Content-Length": "1"}, [b"q"]),
    }))
check("a redirect that brings its own login is sent that login, not the original",
      kind == "text/plain" and bytes(written) == b"q" and len(dialed) == 2
      and dialed[0][1] == basic("user", "s3cret") and dialed[1][1] == basic("other", "tok")
      and "s3cret" not in dialed[1][1] and "s3cret" not in dialed[1][2])

written.clear()
kind = media.retrieve(
    "http://user:s3cret@cdn.example/a", take, 100, 5,
    resolver=resolver_for({"cdn.example": [PUBLIC]}),
    dialer=scripted({
        "http://user:s3cret@cdn.example/a": (302, {"Location": "https://cdn.example/b"}, []),
        "https://cdn.example/b": (200, {"Content-Type": "text/plain", "Content-Length": "1"}, [b"z"]),
    }))
check("a redirect that changes the scheme is not sent the login",
      kind == "text/plain" and bytes(written) == b"z" and len(dialed) == 2 and dialed[1][1] is None
      and "s3cret" not in dialed[1][2])

written.clear()
try:
    media.retrieve(
        "https://user:s3cret@cdn.example/a", take, 100, 5,
        resolver=resolver_for({"cdn.example": [PUBLIC], "127.0.0.1": ["127.0.0.1"]}),
        dialer=scripted({
            "https://user:s3cret@cdn.example/a": (302, {"Location": "http://127.0.0.1/latest/meta-data"}, []),
        }))
    leaked = "no error"
except media.FetchError as e:
    leaked = str(e)
check("a redirect to this computer is not opened, and the login is not in the error",
      "wasn't reached" in leaked and "s3cret" not in leaked and [row[0] for row in dialed] == [PUBLIC])

dialed.clear()
try:
    media.retrieve("http://cdn.example/a", take, 100, 5,
                   resolver=resolver_for({"cdn.example": [PUBLIC, "127.0.0.1"]}),
                   dialer=lambda *a: dialed.append("dialed"))
    mixed = ""
except media.FetchError as e:
    mixed = str(e)
check("a name with a private address is never dialed", "wasn't reached" in mixed and dialed == [])

dialed.clear()
try:
    media.retrieve("https://yt3.googleusercontent.com/a.jpg", take, 100, 5, hosts=streamer.LOGO_HOSTS,
                   public_only=True, https_only=True,
                   resolver=resolver_for({"yt3.googleusercontent.com": [PUBLIC], "evil.example": [PUBLIC]}),
                   dialer=scripted({"https://yt3.googleusercontent.com/a.jpg": (302, {"Location": "https://evil.example/a.jpg"}, [])}))
    off = ""
except media.FetchError as e:
    off = str(e)
check("a YouTube logo can't be redirected off YouTube's image servers",
      "isn't one of the servers" in off and [row[0] for row in dialed] == [PUBLIC])

dialed.clear()
try:
    media.retrieve("http://cdn.example/a", take, 100, 5,
                   resolver=resolver_for({"cdn.example": [PUBLIC], "169.254.169.254": ["169.254.169.254"]}),
                   dialer=scripted({"http://cdn.example/a": (302, {"Location": "http://169.254.169.254/"}, [])}))
    meta = ""
except media.FetchError as e:
    meta = str(e)
check("a redirect to a metadata address is not opened",
      "wasn't reached" in meta and [row[0] for row in dialed] == [PUBLIC])

circle = ""
try:
    media.retrieve("http://cdn.example/a", take, 100, 5, resolver=resolver_for({"cdn.example": [PUBLIC]}),
                   dialer=scripted({
                       "http://cdn.example/a": (302, {"Location": "http://cdn.example/b"}, []),
                       "http://cdn.example/b": (302, {"Location": "http://cdn.example/a"}, []),
                   }))
except media.FetchError as e:
    circle = str(e)
check("a redirect in a circle stops", "circle" in circle)

too_many = {("http://cdn.example/" + str(i)): (302, {"Location": "http://cdn.example/" + str(i + 1)}, [])
            for i in range(media.MAX_REDIRECTS + 2)}
try:
    media.retrieve("http://cdn.example/0", take, 100, 5, resolver=resolver_for({"cdn.example": [PUBLIC]}),
                   dialer=scripted(too_many))
    many = ""
except media.FetchError as e:
    many = str(e)
check("redirects stop at five", "too many" in many and len(dialed) == media.MAX_REDIRECTS + 1)

written.clear()
try:
    media.retrieve("http://cdn.example/a", take, 6, 5, resolver=resolver_for({"cdn.example": [PUBLIC]}),
                   dialer=scripted({"http://cdn.example/a": (200, {"Content-Type": "image/png"}, [b"abcd", b"efgh"])}))
    over = ""
except media.FetchError as e:
    over = str(e)
check("the body stops at the limit, and the extra is not kept", "bigger than 6 bytes" in over and bytes(written) == b"abcd")

try:
    media.retrieve("http://cdn.example/a", take, 6, 5, resolver=resolver_for({"cdn.example": [PUBLIC]}),
                   dialer=scripted({"http://cdn.example/a": (200, {"Content-Length": "100"}, [b"nope"])}))
    declared = ""
except media.FetchError as e:
    declared = str(e)
check("a declared length over the limit is refused before the body", "bigger than 6 bytes" in declared)

order = []


def flaky(hop, auth, deadline, connect_timeout=None):
    order.append(hop["addr"])
    if hop["addr"] == "2606:4700:4700::1111":
        raise media.FetchError("couldn't get the link (network is unreachable)")
    return response(200, {"Content-Type": "text/plain", "Content-Length": "2"}, [b"hi"])


written.clear()
kind = media.retrieve("http://cdn.example/a", take, 100, 5,
                      resolver=resolver_for({"cdn.example": ["2606:4700:4700::1111", PUBLIC]}), dialer=flaky)
check("an unreachable address is skipped for the next one that was allowed",
      kind == "text/plain" and bytes(written) == b"hi" and order == ["2606:4700:4700::1111", PUBLIC])

attempts = []


def blackhole(hop, auth, deadline, connect_timeout):
    attempts.append((hop["addr"], connect_timeout))
    if hop["addr"] == "2606:4700:4700::1111":
        time.sleep(connect_timeout)
        raise media.FetchError("couldn't get the link (timed out)")
    if connect_timeout < 1:
        raise media.FetchError("couldn't get the link (timed out)")
    return response(200, {"Content-Type": "text/plain", "Content-Length": "2"}, [b"hi"])


written.clear()
started = time.monotonic()
kind = media.retrieve("http://cdn.example/a", take, 100, 5,
                      resolver=resolver_for({"cdn.example": ["2606:4700:4700::1111", PUBLIC]}),
                      dialer=blackhole)
elapsed = time.monotonic() - started
check("a slow first address leaves time for the next one",
      kind == "text/plain" and bytes(written) == b"hi" and len(attempts) == 2
      and attempts[0][1] <= media.CONNECT_BUDGET + 0.05 and attempts[1][1] > 1 and elapsed < 4.5,
      str(attempts) + " elapsed %.2f" % elapsed)


# ---- the connection itself: the approved address, and a closed socket ------

def fd_count():
    return len(os.listdir("/proc/self/fd"))


def hop_for(port, scheme):
    return {"scheme": scheme, "host": "cdn.example", "port": port, "addr": "127.0.0.1",
            "target": "/logo.png", "addrs": ["127.0.0.1"]}


class OnePage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"pic"
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", "3")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


page = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OnePage)
page_port = page.server_address[1]
threading.Thread(target=page.serve_forever, daemon=True).start()
try:
    before = fd_count()
    status, headers, read, close = media.dial(hop_for(page_port, "http"), None, time.monotonic() + 5)
    body = read(100)
    close()
    check("a fetch connects to the approved address, not the name",
          status == 200 and body == b"pic" and headers.get("Content-Type") == "image/png"
          and fd_count() <= before + 2)
finally:
    page.shutdown()
    page.server_close()


def listen(handler):
    """handler(conn) speaks to one accepted client. Returns (port, stop)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(40)
    stop = threading.Event()

    def run():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            try:
                conn.settimeout(2)
                handler(conn)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1], stop


def fails_closed(name, port, scheme, auth=None):
    base = fd_count()
    text = ""
    for _ in range(20):
        try:
            status, headers, read, close = media.dial(hop_for(port, scheme), auth, time.monotonic() + 5)
            close()
            text = "connected"
            break
        except media.FetchError as e:
            text = str(e)
        except Exception as e:
            text = type(e).__name__ + ": " + str(e)
            break
    extra = fd_count() - base
    for _ in range(40):
        extra = fd_count() - base
        if extra <= 2:
            break
        time.sleep(0.02)
    hidden = auth is None or auth not in text
    check(name, text.startswith("couldn't get the link") and extra <= 2 and hidden,
          text[:180] + " fds+" + str(extra))


def garbage(conn):
    conn.recv(1024)
    conn.sendall(b"NOTHTTP\r\n")


bad_port, bad_stop = listen(garbage)
try:
    fails_closed("a reply that is not HTTP is an error, and the socket is closed",
                 bad_port, "http", auth=basic("user", "s3cret"))
finally:
    bad_stop.set()

cert_dir = tempfile.mkdtemp(prefix="om-pg-dial-")
cert = os.path.join(cert_dir, "cert.pem")
key = os.path.join(cert_dir, "key.pem")
made = subprocess.run(
    ["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key, "-out", cert,
     "-days", "1", "-nodes", "-subj", "/CN=cdn.example"],
    check=False, timeout=30, capture_output=True)
check("a throwaway certificate for the TLS test", made.returncode == 0,
      (made.stderr or b"").decode("utf-8", "replace")[:200])
if made.returncode == 0:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)

    def tls_peer(conn):
        try:
            wrapped = ctx.wrap_socket(conn, server_side=True)
        except OSError:
            return
        try:
            wrapped.recv(1024)
        except OSError:
            pass
        finally:
            wrapped.close()

    tls_port, tls_stop = listen(tls_peer)
    try:
        fails_closed("a certificate this program doesn't trust is refused, and the socket is closed",
                     tls_port, "https", auth=basic("user", "s3cret"))
    finally:
        tls_stop.set()


# ---- the guide's own fetch --------------------------------------------------

folder = tempfile.mkdtemp(prefix="om-pg-mediafetch-")
local = os.path.join(folder, "local.xml")
with open(local, "w") as f:
    f.write("<tv></tv>")
got, temporary = epg.fetch(local, folder)
check("a listings file on disk is read as it is", got == local and temporary is False)

before = set(os.listdir(folder))
for bad in ("http://127.0.0.1/listings.xml", "http://169.254.169.254/latest/meta-data",
            "http://[::ffff:127.0.0.1]/listings.xml", "http://0x7f000001/listings.xml"):
    try:
        epg.fetch(bad, folder)
        text = ""
    except OSError as e:
        text = str(e)
    check("listings are not fetched from " + bad,
          bool(text) and ("wasn't reached" in text or "hides an IPv4" in text or "unusual" in text), text)
check("a refused listings link leaves no file", set(os.listdir(folder)) == before)

# Prove the home network is still fetched: the address check runs for real,
# and only the socket is stood in, so nothing is connected.
dialed_epg = []
real_dial = epg.media.dial


def fake_dial(hop, auth, deadline, user_agent=None, connect_timeout=None):
    dialed_epg.append(hop["addr"])

    def read(n):
        return b""

    return 200, {"Content-Type": "text/xml"}, read, lambda: None


epg.media.dial = fake_dial
try:
    path, temporary = epg.fetch("http://10.0.0.1/listings.xml", folder)
    check("a listings link on the user's own network is fetched", dialed_epg == ["10.0.0.1"] and temporary and os.path.isfile(path))
    os.unlink(path)
finally:
    epg.media.dial = real_dial

check("unpacked listings default to 512 MB", epg.MAX_UNPACKED == 512 * 1024 * 1024)


def gzip_of(payload):
    raw = os.path.join(folder, "sample.xml.gz")
    with gzip.open(raw, "wb") as out:
        out.write(payload)
    return raw


epg.MAX_UNPACKED = 64
try:
    with epg.opened(gzip_of(b"y" * 64)) as reader:
        exact = reader.read()
    check("exactly 512 MB unpacked would be kept (the cap, tried small)", exact == b"y" * 64)
    try:
        with epg.opened(gzip_of(b"x" * 200)) as reader:
            while reader.read(32):
                pass
        bomb = ""
    except OSError as e:
        bomb = str(e)
    check("one byte past the unpacked cap stops the read", "unpacked" in bomb)
finally:
    epg.MAX_UNPACKED = 512 * 1024 * 1024


def xz_of(payload, dict_size):
    raw = os.path.join(folder, "sample-%d.xml.xz" % dict_size)
    with open(raw, "wb") as out:
        out.write(lzma.compress(payload, format=lzma.FORMAT_XZ,
                                filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}]))
    return raw


epg.MAX_UNPACKED = 1024 * 1024
try:
    with epg.opened(xz_of(b"<tv></tv>", 4096)) as reader:
        plain = reader.read()
    check("a small xz listing is read", plain == b"<tv></tv>")
    try:
        with epg.opened(xz_of(b"<tv></tv>", 8 * 1024 * 1024)) as reader:
            reader.read(64)
        huge = ""
    except lzma.LZMAError as e:
        huge = str(e)
    check("an xz dictionary bigger than the unpacked cap is refused", "limit" in huge.lower(), huge)
finally:
    epg.MAX_UNPACKED = 512 * 1024 * 1024


# ---- logos and a media playlist, through the streamer ----------------------

logos = tempfile.mkdtemp(prefix="om-pg-logos-")
streamer.LOGOS = __import__("pathlib").Path(logos)
streamer.last_logo[0] = 0
try:
    streamer.logo("test-private-address", "http://127.0.0.1/x.png", any_host=True)
    logo_err = ""
except OSError as e:
    logo_err = str(e)
check("an IPTV logo aimed at this computer is not fetched", "wasn't reached" in logo_err and os.listdir(logos) == [])

streamer.last_logo[0] = 0
try:
    streamer.logo("UCaaaaaaaaaaaaaaaaaaaaaa", "https://evil.example/a.jpg")
    host_err = ""
except LookupError as e:
    host_err = str(e)
check("a YouTube logo from anywhere else is refused", host_err == "not a YouTube image")


class FakeYDL:
    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        return {"formats": [{"protocol": "m3u8_native", "manifest_url": "https://10.0.0.1/pl.m3u8"}]}


streamer.yt_dlp.YoutubeDL = FakeYDL
streamer.cache.clear()
try:
    streamer.playlist("abcdefghijk")
    play_err = ""
except OSError as e:
    play_err = str(e)
check("a YouTube media playlist on a home-network address is not fetched",
      "wasn't reached" in play_err and "abcdefghijk" not in streamer.cache)

print("\n" + ("mediafetch: all good" if not failures else str(failures) + " failed"))
sys.exit(1 if failures else 0)
