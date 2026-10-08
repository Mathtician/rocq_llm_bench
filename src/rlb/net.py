"""Network-level timing, transparent to the harness.

The harness runs inside its own network namespace, created by `pasta`
(package `passt`), whose user-space gateway writes every packet it forwards
to a pcap file. The harness sees an ordinary network: no proxy variables, no
injected CA, nothing to honor. So this works for any future harness.

Traffic stays TLS-encrypted; we recover what we need from the parts that are
in the clear:

  * the host, from the Server Name Indication in each TLS ClientHello;
  * request/response timing, from the direction and size of TLS application
    data records. A request is an outbound burst; its response is the inbound
    data that follows, until the next outbound burst on that connection.

That is enough for an agent loop, which issues one API request at a time:
each request's interval [sent, last response byte] is the model time we
want, and the first response byte gives time-to-first-token.

Known imprecision: TLS 1.3 servers send session tickets right after the
handshake, which can land just after the first request on a fresh connection
and be taken for its first response byte. The interval end is unaffected.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, asdict, field
from pathlib import Path

PCAP_MAGIC_US = 0xA1B2C3D4  # microsecond timestamps, host byte order as written by pasta
PCAP_MAGIC_NS = 0xA1B23C4D
LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = 101

TLS_HANDSHAKE = 0x16
TLS_APPDATA = 0x17
REQUEST_MIN_BYTES = 200  # outbound app-data segments this large start a request; smaller ones are ACK-level chatter (WINDOW_UPDATE, PING, TLS Finished)
RESPONSE_MIN_BYTES = 60  # inbound app-data segments this large are response data; smaller are HTTP/2 PING / WINDOW_UPDATE


@dataclass(frozen=True)
class ApiCall:
    host: str
    port: int  # client-side port, identifies the connection
    start: float  # request sent (epoch seconds)
    first: float | None  # first response byte; None if the harness was killed before any arrived
    end: float  # last response byte (== start if none)
    req_bytes: int
    resp_bytes: int

    @property
    def seconds(self) -> float:
        return self.end - self.start


@dataclass
class NetStats:
    calls: int = 0
    api_calls: int = 0
    api_busy_s: float = 0.0  # union of API-call intervals
    api_ttfb_sum_s: float = 0.0  # sum over API calls of (first byte - request sent)
    by_host: dict[str, dict] = field(default_factory=dict)  # host -> {calls, busy_s}
    source: str = "pcap"  # "proxy": intervals from the TLS-terminating proxy (exact); "pcap": TLS record heuristics
    pcap_busy_s: float | None = None  # the capture's figure, for cross-checking the proxy's
    tokens_in: int = 0  # from the proxy's usage records, provider fields normalized (proxy_policy.normalize_usage)
    tokens_out: int = 0
    tokens_cached: int = 0
    blocked: list[str] = field(default_factory=list)  # requests the proxy refused (endpoint off the allowlist)

    @staticmethod
    def from_calls(calls: list[ApiCall], api_hosts: tuple[str, ...]) -> NetStats:
        from .shim import union_seconds
        api = [c for c in calls if is_api_host(c.host, api_hosts)]
        st = NetStats(calls=len(calls), api_calls=len(api), by_host={})
        st.api_busy_s = union_seconds([(c.start, c.end) for c in api])
        st.api_ttfb_sum_s = sum(c.first - c.start for c in api if c.first is not None)
        for h in sorted({c.host for c in calls}):
            mine = [c for c in calls if c.host == h]
            st.by_host[h] = {"calls": len(mine), "busy_s": union_seconds([(c.start, c.end) for c in mine])}
        return st


def is_api_host(host: str, api_hosts: tuple[str, ...]) -> bool:
    """Exact match: `ab.chatgpt.com` (A/B telemetry) is not `chatgpt.com`."""
    return host in api_hosts


# --- pcap parsing -----------------------------------------------------------


def _client_hello_sni(p: bytes) -> str | None:
    """Server name from a TLS ClientHello record, if `p` starts with one."""
    if len(p) < 44 or p[0] != TLS_HANDSHAKE or p[5] != 1:
        return None
    try:
        i = 43
        i += 1 + p[i]  # session id
        i += 2 + struct.unpack_from(">H", p, i)[0]  # cipher suites
        i += 1 + p[i]  # compression methods
        end = i + 2 + struct.unpack_from(">H", p, i)[0]
        i += 2
        while i + 4 <= end:
            et, el = struct.unpack_from(">HH", p, i)
            i += 4
            if et == 0:  # server_name: list length(2) type(1) name length(2) name
                n = struct.unpack_from(">H", p, i + 3)[0]
                return p[i + 5 : i + 5 + n].decode("ascii")
            i += el
    except (struct.error, IndexError, UnicodeDecodeError):
        return None
    return None


@dataclass
class _Segment:
    t: float
    outbound: bool  # to server port 443
    port: int  # client-side port
    payload: bytes


def _segments(pcap: Path):
    data = pcap.read_bytes()
    if len(data) < 24:
        return
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == PCAP_MAGIC_US:
        div = 1e6
    elif magic == PCAP_MAGIC_NS:
        div = 1e9
    else:
        raise ValueError(f"{pcap}: not a little-endian pcap (magic {magic:#x})")
    linktype = struct.unpack_from("<I", data, 20)[0]
    off = 24
    while off + 16 <= len(data):
        sec, frac, caplen, _ = struct.unpack_from("<IIII", data, off)
        off += 16
        p = data[off : off + caplen]
        off += caplen
        t = sec + frac / div
        if linktype == LINKTYPE_ETHERNET:
            ethertype = p[12:14]
            p = p[14:]
        elif linktype == LINKTYPE_RAW:
            ethertype = b"\x08\x00" if p[:1] and p[0] >> 4 == 4 else b"\x86\xdd"
        else:
            raise ValueError(f"{pcap}: unsupported link type {linktype}")
        if ethertype == b"\x08\x00":
            if len(p) < 20 or p[9] != 6:
                continue
            hl = (p[0] & 15) * 4
            total = struct.unpack_from(">H", p, 2)[0]
            tcp = p[hl:total]
        elif ethertype == b"\x86\xdd":
            if len(p) < 40 or p[6] != 6:  # no extension-header walking; none appear on a pasta tap
                continue
            plen = struct.unpack_from(">H", p, 4)[0]
            tcp = p[40 : 40 + plen]
        else:
            continue
        if len(tcp) < 20:
            continue
        sport, dport = struct.unpack_from(">HH", tcp, 0)
        doff = (tcp[12] >> 4) * 4
        payload = tcp[doff:]
        if not payload:
            continue
        if dport == 443:
            yield _Segment(t, True, sport, payload)
        elif sport == 443:
            yield _Segment(t, False, dport, payload)


class _RecordStream:
    """TLS record framing for one direction of one connection. Feed TCP
    payload in order; get back, for each record whose header arrives, its
    (content type, length), plus how many bytes of records-in-progress each
    segment carried."""

    def __init__(self):
        self.remaining = 0  # bytes left of the record currently being received

    def feed(self, payload: bytes) -> list[tuple[int, int]]:
        records = []
        i = 0
        while i < len(payload):
            if self.remaining:
                n = min(self.remaining, len(payload) - i)
                self.remaining -= n
                i += n
                continue
            if i + 5 > len(payload):
                break  # header split across segments: rare on a local tap; treat the tail as continuation
            typ = payload[i]
            length = struct.unpack_from(">H", payload, i + 3)[0]
            records.append((typ, length))
            self.remaining = length
            i += 5
        return records


@dataclass
class _Conn:
    host: str | None = None
    out: _RecordStream = field(default_factory=_RecordStream)
    inb: _RecordStream = field(default_factory=_RecordStream)
    start: float | None = None
    first: float | None = None
    end: float | None = None
    req_bytes: int = 0
    resp_bytes: int = 0
    calls: list = field(default_factory=list)

    def close_call(self):
        if self.start is not None:
            self.calls.append(ApiCall(
                host=self.host or "?", port=0, start=self.start, first=self.first,
                end=self.end if self.end is not None else self.start,
                req_bytes=self.req_bytes, resp_bytes=self.resp_bytes,
            ))
        self.start = self.first = self.end = None
        self.req_bytes = self.resp_bytes = 0


def parse_pcap(pcap: Path) -> list[ApiCall]:
    """All TLS request/response intervals in the capture, in start order."""
    conns: dict[int, _Conn] = {}
    for s in _segments(pcap):
        c = conns.get(s.port)
        if c is None:
            c = conns[s.port] = _Conn()
        if s.outbound:
            sni = _client_hello_sni(s.payload)
            if sni:
                c.host = sni
            records = c.out.feed(s.payload)
            big = any(typ == TLS_APPDATA and n >= REQUEST_MIN_BYTES for typ, n in records)
            if big and c.end is not None:
                c.close_call()  # a response has been received: this is a new request
            if c.start is None and big:
                c.start = s.t
            if c.start is not None and c.end is None:
                c.req_bytes += len(s.payload)
        else:
            records = c.inb.feed(s.payload)
            data = any(typ == TLS_APPDATA and n >= RESPONSE_MIN_BYTES for typ, n in records) or (
                not records and len(s.payload) >= RESPONSE_MIN_BYTES  # continuation of a large record
            )
            if c.start is not None and data:
                if c.first is None:
                    c.first = s.t
                c.end = s.t
                c.resp_bytes += len(s.payload)
    calls = []
    for port, c in conns.items():
        c.close_call()
        calls += [ApiCall(**{**asdict(k), "port": port}) for k in c.calls]
    return sorted(calls, key=lambda k: k.start)
