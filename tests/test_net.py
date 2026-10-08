"""The pcap -> ApiCall parser, on synthetic captures built here."""
import struct
from pathlib import Path

from rlb.net import ApiCall, NetStats, parse_pcap

CLIENT, SERVER = b"\x0a\x00\x00\x02", b"\x0a\x00\x00\x01"


def _tls(typ: int, body: bytes) -> bytes:
    return bytes([typ, 3, 3]) + struct.pack(">H", len(body)) + body


def _client_hello(sni: str) -> bytes:
    name = sni.encode()
    ext = struct.pack(">HH", 0, len(name) + 5) + struct.pack(">HBH", len(name) + 3, 0, len(name)) + name
    body = b"\x03\x03" + b"r" * 32 + b"\x00" + b"\x00\x02\x13\x01" + b"\x01\x00" + struct.pack(">H", len(ext)) + ext
    hs = b"\x01" + struct.pack(">I", len(body))[1:] + body
    return _tls(0x16, hs)


class Cap:
    def __init__(self):
        self.frames = []

    def seg(self, t: float, port: int, outbound: bool, payload: bytes):
        src, dst, sp, dp = (CLIENT, SERVER, port, 443) if outbound else (SERVER, CLIENT, 443, port)
        tcp = struct.pack(">HHIIBBHHH", sp, dp, 0, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
        ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0, src, dst) + tcp
        eth = b"\x00" * 12 + b"\x08\x00" + ip
        self.frames.append((t, eth))

    def write(self, path: Path):
        out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        for t, f in self.frames:
            out += struct.pack("<IIII", int(t), int(round((t % 1) * 1e6)), len(f), len(f)) + f
        path.write_bytes(out)


def _parse(cap: Cap, tmp_path: Path) -> list[ApiCall]:
    p = tmp_path / "x.pcap"
    cap.write(p)
    return parse_pcap(p)


def test_two_requests_on_one_connection_with_handshake_noise(tmp_path):
    c = Cap()
    c.seg(100.0, 5000, True, _client_hello("api.example.com"))
    c.seg(100.1, 5000, False, _tls(0x16, b"s" * 1200))  # ServerHello + certs
    # CCS + Finished + the request, all in one segment (as Node does)
    c.seg(100.2, 5000, True, _tls(0x14, b"\x01") + _tls(0x17, b"f" * 40) + _tls(0x17, b"q" * 5000))
    c.seg(100.3, 5000, False, _tls(0x17, b"t" * 250))  # session ticket: counted as first byte (documented)
    c.seg(101.0, 5000, False, _tls(0x17, b"a" * 100))
    c.seg(101.5, 5000, True, _tls(0x17, b"w" * 20))  # WINDOW_UPDATE-sized chatter: not a request
    c.seg(102.0, 5000, False, _tls(0x17, b"a" * 100))
    c.seg(105.0, 5000, True, _tls(0x17, b"q" * 300))  # second request
    c.seg(106.0, 5000, False, _tls(0x17, b"a" * 100))
    calls = _parse(c, tmp_path)
    assert [(k.host, k.port, round(k.start, 1), round(k.first, 1), round(k.end, 1)) for k in calls] == [
        ("api.example.com", 5000, 100.2, 100.3, 102.0),
        ("api.example.com", 5000, 105.0, 106.0, 106.0),
    ]


def test_request_split_across_segments_and_large_response_records(tmp_path):
    c = Cap()
    c.seg(1.0, 6000, True, _client_hello("h"))
    body = b"q" * 16000
    rec = _tls(0x17, body)
    c.seg(2.0, 6000, True, rec[:9000])
    c.seg(2.1, 6000, True, rec[9000:] + _tls(0x17, b"q" * 16000))  # continuation, then another full record
    big = _tls(0x17, b"a" * 16000)
    c.seg(3.0, 6000, False, big[:8000])
    c.seg(3.5, 6000, False, big[8000:])  # continuation segment with no record header: still response data
    calls = _parse(c, tmp_path)
    assert len(calls) == 1
    k = calls[0]
    assert (k.start, k.first, k.end) == (2.0, 3.0, 3.5)
    assert k.req_bytes == 2 * (16000 + 5) and k.resp_bytes == 16005


def test_killed_before_response(tmp_path):
    c = Cap()
    c.seg(1.0, 7000, True, _client_hello("h"))
    c.seg(2.0, 7000, True, _tls(0x17, b"q" * 300))
    (k,) = _parse(c, tmp_path)
    assert k.first is None and k.end == k.start == 2.0


def test_netstats_exact_host_match_and_union():
    calls = [
        ApiCall("chatgpt.com", 1, 10.0, 10.5, 12.0, 1, 1),
        ApiCall("chatgpt.com", 2, 11.0, 11.2, 13.0, 1, 1),  # overlaps the first
        ApiCall("ab.chatgpt.com", 3, 20.0, 20.1, 25.0, 1, 1),  # telemetry, not an API host
    ]
    st = NetStats.from_calls(calls, ("chatgpt.com",))
    assert st.calls == 3 and st.api_calls == 2
    assert st.api_busy_s == 3.0
    assert abs(st.api_ttfb_sum_s - 0.7) < 1e-9
    assert st.by_host["ab.chatgpt.com"] == {"calls": 1, "busy_s": 5.0}


def test_bypassed_kernel_check_is_rejected():
    from rlb.rocq import BypassedCheck, parse_assumptions
    import pytest
    with pytest.raises(BypassedCheck):
        parse_assumptions("Axioms:\nSolution.putnam_2025_b3_false is assumed to be guarded.\n")
    assert parse_assumptions("Axioms:\nClassical_Prop.classic : forall P : Prop, P \\/ ~ P\n") == ["Classical_Prop.classic"]
