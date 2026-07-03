"""Area metrics: normalized resource-utilization scoring for HLS designs.

HARPO ranks candidates partly on area. Raw resource counts (LUT/FF/DSP/...)
are not comparable across resource types -- 13k LUTs and 4 DSPs say nothing
about which design is "bigger" relative to the chip. We adopt **Option A: a
normalized utilization metric** = sum of (used / available) over resources.

Why normalize-then-sum and *not* per-resource weights: dividing by each
resource's device capacity already makes scarce resources (small denominators)
dominate the sum naturally. A DSP on a Zynq-7020 (220 total) costs ~240x more
per unit toward the score than a LUT (53200 total). Adding hand-tuned scarcity
weights on top would double-count that same scarcity, so we deliberately omit
them.

Everything here is defensive: csynth reports are frequently missing keys or
carry ``None``, so each function must degrade to ``None`` rather than raise.
"""

from __future__ import annotations

# Fallback device capacities, used ONLY when a candidate's metrics lack avail_*
# values. xc7z020 = Zynq-7020 (clg400). URAM: none on 7-series (capacity 0 ->
# the uram resource simply never contributes to the sum).
DEVICE_CAPS: dict[str, dict[str, float]] = {
    "xc7z020-clg400-1": {"lut": 53200, "ff": 106400, "dsp": 220, "bram_18k": 280, "uram": 0},
}

# Resource -> the metrics key carrying its device capacity. Note bram_18k maps
# to avail_bram (the report names the capacity without the _18k suffix).
_AVAIL_KEY = {
    "lut": "avail_lut",
    "ff": "avail_ff",
    "dsp": "avail_dsp",
    "bram_18k": "avail_bram",
    "uram": "avail_uram",
}

_RESOURCES = ("lut", "ff", "dsp", "bram_18k", "uram")


def _num(value) -> float | None:
    """Return ``value`` as a float if it is a real number, else None.

    bool is an int subclass but is never a valid resource count, so reject it.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _fallback_caps(metrics: dict, caps: dict | None) -> dict | None:
    """Per-part capacity table from an explicit ``caps`` arg or DEVICE_CAPS.

    Lookup is tolerant: try the exact ``part`` string first, then the part with
    a trailing speed grade ("-1") stripped, so "xc7z020-clg400-1" still resolves
    against a table keyed without the grade (and vice-versa).
    """
    table = caps if caps is not None else DEVICE_CAPS
    part = metrics.get("part")
    if not isinstance(part, str):
        return None
    if part in table:
        return table[part]
    # Drop a trailing "-<grade>" speed-grade suffix and retry.
    base, _, _ = part.rpartition("-")
    if base and base in table:
        return table[base]
    return None


def _capacity(resource: str, metrics: dict, fb_caps: dict | None) -> float | None:
    """Capacity for one resource: prefer in-report avail_*, else the fallback.

    Returns a positive capacity, or None when none is known. A known-but-zero
    capacity (e.g. uram on 7-series) is treated as "no usable capacity" so the
    resource contributes nothing -- and we never divide by zero.
    """
    avail = _num(metrics.get(_AVAIL_KEY[resource]))
    if avail is not None and avail > 0:
        return avail
    if fb_caps is not None:
        cap = _num(fb_caps.get(resource))
        if cap is not None and cap > 0:
            return cap
    return None


def area_score(metrics: dict | None, *, caps: dict | None = None) -> float | None:
    """Option A normalized utilization: sum of (used / capacity) over resources.

    Considers lut, ff, dsp, bram_18k, uram. For each resource where both a
    numeric used-count and a positive capacity are known, adds count/capacity.
    Capacity is the in-report avail_* value if positive, else the per-part
    fallback (``caps`` arg or DEVICE_CAPS via ``metrics["part"]``).

    Returns the sum (typically ~0.0-2.0), or None if no resource was usable
    (metrics None/empty, or no count+capacity pair could be formed).
    """
    if not metrics:
        return None

    fb_caps = _fallback_caps(metrics, caps)
    total = 0.0
    used_any = False
    for res in _RESOURCES:
        count = _num(metrics.get(res))
        if count is None:
            continue
        cap = _capacity(res, metrics, fb_caps)
        if cap is None:  # unknown or zero capacity -> skip (no div-by-zero)
            continue
        total += count / cap
        used_any = True

    return total if used_any else None


def _throughput(metrics: dict) -> float | None:
    """Honest throughput: interval_max preferred, then latency_worst, then ii.

    interval_max is the truthful steady-state interval; ii can be misreported as
    None for fully-unrolled loops (the known scoring trap), so it is last.
    """
    for key in ("interval_max", "latency_worst", "ii"):
        v = _num(metrics.get(key))
        if v is not None:
            return v
    return None


def adp(metrics: dict | None, *, caps: dict | None = None) -> float | None:
    """Area-delay product: area_score * throughput (lower is better).

    Returns None if either the area score or the throughput metric is missing.
    """
    if not metrics:
        return None
    a = area_score(metrics, caps=caps)
    t = _throughput(metrics)
    if a is None or t is None:
        return None
    return a * t


def resource_growth_ratio(
    cand_metrics: dict | None,
    baseline_metrics: dict | None,
    *,
    caps: dict | None = None,
) -> float | None:
    """area_score(cand) / area_score(baseline) -- how much bigger than baseline.

    Returns None if either area score is None or the baseline area score is 0
    (no meaningful ratio against a zero-area baseline).
    """
    cand = area_score(cand_metrics, caps=caps)
    base = area_score(baseline_metrics, caps=caps)
    if cand is None or base is None or base == 0:
        return None
    return cand / base
