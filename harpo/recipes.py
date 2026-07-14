"""Recipe library: canonical, PRECISE HLS pragmas + a deterministic provider.

The local LLM optimizer is fluent but imprecise — it loves to emit forms like
``#pragma HLS ARRAY_PARTITION variable=in factor=8`` with NO partition TYPE,
which Vitis defaults to ``complete`` and detonates area, or it pipelines the
wrong loop. This module is the antidote: a fixed catalogue of well-formed,
correct-by-construction pragma recipes plus a ``RecipeProvider`` that proposes
them ONE at a time, in a sensible priority order, by simple robust text
scanning of the kernel — no model, no tokens, no malformed C.

It is shaped exactly like the providers in ``patch_engine`` (``MockProvider`` /
``OllamaProvider``): ``propose(self, task, sources, diagnosis, history) ->
PatchProposal | None`` and a ``self.last_usage`` attribute (always ``None`` —
recipes spend no LLM tokens). The SAME instance is reused across optimize-loop
iterations, so the worklist cursor lives on ``self`` and advances per call.

Insertion is purely textual and conservative: a recipe that can't find a sane
anchor is skipped, never forced — so the emitted ``whole_file`` is always valid
C++. Validate offline with ``scripts/selftest_recipes.py`` (g++ -fsyntax-only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import PatchProposal

# ---------------------------------------------------------------------------
# Recipe — one canonical, precise pragma
# ---------------------------------------------------------------------------
# `kind` selects the insertion strategy used by RecipeProvider:
#   "loop"     -> after a `for (...) {` header (which loop chosen per recipe)
#   "array"    -> after the top function's opening `{`, naming an array PARAM
#   "function" -> after the top function's opening `{`, no array needed
@dataclass(frozen=True)
class Recipe:
    """A single, well-formed HLS pragma and where it belongs.

    `pragma_template` is a format string. For loop/function recipes it takes no
    fields. For array recipes it takes a single ``{var}`` field filled in with a
    concrete array parameter name parsed from the top-function signature.
    `loop_pos` ("outer"|"inner") only applies when kind == "loop": which loop in
    the top function to anchor on. `priority` orders the worklist (low first).
    """

    name: str
    kind: str                 # "loop" | "array" | "function"
    pragma_template: str      # e.g. "#pragma HLS ARRAY_PARTITION variable={var} cyclic factor=8 dim=1"
    rationale: str
    priority: int
    loop_pos: str = "outer"   # only meaningful for kind == "loop"
    risk_tags: list[str] = field(default_factory=list)

    def render(self, var: str | None = None) -> str:
        """The literal pragma line (no leading indentation)."""
        return self.pragma_template.format(var=var or "")


# ---------------------------------------------------------------------------
# The canonical catalogue — precise forms only.
# ---------------------------------------------------------------------------
# Ordering note: cyclic ARRAY_PARTITION on the kernel input(s) tends to be the
# enabling move for a pipelined/unrolled loop (it removes the memory-port
# bottleneck), so partitions come first, then PIPELINE on the outer loop, then
# UNROLL on the inner loop, then the lower-priority structural pragmas.
#
# ARRAY_PARTITION recipes are EXPANDED per array parameter at proposal time, so
# here we keep one template per (type, factor) and let the provider apply it to
# each array param it parses out of the signature. We deliberately prefer
# `cyclic` for strided/windowed access (the mac8 `in[i*8+k]` pattern) and offer
# a couple of factors; `block` is the contiguous-chunk alternative.
RECIPES: tuple[Recipe, ...] = (
    # --- arrays: cyclic (strided/windowed access — preferred) ---
    Recipe(
        name="array_partition_cyclic_8",
        kind="array",
        pragma_template="#pragma HLS ARRAY_PARTITION variable={var} cyclic factor=8 dim=1",
        rationale="Cyclic partition (factor 8) gives 8 parallel ports for "
                  "strided/windowed access — the classic enabler for a "
                  "pipelined/unrolled loop without going fully `complete`.",
        priority=10,
        risk_tags=["array_partition", "cyclic", "area"],
    ),
    Recipe(
        name="array_partition_cyclic_4",
        kind="array",
        pragma_template="#pragma HLS ARRAY_PARTITION variable={var} cyclic factor=4 dim=1",
        rationale="Cyclic partition (factor 4) — fewer ports, less area than "
                  "factor 8; a moderate-parallelism point.",
        priority=11,
        risk_tags=["array_partition", "cyclic", "area"],
    ),
    Recipe(
        name="array_partition_cyclic_2",
        kind="array",
        pragma_template="#pragma HLS ARRAY_PARTITION variable={var} cyclic factor=2 dim=1",
        rationale="Cyclic partition (factor 2) — cheapest cyclic point.",
        priority=12,
        risk_tags=["array_partition", "cyclic", "area"],
    ),
    # --- arrays: block (contiguous-chunk access — alternative) ---
    Recipe(
        name="array_partition_block_4",
        kind="array",
        pragma_template="#pragma HLS ARRAY_PARTITION variable={var} block factor=4 dim=1",
        rationale="Block partition (factor 4) for contiguous-chunk access "
                  "patterns where neighbours land in the same sub-array.",
        priority=20,
        risk_tags=["array_partition", "block", "area"],
    ),
    Recipe(
        name="array_partition_block_2",
        kind="array",
        pragma_template="#pragma HLS ARRAY_PARTITION variable={var} block factor=2 dim=1",
        rationale="Block partition (factor 2) — cheapest block point.",
        priority=21,
        risk_tags=["array_partition", "block", "area"],
    ),
    # --- loops: pipeline the OUTER loop (II=1) ---
    Recipe(
        name="pipeline_outer_ii1",
        kind="loop",
        pragma_template="#pragma HLS PIPELINE II=1",
        rationale="Pipeline the outer loop at II=1 to overlap iterations — the "
                  "single biggest latency win when the loop isn't auto-pipelined.",
        priority=30,
        loop_pos="outer",
        risk_tags=["pipeline", "latency"],
    ),
    # --- loops: unroll the INNER loop ---
    Recipe(
        name="unroll_inner_factor_8",
        kind="loop",
        pragma_template="#pragma HLS UNROLL factor=8",
        rationale="Unroll the inner loop by 8 to expose parallel datapath; "
                  "pairs with a cyclic array partition for the bandwidth.",
        priority=40,
        loop_pos="inner",
        risk_tags=["unroll", "area"],
    ),
    Recipe(
        name="unroll_inner_factor_4",
        kind="loop",
        pragma_template="#pragma HLS UNROLL factor=4",
        rationale="Unroll the inner loop by 4 — partial unroll, less area than 8.",
        priority=41,
        loop_pos="inner",
        risk_tags=["unroll", "area"],
    ),
    Recipe(
        name="unroll_inner_full",
        kind="loop",
        pragma_template="#pragma HLS UNROLL",
        rationale="Fully unroll the inner loop — only sane for small, "
                  "compile-time-bounded trip counts.",
        priority=42,
        loop_pos="inner",
        risk_tags=["unroll", "full", "area"],
    ),
    # --- function-level structural pragmas (lower priority) ---
    Recipe(
        name="loop_flatten",
        kind="loop",
        pragma_template="#pragma HLS LOOP_FLATTEN",
        rationale="Flatten perfectly-nested loops into one to reduce loop-entry "
                  "overhead between nest levels.",
        priority=50,
        loop_pos="outer",
        risk_tags=["loop_flatten"],
    ),
    Recipe(
        name="inline",
        kind="function",
        pragma_template="#pragma HLS INLINE",
        rationale="Inline the function to dissolve the call boundary and let the "
                  "caller's scheduler optimize across it.",
        priority=60,
        risk_tags=["inline"],
    ),
    Recipe(
        name="dataflow",
        kind="function",
        pragma_template="#pragma HLS DATAFLOW",
        rationale="Task-level pipelining across sequential producer/consumer "
                  "stages — only correct when the body decomposes that way.",
        priority=61,
        risk_tags=["dataflow", "structural"],
    ),
)


# ---------------------------------------------------------------------------
# Text-scanning helpers — robust, conservative, never raise.
# ---------------------------------------------------------------------------
# A C identifier (function / variable name).
_IDENT = r"[A-Za-z_]\w*"
# A `for (...) {` header on a single line (the kernels here are written that
# way). We anchor on the line so the pragma lands on the NEXT line.
_FOR_HEADER = re.compile(r"^\s*for\s*\(.*\)\s*\{\s*$")


def _find_top_function_file(
    sources: dict[str, str], top_function: str,
) -> str | None:
    """Pick the source file that DEFINES the top function.

    A definition looks like ``<ret> top_function(<params>) {`` (the `{` may be
    on the same or a following line). Falls back to the single ``.cpp`` if the
    top function name is empty or not found by signature.
    """
    cpps = [n for n in sources if n.endswith((".cpp", ".cc", ".cxx", ".c"))]
    if top_function:
        # A definition has the name followed by `(` and, before the next `;`,
        # an opening brace — that distinguishes it from a prototype/call.
        defn = re.compile(re.escape(top_function) + r"\s*\([^;{]*\)\s*\{",
                          re.DOTALL)
        for name, text in sources.items():
            if defn.search(text):
                return name
    if len(cpps) == 1:
        return cpps[0]
    # Last resort: any file that at least mentions the name.
    if top_function:
        for name in cpps:
            if top_function in sources[name]:
                return name
    return cpps[0] if cpps else None


def _function_open_brace_line(lines: list[str], top_function: str) -> int | None:
    """Index of the line carrying the top function's opening ``{``.

    Scans from the function-name occurrence forward to the first ``{``. Returns
    None if neither the name nor a following brace is found.
    """
    if not top_function:
        return None
    name_line = None
    sig = re.compile(re.escape(top_function) + r"\s*\(")
    for i, ln in enumerate(lines):
        if sig.search(ln):
            name_line = i
            break
    if name_line is None:
        return None
    for j in range(name_line, len(lines)):
        if "{" in lines[j]:
            return j
    return None


def _for_header_lines(lines: list[str], start: int) -> list[int]:
    """Indices of ``for (...) {`` header lines at/after `start`, in order."""
    return [i for i in range(start, len(lines)) if _FOR_HEADER.match(lines[i])]


def _parse_array_params(text: str, top_function: str) -> list[str]:
    """Array parameter NAMES from the top-function signature, in order.

    Handles both ``T name[SIZE]`` (e.g. ``const int in[IN_SIZE]``) and pointer
    form ``T *name`` / ``T* name`` (e.g. ``const int *a``). Returns [] if the
    signature can't be parsed — caller then skips array recipes (no crash).
    """
    if not top_function:
        return []
    m = re.search(re.escape(top_function) + r"\s*\(([^;{]*)\)\s*\{", text,
                  re.DOTALL)
    if not m:
        return []
    params_blob = m.group(1).strip()
    if not params_blob or params_blob == "void":
        return []
    names: list[str] = []
    for raw in params_blob.split(","):
        p = raw.strip()
        if not p:
            continue
        # `T name[...]` — array-of form.
        am = re.search(r"(" + _IDENT + r")\s*\[", p)
        if am:
            names.append(am.group(1))
            continue
        # `T *name` / `T* name` — pointer form (also an array at the HW level).
        pm = re.search(r"\*\s*(" + _IDENT + r")\b", p)
        if pm:
            names.append(pm.group(1))
            continue
    return names


def _leading_ws(line: str) -> str:
    """The leading whitespace of `line` (so the pragma matches indentation)."""
    return line[: len(line) - len(line.lstrip())]


def _insert_after(lines: list[str], idx: int, pragma: str, indent: str) -> str:
    """Return the full text of `lines` with `pragma` inserted after line `idx`."""
    out = list(lines)
    out.insert(idx + 1, indent + pragma)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# RecipeProvider — deterministic, one recipe per propose() call.
# ---------------------------------------------------------------------------
class RecipeProvider:
    """Deterministic, non-LLM optimization provider over the recipe catalogue.

    Builds an ordered worklist of concrete (recipe, target-array) pairs the
    first time it sees a usable source, then emits ONE ``PatchProposal`` per
    ``propose()`` call, advancing an internal cursor. Skips any recipe whose
    exact pragma is already present, or whose insertion anchor can't be found.
    Returns ``None`` once the worklist is exhausted.

    Like the other providers it sets ``self.last_usage = None`` (no tokens).
    The optimize loop reuses ONE instance, so the cursor persists across steps.
    """

    def __init__(self, recipes: tuple[Recipe, ...] = RECIPES):
        self.recipes = tuple(sorted(recipes, key=lambda r: r.priority))
        self.last_usage: dict | None = None
        self.model_id = "recipe"  # provenance tag: deterministic, no LLM
        # Lazy worklist of (recipe, array_var|None) tuples, built on first use.
        self._worklist: list[tuple[Recipe, str | None]] | None = None
        self._cursor = 0
        self._target_file: str | None = None

    # -- worklist construction ------------------------------------------------
    def _build_worklist(
        self, sources: dict[str, str], top_function: str,
    ) -> None:
        """Expand the catalogue into concrete (recipe, var) work items."""
        target = _find_top_function_file(sources, top_function)
        self._target_file = target
        work: list[tuple[Recipe, str | None]] = []
        if target is None:
            self._worklist = work
            return
        arrays = _parse_array_params(sources[target], top_function)
        for recipe in self.recipes:
            if recipe.kind == "array":
                # One work item per array param (priority already grouped).
                for var in arrays:
                    work.append((recipe, var))
            else:
                work.append((recipe, None))
        self._worklist = work

    # -- rendering one work item into a proposal ------------------------------
    def _render_proposal(
        self, recipe: Recipe, var: str | None, source_text: str,
        diagnosis_klass: str,
    ) -> PatchProposal | None:
        """Apply one recipe to `source_text`; None if it can't anchor cleanly."""
        pragma = recipe.render(var)
        # De-dup: never re-insert a pragma that's already in the file verbatim.
        if pragma in source_text:
            return None

        lines = source_text.split("\n")
        top = recipe  # for readability below
        new_text: str | None = None
        plan: str = ""

        if recipe.kind == "array":
            if not var:
                return None
            brace = _function_open_brace_line(lines, self._top_function)
            if brace is None:
                return None
            indent = _leading_ws(lines[brace]) + "  "
            new_text = _insert_after(lines, brace, pragma, indent)
            plan = f"{self._partition_label(recipe)} on `{var}`"

        elif recipe.kind == "loop":
            brace = _function_open_brace_line(lines, self._top_function)
            search_from = brace if brace is not None else 0
            fors = _for_header_lines(lines, search_from)
            if not fors:
                return None
            anchor = fors[0] if recipe.loop_pos == "outer" else fors[-1]
            indent = _leading_ws(lines[anchor]) + "  "
            new_text = _insert_after(lines, anchor, pragma, indent)
            plan = f"{self._loop_label(recipe)} ({recipe.loop_pos} loop)"

        elif recipe.kind == "function":
            brace = _function_open_brace_line(lines, self._top_function)
            if brace is None:
                return None
            indent = _leading_ws(lines[brace]) + "  "
            new_text = _insert_after(lines, brace, pragma, indent)
            plan = self._func_label(recipe)

        if new_text is None:
            return None

        return PatchProposal(
            diagnosis=diagnosis_klass,
            edit_plan=plan,
            target_file=self._target_file,
            whole_file=new_text,
            expected_effect=recipe.rationale,
            risk_tags=["recipe", *top.risk_tags],
        )

    # -- human-readable edit_plan labels --------------------------------------
    @staticmethod
    def _partition_label(recipe: Recipe) -> str:
        # e.g. "ARRAY_PARTITION cyclic factor=8 dim=1"
        body = recipe.pragma_template.replace(
            "#pragma HLS ", "").replace("variable={var} ", "")
        return body

    @staticmethod
    def _loop_label(recipe: Recipe) -> str:
        return recipe.pragma_template.replace("#pragma HLS ", "")

    @staticmethod
    def _func_label(recipe: Recipe) -> str:
        return recipe.pragma_template.replace("#pragma HLS ", "")

    # -- the PatchProvider entry point ----------------------------------------
    def propose(self, task, sources, diagnosis, history):
        """Emit the next applicable recipe as a PatchProposal, or None.

        Only fires for PPA optimization (``recommended_action ==
        'optimize_ppa'``); for any other action it abstains (returns None) so a
        repair-oriented provider downstream can handle correctness fixes.
        """
        self.last_usage = None  # recipes cost no LLM tokens

        # Only contribute to the optimize phase.
        if getattr(diagnosis, "recommended_action", None) != "optimize_ppa":
            return None

        self._top_function = getattr(task, "top_function", "") or ""

        if self._worklist is None:
            self._build_worklist(sources, self._top_function)

        if not self._target_file or self._target_file not in sources:
            return None
        source_text = sources[self._target_file]

        # Deprioritize work items already reported as no-improvement: skip a
        # recipe whose pragma appears in the "Already attempted" evidence line
        # or in history-derived plans. Primary advance is still the cursor.
        attempted_blob = " | ".join(
            e for e in (getattr(diagnosis, "evidence", None) or [])
            if "Already attempted" in e
        )

        worklist = self._worklist or []
        while self._cursor < len(worklist):
            recipe, var = worklist[self._cursor]
            self._cursor += 1
            proposal = self._render_proposal(
                recipe, var, source_text, diagnosis.klass)
            if proposal is None:
                continue  # already present / no anchor — try the next item
            # Opportunistic skip if this exact plan already failed to help.
            if attempted_blob and proposal.edit_plan in attempted_blob:
                continue
            return proposal

        return None  # worklist exhausted
