"""Explain Mode (design spec §33).

Every transfer records its :class:`~rpython.data.context.TransferPlan`.
``rp.explain_last()`` renders the most recent one; ``rp.explain(n)``
shows the last *n*; ``rp.explain_plan(obj)`` dry-runs the planner on a
Python object without sending it anywhere.
"""
from __future__ import annotations

import collections
from typing import Any

from .data.context import Context, TransferPlan

_HISTORY: collections.deque[tuple[str, TransferPlan]] = collections.deque(maxlen=200)


def record_plan(plan: TransferPlan, label: str = "") -> None:
    from .config import get_config
    if get_config().explain:
        _HISTORY.append((label, plan))


def last_plan() -> TransferPlan | None:
    return _HISTORY[-1][1] if _HISTORY else None


def explain_last(print_it: bool = True) -> str:
    """Explain what RPython did during the most recent transfer."""
    if not _HISTORY:
        txt = "No transfer recorded yet."
    else:
        label, plan = _HISTORY[-1]
        txt = f"[{label}]\n{plan.render()}"
    if print_it:
        print(txt)
    return txt


def explain(n: int = 5, print_it: bool = True) -> str:
    items = list(_HISTORY)[-n:]
    txt = "\n\n".join(f"[{label}]\n{plan.render()}" for label, plan in items) or "No transfer recorded yet."
    if print_it:
        print(txt)
    return txt


def explain_plan(obj: Any, print_it: bool = True) -> TransferPlan:
    """Dry-run: show the transfer plan RPython would use for ``obj`` (nothing is sent)."""
    from .data.convert import to_envelope
    from .data.semantic import Runtime
    ctx = Context(direction="py->r", target_runtime=Runtime.R)
    to_envelope(obj, ctx)
    ctx.plan.target = "R (dry run)"
    record_plan(ctx.plan, "dry run")
    if print_it:
        print(ctx.plan.render())
    return ctx.plan


def history() -> list[tuple[str, TransferPlan]]:
    return list(_HISTORY)


def clear() -> None:
    _HISTORY.clear()
