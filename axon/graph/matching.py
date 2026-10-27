"""Match episodic facts to procedural preconditions and lessons (SEGMENT 4).

The one place the lesson/precondition match rule lives, so it is applied the same way every
time. Rule (from config ``memory.match.version_granularity``):

* ``exact``: same service AND same exact version.
* ``major`` (default): same service AND same major version (e.g. 2.4.49 ~ 2.4.1).
* ``any``:  same service, version ignored.

A different service never matches. Defense is compared only when the lesson specifies one.
"""

from __future__ import annotations

from .schema import ContextSignature, Lesson


def signatures_match(
    lesson_ctx: ContextSignature,
    state_ctx: ContextSignature,
    *,
    version_granularity: str = "major",
) -> bool:
    """True if a lesson keyed by ``lesson_ctx`` applies to the present ``state_ctx``."""
    l = lesson_ctx.normalized()
    s = state_ctx.normalized()

    # Service must match when the lesson names one. A lesson with no service is generic.
    if l.service is not None:
        if s.service is None or l.service != s.service:
            return False

    # Version comparison per granularity, only when the lesson pins a version.
    if l.version is not None and version_granularity != "any":
        if s.version is None:
            return False
        if version_granularity == "exact":
            if l.version != s.version:
                return False
        elif version_granularity == "major":
            if l.major_version() != s.major_version():
                return False

    # Defense: if the lesson is specific to a defense, the state must show the same one.
    if l.defense is not None:
        if s.defense is None or l.defense != s.defense:
            return False

    return True


def matching_lessons(
    lessons: list[Lesson],
    state_ctx: ContextSignature,
    *,
    version_granularity: str = "major",
    limit: int | None = None,
) -> list[Lesson]:
    """Return only the lessons whose context matches the present state (SEGMENT 4).

    Successful lessons are ordered before failure lessons (both are kept — we learn from
    failures too), preserving insertion order within each group.
    """
    matched = [
        l
        for l in lessons
        if signatures_match(l.context, state_ctx, version_granularity=version_granularity)
    ]
    matched.sort(key=lambda l: 0 if l.success else 1)
    return matched[:limit] if limit is not None else matched
