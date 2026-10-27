"""The verification gate and error attribution (SEGMENT 5).

Nothing is written to the procedural graph until this gate passes. It answers two questions
from the execution trace:

1. **Is the outcome real?** A claimed success must be backed by a real state transition
   (a new shell, an HTTP 200 after a 403, a harness-reported milestone/flag). A claimed flag
   with no trace behind it is treated as *not verified* — written nowhere durable.
2. **Who is to blame for a failure?** A tool/syntax error (typo, missing binary, bad flags,
   crash) must NOT be charged against the technique. Only a genuine failure of the technique's
   hypothesis counts as a failure.

If the gate cannot verify, nothing goes to G_K (it may be noted in G_E or a log).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..execution.result import ActionResult
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import error_attribution


class Attribution(str, Enum):
    REAL_SUCCESS = "REAL_SUCCESS"
    HYPOTHESIS_FAILURE = "HYPOTHESIS_FAILURE"   # the technique genuinely did not work
    TOOL_ERROR = "TOOL_ERROR"                   # typo/tool/syntax error — NOT the technique
    HALLUCINATED = "HALLUCINATED"               # claimed success with no trace backing


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    INCONCLUSIVE = "INCONCLUSIVE"   # tool error or hallucination — write nothing durable


@dataclass
class VerificationResult:
    outcome: Outcome
    attribution: Attribution
    verified: bool          # True => safe to write to G_K (a verified success OR genuine failure)
    reason: str

    @property
    def is_success(self) -> bool:
        return self.outcome is Outcome.SUCCESS

    @property
    def is_genuine_failure(self) -> bool:
        return self.outcome is Outcome.FAILURE and self.attribution is Attribution.HYPOTHESIS_FAILURE


# Heuristic signals that a failure is a tool/syntax error, not a technique failure.
_TOOL_ERROR_EXIT_CODES = {126, 127}  # not executable / command not found
_TOOL_ERROR_MARKERS = (
    "command not found",
    "not found",
    "no such file",
    "syntax error",
    "unknown option",
    "invalid option",
    "unrecognized option",
    "usage:",
    "cannot open",
    "permission denied: /usr/bin",
)


def _looks_like_tool_error(result: ActionResult) -> bool:
    if result.timed_out:
        return True
    if result.exit_code in _TOOL_ERROR_EXIT_CODES:
        return True
    blob = (result.stderr or "").lower()
    return any(marker in blob for marker in _TOOL_ERROR_MARKERS)


class VerificationGate:
    """Gate every outcome before any procedural writeback.

    ``llm`` is optional: when provided and the heuristics are ambiguous, the gate asks the model
    to classify a tool error vs. a hypothesis failure. The model can never *grant* a success —
    a success still requires a real state transition in the trace.
    """

    def __init__(self, cfg: dict, llm: Optional[LLMClient] = None) -> None:
        self.require_state_transition = bool(
            cfg.get("verify", {}).get("require_state_transition", True)
        )
        self.llm = llm

    def check(self, result: ActionResult) -> VerificationResult:
        # 1) Claimed success path: demand a real state transition.
        if result.claimed_success:
            if not self.require_state_transition or result.has_state_transition():
                return VerificationResult(
                    outcome=Outcome.SUCCESS,
                    attribution=Attribution.REAL_SUCCESS,
                    verified=True,
                    reason="claimed success backed by a state transition in the trace",
                )
            # Claimed but unbacked -> hallucination. Write nothing durable.
            return VerificationResult(
                outcome=Outcome.INCONCLUSIVE,
                attribution=Attribution.HALLUCINATED,
                verified=False,
                reason="claimed success with no state transition in the trace; not verified",
            )

        # 2) No success claimed. Was it a tool error or a genuine failure?
        if _looks_like_tool_error(result):
            return VerificationResult(
                outcome=Outcome.INCONCLUSIVE,
                attribution=Attribution.TOOL_ERROR,
                verified=False,
                reason="tool/syntax error or timeout; not charged against the technique",
            )

        # Exit code 0 but no success and no error markers: ambiguous. Ask the model if available.
        if result.exit_code == 0 and self.llm is not None:
            attribution = self._llm_attribution(result)
            if attribution is Attribution.TOOL_ERROR:
                return VerificationResult(
                    outcome=Outcome.INCONCLUSIVE,
                    attribution=Attribution.TOOL_ERROR,
                    verified=False,
                    reason="model attributed the failure to a tool error",
                )

        # 3) Genuine failure of the technique's hypothesis — this DOES count as a failure.
        return VerificationResult(
            outcome=Outcome.FAILURE,
            attribution=Attribution.HYPOTHESIS_FAILURE,
            verified=True,
            reason="command ran but the technique did not achieve its goal; genuine failure",
        )

    def _llm_attribution(self, result: ActionResult) -> Attribution:
        prompt = error_attribution(
            result.command, result.stdout, result.stderr, result.exit_code
        )
        try:
            parsed = self.llm.complete_json(
                prompt,
                validate=lambda d: isinstance(d, dict) and "category" in d,
            )
        except LLMError:
            # If the model can't be reached, fall back to treating it as a hypothesis failure.
            return Attribution.HYPOTHESIS_FAILURE
        return (
            Attribution.TOOL_ERROR
            if parsed.get("category") == "tool_error"
            else Attribution.HYPOTHESIS_FAILURE
        )
