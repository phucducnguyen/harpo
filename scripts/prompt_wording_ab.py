"""A/B: does the violation-message wording flip the temperature-0 proposal?

Rebuilds the exact first-optimize-step prompt from a stored run's artifacts
(csynth_parsed.json + src/), then queries the Ollama endpoint twice at
temperature 0: once per violation wording. Prints target_file, edit_plan and
token counts for each arm. Read-only against the repo; two LLM calls total.

Run record: docs/case-study/lns_mac_001_prompt_wording_ab.md

Usage:
    HARPO_OLLAMA_URL=http://<host>:11434 python3 scripts/prompt_wording_ab.py \
        [task_dir] [cand_dir]
defaults: tasks/lns_mac_001  runs/lns_mac_001/cand_0000
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harpo.diagnosis import diagnose_csynth
from harpo.patch_engine import OllamaProvider, _OLLAMA_OPT_SYSTEM_PROMPT
from harpo.task import load_task

ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "tasks/lns_mac_001")
CAND_DIR = Path(sys.argv[2] if len(sys.argv) > 2
                else ROOT / "runs/lns_mac_001/cand_0000")

# The two wordings under test (see docs/case-study record). A = the transient
# 2026-07-15 count-based message; B = the utilization message every recorded
# run was produced with (restored as the default for util>100 cases).
WORDING_A = "resource: LUT count 89773 > available 53200 (168.75%)"
WORDING_B = "resource: LUT utilization 168.7% > 100%"

task = load_task(TASK_DIR)
parsed = json.loads((CAND_DIR / "csynth_parsed.json").read_text())
sources = {f.name: f.read_text() for f in sorted((CAND_DIR / "src").iterdir())}
prov = OllamaProvider()
print("endpoint:", prov.url, "model:", prov.model)

for label, wording in (("A_count", WORDING_A), ("B_utilization", WORDING_B)):
    p = dict(parsed)
    p["violations"] = [wording if v in (WORDING_A, WORDING_B) else v
                       for v in parsed["violations"]]
    diag = diagnose_csynth(p, [])
    user = prov._build_user_prompt(task, sources, diag, optimize=True)
    payload = {
        "model": prov.model,
        "messages": [
            {"role": "system", "content": _OLLAMA_OPT_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        f"{prov.url}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as resp:
        env = json.loads(resp.read().decode())
    try:
        data = json.loads(env["message"]["content"])
        plan, target = data.get("edit_plan"), data.get("target_file")
    except Exception as e:  # keep the arm's failure visible, not fatal
        plan, target = f"<unparseable: {e}>", None
    print(f"\n[{label}] prompt_chars={len(user)} "
          f"prompt_eval={env.get('prompt_eval_count')} "
          f"eval={env.get('eval_count')}")
    print(f"  target: {target}")
    print(f"  plan:   {str(plan)[:200]}")
