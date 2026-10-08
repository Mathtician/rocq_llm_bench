"""One sandbox for every harness: filesystem and network confinement that the
harness cannot see or opt out of, so each harness can run with its own
permission prompts disabled.

Layers, outermost first:

  pasta        user + network namespace, packet capture (net.py). Inside it we
               are root with all capabilities, so we can program the netns.
  guard        `python -m rlb.sandbox <spec.json>`, this module's main(). Runs
               in the namespace before the harness:
                 * DNS forwarder on 127.0.0.1:53 that resolves only the allowed
                   hosts (upstream: the host's resolver, via pasta) and replies
                   NXDOMAIN to everything else;
                 * nftables output policy: loopback, DNS to the upstream, and
                   TCP/443 to addresses the forwarder has resolved. Everything
                   else is rejected;
               then runs bwrap and waits for it.
  proxy        mitmdump with rlb/proxy.py, also inside the namespace: the
               harness is pointed at it (HTTPS_PROXY + CA env vars, bwrap
               --setenv), so every API request is seen in the clear: server-
               side tool declarations are stripped, exact timing and usage
               logged to the attempt's api.jsonl.
  bwrap        mount namespace with: the Nix store and system paths read-only
               (minus this repo's flake snapshots in the store, masked), the
               workdir read-write, the opam switch and shim dir read-only
               at their real paths, the harness's own state dirs read-write
               under an otherwise empty HOME, tmpfs /tmp, resolv.conf pointing
               at the forwarder, the nscd socket hidden (so glibc reads
               resolv.conf). The repo, its problems and results are invisible.

Known hole: the agent can send DNS queries to the upstream resolver directly
(same nft rule the forwarder needs). That is exfiltration-shaped, not
lookup-shaped; a held-out test set is the real answer.
"""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from . import ROOT

DNS_PORT = 53


@dataclass(frozen=True)
class SandboxSpec:
    argv: list[str]  # the harness command
    workdir: str  # rw, and cwd
    allowed_hosts: list[str]  # only these names resolve; only their addresses are reachable (TCP/443)
    ro_paths: list[str]  # bound read-only at their real paths (opam switch, shim dir)
    rw_paths: list[str]  # bound read-write at their real paths (harness state dirs under HOME)
    uid: int
    gid: int
    home: str
    pcap: str
    ca_dir: str = ""  # mitmproxy confdir (CA generated on first use; shared per run); "" = no proxy
    api_log: str = ""  # where the proxy addon writes its JSON lines (attempt dir)
    passthrough_hosts: list[str] = field(default_factory=list)  # TLS passed through the proxy un-inspected (still allowlisted)

    @staticmethod
    def write(spec: SandboxSpec, path: Path) -> None:
        path.write_text(json.dumps(asdict(spec), indent=1))


def ensure_ca(ca_dir: Path) -> None:
    """Create the proxy CA once per run, before any attempt starts. Concurrent
    mitmdump instances sharing a confdir would each generate their own and
    overwrite one another (seen: a Go client trusting one CA while its proxy
    signed with another)."""
    ca_dir.mkdir(parents=True, exist_ok=True)
    key_and_cert, cert = ca_dir / "mitmproxy-ca.pem", ca_dir / "mitmproxy-ca-cert.pem"
    if key_and_cert.exists() and cert.exists():
        return
    key = ca_dir / "ca.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=rlb sandbox CA",
                    "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    key_and_cert.write_bytes(key.read_bytes() + cert.read_bytes())  # mitmproxy's combined format
    key.unlink()
    os.chmod(key_and_cert, 0o600)


def sandbox_argv(spec_path: Path, pcap: Path) -> list[str]:
    """The full command the runner launches: pasta -> guard -> bwrap -> harness."""
    return [
        # No automatic port forwarding: pasta's default `auto` mode mirrors host-bound ports into
        # the namespace (and vice versa), so with concurrent sandboxes the first one's proxy port
        # appeared pre-bound in every later namespace and its mitmdump could not bind (2026-09-05).
        "pasta", "--config-net", "--quiet", "-t", "none", "-u", "none", "-T", "none", "-U", "none",
        "--pcap", str(pcap), "--",
        sys.executable, "-m", "rlb.sandbox", str(spec_path),
    ]


# --- inside the namespace ----------------------------------------------------


def _upstream_resolver() -> str:
    for line in Path("/etc/resolv.conf").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver" and ":" not in parts[1]:
            return parts[1]
    raise SystemExit("sandbox: no IPv4 nameserver in /etc/resolv.conf")


def _qname(msg: bytes) -> tuple[str, int]:
    """(name, offset past the question name) of the first question."""
    i, labels = 12, []
    while True:
        n = msg[i]
        if n == 0:
            i += 1
            break
        labels.append(msg[i + 1 : i + 1 + n].decode("ascii", "replace"))
        i += 1 + n
    return ".".join(labels).lower(), i


