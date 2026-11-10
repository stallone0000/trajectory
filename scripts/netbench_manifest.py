#!/usr/bin/env python3
"""Example adapter: build a mswea_import manifest from the 360 network-benchmark ledger (final attempt of each job).

    python3 scripts/netbench_manifest.py > /root/pi-runs/netbench-360/manifest.csv
    python3 scripts/netbench_manifest.py --all-attempts > ...   # every attempt, labelled attemptN

score: 1/0 for graded pass/fail, empty for unscored. verdict: pass|fail|unscored; detail: why unscored, or how decided.
"""
import argparse, csv, json, pathlib, sys
LEDGER = pathlib.Path("/share/network-agent-benchmark-20261107/lightweight/evaluation-360-20261108/final-v4-nocap/ledger.json")
UNSCORED = {"interface_or_agent_error": "API error", "output_limit_exhausted": "output limit", "invalid_model_response": "format errors",
            "infrastructure_error": "infrastructure error", "budget_exhausted": "budget exhausted", "timeout": "timeout"}
# Evaluator adjudications recorded in v7-full-scope/README.md (ledger values are kept unchanged).
ADJUDICATED = {"t16-m04": ("fail", "adjudicated: malformed output crashed the grader"),
               "t05-m03": ("unscored", "invalid tool command (NUL byte)")}
ap = argparse.ArgumentParser(); ap.add_argument("--all-attempts", action="store_true"); a = ap.parse_args()
w = csv.writer(sys.stdout); w.writerow(["trajectory", "task", "model", "provider", "score", "verdict", "detail", "label"])
for j in json.loads(LEDGER.read_text())["jobs"]:
    attempts = (j.get("historical_attempts") or []) + (j.get("attempts") or [])
    if j.get("state") != "finished" and not a.all_attempts:
        continue
    chosen = [x for x in attempts if (x.get("result") or {}).get("run")]
    if not a.all_attempts:
        chosen = [x for x in chosen if x["result"] == j.get("final_result")][-1:]
    for x in chosen:
        run = pathlib.Path(x["result"]["run"]); traj = run / "trajectory.traj.json"
        if not traj.exists():
            continue
        r = x["result"]; st = r.get("status")
        score = r["score"] if st in ("pass", "fail") else ""
        verdict, detail = (st, "") if st in ("pass", "fail") else ("unscored", UNSCORED.get(st, st or "unknown"))
        if not a.all_attempts and j["id"] in ADJUDICATED:
            verdict, detail = ADJUDICATED[j["id"]]
            score = 0 if verdict == "fail" else score
        label = f"{x.get('policy_origin','')}-attempt{x['number']}" if a.all_attempts else ""
        w.writerow([traj, j["task"], j["model"], "360", score, verdict, detail, label])
