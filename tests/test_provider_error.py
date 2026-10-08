"""Provider refusals (quota, rate limit, billing) as each harness reports them,
taken verbatim from sweep-2 transcripts, must be recognised; ordinary failures
must not."""
import json

from rlb.harness import HARNESSES
from rlb.harness.base import is_provider_error
from rlb.runner import detect_provider_error

CLAUDE_LIMIT = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429,
                "result": "You've hit your session limit \u00b7 resets 5am (America/Chicago)"}
CODEX_LIMIT = {"type": "turn.failed", "error": {"message": "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 6:41 AM."}}
PI_SUSPENDED = {"type": "message_end", "message": {"role": "assistant", "stopReason": "error",
                "errorMessage": "412 {\"error\":{\"message\":\"Account x is suspended, possibly due to reaching the monthly spending limit or failure to pay past invoices.\"}}"}}
PI_429 = {"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "errorMessage": "429 \"Rate limit exceeded\""}}
AGY_ELIGIBILITY = {"event": "result", "result": {"status": "ERROR", "error": "Eligibility check failed: Get \"https://www.googleapis.com/oauth2/v2/userinfo\": dial tcp: lookup www.googleapis.com: no such host"}}

PI_CONTEXT = {"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "errorMessage": "400 context length exceeded"}}
AGY_SPURIOUS = {"event": "result", "result": {"status": "ERROR", "error": "declaring permissions: cortex tool write_to_file: convert tool call for permissions: model output error: invalid"}}
CLAUDE_TEXT = {"type": "assistant", "message": {"content": [{"type": "text", "text": "The rate of convergence is limited by the second term; I'll bound it with lra."}]}}


def test_refusals_recognised():
    assert HARNESSES["claude"].provider_error(CLAUDE_LIMIT)
    assert HARNESSES["codex"].provider_error(CODEX_LIMIT)
    assert HARNESSES["pi"].provider_error(PI_SUSPENDED)
    assert HARNESSES["pi"].provider_error(PI_429)
    assert HARNESSES["agy"].provider_error(AGY_ELIGIBILITY)


def test_model_side_failures_are_not_refusals():
    assert HARNESSES["pi"].provider_error(PI_CONTEXT) is None
    assert HARNESSES["agy"].provider_error(AGY_SPURIOUS) is None
    assert HARNESSES["claude"].provider_error(CLAUDE_TEXT) is None  # prose mentioning "rate" is not a 429


def test_unsolved_trial_with_a_refusal_is_invalid_but_a_solved_one_stands():
    lines = [(0.0, json.dumps(PI_429)), (1.0, json.dumps({"type": "turn_end"}))]
    st = HARNESSES["pi"].stats(lines)
    assert st.provider_errors == ['429 "Rate limit exceeded"']
    assert detect_provider_error(st, solved=False) == '429 "Rate limit exceeded"'
    assert detect_provider_error(st, solved=True) is None


def test_pattern_scope():
    assert is_provider_error("HTTP 503 Service Unavailable")
    assert not is_provider_error("Error: No applicable tactic.")


def test_suspend_invalidates():
    from rlb.runner import invalid_reason
    base = {"provider_error": None, "suspended_s": 0.0, "solved": True}
    assert invalid_reason(base) is None
    assert invalid_reason({**base, "suspended_s": 2813.0}).startswith("machine suspended 2813s")
    assert invalid_reason({**base, "provider_error": "429"}) == "429"


def test_reference_access_rule(tmp_path):
    from rlb.runner import reference_access
    (tmp_path / "stdout.txt").write_text('{"x":"find output: /nix/store/abcdefghijklmnopqrstuvwxyz012345-source/_opam/lib/coq/Stdlib.v"}\n')
    assert reference_access(tmp_path) is None  # a snapshot's Stdlib copy is not reference material
    (tmp_path / "stdout.txt").write_text('{"x":"/nix/store/abcdefghijklmnopqrstuvwxyz012345-source/problems/putnam/putnam_2025_b6.ref.v"}\n')
    assert reference_access(tmp_path).startswith("reference material reached")
