"""All prompt templates in one file (SEGMENT 9).

Every template asks for strict, parseable JSON. Keep them short; never stuff raw tool logs in
(that is what context folding is for). The functions here only *build* strings — parsing and
the verification gate happen in the caller, so raw model text never becomes a graph write.
"""

from __future__ import annotations

from typing import Sequence

_JSON_REMINDER = "Reply with ONLY valid JSON, no prose, no code fences."


def technique_extraction(source_chunk: str) -> str:
    """SEGMENT 3: extract techniques from a source write-up into typed nodes."""
    return (
        "You extract pentest techniques from reference text into a knowledge graph.\n"
        "For each distinct technique, output an object with:\n"
        '  "spec": one-sentence description,\n'
        '  "type": one of RECON, ENUM, EXPLOIT, PRIVESC, LATERAL, EXFIL,\n'
        '  "reversibility": REVERSIBLE or IRREVERSIBLE.\n'
        "If a technique has no clear type, set \"type\": null (it will be held for review, "
        "not guessed).\n"
        f"{_JSON_REMINDER} Output a JSON list.\n\n"
        f"TEXT:\n{source_chunk}\n"
    )


def applicability_prior(src_spec: str, dst_spec: str, edge_type: str) -> str:
    """SEGMENT 3: the LLM prior P for a new edge (how applicable the transition is)."""
    return (
        "Rate how applicable this technique transition is in general, as a probability.\n"
        f'FROM: {src_spec}\nTO: {dst_spec}\nRELATION: {edge_type}\n'
        f'{_JSON_REMINDER} Output {{"P": <float 0..1>}}.\n'
    )


def prune_candidates(state_summary: str, candidates: Sequence[tuple[str, str]]) -> str:
    """SEGMENT 6: let the LLM drop clearly-irrelevant out-edges before scoring.

    ``candidates`` is a list of (edge_id, technique_spec). The model returns the edge_ids worth
    keeping, so the PUCT search stays small.
    """
    listing = "\n".join(f"- {eid}: {spec}" for eid, spec in candidates)
    return (
        "Given the current target state, which candidate techniques are worth considering "
        "next? Drop ones that cannot apply. Keep the rest.\n\n"
        f"STATE:\n{state_summary}\n\nCANDIDATES:\n{listing}\n\n"
        f'{_JSON_REMINDER} Output {{"keep": [<edge_id>, ...]}}.\n'
    )


def lesson_distillation(technique_spec: str, context_summary: str, outcome: str) -> str:
    """SEGMENT 5: one short, reusable lesson — why it worked or failed."""
    return (
        "Write ONE short, reusable lesson (max 30 words) about why this attempt had its "
        "outcome, so a future engagement in a similar context benefits.\n\n"
        f"TECHNIQUE: {technique_spec}\nCONTEXT: {context_summary}\nOUTCOME: {outcome}\n\n"
        f'{_JSON_REMINDER} Output {{"lesson": "<text>"}}.\n'
    )


def error_attribution(command: str, stdout: str, stderr: str, exit_code: int) -> str:
    """SEGMENT 5: tool/syntax error vs. a genuine failure of the technique's hypothesis.

    Only the trace summary is passed, never full logs. A typo/tool error must NOT be charged
    against the technique.
    """
    return (
        "Classify why this command did not achieve its goal.\n"
        '  "tool_error": the command itself was malformed, a typo, a missing binary, bad '
        "flags, or a crash unrelated to the target's security posture.\n"
        '  "hypothesis_failure": the command ran fine but the technique genuinely did not '
        "work against this target.\n\n"
        f"COMMAND: {command}\nEXIT: {exit_code}\n"
        f"STDOUT (trimmed): {stdout[:500]}\nSTDERR (trimmed): {stderr[:500]}\n\n"
        f'{_JSON_REMINDER} Output {{"category": "tool_error" | "hypothesis_failure", '
        '"reason": "<short>"}}.\n'
    )


def verify_outcome(goal: str, claimed: str, trace_summary: str) -> str:
    """SEGMENT 5: support outcome verification where the trace alone is ambiguous.

    The trace is the primary evidence; this only assists. The gate still requires a real state
    transition — the model cannot grant a success on its own.
    """
    return (
        "Does the execution trace actually support the claimed outcome? Judge only from the "
        "trace; do not assume success without evidence in it.\n\n"
        f"GOAL: {goal}\nCLAIMED: {claimed}\nTRACE (trimmed): {trace_summary[:800]}\n\n"
        f'{_JSON_REMINDER} Output {{"supported": true | false, "evidence": "<short>"}}.\n'
    )