def _skip_name(msg: bytes, i: int) -> int:
    while True:
        n = msg[i]
        if n == 0:
            return i + 1
        if n & 0xC0 == 0xC0:  # compression pointer
            return i + 2
        i += 1 + n


def _answer_addresses(msg: bytes) -> list[str]:
    """A/AAAA addresses in the answer section (whatever name they are for, so
    CNAME chains are covered)."""
    qd, an = struct.unpack_from(">HH", msg, 4)
    i = 12
    for _ in range(qd):
        i = _skip_name(msg, i) + 4
    out = []
    for _ in range(an):
        i = _skip_name(msg, i)
        typ, _cls, _ttl, rdlen = struct.unpack_from(">HHIH", msg, i)
        i += 10
        rdata = msg[i : i + rdlen]
        i += rdlen
        if typ == 1 and rdlen == 4:
            out.append(socket.inet_ntop(socket.AF_INET, rdata))
        elif typ == 28 and rdlen == 16:
            out.append(socket.inet_ntop(socket.AF_INET6, rdata))
    return out


def _nxdomain(msg: bytes) -> bytes:
    _, qend = _qname(msg)
    flags = 0x8183  # QR, RD, RA, RCODE=3
    return msg[:2] + struct.pack(">HHHHH", flags, 1, 0, 0, 0) + msg[12:qend + 4]


class _Guard:
    def __init__(self, allowed: set[str], upstream: str):
        self.allowed = allowed
        self.upstream = upstream
        self.known: set[str] = set()
        self.lock = threading.Lock()

    def nft_setup(self):
        rules = f"""
        table inet rlb {{
          set allow4 {{ type ipv4_addr; }}
          set allow6 {{ type ipv6_addr; }}
          chain out {{
            type filter hook output priority 0; policy drop;
            oif lo accept
            ip daddr {self.upstream} udp dport 53 accept
            ip daddr {self.upstream} tcp dport 53 accept
            ip daddr @allow4 tcp dport 443 accept
            ip6 daddr @allow6 tcp dport 443 accept
            meta l4proto tcp reject with tcp reset
            reject
          }}
        }}
        """
        subprocess.run(["nft", "-f", "-"], input=rules, text=True, check=True)

    def allow(self, addrs: list[str]):
        with self.lock:
            new = [a for a in addrs if a not in self.known]
            self.known.update(new)
        for a in new:
            fam = "allow6" if ":" in a else "allow4"
            subprocess.run(["nft", "add", "element", "inet", "rlb", fam, "{", a, "}"], check=True)

    def serve(self, sock: socket.socket):
        while True:
            try:
                msg, peer = sock.recvfrom(4096)
            except OSError:
                return
            threading.Thread(target=self.handle, args=(sock, msg, peer), daemon=True).start()

    def handle(self, sock: socket.socket, msg: bytes, peer):
        try:
            name, _ = _qname(msg)
        except (IndexError, UnicodeDecodeError):
            return
        if name not in self.allowed:
            sock.sendto(_nxdomain(msg), peer)
            return
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as up:
            up.settimeout(5)
            up.sendto(msg, (self.upstream, DNS_PORT))
            try:
                reply, _ = up.recvfrom(4096)
            except socket.timeout:
                return
        try:
            self.allow(_answer_addresses(reply))
        except (struct.error, IndexError, subprocess.CalledProcessError) as e:
            print(f"sandbox: dns answer for {name}: {e}", file=sys.stderr)
        sock.sendto(reply, peer)


def repo_copies_in_store() -> list[Path]:
    """Every `nix develop` snapshots this repository into /nix/store/<hash>-source,
    reference proofs and results included, and the store is mounted read-only
    in the sandbox. Those copies must be masked (an agent found one with
    `find / -name "*b6*"` and copied the reference proof)."""
    out = []
    for d in Path("/nix/store").glob("*-source"):
        if (d / "problems" / "manifest.json").exists() or (d / "src" / "rlb").exists():
            out.append(d)
    return sorted(out)


PROXY_PORT = 8080


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _proxy_env(spec: SandboxSpec) -> list[str]:
    """Point every runtime at the proxy and its CA: Node (Claude Code, pi),
    Go (Antigravity), Rust/reqwest (Codex), Python, curl."""
    ca = str(Path(spec.ca_dir) / "mitmproxy-ca-cert.pem")
    url = f"http://127.0.0.1:{PROXY_PORT}"
    env = {"HTTPS_PROXY": url, "HTTP_PROXY": url, "https_proxy": url, "http_proxy": url, "NO_PROXY": "127.0.0.1,localhost",
           "NODE_EXTRA_CA_CERTS": ca, "SSL_CERT_FILE": ca, "REQUESTS_CA_BUNDLE": ca, "CURL_CA_BUNDLE": ca}
    return [a for k, v in env.items() for a in ("--setenv", k, v)]


