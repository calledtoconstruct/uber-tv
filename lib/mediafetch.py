"""Checked downloads for logos and program listings.

A link the guide fetches on its own (a playlist's logo, a playlist's
listings, a YouTube logo, a YouTube media playlist) is resolved before
anything is connected, and the connection is made to one of those
addresses. A redirect is a new link and is checked again. An address of this computer,
a link-local address (including a cloud machine's own metadata address)
and every other special range is refused. A public address is fetched, and
so is one on the user's own network, because a home media server lives
there. YouTube's own logos can be held to YouTube's image servers and to
public addresses only.

The body is written as it arrives, and never past the caller's limit or
deadline. Nothing here is imported by name from outside the standard
library: appnet.py is loaded by its path so the address rules stay in one
place.
"""

import base64
import http.client
import importlib.util
import ipaddress
import os
import socket
import ssl
import time
import urllib.parse
from importlib.machinery import SourceFileLoader

MAX_REDIRECTS = 5
CONNECT_BUDGET = 3          # seconds a non-final address may spend connecting

LAN_V4 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
ULA = ipaddress.ip_network("fc00::/7")


class FetchError(OSError):
    """The link was refused or the download failed. The text names no login."""


def load_appnet():
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "appnet.py")
    loader = SourceFileLoader("om_pg_appnet_for_media", path)
    spec = importlib.util.spec_from_file_location("om_pg_appnet_for_media", path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


appnet = load_appnet()


def address_ok(addr, public_only):
    """Whether a resolved address may be connected to.

    public_only is for YouTube's image servers: a home-network address there
    is someone answering in their place. Logos and listings also allow the
    user's own network (10/8, 172.16/12, 192.168/16, and IPv6 local
    addresses). Loopback, link-local, multicast, documentation and mapped
    forms are never allowed: a playlist must not be able to call this
    computer, or a cloud machine's metadata address.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and (ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None):
        return False
    if appnet.global_unicast(str(ip)):
        return True
    if public_only:
        return False
    if ip.version == 4:
        return any(ip in n for n in LAN_V4)
    return ip in ULA


def _host_of(url):
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        raise FetchError("the link has characters that aren't allowed")
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as e:
        raise FetchError("the link isn't valid") from e
    raw = parts.hostname
    if not raw:
        raise FetchError("the link has no host")
    if ":" in raw and not (raw.startswith("[") and raw.endswith("]")):
        raw = "[" + raw + "]"
    try:
        host = appnet.canonical_host(raw)
    except appnet.NetError as e:
        raise FetchError(str(e)) from e
    return parts, host


def approve(url, resolver=None, hosts=None, public_only=False, https_only=False):
    """The link, its host and the address to connect to, or FetchError.

    Every address the name resolves to must be allowed. One private address
    beside a public one is refused, and nothing is connected to: that is how
    a name points at this computer only some of the time. resolver, when
    given, is called as resolver(host, port) and returns address strings, so
    a test can answer without looking anything up.
    """
    parts, host = _host_of(url)
    if parts.scheme not in ("http", "https") or (https_only and parts.scheme != "https"):
        raise FetchError("the link isn't a web link" if not https_only else "the link isn't https")
    if hosts is not None and host not in hosts:
        raise FetchError(host + " isn't one of the servers this is fetched from")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as e:
        raise FetchError("the link's port isn't valid") from e
    bare = host[1:-1] if host.startswith("[") else host
    try:
        if resolver:
            found = list(resolver(host, port))
        else:
            found = [item[4][0] for item in socket.getaddrinfo(bare, port, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP)]
    except OSError as e:
        raise FetchError("couldn't find " + host + " (" + (e.strerror or str(e))[:80] + ")") from e
    if not found:
        raise FetchError("couldn't find " + host)
    for addr in found:
        if not address_ok(addr, public_only):
            raise FetchError(host + " points at a private or special address, so it wasn't reached")
    # urlunsplit with an empty netloc turns a path of "//file" into "////file".
    path = parts.path or "/"
    target = path if not parts.query else path + "?" + parts.query
    if " " in target or " " in host:
        raise FetchError("the link has characters that aren't allowed")
    auth = None
    if parts.username is not None:
        user = urllib.parse.unquote(parts.username)
        password = urllib.parse.unquote(parts.password or "")
        auth = "Basic " + base64.b64encode((user + ":" + password).encode()).decode("ascii")
    return {"url": url, "scheme": parts.scheme, "host": host, "port": port, "addr": found[0],
            "addrs": list(found), "target": target, "auth": auth}


def dial(hop, auth, deadline, user_agent=None, connect_timeout=None):
    """Connect to hop's approved address and send one GET. Returns
    (status, headers, read, close). headers has .get; read(n) returns the
    next bytes of the body; close() releases the socket.

    connect_timeout, when set, is how long the TCP connection may take.
    The handshake and the reply still use deadline. The socket is closed
    here on every failure. A TLS handshake that fails has already closed
    the descriptor and detached the original socket, so that case is not
    closed a second time. A bad status line or a header that can't be
    encoded becomes FetchError, the same as a network error.
    """

    def left():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("took too long")
        return remaining

    family = socket.AF_INET6 if ":" in hop["addr"] else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    handed = False
    try:
        connect_for = left() if connect_timeout is None else min(connect_timeout, left())
        if connect_for <= 0:
            raise FetchError("took too long")
        sock.settimeout(connect_for)
        sock.connect((hop["addr"], hop["port"]))
        peer = sock.getpeername()
        if ipaddress.ip_address(peer[0]) != ipaddress.ip_address(hop["addr"]) or peer[1] != hop["port"]:
            raise FetchError("connected somewhere else than " + hop["host"])
        sock.settimeout(left())
        if hop["scheme"] == "https":
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            sni = hop["host"][1:-1] if hop["host"].startswith("[") else hop["host"]
            sock = ctx.wrap_socket(sock, server_hostname=sni)
            sock.settimeout(left())
        conn = (http.client.HTTPSConnection if hop["scheme"] == "https" else http.client.HTTPConnection)(hop["host"], hop["port"], timeout=left())
        conn.sock = sock
        headers = {"User-Agent": user_agent or "om-pg (Omarchy program guide)", "Accept-Encoding": "identity", "Connection": "close"}
        if auth:
            headers["Authorization"] = auth
        conn.request("GET", hop["target"], headers=headers)
        resp = conn.getresponse()

        def read(n):
            left = deadline - time.monotonic()
            if left <= 0:
                raise FetchError("took too long")
            sock.settimeout(min(5, left))
            return resp.read(n)

        def close():
            try:
                resp.close()
            finally:
                conn.close()

        handed = True
        return resp.status, resp.headers, read, close
    except FetchError:
        raise
    except (OSError, http.client.HTTPException, UnicodeError) as e:
        detail = getattr(e, "strerror", None) or str(e)
        raise FetchError("couldn't get the link (" + str(detail)[:120] + ")") from e
    finally:
        if not handed:
            try:
                # fileno() is -1 once a failed handshake has detached this socket.
                if sock.fileno() != -1:
                    sock.close()
            except OSError:
                pass


def retrieve(url, write, limit, seconds, hosts=None, public_only=False, https_only=False, resolver=None, dialer=None, user_agent=None):
    """GET url and pass the body to write(chunk), at most limit bytes, within
    seconds. Returns the Content-Type. A redirect is followed only after the
    new link is approved. A login on the link is sent only back to that same
    scheme, host and port, never to a host, port or scheme a redirect changes,
    and a redirect that brings its own login uses that one instead. dialer,
    when given, is dialer(hop, auth, deadline, connect_timeout) and stands in
    for the connection. An address that has another after it may spend only
    CONNECT_BUDGET seconds connecting, so a dropped packet leaves time for
    the next address. The last address gets the time still left.
    """
    if limit < 1 or seconds <= 0:
        raise FetchError("the download has no limit")
    deadline = time.monotonic() + seconds
    current = url
    home = None
    home_auth = None
    seen = []

    def connect(hop, auth, deadline, connect_timeout):
        if dialer:
            return dialer(hop, auth, deadline, connect_timeout)
        return dial(hop, auth, deadline, user_agent, connect_timeout=connect_timeout)

    for _ in range(MAX_REDIRECTS + 1):
        if time.monotonic() >= deadline:
            raise FetchError("took too long")
        if any(current == earlier for earlier in seen):
            raise FetchError("the link redirected in a circle")
        seen.append(current)
        hop = approve(current, resolver, hosts, public_only, https_only)
        origin = (hop["scheme"], hop["host"], hop["port"])
        if home is None:
            home = origin
            home_auth = hop["auth"]
        # This link's own login wins. Otherwise the original login goes only
        # back to the same scheme, host and port, never across a redirect.
        if hop["auth"] is not None:
            auth = hop["auth"]
        elif origin == home:
            auth = home_auth
        else:
            auth = None
        # Every address was allowed. Try them in order: the first is often an
        # IPv6 address this network can't reach. A non-final attempt only waits
        # CONNECT_BUDGET seconds to connect, so that miss doesn't use the whole
        # deadline, and an exhausted deadline does not start another attempt.
        last = None
        status = headers = read = close = None
        addrs = hop["addrs"]
        for index, addr in enumerate(addrs):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise last if last is not None else FetchError("took too long")
            hop["addr"] = addr
            budget = remaining if index == len(addrs) - 1 else min(CONNECT_BUDGET, remaining)
            try:
                status, headers, read, close = connect(hop, auth, deadline, budget)
                break
            except FetchError as e:
                last = e
        else:
            raise last
        try:
            if status in (301, 302, 303, 307, 308):
                loc = headers.get("Location") if headers else None
                if not loc or len(loc) > 2048:
                    raise FetchError("a redirect went nowhere")
                # the body of a redirect is not the file; don't keep it
                dropped = 0
                while dropped < 65536:
                    chunk = read(65536 - dropped)
                    if not chunk:
                        break
                    dropped += len(chunk)
                current = urllib.parse.urljoin(hop["url"], loc)
                continue
            if not 200 <= status < 300:
                raise FetchError("the server said %d" % status)
            declared = headers.get("Content-Length") if headers else None
            if declared is not None and (not str(declared).isdigit() or int(declared) > limit):
                raise FetchError("bigger than %d bytes" % limit)
            got = 0
            while True:
                if time.monotonic() >= deadline:
                    raise FetchError("took too long")
                chunk = read(min(65536, limit - got + 1))
                if not chunk:
                    break
                got += len(chunk)
                if got > limit:
                    raise FetchError("bigger than %d bytes" % limit)
                write(chunk)
            return (headers.get("Content-Type") if headers else "") or ""
        finally:
            close()
    raise FetchError("the link redirected too many times")
