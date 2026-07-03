"""Candidate / run store: persist every run as replayable evidence.

Track A's paper requires a workflow + token/tool-call account, so every run
leaves a JSON trail under runs/<task_id>/<candidate_id>/.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def runs_dir_for(task_id: str) -> Path:
    return REPO_ROOT / "runs" / task_id


def candidate_dir(task_id: str, candidate_id: str) -> Path:
    return runs_dir_for(task_id) / candidate_id


def write_run(task_id: str, candidate_id: str, raw: dict, parsed: dict,
              stage: str | None = None) -> Path:
    """Persist a run's raw + parsed evidence under runs/<task>/<cand>/.

    When ``stage`` is given (e.g. "csim"/"csynth") the files are stage-prefixed
    so a candidate that runs multiple stages keeps both trails; without it the
    legacy ``raw.json``/``parsed.json`` names are used.
    """
    d = candidate_dir(task_id, candidate_id)
    d.mkdir(parents=True, exist_ok=True)
    raw_name = f"{stage}_raw.json" if stage else "raw.json"
    parsed_name = f"{stage}_parsed.json" if stage else "parsed.json"
    (d / raw_name).write_text(json.dumps(raw, indent=2))
    (d / parsed_name).write_text(json.dumps(parsed, indent=2))
    return d
