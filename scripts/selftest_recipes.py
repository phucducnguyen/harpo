#!/usr/bin/env python3
"""Offline check of the recipe provider — NO Vitis HLS needed.

Drives a single ``RecipeProvider`` instance against the real ``tasks/mac8_001``
sources exactly as the optimize loop would (same instance, repeated calls), and
for EACH proposed pragma:
  1. prints the recipe's edit_plan + the inserted pragma, and
  2. syntax-checks the emitted ``whole_file`` with g++ (``-fsyntax-only``) after
     writing it + the kernel header into a temp dir.

This proves the transforms produce valid C++ without touching synthesis. Run:
    python3 scripts/selftest_recipes.py
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harpo.recipes import RecipeProvider  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "tasks" / "mac8_001" / "src"
TOP = "mac8"


class _Task:
    """Minimal stand-in for TaskContext (provider only reads top_function)."""

    def __init__(self, top_function: str, src_dir: Path):
        self.top_function = top_function
        self.src_files = list(src_dir.glob("*.cpp"))


class _Diag:
    """Minimal Diagnosis stand-in: optimize action + PPA evidence."""

    def __init__(self):
        self.klass = "II_TOO_HIGH"
        self.recommended_action = "optimize_ppa"
        self.evidence = ["II=8 latency_worst=2048 LUT=120"]


def _read_sources(src_dir: Path) -> dict[str, str]:
    return {p.name: p.read_text() for p in src_dir.iterdir() if p.is_file()}


def _gpp_available() -> bool:
    try:
        subprocess.run(["g++", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _syntax_check(whole_file: str, target_name: str, header_src: dict) -> tuple[bool, str]:
    """Write whole_file + headers to a temp dir and g++ -fsyntax-only it."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for hname, htext in header_src.items():
            (d / hname).write_text(htext)
        cpp = d / target_name
        cpp.write_text(whole_file)
        proc = subprocess.run(
            ["g++", "-fsyntax-only", "-std=c++14", f"-I{d}", str(cpp)],
            capture_output=True, text=True,
        )
        return proc.returncode == 0, proc.stderr.strip()


def main() -> int:
    sources = _read_sources(SRC_DIR)
    headers = {n: t for n, t in sources.items() if n.endswith((".h", ".hpp"))}
    task = _Task(TOP, SRC_DIR)
    diag = _Diag()

    provider = RecipeProvider()
    have_gpp = _gpp_available()
    if not have_gpp:
        print("WARNING: g++ not found — printing proposals WITHOUT syntax check\n")

    n = 0
    failures = 0
    pragma_re = re.compile(r"^\s*#pragma HLS .*$", re.MULTILINE)
    while True:
        proposal = provider.propose(task, sources, diag, history=[])
        if proposal is None:
            break
        n += 1
        # Identify the pragma line(s) added vs. the original source.
        orig_pragmas = set(pragma_re.findall(sources[proposal.target_file]))
        new_pragmas = [p.strip() for p in pragma_re.findall(proposal.whole_file)
                       if p.strip() not in {o.strip() for o in orig_pragmas}]
        added = new_pragmas[0] if new_pragmas else "(?)"
        status = ""
        if have_gpp:
            ok, err = _syntax_check(proposal.whole_file, proposal.target_file, headers)
            status = "COMPILE OK" if ok else f"COMPILE FAIL\n      {err}"
            if not ok:
                failures += 1
        print(f"[{n:02d}] {proposal.edit_plan}")
        print(f"     + {added}")
        if status:
            print(f"     {status}")
        print()

    print(f"Proposed {n} recipe(s); "
          f"{'all compiled' if have_gpp and failures == 0 else f'{failures} compile failure(s)' if have_gpp else 'g++ skipped'}.")
    return 1 if (have_gpp and failures) else 0


if __name__ == "__main__":
    sys.exit(main())
