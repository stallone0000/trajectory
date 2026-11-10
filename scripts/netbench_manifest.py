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
RERUN = pathlib.Path("/share/network-agent-benchmark-20261107/lightweight/evaluation-360-20261108/v9-robust-runner/rerun-ledger.json")
ap = argparse.ArgumentParser(); ap.add_argument("--all-attempts", action="store_true")
ap.add_argument("--binary", action="store_true", help="site mode: jobs re-run with v9 use the v9 result, and any run without a "
                "gradable submission is shown as fail (reason kept in detail)")
a = ap.parse_args()
reruns = {}
if a.binary:  # all v9 re-run ledgers (auto route, then pinned-route rounds), trials in start order
    for led in sorted(RERUN.parent.glob("rerun*-ledger.json")):
        for jid, job in json.loads(led.read_text())["jobs"].items():
            reruns.setdefault(jid, {"trials": []})["trials"].extend(job["trials"])
    for job in reruns.values():
        job["trials"].sort(key=lambda t: t.get("started", 0))
w = csv.writer(sys.stdout); w.writerow(["trajectory", "task", "model", "provider", "score", "verdict", "detail", "label"])
for j in json.loads(LEDGER.read_text())["jobs"]:
    attempts = (j.get("historical_attempts") or []) + (j.get("attempts") or [])
    if j.get("state") != "finished" and not a.all_attempts:
        continue
    chosen = [x for x in attempts if (x.get("result") or {}).get("run")]
    if not a.all_attempts:
        chosen = [x for x in chosen if x["result"] == j.get("final_result")][-1:]
    rr = [t for t in reruns.get(j["id"], {}).get("trials", []) if (t.get("result") or {}).get("run")]
    if rr and not a.all_attempts:  # v9 robust re-run replaces an unscored main-batch result
        best = next((t for t in rr if t["result"]["status"] in ("pass", "fail")), rr[-1])
        chosen = [{"result": best["result"], "number": best["n"], "policy_origin": "v9_robust", "v9": True}]
    for x in chosen:
        run = pathlib.Path(x["result"]["run"]); traj = run / "trajectory.traj.json"
        if not traj.exists():
            continue
        r = x["result"]; st = r.get("status")
        score = r["score"] if st in ("pass", "fail") else ""
        verdict, detail = (st, "") if st in ("pass", "fail") else ("unscored", UNSCORED.get(st, st or "unknown"))
        if not a.all_attempts and j["id"] in ADJUDICATED and not x.get("v9"):
            verdict, detail = ADJUDICATED[j["id"]]
            score = 0 if verdict == "fail" else score
        if x.get("v9"):
            att = run / "model-attempts.jsonl"
            cuts = att.exists() and sum('"empty reply' in line for line in att.open(errors="replace"))
            if verdict == "unscored" and cuts >= 3:  # the "format errors" were replies the provider cut off
                detail = f"provider cut the model's long reasoning {cuts} times"
            detail = "re-run with the robust runner" + (f"; {detail}" if detail else "")
        if a.binary and verdict == "unscored":  # no gradable submission counts as not solved
            verdict, detail, score = "fail", f"no gradable submission ({detail})", 0
        label = f"{x.get('policy_origin','')}-attempt{x['number']}" if a.all_attempts else ""
        w.writerow([traj, j["task"], j["model"], "360", score, verdict, detail, label])
