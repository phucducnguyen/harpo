"""Offline tests for run-evidence MODEL provenance.

Pure stdlib `unittest`; csynth is canned, csim uses the real g++ backend
(skipped if no compiler). The paper's reproducibility story needs committed
run artifacts to prove WHICH model produced each patch — previously events
logged only ``provider: "OllamaProvider"``, so the exact model tag was
unrecoverable from evidence alone. Every provider now carries a ``model_id``
(Ollama = the model tag ONLY — never the endpoint URL, which would leak LAN
addresses into published artifacts) and each propose event records it. Run::

    python3 -m unittest tests.test_provenance -v
    python3 tests/test_provenance.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo import store
from harpo.agent import run_repair
from harpo.patch_engine import MockProvider, OllamaProvider
from harpo.recipes import RecipeProvider
from harpo.task import load_task

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = REPO_ROOT / "tasks" / "vadd_buggy_001"


class TestProviderModelIds(unittest.TestCase):
    def test_mock_and_recipe_tags(self):
        self.assertEqual(MockProvider([]).model_id, "mock")
        self.assertEqual(RecipeProvider().model_id, "recipe")

    def test_ollama_model_id_is_the_model_tag(self):
        prov = OllamaProvider(url="http://example.invalid:11434",
                              model="qwen-test:1b-q4")
        self.assertEqual(prov.model_id, "qwen-test:1b-q4")

    def test_ollama_model_id_never_contains_endpoint(self):
        """Run JSONs are published artifacts; the 2026-07-02 scrub keeps LAN
        addresses/hostnames out of the repo — model_id must not smuggle the
        URL back in."""
        prov = OllamaProvider(url="http://10.9.8.7:11434", model="m:tag")
        self.assertNotIn("10.9.8.7", prov.model_id)
        self.assertNotIn("http", prov.model_id)


class TestProposeEventRecordsModel(unittest.TestCase):
    """End-to-end (csim via real g++): repair events carry the model tag."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="harpo_provenance_")
        self._orig_repo_root = store.REPO_ROOT
        store.REPO_ROOT = Path(self._tmp)
        self.addCleanup(self._restore_repo_root)
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def _restore_repo_root(self):
        store.REPO_ROOT = self._orig_repo_root

    def test_repair_propose_event_has_model(self):
        if not any(shutil.which(c) for c in
                   (os.environ.get("CXX") or "", "g++", "clang++", "c++")):
            self.skipTest("no C++ compiler available; gpp csim cannot run")

        task = load_task(TASK_DIR)
        edits = [tuple(e) for e in
                 json.loads((TASK_DIR / "mock_patch.json").read_text())]
        result = run_repair(task, providers=[MockProvider(edits)],
                            backend="gpp")

        proposes = [e for e in result["events"] if e.get("event") == "propose"]
        self.assertTrue(proposes, "expected at least one propose event")
        for e in proposes:
            self.assertEqual(e.get("provider"), "MockProvider")
            self.assertEqual(e.get("model"), "mock")


if __name__ == "__main__":
    unittest.main()