def _bwrap_argv(spec: SandboxSpec, resolv: Path) -> list[str]:
    home = spec.home
    args = [
        "bwrap", "--unshare-user", "--uid", str(spec.uid), "--gid", str(spec.gid),
        "--unshare-pid", "--die-with-parent",
        "--ro-bind", "/nix/store", "/nix/store",
        *[a for d in repo_copies_in_store() for a in ("--tmpfs", str(d))],  # hide this repo's flake snapshots
        "--ro-bind", "/run", "/run",
        "--tmpfs", "/run/nscd",  # hide the nscd socket: glibc then resolves via /etc/resolv.conf
        "--ro-bind", "/etc", "/etc",
        "--ro-bind", str(resolv), "/etc/resolv.conf",
        "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--dir", home, "--tmpfs", f"{home}/.cache",
    ]
    for p in ("/usr", "/bin", "/lib64", "/var/empty"):  # /lib64: nix-ld loader for foreign binaries (Cursor's bundled node)
        if Path(p).exists():
            args += ["--ro-bind", p, p]
    for p in spec.ro_paths:
        args += ["--ro-bind", p, p]
    for p in spec.rw_paths:
        if Path(p).is_dir():
            args += ["--bind", p, p]
        elif Path(p).is_file():
            args += ["--bind", p, p]
    args += ["--bind", spec.workdir, spec.workdir, "--chdir", spec.workdir]
    args += ["--setenv", "HOME", home]
    if spec.ca_dir:
        args += ["--ro-bind", spec.ca_dir, spec.ca_dir, *_proxy_env(spec)]
    args += ["--"]
    return args + spec.argv


def main(spec_path: str) -> int:
    spec = SandboxSpec(**json.loads(Path(spec_path).read_text()))
    upstream = _upstream_resolver()
    guard = _Guard({h.lower().rstrip(".") for h in spec.allowed_hosts}, upstream)
    guard.nft_setup()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", DNS_PORT))
    threading.Thread(target=guard.serve, args=(sock,), daemon=True).start()
    resolv = Path(spec.workdir).parent / f".resolv-{Path(spec.workdir).name}"
    resolv.write_text("nameserver 127.0.0.1\noptions ndots:0\n")
    # The guard's own children (the proxy, bwrap) must resolve through the forwarder too, so
    # that the addresses they connect to are the ones the allowlist admits: a private mount
    # namespace with the forwarder's resolv.conf over /etc/resolv.conf and the nscd socket hidden.
    os.unshare(os.CLONE_NEWNS)
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)
    if Path("/run/nscd").is_dir():
        subprocess.run(["mount", "-t", "tmpfs", "none", "/run/nscd"], check=True)
    subprocess.run(["mount", "--bind", str(resolv), "/etc/resolv.conf"], check=True)

    proxy = None
    if spec.ca_dir:
        # The proxy runs here, inside the namespace: its upstream connections go through the
        # DNS forwarder and the allowlist like everything else. Its CA lives in ca_dir.
        addon = str(Path(__file__).with_name("proxy.py"))
        proxy = subprocess.Popen(
            ["mitmdump", "--listen-host", "127.0.0.1", "-p", str(PROXY_PORT), "--set", f"confdir={spec.ca_dir}",
             "-q", "-s", addon,
             # bidirectional streams (Cursor's agent gRPC) break under interception: pass them through
             *(["--ignore-hosts", "|".join(re.escape(h) + "(:443)?$" for h in spec.passthrough_hosts)] if spec.passthrough_hosts else [])],
            env={**os.environ, "RLB_PROXY_LOG": spec.api_log}, stdout=subprocess.DEVNULL,
            stderr=open(Path(spec.api_log).with_name("proxy.err"), "wb"),
        )
        assert not _port_open(PROXY_PORT), f"sandbox: something already listens on 127.0.0.1:{PROXY_PORT} in the namespace"
        deadline = time.time() + 30
        while time.time() < deadline and proxy.poll() is None:
            if _port_open(PROXY_PORT):
                break
            time.sleep(0.2)
        else:
            proxy.kill()
            raise SystemExit(f"sandbox: mitmdump did not come up (rc={proxy.returncode}; see proxy.err)")

    child = subprocess.Popen(_bwrap_argv(spec, resolv))
    forward = lambda signum, _frame: child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    rc = child.wait()
    if proxy is not None:
        proxy.terminate()
        try:
            proxy.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proxy.kill()
    resolv.unlink(missing_ok=True)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
