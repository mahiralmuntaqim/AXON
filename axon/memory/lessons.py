"""Lesson distillation (SEGMENT 5).

After a verified outcome, ask the frozen model for one short, reusable lesson and key it with
the context signature (service, version, defense). Lessons are distilled from failures too, not
only successes. If the model is unavailable, fall back to a templated lesson so learning still
lands in the graph (all learning is a graph edit — rule 2).
"""

from __future__ import annotations

from typing import Optional

from ..graph.schema import ContextSignature, Lesson
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import lesson_distillation


def distill_lesson(
    *,
    technique_spec: str,
    context: ContextSignature,
    success: bool,
    outcome_detail: str,
    llm: Optional[LLMClient] = None,
) -> Lesson:
    """Produce one lesson keyed by ``context``. Never raises — falls back to a template."""
    outcome_word = "SUCCESS" if success else "FAILURE"
    ctx_summary = _context_summary(context)
    text: Optional[str] = None

    if llm is not None:
        prompt = lesson_distillation(technique_spec, ctx_summary, f"{outcome_word}: {outcome_detail}")
        try:
            parsed = llm.complete_json(
                prompt,
                validate=lambda d: isinstance(d, dict) and isinstance(d.get("lesson"), str),
            )
            text = parsed["lesson"].strip()
        except LLMError:
            text = None

    if not text:
        verb = "worked" if success else "did not work"
        text = f"Technique {verb} against {ctx_summary}. {outcome_detail}".strip()

    return Lesson(context=context.normalized(), text=text, success=success)


def _context_summary(ctx: ContextSignature) -> str:
    bits = []
    if ctx.service:
        bits.append(ctx.service)
    if ctx.version:
        bits.append(f"v{ctx.version}")
    if ctx.defense:
        bits.append(f"defense={ctx.defense}")
    return " ".join(bits) if bits else "an unspecified context"
