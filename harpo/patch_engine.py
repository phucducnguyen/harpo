"""Patch Engine: providers that propose minimal HLS repairs, plus safe
application and interface-contract checking.

A PatchProvider turns (task, current sources, diagnosis, history) into a
PatchProposal (or None). Two providers ship here:

MockProvider   : deterministic string-replacement patcher. No external
                 services — used for tests/demo and as a fallback.
OllamaProvider : best-effort real patcher backed by a LOCAL Ollama server
                 over plain urllib (stdlib only). Never raises — any
                 network/parse failure yields None so the loop degrades.

Application is split from proposal so the control loop can vet a proposal
against the task's interface contract (check_contract) BEFORE writing it.
apply_patch always writes into the candidate's OWN editable src copy — the
caller guarantees this dir is isolated from the original task.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import ApplyResult, Diagnosis, PatchProposal

# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------
@runtime_checkable
class PatchProvider(Protocol):
    """Anything that can propose a patch.

    `sources` maps a path RELATIVE to the candidate src dir (e.g. "vadd.cpp",
    "vadd.h") to that file's full text. `diagnosis` is the current failure
    diagnosis; `history` is the per-step diagnosis-class history this run.
    Return a PatchProposal, or None when the provider can't help.

    `model_id` is the provenance tag recorded in run evidence for every
    propose event (a model name only — never an endpoint URL).
    """

    model_id: str

    def propose(
        self,
        task,
        sources: dict[str, str],
        diagnosis: Diagnosis,
        history: list[str],
    ) -> PatchProposal | None:
        ...


# ---------------------------------------------------------------------------
# MockProvider — deterministic, no external services
# ---------------------------------------------------------------------------
class MockProvider:
    """Deterministic patcher driven by a fixed list of string edits.

    edits = [(target_file, find, replace), ...]. On propose() the first
    target_file present in `sources` whose `find` string is found is patched
    (all such edits for that file are applied), and a PatchProposal carrying
    the patched whole-file contents is returned. Returns None if no edit
    applies — i.e. the file isn't in sources or no `find` string matches.
    """

    def __init__(self, edits: list[tuple[str, str, str]]):
        self.edits = list(edits)
        self.last_usage: dict | None = None  # mock spends no tokens
        self.model_id = "mock"  # provenance tag recorded in run evidence

    def propose(
        self,
        task,
        sources: dict[str, str],
        diagnosis: Diagnosis,
        history: list[str],
    ) -> PatchProposal | None:
        # Group edits by target so a single file gets all its replacements.
        for target_file in dict.fromkeys(e[0] for e in self.edits):
            if target_file not in sources:
                continue
            contents = sources[target_file]
            applied: list[str] = []
            for tf, find, replace in self.edits:
                if tf != target_file:
                    continue
                if find in contents:
                    contents = contents.replace(find, replace)
                    applied.append(f"{find!r} -> {replace!r}")
            if applied:
                return PatchProposal(
                    diagnosis=diagnosis.klass,
                    edit_plan="; ".join(applied),
                    target_file=target_file,
                    whole_file=contents,
                    expected_effect="mock string replacement applied",
                    risk_tags=["mock"],
                )
        return None


# ---------------------------------------------------------------------------
# OllamaProvider — best-effort real patcher over local Ollama (stdlib only)
# ---------------------------------------------------------------------------
_OLLAMA_SYSTEM_PROMPT = (
    "You are a minimal-patch HLS (high-level synthesis) repair agent. "
    "Correctness comes before performance. Make the SMALLEST change that "
    "fixes the reported failure. Do NOT change the top function name, "
    "signature, interface, or argument types, and do NOT edit the testbench. "
    "Keep the code synthesizable: no recursion, no dynamic allocation "
    "(malloc/new), and no unsupported STL in the kernel. "
    "Return ONLY a JSON object with these keys: "
    "target_file (string, relative path of the file you edit), "
    "edit_plan (string, one-line intent), "
    "whole_file (string, the FULL new contents of target_file), "
    "expected_effect (string), "
    "risk_tags (array of strings)."
)

_OLLAMA_OPT_SYSTEM_PROMPT = (
    "You are an HLS (high-level synthesis) performance-optimization agent for "
    "AMD Vitis HLS. The design ALREADY passes C-simulation and is synthesizable. "
    "Your job: improve PPA — lower the loop initiation interval (II), lower "
    "latency, or lower resource usage — WITHOUT changing functional behavior or "
    "numerical results. Prefer HLS pragmas: "
    "#pragma HLS PIPELINE, UNROLL, ARRAY_PARTITION, INLINE, LOOP_FLATTEN, "
    "DATAFLOW, and bind_op/bind_storage; or equivalent loop restructuring.\n"
    "AREA DISCIPLINE — this is the most important rule and the easiest to get "
    "wrong. Candidates are judged lexicographically (throughput first, then "
    "latency, then AREA), so it is tempting to keep piling on parallelism for a "
    "marginally lower latency. DO NOT. Over-parallelizing trades a tiny latency "
    "win for an ORDER-OF-MAGNITUDE area blow-up:\n"
    "- Propose EXACTLY ONE pragma per turn — the single most surgical change that "
    "moves the current bottleneck. NEVER stack multiple aggressive directives at "
    "once (e.g. partition AND pipeline AND unroll all in one turn).\n"
    "- If a loop's II is ALREADY 1, or already meets the throughput target, DO "
    "NOT add more parallelism to it — no `UNROLL`, no extra `PIPELINE`. Adding "
    "`UNROLL` on top of an already-pipelined loop fully spatially unrolls it and "
    "EXPLODES LUT/FF area for little or no throughput gain.\n"
    "- Prefer the MINIMAL area-preserving move that unblocks throughput: a precise "
    "`ARRAY_PARTITION ... cyclic factor=N dim=1` to break a memory-port "
    "bottleneck, then a single `PIPELINE II=1` — NOT partition AND unroll AND "
    "extra pipelines together. Reaching II=1 with one partition + one pipeline is "
    "the goal; a fully-unrolled reduction is a FAILURE even if it is faster.\n"
    "- Once throughput (II) is at target, SHIFT the objective to REDUCING area "
    "(try a smaller/cheaper partition factor) or improving timing — do NOT chase "
    "marginal latency at large area cost. Smaller is better once II=1.\n"
    "- Respect the part's resource ceiling stated in the user message; stay well "
    "under it on every dimension (LUT/FF/BRAM/DSP).\n"
    "ALWAYS write pragmas in their PRECISE, fully-specified form — a vague "
    "pragma silently defaults to the most expensive option and blows up area:\n"
    "- ARRAY_PARTITION: ALWAYS give a type (cyclic or block), a factor=N, AND "
    "dim=N (e.g. `#pragma HLS ARRAY_PARTITION variable=A cyclic factor=4 "
    "dim=1`). Prefer `cyclic` for strided/windowed/interleaved access. NEVER "
    "use `complete` on a large array — it makes one register per element "
    "(huge LUT/FF area, ~10-30x); reserve `complete` for tiny arrays only. "
    "Omitting the type defaults to `complete` — do not omit it.\n"
    "- PIPELINE: name/place it INSIDE the specific loop it applies to; prefer "
    "II=1 (e.g. `#pragma HLS PIPELINE II=1`).\n"
    "- UNROLL: give an explicit factor=N (e.g. `#pragma HLS UNROLL factor=4`) "
    "unless you intend a full unroll of a small fixed-trip loop. Do NOT unroll a "
    "loop that is already pipelined to II=1.\n"
    "Do NOT change the top function name, signature, interface, or argument "
    "types, and do NOT edit the testbench. Keep it synthesizable (no recursion, "
    "no malloc/new, no unsupported STL). Make exactly ONE focused improvement; "
    "keep numerical results IDENTICAL. "
    "Return ONLY a JSON object with these keys: "
    "target_file (string, relative path of the file you edit), "
    "edit_plan (string, one-line intent), "
    "whole_file (string, the FULL new contents of target_file), "
    "expected_effect (string), "
    "risk_tags (array of strings)."
)


class OllamaProvider:
    """Best-effort patcher backed by a local Ollama chat model.

    Reads the endpoint from HARPO_OLLAMA_URL (default
    http://localhost:11434) and the model from HARPO_OLLAMA_MODEL.
    Uses urllib only — no third-party HTTP.
    NEVER raises: any network, decode, parse, or missing-key error returns
    None so the control loop can fall back to another provider.
    """

    def __init__(self, url: str | None = None, model: str | None = None,
                 timeout: float = 180.0):
        self.url = (url or os.environ.get(
            "HARPO_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get(
            "HARPO_OLLAMA_MODEL", "qwen3.6:35b-a3b-q4_K_M")
        self.timeout = timeout
        self.last_usage: dict | None = None
        # Provenance tag recorded in run evidence so committed artifacts prove
        # WHICH model produced each patch (the paper's reproducibility story).
        # Model tag ONLY — never the endpoint URL: run JSONs are published and
        # must stay free of LAN addresses/hostnames.
        self.model_id = self.model

    @staticmethod
    def _resource_ceiling(task) -> str:
        """One-line resource-ceiling hint from task.raw, or '' if unavailable.

        Defensive: task may be None, lack `.raw`, or be missing any of the
        nested keys — every access is guarded and this NEVER raises.
        """
        raw = getattr(task, "raw", None)
        if not isinstance(raw, dict):
            return ""
        constraints = raw.get("constraints")
        if not isinstance(constraints, dict):
            return ""
        target = constraints.get("target")
        part = ""
        if isinstance(target, dict):
            part = str(target.get("part") or target.get("device") or "")
        limits = constraints.get("resource_limits")
        parts: list[str] = []
        if isinstance(limits, dict) and limits:
            label_map = [
                ("lut_pct_max", "LUT"),
                ("ff_pct_max", "FF"),
                ("bram_pct_max", "BRAM"),
                ("dsp_pct_max", "DSP"),
            ]
            for key, name in label_map:
                val = limits.get(key)
                if isinstance(val, (int, float)):
                    parts.append(f"{name}<={val}%")
        if not parts and not part:
            return ""
        ceiling = (
            "Resource ceiling: stay within " + ", ".join(parts)
            if parts
            else "Resource ceiling: stay well within the part's capacity"
        )
        if part:
            ceiling += f" of the part ({part})"
        ceiling += "."
        return ceiling

    def _build_user_prompt(
        self, task, sources: dict[str, str], diagnosis: Diagnosis,
        optimize: bool = False,
    ) -> str:
        top = getattr(task, "top_function", "") if task is not None else ""
        evidence = "\n".join(f"  - {e}" for e in (diagnosis.evidence or []))
        files = "\n\n".join(
            f"=== {name} ===\n{text}" for name, text in sources.items()
        )
        if optimize:
            label = (
                "CURRENT design metrics (II / latency / area for the design as it "
                "stands right now)"
            )
            ceiling = self._resource_ceiling(task)
            hint_lines = [
                "Goal: reach II=1 (or the throughput target) at MINIMUM area. "
                "Make ONE focused optimization that moves the bottleneck shown in "
                "the CURRENT metrics above, while producing IDENTICAL results.",
                "Propose exactly ONE precise HLS pragma — the single most surgical "
                "change. If II is already 1, do NOT add more parallelism: shift to "
                "reducing area (smaller partition factor) or timing instead.",
            ]
            if ceiling:
                hint_lines.append(ceiling)
            hint_lines.append(
                "If you see no safe improvement, still return your best single "
                "attempt."
            )
            hint = "\n".join(hint_lines)
        else:
            label = "Diagnosis evidence"
            hint = (
                "Budget hint: return the smallest change that fixes the current "
                "failure; do not optimize."
            )
        return (
            f"Top function: {top}\n"
            f"Diagnosis class: {diagnosis.klass}\n"
            f"{label}:\n{evidence or '  (none)'}\n\n"
            f"Current source files:\n{files}\n\n"
            f"{hint}"
        )

    def propose(
        self,
        task,
        sources: dict[str, str],
        diagnosis: Diagnosis,
        history: list[str],
    ) -> PatchProposal | None:
        self.last_usage = None
        optimize = diagnosis.recommended_action == "optimize_ppa"
        system = _OLLAMA_OPT_SYSTEM_PROMPT if optimize else _OLLAMA_SYSTEM_PROMPT
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",
                     "content": self._build_user_prompt(
                         task, sources, diagnosis, optimize=optimize)},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }
            req = urllib.request.Request(
                f"{self.url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
            envelope = json.loads(raw)
            self.last_usage = {
                "prompt_tokens": envelope.get("prompt_eval_count"),
                "completion_tokens": envelope.get("eval_count"),
                "total_tokens": (envelope.get("prompt_eval_count") or 0)
                + (envelope.get("eval_count") or 0),
            }
            content = envelope["message"]["content"]
            data = json.loads(content)
            target = data.get("target_file")
            if not target:
                # Lenient: if the model omitted the target but there's exactly
                # one source file, assume it.
                cpps = [n for n in sources
                        if n.endswith((".cpp", ".cc", ".cxx", ".c"))]
                target = cpps[0] if len(cpps) == 1 else None
            if not target:
                return None
            return PatchProposal(
                diagnosis=diagnosis.klass,
                edit_plan=str(data.get("edit_plan", "")),
                target_file=str(target),
                whole_file=data.get("whole_file"),
                expected_effect=str(data.get("expected_effect", "")),
                risk_tags=list(data.get("risk_tags", [])),
            )
        except Exception:
            # Best-effort: degrade to None, never break the loop.
            return None


# ---------------------------------------------------------------------------
# Interface-contract checking
# ---------------------------------------------------------------------------
def _extract_param_count(source: str, func_name: str) -> int | None:
    """Heuristically count the parameters of `func_name` in a C/C++ source.

    Finds `func_name(`, matches the balanced closing paren, and counts
    top-level commas (ignoring those nested in <...>, (...), [...], {...}).
    Returns the parameter count, or None if the function or a balanced
    parameter list can't be located (signal "unknown — do not reject").
    """
    needle = func_name + "("
    idx = source.find(needle)
    while idx != -1:
        open_paren = idx + len(needle) - 1
        # Find the matching close paren.
        depth = 0
        params = ""
        closed = False
        for ch in source[open_paren:]:
            if ch == "(":
                depth += 1
                if depth == 1:
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    closed = True
                    break
            params += ch
        if not closed:
            return None
        params = params.strip()
        if params == "" or params == "void":
            return 0
        # Count top-level commas.
        depth = 0
        count = 1
        for ch in params:
            if ch in "<([{":
                depth += 1
            elif ch in ">)]}":
                depth -= 1
            elif ch == "," and depth == 0:
                count += 1
        return count
    return None


def check_contract(
    task, proposal: PatchProposal, new_contents: str,
) -> tuple[bool, list[str]]:
    """Vet a proposal against the task's interface contract / edit policy.

    Returns (ok, reasons). Rejects when:
      * the target is a testbench file and edits to it aren't allowed;
      * the target doesn't match any allowed edit glob;
      * the top function's signature (parameter count) changed while
        allow_top_signature_change is False.

    The signature check is conservative: it only fires on a POSITIVELY
    detected change. If the original file can't be found or either source
    can't be parsed reliably, the check is skipped rather than rejecting.
    """
    reasons: list[str] = []
    policy = getattr(task, "policy", {}) or {}
    target = proposal.target_file

    # 1) Testbench protection.
    tb_names = {Path(p).name for p in getattr(task, "tb_files", []) or []}
    if Path(target).name in tb_names and not policy.get(
        "allow_testbench_edits", False
    ):
        reasons.append(f"testbench edits not allowed: {target}")

    # 2) Allowed-edit globs (lenient: match "src/<name>" and bare "<name>").
    globs = policy.get("allowed_edit_globs", ["src/**"])
    bare = Path(target).name
    candidates = {target, bare, f"src/{bare}", f"src/{target}"}
    if not any(
        fnmatch.fnmatch(c, g) for c in candidates for g in globs
    ):
        reasons.append(
            f"target {target} not in allowed_edit_globs {globs}"
        )

    # 3) Top-function signature preservation.
    if not policy.get("allow_top_signature_change", False):
        top = getattr(task, "top_function", "") or ""
        if top:
            if top not in new_contents:
                reasons.append(
                    f"top function {top!r} missing from patched file"
                )
            else:
                src_dir = getattr(task, "src_dir", None)
                orig_path = Path(src_dir) / target if src_dir else None
                if orig_path is not None and orig_path.exists():
                    try:
                        original = orig_path.read_text()
                    except OSError:
                        original = None
                    if original is not None:
                        old_n = _extract_param_count(original, top)
                        new_n = _extract_param_count(new_contents, top)
                        # Only reject on a positively detected change.
                        if (old_n is not None and new_n is not None
                                and old_n != new_n):
                            reasons.append(
                                f"top function {top!r} parameter count changed "
                                f"{old_n} -> {new_n}"
                            )

    return (len(reasons) == 0, reasons)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def apply_patch(
    candidate_src_dir: Path, proposal: PatchProposal,
) -> ApplyResult:
    """Write a vetted proposal into the candidate's own editable src dir.

    Prefers whole_file (robust). Falls back to a unified diff applied via
    `git apply` then `patch -p0`. The caller guarantees candidate_src_dir is
    an isolated copy, never the original task source.
    """
    candidate_src_dir = Path(candidate_src_dir)

    if proposal.whole_file is not None:
        dest = candidate_src_dir / proposal.target_file
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(proposal.whole_file)
        return ApplyResult(
            ok=True, method="whole_file", file=proposal.target_file,
        )

    if proposal.patch_unified_diff:
        for cmd in (["git", "apply", "-"], ["patch", "-p0"]):
            try:
                proc = subprocess.run(
                    cmd,
                    input=proposal.patch_unified_diff,
                    text=True,
                    capture_output=True,
                    cwd=str(candidate_src_dir),
                )
                if proc.returncode == 0:
                    return ApplyResult(
                        ok=True, method="unified_diff",
                        file=proposal.target_file,
                    )
            except (OSError, FileNotFoundError):
                continue
        return ApplyResult(
            ok=False, method="none", reasons=["diff did not apply"],
        )

    return ApplyResult(ok=False, method="none", reasons=["empty proposal"])
