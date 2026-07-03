"""Throughput-target probe: derive a defensible ``interval_max`` ceiling with
ZERO LLM tokens, capped synthesis, and no over-parallelization.

``satisfice_then_area`` (and ``pareto_report``) only works when a
``throughput_target`` exists — meet that interval_max ceiling, THEN minimize
area. Specs may hand-set one; when they don't, the agent must DERIVE one rather
than degrade to speed-first. This module does that with the recipe library only:

    baseline csim+csynth -> try a capped number of SINGLE-pragma candidates,
    each a FRESH fork from the baseline (NOT stacked), proposed by
    ``RecipeProvider`` in its natural priority order, SKIPPING any FULL-UNROLL
    recipe (over-parallelization trap) -> re-verify csim -> csynth -> record
    interval_max + area_score. The target is the LOWEST interval_max among the
    baseline plus the probe candidates that pass csim+csynth and stay within an
    area cap (default 2.0x baseline area). Falls back to baseline interval_max,
    or None when even the baseline interval is unknown.

The selector (:func:`select_target`) is a PURE function — the testable core.
:func:`derive_throughput_target` runs the capped probe over a fresh
``CandidateManager`` and the shared budget, reusing ``agent._run_csim`` /
``agent._run_csynth`` so behavior matches the optimize loop exactly. It NEVER
raises on a probe failure: a broken probe simply yields the baseline interval
(or None) and the caller falls back.
"""

from __future__ import annotations

from .area import area_score
from .candidate import CandidateManager, score
from .diagnosis import diagnose_csynth
from .patch_engine import apply_patch
from .recipes import RecipeProvider


