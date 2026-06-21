"""Real HTTP transport for the live path — pure stdlib (urllib).

Matches the injectable transport contract used everywhere else:
    transport(method, path, body, headers) -> (status:int, payload:dict)

A timeout / connection error returns status 0 so the error taxonomy treats it as
INDETERMINATE (reconcile before any retry), never as a clean failure. This is the
ONLY module that touches the network; it is swapped out for the in-process
MockBitsoAPI during all local testing, so no test ever hits Bitso.

force_ipv4 (default True): the Bitso API key is IP-allowlisted to the VPS's IPv4
address (152.53.167.28). But api.bitso.com publishes IPv6 too, and a dual-stack
host PREFERS IPv6 by default — Bitso would then see the VPS's IPv6 source, not the
allowlisted IPv4, and reject every call with 0213. Forcing IPv4 pins the source
to the allowlisted address.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable

DEFAULT_BASE = "https://api.bitso.com"


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that resolves and connects over IPv4 only."""

    def connect(self) -> None:
        infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        af, socktype, proto, _canon, sa = infos[0]
        sock = socket.socket(af, socktype, proto)
        if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # type: ignore[attr-defined]
            sock.settimeout(self.timeout)
        if self.source_address:
            sock.bind(self.source_address)
        sock.connect(sa)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req)


# Bitso sits behind Cloudflare, which 403s the default "Python-urllib/x.y"
# User-Agent. A descriptive UA passes. (Verified on the VPS: urllib UA -> 403,
# custom UA -> 200.)
DEFAULT_UA = "treasuryforge/0.1"


def make_http_transport(base_url: str = DEFAULT_BASE, timeout: float = 15.0,
                        force_ipv4: bool = True, user_agent: str = DEFAULT_UA) -> Callable:
    if force_ipv4:
        opener = urllib.request.build_opener(_IPv4HTTPSHandler(context=ssl.create_default_context()))
    else:
        opener = urllib.request.build_opener()

    def transport(method: str, path: str, body: str, headers: dict) -> tuple[int, dict]:
        url = base_url + path
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method.upper())
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", user_agent)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as e:          # 4xx/5xx incl. 420 rate-limit
            raw = e.read().decode("utf-8", "replace")
            status = e.code
        except (urllib.error.URLError, TimeoutError, OSError):
            return 0, {}                              # INDETERMINATE — outcome unknown
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        return status, payload

    return transport
