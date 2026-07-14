"""Offline unit tests for the optional spec ``include_dirs`` key.

Pure stdlib `unittest`. No Vitis, no compiler, no network. Real HLS kernels
almost always need headers the agent must never edit (ap_int.h and friends);
``include_dirs`` lets a task vendor them for the HOST csim backend. The vitis
backend must NOT see them (the open-source AP types #error under csynth). Run::

    python3 -m unittest tests.test_include_dirs -v
    python3 tests/test_include_dirs.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo.runner import _gen_tcl
from harpo.task import load_task


def _write_temp_task(tmp: Path, *, include_dirs=None):
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "tb").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "k.cpp").write_text("void k(){}\n")
    (tmp / "tb" / "tb_k.cpp").write_text("int main(){return 0;}\n")
    spec = {
        "task_id": "tmp_task",
        "top_function": "k",
        "entry_files": ["src/k.cpp"],
        "testbench_files": ["tb/tb_k.cpp"],
    }
    if include_dirs is not None:
        spec["include_dirs"] = include_dirs
    (tmp / "spec.json").write_text(json.dumps(spec))


class TestLoadTaskIncludeDirs(unittest.TestCase):
    def _load(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _write_temp_task(tmp, **kw)
            return load_task(tmp), tmp.resolve()

    def test_absent_is_empty_list(self):
        ctx, _ = self._load()
        self.assertEqual(ctx.include_dirs, [])

    def test_relative_resolves_against_task_dir(self):
        ctx, tmp = self._load(include_dirs=["deps/hls_types/include"])
        self.assertEqual(ctx.include_dirs,
                         [(tmp / "deps" / "hls_types" / "include")])

    def test_parent_relative_resolves(self):
        # Repo-level shared deps: tasks/<id>/../../.deps/... must normalize.
        ctx, tmp = self._load(include_dirs=["../../.deps/hls_types/include"])
        self.assertEqual(ctx.include_dirs,
                         [(tmp / "../../.deps/hls_types/include").resolve()])
        self.assertNotIn("..", str(ctx.include_dirs[0]))

    def test_absolute_passes_through(self):
        ctx, _ = self._load(include_dirs=["/opt/hls/include"])
        self.assertEqual(ctx.include_dirs, [Path("/opt/hls/include")])

    def test_missing_dir_does_not_raise_at_load(self):
        # Deliberate: a bad path surfaces as a compile error with the -I in the
        # log, which is more actionable than a load-time exception.
        ctx, _ = self._load(include_dirs=["no/such/dir"])
        self.assertEqual(len(ctx.include_dirs), 1)


class TestBackendIncludeDirScoping(unittest.TestCase):
    def test_gen_tcl_excludes_vendored_dirs(self):
        """REGRESSION: passing vendored AP-types headers to Vitis breaks csynth
        outright — ap_common.h #errors with "The open-source version of AP
        types does not support synthesis." include_dirs is host-csim only; the
        vitis backend must use only src/tb dirs (the tool ships its own
        ap_int.h)."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _write_temp_task(tmp, include_dirs=["deps/inc"])
            ctx = load_task(tmp)
            tcl = _gen_tcl(ctx, "proj")
            self.assertNotIn(str((tmp / "deps" / "inc").resolve()), tcl)
            self.assertIn(f"-I{ctx.src_dir} -I{ctx.tb_dir}", tcl)


if __name__ == "__main__":
    unittest.main()