def _num(value) -> float | None:
    """``value`` as a float if it is a real (non-bool) number, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def select_target(
    baseline_metrics: dict | None,
    probe_results: list[dict],
    *,
    area_cap: float = 2.0,
) -> float | None:
    """PURE selector (no I/O) — the testable core.

    ``probe_results`` items: ``{"interval_max": float|None, "area_score":
    float|None, "csim_pass": bool, "csynth_pass": bool}``.

    Returns the chosen target: the LOWEST ``interval_max`` among the baseline
    plus every probe candidate that csim-passes AND csynth-passes AND whose
    ``area_score`` is within ``area_cap * baseline_area_score`` (the baseline
    itself always qualifies at ratio 1.0). If no candidate beats the baseline
    within the area cap, returns the baseline ``interval_max``. If the baseline
    ``interval_max`` is unknown (None), returns None. Never raises.
    """
    baseline = baseline_metrics or {}
    base_iv = _num(baseline.get("interval_max"))
    if base_iv is None:
        # Baseline interval unknown -> the probe can't help; caller falls back.
        return None

    base_area = _num(area_score(baseline)) if baseline else None

    # The baseline always qualifies at its own interval (area ratio 1.0).
    best = base_iv

    for r in probe_results or []:
        try:
            if not (r.get("csim_pass") and r.get("csynth_pass")):
                continue
            iv = _num(r.get("interval_max"))
            if iv is None:
                continue
            # Area cap: only enforce when we have both areas to compare.
            cand_area = _num(r.get("area_score"))
            if base_area is not None and base_area > 0 and cand_area is not None:
                if cand_area > area_cap * base_area:
                    continue
            if iv < best:
                best = iv
        except Exception:
            # Defensive: a malformed result row never breaks selection.
            continue

    return best


def _is_full_unroll(proposal) -> bool:
    """True if a proposal is a FULL UNROLL (the over-parallelization trap).

    RecipeProvider DOES copy the recipe's ``risk_tags`` into the proposal
    (``risk_tags=["recipe", *recipe.risk_tags]``), so the "full" tag is the
    primary signal. We also defensively match the pragma TEXT: a bare
    ``#pragma HLS UNROLL`` with no ``factor=`` is a full unroll regardless of
    tags.
    """
    tags = list(getattr(proposal, "risk_tags", None) or [])
    if "full" in tags:
        return True
    text = getattr(proposal, "whole_file", None) or ""
    # A bare UNROLL with no factor= anywhere is a full unroll. Cheap, defensive.
    if "UNROLL" in text and "factor=" not in text:
        return True
    return False


def derive_throughput_target(
    task,
    *,
    budget,
    csim_backend: str = "gpp",
    synth_backend: str = "vitis_hls",
    max_synth: int = 4,
    area_cap: float = 2.0,
    events: list | None = None,
) -> tuple[float | None, dict]:
    """Run the capped recipe-only probe; return ``(target, probe_log)``.

    Spends csim/csynth via the shared ``budget`` (respects
    ``budget.can``/``budget.policy_allows``); stops at ``max_synth`` APPLIED
    candidates OR budget exhaustion. Builds candidates on a FRESH
    ``CandidateManager(task)``: ``baseline = cm.create_initial()``; each probe
    candidate = ``cm.fork(baseline, f"probe_{i}")`` with ONE recipe proposal's
    ``whole_file`` applied via ``apply_patch`` (the same path run_optimize uses).

    Uses ``RecipeProvider`` ONLY — 0 LLM tokens. Never raises on a probe
    failure: returns ``(baseline_interval_or_None, log)``.
    """
    # Local import to avoid a circular import at module load (agent imports the
    # probe in run_optimize, the probe reuses agent's stage helpers here).
    from . import agent

    log: dict = {
        "objective": getattr(task, "objective", None),
        "max_synth": max_synth,
        "area_cap": area_cap,
        "baseline_interval_max": None,
        "baseline_area_score": None,
        "tried": [],            # one entry per applied probe candidate
        "skipped_full_unroll": [],
        "target": None,
        "fell_back_to_baseline": False,
        "tokens": 0,            # recipe-only path spends ZERO LLM tokens
    }

    try:
        cm = CandidateManager(task)
        baseline = cm.create_initial()

        # --- baseline correctness: must pass csim to mean anything ---
        if not budget.can("csim"):
            log["note"] = "no csim budget for probe baseline"
            return (None, log)
        parsed = agent._run_csim(cm, baseline, task, budget, csim_backend)
        score(baseline)
        if not baseline.csim_pass:
            log["note"] = "probe baseline csim did not pass"
            return (None, log)

        # --- baseline synthesis (the probe owns its own baseline) ---
        allowed, reason = budget.policy_allows(
            "csynth", csim_pass=True, regressed=False, repeated=False)
        if not allowed:
            log["note"] = f"cannot synthesize probe baseline: {reason}"
            return (None, log)
        base_cs = agent._run_csynth(
            cm, baseline, task, budget, synth_backend, events or [])
        score(baseline)
        baseline_metrics = baseline.csynth_metrics
        if base_cs.get("status") == "tool_unavailable":
            log["note"] = "synth tool unavailable — probe cannot derive a target"
            return (None, log)

        base_iv = _num((baseline_metrics or {}).get("interval_max"))
        base_area = _num(area_score(baseline_metrics)) if baseline_metrics else None
        log["baseline_interval_max"] = base_iv
        log["baseline_area_score"] = base_area

        # --- capped single-pragma probe: RecipeProvider, recipe-only ---
        provider = RecipeProvider()
        assert getattr(provider, "last_usage", "x") is None, \
            "probe must be recipe-only (zero LLM tokens)"
        diag = diagnose_csynth(base_cs)          # -> recommended_action optimize_ppa
        sources = cm.sources_dict(baseline)

        probe_results: list[dict] = []
        applied = 0
        i = 0
        history: list[str] = []
        # The provider's worklist is finite; iterate until max_synth applied,
        # budget exhaustion, or the worklist is exhausted (propose -> None).
        while applied < max_synth:
            if not (budget.can("csim") and budget.can("csynth")):
                log["note"] = "probe stopped: budget exhausted"
                break
            proposal = provider.propose(
                cm.task_view(baseline), sources, diag, history)
            # Recipes spend NO tokens; assert the invariant every call.
            assert provider.last_usage is None, \
                "RecipeProvider must not consume LLM tokens"
            if proposal is None:
                break  # worklist exhausted

            # Skip the over-parallelization trap: full unroll.
            if _is_full_unroll(proposal):
                log["skipped_full_unroll"].append(
                    proposal.edit_plan or proposal.target_file)
                continue

            # FRESH fork from the baseline (NOT stacked) + apply ONE proposal.
            child = cm.fork(baseline, f"probe_{i}")
            i += 1
            ar = apply_patch(child.src_dir, proposal)
            if not ar.ok:
                log["tried"].append({
                    "recipe": proposal.edit_plan,
                    "applied": False,
                    "reasons": ar.reasons,
                })
                continue
            applied += 1

            # RE-VERIFY csim (must still pass), then csynth.
            agent._run_csim(cm, child, task, budget, csim_backend)
            csim_ok = bool(child.csim_pass)
            csynth_ok = False
            iv = None
            ar_score = None
            if csim_ok and budget.can("csynth"):
                child_cs = agent._run_csynth(
                    cm, child, task, budget, synth_backend, events or [])
                csynth_ok = bool(child.csynth_pass)
                m = child.csynth_metrics or {}
                iv = _num(m.get("interval_max"))
                ar_score = _num(area_score(m)) if m else None
            score(child)

            row = {
                "interval_max": iv,
                "area_score": ar_score,
                "csim_pass": csim_ok,
                "csynth_pass": csynth_ok,
            }
            probe_results.append(row)
            log["tried"].append({
                "recipe": proposal.edit_plan,
                "candidate": child.candidate_id,
                "applied": True,
                **row,
            })

        # --- choose the target (pure selector) ---
        target = select_target(baseline_metrics, probe_results, area_cap=area_cap)
        log["target"] = target
        # We "fell back" when no probe candidate beat the baseline interval.
        log["fell_back_to_baseline"] = (
            target is not None and base_iv is not None and target >= base_iv)
        return (target, log)

    except Exception as exc:  # noqa: BLE001 — probe NEVER breaks the caller
        # Best-effort: a probe failure degrades to the baseline interval (or
        # None). Report what we know.
        log["error"] = f"{type(exc).__name__}: {exc}"
        fallback = log.get("baseline_interval_max")
        log["target"] = fallback
        log["fell_back_to_baseline"] = fallback is not None
        return (fallback, log)
