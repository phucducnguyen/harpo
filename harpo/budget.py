"""Budget Policy: account for tool calls AND encode the control rules.

This is the spine of Track A (strict tool-invocation budgets). It tracks how
many times each action has been spent, enforces per-tool limits with a reserve
held back for the final verification pass, and encodes the loop's decision
rules (e.g. no csynth before csim passes; stop on regression/repetition).

Budget shape::

    {"mode": "per_tool",
     "limits": {"static_check": 100, "csim": 20, "csynth": 10,
                "cosim": 5, "llm_calls": 30},
     "reserve": {"final_csim": 1, "final_csynth": 1, "final_cosim": 1}}

A limit that is absent is treated as unlimited (``float('inf')``). The reserve
maps ``final_<stage>`` -> count held back so a passing candidate can always be
re-verified at the end.
"""

from __future__ import annotations


class BudgetManager:
    """Accounts for tool invocations and enforces the per-tool budget policy."""

    def __init__(self, budget: dict) -> None:
        self.limits: dict = dict(budget.get("limits", {}))
        self.reserve: dict = dict(budget.get("reserve", {}))
        self.spent: dict[str, int] = {}

    def _limit(self, action: str) -> float | int:
        """Configured limit for ``action``; missing => unlimited."""
        return self.limits.get(action, float("inf"))

    def _reserved_for(self, action: str) -> int:
        """Count held back for the final-verification pass of this action."""
        return self.reserve.get(f"final_{action}", 0)

    def can(self, action: str) -> bool:
        """True if a non-reserved invocation of ``action`` is still affordable."""
        spent = self.spent.get(action, 0)
        return spent < self._limit(action) - self._reserved_for(action)

    def spend(self, action: str) -> None:
        """Record one invocation of ``action``."""
        self.spent[action] = self.spent.get(action, 0) + 1

    def remaining(self, action: str) -> float | int:
        """Non-reserved invocations of ``action`` left (may be ``inf``)."""
        return self._limit(action) - self._reserved_for(action) - self.spent.get(action, 0)

    def exhausted(self) -> bool:
        """True when no further progress is possible (no csim and no llm calls)."""
        return not self.can("csim") and not self.can("llm_calls")

    def snapshot(self) -> dict:
        """JSON-serializable view of limits/spent/reserve (``inf`` -> ``None``)."""
        limits = {k: (None if v == float("inf") else v) for k, v in self.limits.items()}
        return {
            "limits": limits,
            "spent": dict(self.spent),
            "reserve": dict(self.reserve),
        }

    def policy_allows(
        self,
        action: str,
        *,
        csim_pass: bool,
        regressed: bool,
        repeated: bool,
    ) -> tuple[bool, str]:
        """Decide whether ``action`` is allowed now; return ``(allowed, reason)``.

        Rules, in order: budget first, then stage ordering (no csynth/cosim
        before csim passes), then the stop/rollback guard for repeated or
        regressed states on LLM calls.
        """
        if not self.can(action):
            return (False, f"budget exhausted for {action}")
        if action == "csynth" and not csim_pass:
            return (False, "no csynth before csim passes")
        if action == "cosim" and not csim_pass:
            return (False, "no cosim before csim passes")
        if action == "impl" and not csim_pass:
            # (The agent additionally verifies only csynth-passing candidates;
            # this guards the tool-budget layer the same way csynth/cosim are.)
            return (False, "no impl before csim passes")
        if (regressed or repeated) and action in ("llm_calls",):
            return (False, "stop/rollback: repeated or regressed")
        return (True, "ok")
