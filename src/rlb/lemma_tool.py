"""Hand lemmas to subagents: `python3 lemma.py prove L [--hint TEXT]`, `python3 lemma.py assemble`.

Installed as `lemma.py` in the workdir of attempts whose config names a subagent config (never on
PATH). The runner imports this same file, so the graded file is exactly what `assemble` builds.
Standard library only: it runs inside the sandbox.

    prove L     L is stated in the main file as `Lemma L : ... .` `Proof.` `Admitted.` Asks the runner,
                through a request file under .rlb/delegate/, to run a subagent on L: a separate
                sandboxed attempt whose task file is the main file up to L, then L as the theorem to
                prove, graded by the benchmark's verifier. Blocks until it ends; prints
                "L: proved" (exit 0) or why not plus the subagent's closing message (exit 1). Killing
                this process cancels the subagent.
    assemble    The main file with each proved lemma's proof (from lemmas/L.v, written by the
                runner) in place of its `Admitted`, as lemmas/assembled.v; compiles it and says
                whether it compiles. Prints no proof text.

A proof is spliced only while the main file still states L exactly as it was delegated.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MAIN_FILE = "__MAIN_FILE__"  # substituted at install
LEMMA_DIR = "lemmas"  # proved lemmas: L.v (the proof part), L.json (the statement it proves)
DELEGATE_DIR = ".rlb/delegate"  # one directory per request: request.json, result.json, cancel
ASSEMBLED = "assembled.v"
POLL_S = 2.0

_KIND = r"(?:Lemma|Theorem|Fact|Remark|Corollary|Proposition)"
_PROOF = re.compile(r"\bProof\s*\.")
_END = re.compile(r"\b(Qed|Admitted|Defined|Abort)\s*\.")
_HOLE = re.compile(r"\b(Admitted|admit|give_up|Axiom|Axioms|Parameter|Parameters|Conjecture)\b")


@dataclass(frozen=True)
class Block:
    start: int  # the Lemma keyword
    proof: int  # the `Proof.` keyword (end of the statement)
    end: int  # just past `Qed.` / `Admitted.` / ...
    ending: str  # Qed | Admitted | Defined | Abort


def find_block(text: str, name: str) -> Block | None:
    m = re.search(rf"^[ \t]*{_KIND}\s+{re.escape(name)}\b", text, re.M)
    if not m:
        return None
    p = _PROOF.search(text, m.end())
    if not p:
        return None
    e = _END.search(text, p.end())
    if not e:
        return None
    return Block(m.start(), p.start(), e.end(), e.group(1))


def statement_key(text: str, b: Block) -> str:
    """The statement without its keyword, whitespace-normalized: `L : forall ...`."""
    return " ".join(re.sub(rf"^\s*{_KIND}\s+", "", text[b.start:b.proof]).split())


def assemble(root: Path, main: str) -> tuple[str, list[str]]:
    """(main with every proved, still identically stated lemma spliced in, the lemmas spliced)."""
    text, inlined = main, []
    lemma_dir = root / LEMMA_DIR
    for meta in sorted(lemma_dir.glob("*.json")) if lemma_dir.is_dir() else []:
        name = meta.stem
        b = find_block(text, name)
        if b is None or b.ending != "Admitted" or statement_key(text, b) != json.loads(meta.read_text())["statement"]:
            continue
        text = text[:b.start] + (lemma_dir / f"{name}.v").read_text().rstrip() + "\n" + text[b.end:]
        inlined.append(name)
    return text, inlined


def compile_text(text: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="lemma-") as d:
        (Path(d) / "Assembled.v").write_text(text)
        r = subprocess.run([shutil.which("coqc") or "coqc", "-q", "Assembled.v"], cwd=d, capture_output=True, text=True)
        return r.returncode == 0, (r.stdout + r.stderr).strip()


def prove(root: Path, name: str, hint: str) -> int:
    text = (root / MAIN_FILE).read_text()
    b = find_block(text, name)
    if b is None:
        print(f"{name}: no `Lemma {name} : ... .` followed by `Proof.` and `Admitted.` in {MAIN_FILE}")
        return 1
    if b.ending != "Admitted":
        print(f"{name}: already closed with {b.ending}. in {MAIN_FILE}")
        return 1
    req = root / DELEGATE_DIR / f"{name}-{time.time_ns()}-{os.getpid()}"
    req.mkdir(parents=True)
    body = {"name": name, "prefix": text[:b.start], "statement": text[b.start:b.proof], "hint": hint,
            "statement_key": statement_key(text, b)}
    (req / "request.json.tmp").write_text(json.dumps(body))
    (req / "request.json.tmp").rename(req / "request.json")  # atomic: the runner never sees half a request

    def cancel(signum, _frame):
        (req / "cancel").touch()
        sys.exit(128 + signum)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, cancel)
    print(f"{name}: subagent started", flush=True)
    while not (req / "result.json").exists():
        time.sleep(POLL_S)
    r = json.loads((req / "result.json").read_text())
    if r["status"] == "proved":
        print(f"{name}: proved")
        return 0
    print(f"{name}: not proved ({r['reason']})")
    if r.get("message"):
        print(f"subagent's closing message:\n{r['message']}")
    return 1


def main(argv: list[str]) -> int:
    root = Path.cwd()
    if len(argv) >= 2 and argv[0] == "prove" and (len(argv) == 2 or (len(argv) == 4 and argv[2] == "--hint")):
        return prove(root, argv[1], argv[3] if len(argv) == 4 else "")
    if argv == ["assemble"]:
        text, inlined = assemble(root, (root / MAIN_FILE).read_text())
        (root / LEMMA_DIR).mkdir(exist_ok=True)
        (root / LEMMA_DIR / ASSEMBLED).write_text(text)
        ok, out = compile_text(text)
        print(f"spliced in: {', '.join(inlined) or '-'}")
        if not ok:
            print("does not compile:\n" + "\n".join(out.splitlines()[-15:]))
        elif _HOLE.search(text):
            print("compiles, but something is still admitted")
        else:
            print("compiles, nothing admitted")
        return 0 if ok and not _HOLE.search(text) else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
