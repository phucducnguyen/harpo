#!/usr/bin/env python3
"""Offline check of the csynth parser's resource-utilization fix — NO Vitis.

Loads the csynth XML reports already stored under runs/ (the same files
run_csynth_vitis would have stashed) and feeds them through parse_csynth exactly
as the runner would: the overall csynth.xml as the primary `csynth_xml`, and the
per-module <top>_csynth.xml as the secondary `csynth_xml_module` merge fallback.

For each fixture it asserts:
  * status == "pass"
  * raw counts (lut/ff/dsp/bram_18k) are present
  * every util_* is a number in [0, 100] for resources that EXIST on the part
    (avail_* > 0). URAM has avail 0 on xc7z020, so util_uram stays None — that
    is correct, not a failure.

Run:  python3 scripts/selftest_csynth.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harpo.parser import parse_csynth  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# (label, overall csynth.xml path, top function for the per-module report)
FIXTURES = [
    ("mac8_001",
     "runs/mac8_001/cand_0001/hls_proj/sol1/syn/report/csynth.xml", "mac8"),
    ("vadd_001",
     "runs/vadd_001/cand_csynth2/hls_proj/sol1/syn/report/csynth.xml", "vadd"),
    ("stencil3_001",
     "runs/stencil3_001/cand_0000/hls_proj/sol1/syn/report/csynth.xml", "stencil3"),
    ("unroll8_001",
     "runs/unroll8_001/cand_0000/hls_proj/sol1/syn/report/csynth.xml", "unroll8"),
]

RAW_KEYS = ("lut", "ff", "dsp", "bram_18k")
UTIL_KEYS = ("util_lut", "util_ff", "util_dsp", "util_bram", "util_uram")
AVAIL_KEYS = ("avail_lut", "avail_ff", "avail_dsp", "avail_bram", "avail_uram")
# util_* <-> avail_* pairing so we only require util where the resource exists.
UTIL_TO_AVAIL = dict(zip(UTIL_KEYS, AVAIL_KEYS))


def _build_raw(overall: Path, module: Path | None) -> dict:
    """Reconstruct what run_csynth_vitis stashes (primary + secondary report)."""
    return {
        "stage": "csynth",
        "backend": "vitis_hls",
        "available": True,
        "tool": "vitis_hls",
        "rc": 0,
        "log": "",
        "csynth_xml": overall.read_text(),
        "csynth_xml_module": module.read_text() if module and module.exists() else None,
        "csynth_report_path": str(overall),
        "duration_sec": 0.0,
    }


def _check(label: str, overall_rel: str, top: str) -> bool | None:
    overall = ROOT / overall_rel
    module = overall.parent / f"{top}_csynth.xml"
    if not overall.exists():
        # ⚠️ "could not check" is NOT "passed". The fixtures live under runs/,
        # which is gitignored, so a fresh clone has none — this used to return
        # True and print ALL PASS having verified nothing.
        print(f"[MISSING] {label}: no fixture at {overall}")
        return None

    parsed = parse_csynth(_build_raw(overall, module))
    m = parsed.get("metrics") or {}
    problems = []

    if parsed["status"] != "pass":
        problems.append(f"status={parsed['status']} (want pass)")

    for k in RAW_KEYS:
        if m.get(k) is None:
            problems.append(f"raw {k} missing")

    util_report = []
    for uk in UTIL_KEYS:
        av = m.get(UTIL_TO_AVAIL[uk])
        uv = m.get(uk)
        if av is not None and av > 0:
            # Resource exists -> util MUST be a number in [0, 100].
            if not isinstance(uv, (int, float)):
                problems.append(f"{uk}={uv!r} not numeric (avail={av})")
            elif not (0 <= uv <= 100):
                problems.append(f"{uk}={uv} out of [0,100]")
            else:
                util_report.append(f"{uk}={uv}")
        else:
            util_report.append(f"{uk}=n/a(avail={av})")

    ok = not problems
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {label}: status={parsed['status']} "
          f"counts(lut={m.get('lut')},ff={m.get('ff')},dsp={m.get('dsp')},"
          f"bram_18k={m.get('bram_18k')},uram={m.get('uram')}) "
          f"util({', '.join(util_report)})")
    if problems:
        print(f"        problems: {problems}")
    return ok


def main() -> int:
    """0 = every fixture checked and passed · 1 = a real failure ·
    2 = INCONCLUSIVE, a fixture was absent so nothing was verified.

    The three verdicts stay distinct on purpose: a checker that cannot run must
    never be readable as a checker that passed.
    """
    results = [_check(label, rel, top) for label, rel, top in FIXTURES]
    failed = [r for r in results if r is False]
    missing = [r for r in results if r is None]

    if failed:
        print(f"\nselftest_csynth: FAILURES ({len(failed)}/{len(results)})")
        return 1
    if missing:
        print(f"\nselftest_csynth: INCONCLUSIVE — {len(missing)}/{len(results)} "
              f"fixture(s) absent, nothing verified. Fixtures are produced by a "
              f"real csynth run and live under the gitignored runs/ tree; a "
              f"fresh clone cannot run this check.")
        return 2
    print(f"\nselftest_csynth: ALL PASS ({len(results)}/{len(results)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
