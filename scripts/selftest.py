#!/usr/bin/env python3
"""Offline check of the parser logic — NO compiler needed.

Feeds synthetic tool output through parse_csim so the pass / compile_error /
functional_fail / timeout / tool_unavailable classification is verified even
before g++ or Vitis HLS is installed. Run:  python3 scripts/selftest.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harpo.parser import parse_csim  # noqa: E402

# (name, raw_tool_output, expected_status, expected_pass)
CASES = [
    ("pass", {
        "available": True, "backend": "gpp", "compiler": "g++",
        "compile_rc": 0, "compile_log": "",
        "run_rc": 0, "run_stdout": "TEST PASSED", "run_stderr": "",
        "duration_sec": 0.4,
    }, "pass", True),
    ("functional_fail", {
        "available": True, "backend": "gpp", "compiler": "g++",
        "compile_rc": 0, "compile_log": "",
        "run_rc": 1,
        "run_stdout": "MISMATCH at 0: expected 0 got 0\n"
                      "MISMATCH at 1: expected 3 got -1\n"
                      "TEST FAILED: 1024 mismatches",
        "run_stderr": "", "duration_sec": 0.4,
    }, "functional_fail", False),
    ("compile_error", {
        "available": True, "backend": "gpp", "compiler": "g++",
        "compile_rc": 1,
        "compile_log": "src/vadd.cpp:18:14: error: 'd' was not declared in this scope",
        "run_rc": None, "run_stdout": "", "run_stderr": "", "duration_sec": 0.1,
    }, "compile_error", False),
    ("timeout", {
        "available": True, "backend": "gpp", "compiler": "g++",
        "compile_rc": 0, "compile_log": "",
        "run_rc": -1, "run_stdout": "", "run_stderr": "run timed out after 30s",
        "duration_sec": 30.0,
    }, "timeout", False),
    ("tool_unavailable", {
        "available": False, "backend": "gpp", "compiler": None,
        "compile_log": "no C++ compiler found", "duration_sec": 0.0,
    }, "tool_unavailable", None),
]


def main() -> int:
    ok = True
    for name, raw, want_status, want_pass in CASES:
        got = parse_csim(raw)
        good = got["status"] == want_status and got["pass"] is want_pass
        ok = ok and good
        print(f"[{'PASS' if good else 'FAIL'}] {name}: "
              f"status={got['status']} pass={got['pass']} "
              f"errors={got['errors'][:1]}")
    print("\nselftest:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
