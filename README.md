# rocq_llm_bench

Benchmark LLM agent harnesses (Claude Code, Codex CLI, pi) on Rocq theorem
proving, measuring capability *and* where the wall-clock time goes: model
inference vs. the Rocq prover.

## Status

This is a **code release**: the meta-harness, sandbox, configs, prompts and
tests. Results, transcripts and the run ledger (`results/`, `log/`) are not
published yet. No license has been chosen yet, so for now all rights are
reserved; third-party problem statements keep their own licenses
([THIRD_PARTY.md](THIRD_PARTY.md)).

No reference proofs (`*.ref.v`) or agent-produced solutions are included, so
`problems/manifest.json` keeps only reference metadata (`ref_proof_lines`,
`ref_check_s`) and `rlb selftest` has nothing
to check. Problem statements included in `problems/`:

| tier | included? | why |
|---|---|---|
| putnam | statements (9) | Putnam2025-Rocq, Apache-2.0 |
| imo, aime | statements (32, 21) | miniF2F-rocq, MIT |
| research | statements (17), `problems_src/research/` | written for this benchmark; the 4 generated algebra references can be regenerated with `scripts/generate-research-equations.py` |
| custom | statements (6) | written for this benchmark; the source files in `problems_src/custom/` are complete proofs, so they are left out and `rlb tier custom` cannot rebuild this tier |
| easy, medium, hard, vhard | **no**: build them yourself | derived from [rocq-workbook](https://github.com/LLM4Rocq/rocq-workbook), which has no license; clone it into `vendor/` and run `rlb select` / `rlb tier vhard` (see Setup) |

## Layout

| path | what |
|---|---|
| `nix/flake.nix` | system deps for the opam switch and the sandbox. In its own directory on purpose: `nix develop ./nix` then snapshots only that directory into the Nix store, not the repository (a root flake copied the whole repo, reference proofs and results included, on every source change: ~5 GB a time, and readable from inside the sandbox). |
| `scripts/setup-rocq.sh` | creates `./_opam` with Rocq 9.1.1 (+ `coqc` compat names) and coq-lsp |
| `pyproject.toml`, `src/rlb/` | the meta-harness (`uv run rlb ...`), zero runtime deps |
| `vendor/` | problem sources (git clones, ignored by git): rocq-workbook, Putnam2025-Rocq, miniF2F-rocq |
| `problems/` | `<tier>/<name>.v` (task), `<tier>/<name>.ref.v` (reference, when there is one), `manifest.json` |
| `problems_src/` | hand-written problems (`rlb tier custom`, `rlb tier research`) and our miniF2F audit (`minif2f/audit.json`, `minif2f/counterexamples/`) |
| `prompts/default.md` | the task prompt (`$file`, `$theorem` substituted) |
| `configs/*.toml` | one (harness, model, knobs) per file; `subagent` is required: `"none"` (main agent only) or the path of another config (itself `"none"`) that the main agent can hand lemmas to with `python3 lemma.py prove L --hint ...` (`src/rlb/lemma_tool.py`, installed in the workdir, not on PATH). rlb runs each as an ordinary sandboxed attempt of that config on the lemma (`src/rlb/delegate.py`), graded by the verifier, recorded under `<attempt>/sub/<id>/`; the main agent gets "proved" or the reason and the subagent's closing message, and the graded file has proved lemmas spliced in (`attempt.graded`). Harness-native subagents are blocked (a call that gets through is a sandbox failure), except agy's, which cannot be disabled and are declared in its prompt |
| `results/<run-id>/<config>/<problem>/r<k>/` | everything an attempt produced (`net.pcap`, the raw capture, is gitignored; `net.json` is its parse); `run.<commit>-<time>.json` and `summary.<commit>-<time>.json` per invocation, since a run id can be resumed |

## Setup

```sh
nix develop ./nix           # gmp etc.; activates ./_opam if it exists
scripts/setup-rocq.sh       # once, ~minutes: opam switch with Rocq 9.1.1 + coq-lsp
uv sync                     # Python env with the `rlb` CLI
git clone https://github.com/LLM4Rocq/rocq-workbook vendor/rocq-workbook   # if missing
uv run rlb select           # easy/medium/hard: 10 workbook problems each, seed 0, references verified
uv run rlb tier vhard       # the extra tiers (see below); each replaces only its own directory
uv run pytest               # verifier regression tests
```

In this release, run `uv run python scripts/generate-research-equations.py`
once before `pytest`: it regenerates the four research-tier algebra references
(byte-identical), which two research tests expect.

The other upstream sources, for rebuilding the putnam/imo/aime tiers
(`rlb tier putnam|imo|aime`):

```sh
git clone https://github.com/LLM4Rocq/Putnam2025-Rocq vendor/Putnam2025-Rocq   # used at 9e221268
git clone https://github.com/LLM4Rocq/miniF2F-rocq vendor/miniF2F-rocq         # used at d9480b5e
```

Caveat: `rlb select` writes `problems/manifest.json` from scratch, dropping
every other tier's entries (`rlb tier` only replaces its own). So run it
first, then `rlb tier` for the other tiers. The custom tier cannot be rebuilt
from this release (see Status): copy its entries back from the shipped
`problems/manifest.json` (`git show HEAD:problems/manifest.json`).

The agent CLIs (`claude`, `codex`, `pi`, `agy`) are expected on PATH and logged
in (`claude` with the Max subscription, `codex` with ChatGPT, `agy` with the
Google AI Pro login, `pi` with the provider API keys in the environment or its
own auth store).

## The sandbox

Every attempt runs inside `src/rlb/sandbox.py`, the same for all harnesses, so
each CLI runs with its own permission prompts off:

- **Network**: a `pasta` namespace (packet capture, see below) whose egress is
  an nftables allowlist. Only the harness's API hosts and the few auth hosts
  it needs (`api_hosts`, `aux_hosts` in `harness/<name>.py`) resolve; only
  their addresses are reachable, on TCP/443. Everything else gets NXDOMAIN or
  a reset. Known hole: raw DNS queries to the upstream resolver.
- **API traffic in the clear**: a TLS-terminating proxy (mitmproxy with
  `src/rlb/proxy.py`) runs inside the namespace; the harness is pointed at it
  (`HTTPS_PROXY`) and trusts its per-run CA through the usual environment
  variables. Its policy (`src/rlb/proxy_policy.py`) is an allowlist: only
  listed endpoints per host pass (403 and a `blocked` record otherwise: e.g.
  Codex's search endpoint, Gemini's URL-fetch cache); in inference requests
  only client-side tool declarations survive (function/custom tools with a
  schema, Gemini `functionDeclarations`), so **server-side tools** (web
  search, URL context, code execution, MCP connectors, whatever they are
  named next) never reach the model, Codex's WebSocket frames included; a
  response that shows a server-side tool having run anyway is a `rule
  violation`. These tools were used to hunt for the published Putnam
  reference solutions before this existed (Gemini fetched and copied two
  verbatim). The proxy also records exact per-call timing and the provider's
  usage block to `api.jsonl` (bodies are never stored).
- **Filesystem**: `bwrap` with the Nix store and system paths read-only, the
  workdir read-write, the opam switch and shim dir at their real paths, and
  under an otherwise empty HOME only the CLI's own state directory
  (`state_paths`). This repo, its `problems/*.ref.v` and other attempts'
  `results/` do not exist from inside. Two ways agents still reached them,
  both closed: before the sandbox, Gemini via `agy` ran `git log -S` on the
  repo and copied a reference; inside it, a root-level `nix develop` had snapshotted the
  whole repo (reference proofs included) into `/nix/store/<hash>-source`,
  which the store mount exposed until those snapshots were masked (Gemini
  found one with `find /` and copied Putnam B6; Codex Terra listed the
  reference directory on B5/B6). Any mention of such a path or of a `.ref.v`
  file in a transcript is a `rule violation` (`runner.reference_access`).

`sandbox.json` in each attempt dir records the exact spec.

What the agent can run is whatever the dev shell puts on PATH from the Nix
store (plus the opam switch): the flake lists `python3` explicitly for that
reason. Anything installed under HOME (`~/.local/bin`, the user Nix profile)
is not visible.

## Tiers

| tier | source | problems | reference proofs |
|---|---|---|---|
| easy, medium, hard | rocq-workbook, by its own difficulty label | 10 each | yes |
| vhard | rocq-workbook, reference proof >= 30 lines (the label does not track what agents find hard) | 10 | yes |
| custom | `problems_src/custom/` (not in this release), written for this benchmark | 6 | yes |
| putnam (timeout 3600 s, set in the manifest) | LLM4Rocq/Putnam2025-Rocq (`vendor/`, git clone); the 9 of 12 whose statement the verifier can re-check and whose machine-found proof verifies here | 9 | yes, 300-1500 lines |
| imo, aime | LLM4Rocq/miniF2F-rocq (`vendor/`, git clone); statements that compile with Stdlib on Rocq 9.1.1, minus the 3 upstream's audit marks wrong and the 3 [ours](problems_src/minif2f/audit.json) proves false or vacuous (`counterexamples/`); 17 more are tagged `weakened` (e.g. one direction of a "find all") in `manifest.tiers.<tier>.audit` | 32, 21 | yes: verified benchmark solutions (`problems_src/minif2f/`, not in this release; `scripts/harvest-minif2f-refs.py`) |
| research | [research pilot](problems_src/research/README.md): two binary-representation results, generalized parking-function counting, and generated algebra controls | 7 | 4 algebra references; 3 paper statements with informal proofs only |

Build the research pilot with `uv run rlb tier research`. Its four-hour timeout
is provisional; difficulty is uncalibrated. This adds tasks without changing the
runner's network restrictions or enabling multi-agent evaluation.

## Running

```sh
uv run rlb run -c configs/claude-opus-high.toml -c configs/codex-high.toml
uv run rlb run -c configs/pi-groq.toml --tier hard --repeat 3
uv run rlb run -c configs/claude-haiku.toml --limit 1 --timeout 120   # smoke test
uv run rlb log run -- uv run rlb run -c configs/claude-opus-high.toml # same, with a ledger entry
uv run rlb report results/20260901-*                                  # tables
uv run rlb timeline results/<run>/<config>/<problem>/r0                # where did the time go? (one attempt, text)
uv run rlb gantt results/<run> -o timeline.html                        # all attempts, one segmented bar each
```

## Cost accounting

`src/rlb/cost.py` gives every attempt an API-equivalent cost in USD, the unit that adds up across
models (composites include their subagents): per-call usage from the proxy log, or the harness's own
usage totals where that log is missing or incomplete, times the list prices in `prices.toml` (one
table per model id, each with its source; subscription models are priced at their provider's
pay-as-you-go API rate). The harness's own figures (Claude Code, pi) serve as fallback and cross-check:
for Opus 5.5 the two agree exactly. `scripts/fit_tokens.py --measure cost` (the default) fits on it.

## Time accounting

Model time is the union of request/response intervals to the harness's API
hosts. Since the proxy (above) sees requests in the clear, those intervals
are exact: request sent, response headers, first body byte, last byte, plus
the provider's own token usage (`net.source = "proxy"`). The packet capture
from the `pasta` namespace (`src/rlb/net.py`, TLS record heuristics) is kept
as a cross-check (`net.pcap_busy_s`) and as the fallback when a harness
bypasses the proxy. Prover time comes from PATH shims around the Rocq
binaries; tool time from the harness's event stream when it has one.
Harness-reported model time (Claude's `duration_api_ms`) is kept alongside.

`run` is resumable: attempts with an `attempt.json` are skipped unless
`--force`. `--jobs N` parallelizes but makes prover timings contend for CPU.

## The log (append-only ledger)

`log/entries.jsonl` records "on commit X, running command Y produced output
Z", one JSON object per line:

```sh
uv run rlb log run --note "first full sweep" -- uv run rlb run -c configs/claude-opus-high.toml
uv run rlb log run -- uv run pytest -q
uv run rlb log show -n 5        # "#12  2026-09-01T...  a1b2c3d4  exit=0  uv run rlb run ...  claude-opus-high/hard 4/10"
```

`log run` commits by itself: before the command starts, every change outside
`log/` and `results/` is committed (so the entry's commit is exactly the code
that ran, even if an earlier run is still in flight and its results have not
landed); after it finishes, the entry and the run's completed artifacts are
committed together, and the command runs under a systemd sleep inhibitor
(a suspend would freeze every attempt while its clock runs; an attempt that
sees one is invalid and redone). Each entry has: `schema` (`rlb.log/1`); that commit and
branch; versions of `claude`,
`codex`, `pi`, `uv`, Rocq and Python; host; argv; start/end/seconds; exit
code; stdout/stderr tails (last 8 KB each); `output.data` (any JSON the
command wrote to `$RLB_LOG_OUTPUT`, which `rlb run` and `rlb report` do with
their summary rows); and `artifacts`, the repo-relative directories that
output names. An entry's id is its line number.

Git is the history. The pre-commit hook (`git config core.hooksPath
.githooks`, set in this clone) enforces two invariants: the staged
`log/entries.jsonl` must extend the committed one byte-for-byte, and files
under `results/` and `log/patches/` may be added but never changed or
removed. So every commit's version of the log and of `results/` contains
everything earlier commits had.

### Reinterpreting old results

The summary rows inside an entry are the interpretation *at the time*. The
raw material for a new interpretation is committed alongside: for every
attempt, `results/<run>/<config>/<problem>/r<k>/` holds `attempt.json`
(timings, verification, usage), the harness event stream (`stdout.txt` with
`stdout.times`), `stderr.txt`, the prover `trace.tsv`, the prompt and argv,
and the final `workdir/` with the agent's `.v` file. Only regenerable scratch
(`verify/`, `shim/`) is left out.

So "what would entry #12 look like under today's `rlb report`?" is just
`uv run rlb report results/<run-id>` on the current commit, and it can be
logged as a new entry. If the code that produced an old run matters, it is
`git show <commit>:path` for the commit in the entry (plus the patch if it
was dirty).

Rules that keep this working across many code changes:

- JSON records carry a `schema` tag (`rlb.log/1`, `rlb.attempt/1`,
  `rlb.summary/1`). Adding fields is free. When a field's meaning changes,
  bump the tag and keep reading old tags, or give the new meaning a new name.
  Never silently redefine a field.
- Files under `results/` are never edited or deleted; a rerun gets a new run
  id. The hook enforces this.
- The log is never edited; corrections are new entries with a `note`.
- Strict JSON only (no `NaN`/`Infinity`): the writers pass `allow_nan=False`,
  so summaries stay readable by `jq` and everything else. Program output is
  escaped by JSON (`\n`, `\t`, quotes) and non-UTF-8 bytes are kept as
  `\xNN`, so one record is always one line.

Why not one Nix derivation per row: a derivation is input-addressed, and the
inputs here (models behind aliases, CLI auto-updates, timing) are not
addressable. The row's job is to record what was *observed*, including the
tool versions, and let the analysis treat entries as noisy samples.

## What is measured

Per attempt (`attempt.json`):

- `wall_s`: lifetime of the harness process.
- `prover.busy_s` / `prover.sum_s` / `prover.calls`: from PATH shims around
  every Rocq binary (`coqc`, `rocq`, `coqtop`, `coq-lsp`, ...). `busy` is the
  union of intervals; `sum` counts overlapping calls separately.
- `inference_s` with `inference_source`:
  - `harness`: Claude Code reports `duration_api_ms` directly.
  - `wall_minus_tools`: Codex and pi emit tool start/end events; inference is
    wall time minus the union of tool-execution intervals.
  - `wall_minus_prover`: fallback if the harness emitted nothing usable.
- `tools_busy_s`: union of the harness's tool-execution intervals (Codex, pi,
  Claude). Tool time minus prover time is the agent doing other things:
  `grep`/`find` over the stdlib sources, file edits, hooks. `rlb timeline`
  shows it call by call.
- `harness.usage`, `harness.turns`, `harness.cost_usd` where reported.
  Claude Code's cost is what the API would have charged; the Max plan is flat.
- `verify`: see below. `solved` is `verify.status == "ok"`, independent of
  whether the harness hit the timeout.

Agents work in `/tmp/rlb-work/...` (not under `$HOME`) so that none of the
CLIs pick up this machine's `CLAUDE.md`/`AGENTS.md`; the final workdir is
copied into the results directory. The shim trace also lives in the workdir
because Codex's sandbox allows writes only under its cwd and `/tmp`.

Harness defaults chosen for a controlled comparison (all overridable in
`[args]`): Claude Code runs with `--setting-sources local` and
`--strict-mcp-config` (no user plugins, hooks or MCP servers), web tools
disallowed; Codex runs with `--ignore-user-config` and the `workspace-write`
sandbox (no network); pi runs with `--no-extensions --no-skills
--no-context-files`. Each adapter documents its knobs in `src/rlb/harness/`.

Per attempt the results directory holds `stdout.txt` (+ `stdout.times`, one
arrival timestamp per line), `stderr.txt`, `trace.tsv` (prover calls),
`prompt.md`, `argv.json`, the final `workdir/`, the `verify/` scratch files,
and `attempt.json`.

## Verification (the ground truth)

The agent's file is copied alone into a clean directory as `Solution.v`,
compiled, and then a generated `Verify.v` re-proves the *original* statement:

```coq
<original imports + preamble>
Require Solution.                 (* loaded, NOT imported *)
Theorem <name> <original binders> : <original goal>.
Proof. repeat match goal with H : _ |- _ => revert H end. exact Solution.<name>. Qed.
Print Assumptions <name>.
```

Because `Solution` is not imported, the agent's notations, scopes and hints
cannot change what the statement means (tested: redefining `+` is caught).
Every printed assumption is then `Locate`d and must resolve under `Stdlib.` or
`Corelib.`, which rejects `Axiom`, `Admitted`, and anything the agent declared.
Residual gap: a `#[global]` instance or canonical structure in `Solution.v`
takes effect on `Require` and could in principle influence elaboration of the
statement; for stdlib arithmetic statements there is nothing to hijack.

## Problem selection

From rocq-workbook's 10k problems: stdlib-only, with a machine-checked
reference proof (so the statement is known provable; the Lean workbook has
false statements), theorem name equal to the record id, no `Inductive`/
`Parameter`-style preamble. Within each tier, domains are cycled round-robin
so a tier is not dominated by inequalities. Each pick's reference proof must
pass the verifier above. Reference proof length and check time are recorded
in the manifest as within-tier difficulty hints.

The "has a reference proof" requirement biases toward problems some prover
already solved. To probe beyond that, `rlb select` could be extended with an
`--unproved` pool; those results would need manual review of false statements.
