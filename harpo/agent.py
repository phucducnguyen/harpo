"""Agent control loop — the closed-loop repair + optimize drivers (ForgeLoop).

run_repair() drives correctness, under the BudgetManager:

    csim -> parse -> diagnose -> (if fail) propose patch -> contract-check ->
    fork candidate -> apply patch -> repeat

run_optimize() drives PPA once correctness holds:

    [baseline csim+csynth] -> diagnose_csynth -> propose pragma/restructure ->
    contract-check -> fork -> apply -> RE-VERIFY csim (must still pass) ->
    csynth -> keep iff the lexicographic score improved -> repeat

The hard invariant of the optimize loop: an optimization is accepted ONLY if it
keeps csim correct AND improves the score. Every step is recorded as a
replayable event for the Track-A workflow/token account.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

from . import store
from .budget import BudgetManager
from .candidate import CandidateManager, best, score, score_measured
from .diagnosis import diagnose, diagnose_csynth
from .parser import parse_csim, parse_csynth, parse_impl
from .patch_engine import apply_patch, check_contract
from .runner import run_stage
from .task import TaskContext


def _event(events: list[dict], msg: str, **kw) -> None:
    kw["msg"] = msg
    events.append(kw)
    print(f"  · {msg}")


def _provider_errors(providers: list) -> dict | None:
    """Per-provider failure reasons from the last propose() round, for the
    stop event — so a run log can say WHY no proposal was produced."""
    errs = {type(p).__name__: getattr(p, "last_error", None) for p in providers}
    return {k: v for k, v in errs.items() if v} or None


def run_repair(task: TaskContext, providers: list, *, backend: str = "gpp",
               max_steps: int = 12, budget: BudgetManager | None = None) -> dict:
    # A caller may thread in a shared BudgetManager (e.g. run_pipeline, so repair
    # and optimize draw from ONE per-task tool budget); default to a fresh one.
    budget = budget or BudgetManager(task.budget)
    cm = CandidateManager(task)
    cand = cm.create_initial()
    candidates = [cand]
    history: list[str] = []
    events: list[dict] = []
    tokens_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    step = 0
    prev_pass = False

    while step < max_steps and not budget.exhausted():
        step += 1

        # --- run csim on the current candidate ---
        allowed, reason = budget.policy_allows(
            "csim", csim_pass=cand.csim_pass, regressed=False, repeated=False)
        if not allowed:
            _event(events, f"stop before csim: {reason}", event="stop")
            break

        raw = run_stage(cm.task_view(cand), "csim", cand.workdir, backend=backend)
        budget.spend("csim")
        parsed = parse_csim(raw)
        store.write_run(task.task_id, cand.candidate_id, raw, parsed)
        cand.csim_status = parsed["status"]
        cand.csim_pass = bool(parsed["pass"])
        score(cand)

        diag = diagnose(parsed, history)
        cand.diagnosis_history.append(diag.klass)
        history.append(diag.klass)
        _event(events, f"{cand.candidate_id}: csim {parsed['status']} -> {diag.klass}",
               event="csim", candidate=cand.candidate_id,
               status=parsed["status"], diagnosis=diag.klass)

        if cand.csim_pass:
            _event(events, f"{cand.candidate_id}: csim PASS — repaired",
                   event="success", candidate=cand.candidate_id)
            break
        if parsed["status"] == "tool_unavailable":
            _event(events, "tool unavailable; cannot proceed", event="stop")
            break

        regressed = prev_pass and not cand.csim_pass
        prev_pass = cand.csim_pass

        # --- a fix is needed: gate on budget/policy ---
        allowed, reason = budget.policy_allows(
            "llm_calls", csim_pass=cand.csim_pass,
            regressed=regressed, repeated=diag.repeated)
        if not allowed:
            _event(events, f"stop before patch: {reason}", event="stop")
            break

        # --- ask providers (in order) for one minimal patch ---
        sources = cm.sources_dict(cand)
        proposal = None
        for prov in providers:
            if not budget.can("llm_calls"):
                break
            proposal = prov.propose(cm.task_view(cand), sources, diag, history)
            budget.spend("llm_calls")
            if proposal:
                usage = getattr(prov, "last_usage", None) or {}
                for k in tokens_total:
                    tokens_total[k] += usage.get(k) or 0
                _event(events,
                       f"proposal from {type(prov).__name__}: {proposal.edit_plan}",
                       event="propose", provider=type(prov).__name__,
                       model=prov.model_id,
                       target=proposal.target_file, tokens=usage or None)
                break
        if not proposal:
            _event(events, "no provider produced a patch", event="stop",
                   provider_errors=_provider_errors(providers))
            break

        # --- contract check before spending a tool call on it ---
        new_contents = proposal.whole_file or ""
        ok, reasons = check_contract(cm.task_view(cand), proposal, new_contents)
        if not ok:
            _event(events, f"contract rejected patch: {reasons}",
                   event="reject", reasons=reasons)
            break

        # --- fork an isolated candidate and apply ---
        child = cm.fork(cand, f"cand_{step:04d}")
        ar = apply_patch(child.src_dir, proposal)
        if not ar.ok:
            _event(events, f"patch did not apply: {ar.reasons}",
                   event="apply_fail", reasons=ar.reasons)
            break
        _event(events, f"applied via {ar.method} -> {child.candidate_id}",
               event="apply", candidate=child.candidate_id, method=ar.method)
        candidates.append(child)
        cand = child

    winner = best(candidates)
    result = {
        "task_id": task.task_id,
        "steps": step,
        "repaired": bool(winner and winner.csim_pass),
        "best_candidate": winner.candidate_id if winner else None,
        "budget": budget.snapshot(),
        "tokens": tokens_total,
        "events": events,
        "candidates": [c.to_dict() for c in candidates],
    }
    log_path = store.runs_dir_for(task.task_id) / "repair_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(result, indent=2))
    result["log_path"] = str(log_path)
    return result


# ---------------------------------------------------------------------------
# Optimization loop (PPA) — correctness-preserving
# ---------------------------------------------------------------------------
def _accum_tokens(total: dict, usage: dict | None) -> None:
    for k in total:
        total[k] += (usage or {}).get(k) or 0


def _delta(before: dict | None, after: dict | None) -> str:
    """Compact human-readable PPA delta for the event log."""
    b, a = before or {}, after or {}
    parts = []
    for key, label in (("ii", "II"), ("latency_worst", "lat"),
                       ("lut", "LUT"), ("ff", "FF"), ("fmax_mhz", "Fmax")):
        bv, av = b.get(key), a.get(key)
        if bv != av:
            parts.append(f"{label} {bv}->{av}")
    return ", ".join(parts) or "no metric change"


def _run_csynth(cm: CandidateManager, cand, task: TaskContext,
                budget: BudgetManager, backend: str, events: list[dict]) -> dict:
    """Synthesize one candidate: spend budget, parse, record on the candidate."""
    raw = run_stage(cm.task_view(cand), "csynth", cand.workdir, backend=backend)
    budget.spend("csynth")
    cs = parse_csynth(raw)
    store.write_run(task.task_id, cand.candidate_id, raw, cs, stage="csynth")
    cand.csynth_status = cs["status"]
    cand.csynth_pass = bool(cs["pass"])
    cand.csynth_metrics = cs.get("metrics")
    m = cs.get("metrics") or {}
    tail = (f" II={m.get('ii')} lat={m.get('latency_worst')} "
            f"LUT={m.get('lut')} Fmax={m.get('fmax_mhz')}") if m else ""
    _event(events, f"{cand.candidate_id}: csynth {cs['status']}{tail}",
           event="csynth", candidate=cand.candidate_id,
           status=cs["status"], metrics=cs.get("metrics"))
    return cs


def _run_impl(cm: CandidateManager, cand, task: TaskContext,
              budget: BudgetManager, backend: str, events: list[dict]) -> dict:
    """Post-route-implement one candidate: spend budget, parse, record.

    Measured metrics go on ``cand.impl_metrics`` — NEVER onto csynth_metrics,
    so the estimate-vs-measured trail survives as evidence. The impl report
    carries no latency/II data, so those fields are carried over from the
    candidate's csynth metrics and tagged latency_source="csynth".
    """
    raw = run_stage(cm.task_view(cand), "impl", cand.workdir, backend=backend)
    budget.spend("impl")
    ip = parse_impl(raw)
    store.write_run(task.task_id, cand.candidate_id, raw, ip, stage="impl")
    cand.impl_status = ip["status"]
    cand.impl_pass = bool(ip["pass"])
    m = ip.get("metrics")
    if m is not None:
        cs = cand.csynth_metrics or {}
        for k in ("latency_best", "latency_worst", "interval_min",
                  "interval_max", "ii", "depth", "trip_count"):
            if m.get(k) is None and cs.get(k) is not None:
                m[k] = cs[k]
        m["latency_source"] = "csynth"
    cand.impl_metrics = m
    est = (cand.csynth_metrics or {}).get("lut")
    tail = (f" LUT={m.get('lut')} (csynth est {est}) "
            f"CP={m.get('clock_estimated_ns')}ns") if m else ""
    _event(events, f"{cand.candidate_id}: impl {ip['status']}{tail}",
           event="impl_verify", candidate=cand.candidate_id,
           status=ip["status"], metrics=m,
           metrics_estimate=cand.csynth_metrics)
    return ip


def _impl_verify_stage(cm: CandidateManager, task: TaskContext,
                       budget: BudgetManager, backend: str,
                       candidates: list, events: list[dict],
                       top_k: int) -> list:
    """Measured-fidelity verification rung, run AFTER the optimize loop.

    csynth estimates carry real error (measured 2.4x pessimistic on LUTs on
    the LNS MAC — and the tool guarantees no direction), so before declaring a
    winner the top-K candidates by estimate score PLUS the baseline get a real
    Vivado post-route run. Returns the verified candidates (impl attempted).
    Fail-open by design: tool unavailable / budget exhausted just ends the
    rung — the caller falls back to the estimate winner.
    """
    eligible = [c for c in candidates if c.csim_pass and c.csynth_pass]
    if not eligible:
        _event(events, "impl-verify: no csim+csynth-passing candidates to verify",
               event="impl_verify_skip")
        return []
    pool = sorted(eligible, key=score, reverse=True)[:top_k]
    baseline = candidates[0]
    if baseline in eligible and baseline not in pool:
        pool.append(baseline)  # the 'improved' comparison needs the baseline
    #                            measured at the same fidelity as the winner

    verified: list = []
    for cand in pool:
        allowed, reason = budget.policy_allows(
            "impl", csim_pass=cand.csim_pass, regressed=False, repeated=False)
        if not allowed:
            _event(events, f"impl-verify stops: {reason}", event="stop")
            break
        ip = _run_impl(cm, cand, task, budget, backend, events)
        if ip["status"] == "tool_unavailable":
            _event(events, "impl backend unavailable — falling back to "
                   "estimate-based winner", event="stop")
            break
        verified.append(cand)
    return verified


def _run_csim(cm: CandidateManager, cand, task: TaskContext,
              budget: BudgetManager, backend: str) -> dict:
    raw = run_stage(cm.task_view(cand), "csim", cand.workdir, backend=backend)
    budget.spend("csim")
    parsed = parse_csim(raw)
    store.write_run(task.task_id, cand.candidate_id, raw, parsed, stage="csim")
    cand.csim_status = parsed["status"]
    cand.csim_pass = bool(parsed["pass"])
    return parsed


def _optimize_result(task, candidates, events, tokens, budget,
                     baseline, steps, verified=None) -> dict:
    # The estimate-based winner is ALWAYS computed; when an impl-verify rung
    # ran it becomes the recorded comparison point (did ground truth pick a
    # different winner than the estimates?) rather than the final answer.
    winner_estimate = best(candidates)
    base = candidates[0]
    routed = [c for c in (verified or []) if c.impl_pass]
    if routed:
        # All members of `routed` carry measured impl_metrics, so this max()
        # compares at ONE fidelity — never measured-vs-estimate.
        winner = max(routed, key=score_measured)
        winner_fidelity = "post_route"
        if base.impl_pass:
            improved = (winner.candidate_id != base.candidate_id
                        and score_measured(winner) > score_measured(base))
        else:
            # The baseline failed to route/fit at measured fidelity while the
            # winner passed — an improvement in itself (the LNS MAC baseline
            # was exactly this: 168% LUT estimate, unroutable).
            improved = winner.candidate_id != base.candidate_id
    else:
        winner = winner_estimate
        winner_fidelity = "csynth_estimate"
        # 'improved' = winner is a descendant that beat the baseline candidate.
        improved = bool(
            winner and winner.candidate_id != base.candidate_id
            and winner.score > base.score
        )

    result = {
        "task_id": task.task_id,
        "phase": "optimize",
        "steps": steps,
        "baseline_metrics": baseline,
        "best_candidate": winner.candidate_id if winner else None,
        "best_metrics": winner.csynth_metrics if winner else None,
        "winner_fidelity": winner_fidelity,
        "best_candidate_estimate": (
            winner_estimate.candidate_id if winner_estimate else None),
        "best_impl_metrics": winner.impl_metrics if winner else None,
        "improved": improved,
        "budget": budget.snapshot(),
        "tokens": tokens,
        "events": events,
        "candidates": [c.to_dict() for c in candidates],
    }
    log_path = store.runs_dir_for(task.task_id) / "optimize_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(result, indent=2))
    result["log_path"] = str(log_path)
    return result


def run_optimize(task: TaskContext, providers: list, *, csim_backend: str = "gpp",
                 synth_backend: str = "vitis_hls", max_steps: int = 8,
                 patience: int = 2, budget: BudgetManager | None = None,
                 seed_src_dir: str | Path | None = None,
                 impl_verify: int | None = None,
                 impl_backend: str = "vitis_hls") -> dict:
    """Improve PPA of an already-correct design, never breaking correctness.

    Establishes a csim+csynth baseline, then iterates: propose one optimization,
    apply it to a forked candidate, RE-VERIFY csim, re-synthesize, and keep the
    child only if its lexicographic score strictly improves. Stops on budget,
    ``max_steps``, or ``patience`` consecutive non-improvements.

    ``budget`` lets a caller (e.g. run_pipeline) thread ONE shared per-task tool
    budget across repair+optimize; default is a fresh one. ``seed_src_dir``, when
    given, overlays that directory's files onto the baseline candidate's source
    copy so the optimizer baselines the REPAIRED code rather than the original.

    ``impl_verify`` (multi-fidelity rung): when > 0, the loop still explores on
    cheap csynth estimates, but afterwards the top-K candidates + the baseline
    are post-route-implemented and the winner is picked from MEASURED PPA
    (estimate winner recorded alongside). None defers to the task's
    ``impl_verify_top_k`` (constraints.json); 0 forces the rung off.
    """
    budget = budget or BudgetManager(task.budget)
    events: list[dict] = []

    # --- derive a throughput_target when the spec omits one ---------------
    # satisfice_then_area / pareto_report rank by "meet an interval_max ceiling,
    # then minimize area" — useless without a target. When the spec leaves one
    # unset, derive a defensible ceiling with the recipe-only probe (ZERO LLM
    # tokens) BEFORE the working CandidateManager is built, so the candidates
    # below inherit the derived target. The probe runs on the SAME shared budget
    # (its tool calls are honestly accounted) and does an EXTRA baseline synth —
    # acceptable, and only on no-target tasks (it is skipped when a target is
    # already set). It never raises.
    if task.throughput_target is None and task.objective in (
        "satisfice_then_area", "pareto_report"
    ):
        from .probe import derive_throughput_target
        target, probe_log = derive_throughput_target(
            task, budget=budget, csim_backend=csim_backend,
            synth_backend=synth_backend, events=events)
        task = dataclasses.replace(task, throughput_target=target)
        _event(events, f"probe-derived throughput_target={target}",
               event="probe", target=target, probe_log=probe_log)

    cm = CandidateManager(task)
    cand = cm.create_initial()
    if seed_src_dir is not None:
        # Overlay the repaired source over the fresh original copy so the
        # baseline csim+csynth measures the repaired design (mirrors the
        # file-by-file copy in candidate.py).
        seed = Path(seed_src_dir)
        for f in sorted(seed.iterdir()):
            if f.is_file():
                shutil.copy2(f, cand.src_dir / f.name)
    candidates = [cand]
    history: list[str] = []
    tokens_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # --- baseline correctness: must pass csim to be worth optimizing ---
    parsed = _run_csim(cm, cand, task, budget, csim_backend)
    score(cand)
    _event(events, f"{cand.candidate_id}: baseline csim {parsed['status']}",
           event="csim", candidate=cand.candidate_id, status=parsed["status"])
    if not cand.csim_pass:
        _event(events, "baseline csim does not pass — run `repair` first",
               event="stop")
        return _optimize_result(task, candidates, events, tokens_total, budget,
                                baseline=None, steps=0)

    # --- baseline synthesis ---
    allowed, reason = budget.policy_allows("csynth", csim_pass=True,
                                           regressed=False, repeated=False)
    if not allowed:
        _event(events, f"cannot synthesize baseline: {reason}", event="stop")
        return _optimize_result(task, candidates, events, tokens_total, budget,
                                baseline=None, steps=0)
    cur_cs = _run_csynth(cm, cand, task, budget, synth_backend, events)
    score(cand)
    baseline_metrics = cand.csynth_metrics
    if cur_cs["status"] == "tool_unavailable":
        _event(events, "vitis_hls unavailable — cannot optimize", event="stop")
        return _optimize_result(task, candidates, events, tokens_total, budget,
                                baseline=baseline_metrics, steps=0)

    best_cand = cand
    no_improve = 0
    step = 0
    tried: list[str] = []   # optimizations that did NOT improve — feed back so
    #                         the patcher diversifies instead of repeating itself
    while step < max_steps and no_improve < patience:
        step += 1

        allowed, reason = budget.policy_allows("llm_calls", csim_pass=True,
                                               regressed=False, repeated=False)
        if not allowed:
            _event(events, f"stop before patch: {reason}", event="stop")
            break

        diag = diagnose_csynth(cur_cs, history)
        history.append(diag.klass)
        if tried:
            diag.evidence.append(
                "Already attempted with NO improvement (try a DIFFERENT knob, "
                "e.g. ARRAY_PARTITION / UNROLL / DATAFLOW, not these): "
                + " | ".join(tried[-5:]))

        # --- ask providers for one optimization ---
        sources = cm.sources_dict(best_cand)
        proposal = None
        for prov in providers:
            if not budget.can("llm_calls"):
                break
            proposal = prov.propose(cm.task_view(best_cand), sources, diag, history)
            budget.spend("llm_calls")
            if proposal:
                usage = getattr(prov, "last_usage", None) or {}
                _accum_tokens(tokens_total, usage)
                _event(events,
                       f"opt proposal from {type(prov).__name__}: {proposal.edit_plan}",
                       event="propose", provider=type(prov).__name__,
                       model=prov.model_id,
                       target=proposal.target_file, tokens=usage or None)
                break
        if not proposal:
            _event(events, "no provider produced an optimization", event="stop",
                   provider_errors=_provider_errors(providers))
            break

        new_contents = proposal.whole_file or ""
        ok, reasons = check_contract(cm.task_view(best_cand), proposal, new_contents)
        if not ok:
            _event(events, f"contract rejected: {reasons}",
                   event="reject", reasons=reasons)
            tried.append(proposal.edit_plan or "(unnamed)")
            no_improve += 1
            continue

        child = cm.fork(best_cand, f"cand_{step:04d}")
        ar = apply_patch(child.src_dir, proposal)
        if not ar.ok:
            _event(events, f"patch did not apply: {ar.reasons}",
                   event="apply_fail", reasons=ar.reasons)
            tried.append(proposal.edit_plan or "(unnamed)")
            no_improve += 1
            continue
        candidates.append(child)

        # --- INVARIANT: re-verify correctness before trusting the metrics ---
        if not budget.can("csim"):
            _event(events, "out of csim budget to verify optimization",
                   event="stop")
            break
        c_parsed = _run_csim(cm, child, task, budget, csim_backend)
        if not child.csim_pass:
            score(child)
            _event(events,
                   f"{child.candidate_id}: optimization BROKE csim "
                   f"({c_parsed['status']}) — discarded",
                   event="regression", candidate=child.candidate_id)
            tried.append(f"{proposal.edit_plan or '(unnamed)'} [broke csim]")
            no_improve += 1
            continue

        # --- measure PPA and keep only if the score strictly improves ---
        allowed, reason = budget.policy_allows("csynth", csim_pass=True,
                                               regressed=False, repeated=False)
        if not allowed:
            score(child)
            _event(events, f"cannot synthesize {child.candidate_id}: {reason}",
                   event="stop")
            break
        child_cs = _run_csynth(cm, child, task, budget, synth_backend, events)

        if score(child) > score(best_cand):
            _event(events,
                   f"{child.candidate_id}: IMPROVED "
                   f"({_delta(best_cand.csynth_metrics, child.csynth_metrics)}) — kept",
                   event="accept", candidate=child.candidate_id,
                   metrics=child.csynth_metrics)
            best_cand = child
            cur_cs = child_cs
            no_improve = 0
        else:
            _event(events,
                   f"{child.candidate_id}: no score improvement "
                   f"({_delta(best_cand.csynth_metrics, child.csynth_metrics)}) — discarded",
                   event="reject_ppa", candidate=child.candidate_id,
                   metrics=child.csynth_metrics)
            tried.append(proposal.edit_plan or "(unnamed)")
            no_improve += 1

    top_k = task.impl_verify_top_k if impl_verify is None else max(0, impl_verify)
    verified: list = []
    if top_k > 0:
        _event(events,
               f"impl-verify: post-route measuring top-{top_k} + baseline",
               event="impl_verify_start", top_k=top_k)
        verified = _impl_verify_stage(cm, task, budget, impl_backend,
                                      candidates, events, top_k)

    return _optimize_result(task, candidates, events, tokens_total, budget,
                            baseline=baseline_metrics, steps=step,
                            verified=verified)


# ---------------------------------------------------------------------------
# Pipeline — chain repair -> optimize under ONE shared per-task budget
# ---------------------------------------------------------------------------
def run_pipeline(task: TaskContext, repair_providers: list,
                 optimize_providers: list, *, repair_backend: str = "gpp",
                 csim_backend: str = "gpp", synth_backend: str = "vitis_hls",
                 max_repair_steps: int = 12, max_optimize_steps: int = 8,
                 patience: int = 2, impl_verify: int | None = None) -> dict:
    """Run repair, then (only if repaired) optimize, sharing ONE tool budget.

    The whole point of Track A is a strict per-task tool-invocation budget, so a
    single ``BudgetManager`` is threaded through both phases — repair's csim/llm
    spend is debited from the same account optimize then draws on, never two
    independent budgets. Optimize baselines the repaired winner's source (via
    ``seed_src_dir``) so it improves the FIXED design, not the broken original.
    Skips optimize entirely if repair fails. Writes the combined result to
    ``runs/<task>/pipeline_log.json``.
    """
    budget = BudgetManager(task.budget)
    print(f"=== pipeline {task.task_id}: REPAIR phase ===")
    rep = run_repair(task, repair_providers, backend=repair_backend,
                     max_steps=max_repair_steps, budget=budget)

    def _combined(opt: dict | None) -> dict:
        rep_tok = rep.get("tokens", {})
        opt_tok = (opt or {}).get("tokens", {})
        tokens = {k: rep_tok.get(k, 0) + opt_tok.get(k, 0)
                  for k in set(rep_tok) | set(opt_tok)}
        result = {
            "task_id": task.task_id,
            "repaired": bool(rep["repaired"]),
            "improved": bool(opt and opt.get("improved")),
            "repair": rep,
            "optimize": opt,
            "budget": budget.snapshot(),
            "tokens": tokens,
        }
        log_path = store.runs_dir_for(task.task_id) / "pipeline_log.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(result, indent=2))
        result["log_path"] = str(log_path)
        return result

    if not rep["repaired"]:
        print(f"=== pipeline {task.task_id}: repair FAILED — skipping optimize ===")
        return _combined(None)

    # Optimize starting from the repaired winner's source copy, on the SAME budget.
    seed = store.candidate_dir(task.task_id, rep["best_candidate"]) / "src"
    print(f"=== pipeline {task.task_id}: OPTIMIZE phase (seed={seed}) ===")
    opt = run_optimize(task, optimize_providers, csim_backend=csim_backend,
                       synth_backend=synth_backend, max_steps=max_optimize_steps,
                       patience=patience, budget=budget, seed_src_dir=seed,
                       impl_verify=impl_verify)
    return _combined(opt)
