#!/usr/bin/env python3
"""Batch-convert mini-swe-agent trajectories to pi sessions, write results.csv, and (optionally) ingest into pika.

    python3 scripts/mswea_import.py --benchmark netbench --manifest manifest.csv [--ingest]

manifest.csv columns (header required; extra columns ignored):
    trajectory  path to a mini-swe-agent *.traj.json
    task        task id                       -> title <benchmark>/<task>/<bare model name>
    model       model id as requested          (also shown in pika)
    provider    optional, e.g. 360             (default: model prefix)
    score       optional 1/0
    verdict     optional pass|fail|unscored (default from score); shown as a badge on the site
    detail      optional reason for unscored / how a verdict was decided
    thinking    optional thinking-level note
    label       optional suffix to tell repeated attempts apart (e.g. attempt2)

Output under /root/pi-runs/<benchmark>/ (override with --out):
    sessions/<task>-<model>[-<label>].jsonl     pi session files (deterministic; re-running is idempotent)
    results.csv                                 session_id, task, model, score, label, trajectory

With --ingest the sessions are uploaded to the local pika (project = <benchmark>). Publishing is a separate,
deliberate step: `cd /root/trajectory && scripts/publish.sh` publishes EVERYTHING in that pika.

Secrets: every output is scanned for the literals in ~/.config/trajectory-render/redact.txt and for the contents
of any --secret-file; matches are replaced with [REDACTED] and only counted (values are never printed).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mswea_to_pi", HERE / "mswea_to_pi.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "x"


def load_secrets(extra: list[Path]) -> list[str]:
    paths = [Path("~/.config/trajectory-render/redact.txt").expanduser(), *extra]
    out = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines() if p.name.endswith(".txt") else [text]
        out += [x.strip() for x in lines if len(x.strip()) >= 8 and not x.strip().startswith("#")]
    return sorted(set(out), key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> tuple[str, int]:
    n = 0
    for s in secrets:
        if s in text:
            n += text.count(s)
            text = text.replace(s, "[REDACTED]")
    return text, n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out", type=Path, help="default /root/pi-runs/<benchmark>")
    ap.add_argument("--ingest", action="store_true", help="upload to the local pika (does not publish)")
    ap.add_argument("--prices", type=Path, help="prices JSON for cost (e.g. scripts/prices-360.json)")
    ap.add_argument("--tasks", type=Path, help="JSON {task id: one or two sentence description} shown on session pages")
    ap.add_argument("--server", default="http://127.0.0.1:7171")
    ap.add_argument("--token-file", type=Path, default=Path("/root/pika-data/ingest.token"))
    ap.add_argument("--secret-file", type=Path, action="append", default=[],
                    help="extra file whose content must never appear (e.g. an API key file); repeatable")
    a = ap.parse_args()

    bench = a.benchmark
    out = a.out or Path("/root/pi-runs") / safe(bench)
    sessions_dir = out / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets(a.secret_file)
    rows = list(csv.DictReader(a.manifest.open(encoding="utf-8")))
    missing = {"trajectory", "task", "model"} - set(rows[0].keys() if rows else [])
    if missing:
        sys.exit(f"manifest lacks columns: {sorted(missing)}")

    results, files, total_redacted, request_files = [], [], 0, []
    used = set()
    for r in rows:
        traj_path = Path(r["trajectory"])
        task, model = r["task"].strip(), r["model"].strip()
        label = (r.get("label") or "").strip()
        stem = "-".join(filter(None, [safe(task), safe(model.split("/")[-1]), safe(label) if label else ""]))
        if stem in used:
            sys.exit(f"duplicate output name {stem}; add a distinct label column value")
        used.add(stem)
        raw = traj_path.read_bytes()
        traj = json.loads(raw)
        name = f"{bench}/{task}/{model.split('/')[-1]}" + (f" ({label})" if label else "")
        price = conv.load_price(a.prices, model)
        if a.prices and not price:
            print(f"warning: no price for {model}; cost left as recorded", file=sys.stderr)
        requests: list = []
        lines = conv.translate(traj, name=name, provider=(r.get("provider") or "").strip() or None, model=model,
                               cwd=str(out / f"{safe(task)}-{safe(model.split('/')[-1])}"),
                               thinking=(r.get("thinking") or "").strip() or None, source_bytes=raw,
                               fallback_end_ms=int(os.stat(traj_path).st_mtime * 1000),
                               price=price, attempts=conv.load_attempts(traj_path), requests_out=requests)
        text = "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in lines)
        text, n = redact(text, secrets)
        total_redacted += n
        dest = sessions_dir / f"{stem}.jsonl"
        dest.write_text(text, encoding="utf-8")
        files.append(dest)
        if requests:  # measured provider timing (streamed runs): uploaded next to the session
            rtext, n2 = redact(json.dumps(requests, ensure_ascii=False), secrets)
            dest.with_suffix(".requests.json").write_text(rtext + "\n", encoding="utf-8")
            request_files.append(dest.with_suffix(".requests.json"))
        # Per-trajectory figures for the benchmark page: steps = model calls that produced an answer.
        asst = [x["message"] for x in lines if x["type"] == "message" and x["message"]["role"] == "assistant"]
        ok = [m for m in asst if m.get("stopReason") not in ("error", "length")]
        metrics = {"steps": len(ok), "failedRequests": len(asst) - len(ok),
                   "toolCalls": sum(1 for m in asst for b in m["content"] if b.get("type") == "toolCall"),
                   "tokens": sum((m.get("usage") or {}).get("totalTokens", 0) for m in asst),
                   "cost": round(sum(((m.get("usage") or {}).get("cost") or {}).get("total", 0) for m in asst), 6),
                   "durationMs": max(0, int(conv.dt.datetime.fromisoformat(lines[-1]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
                                     - int(conv.dt.datetime.fromisoformat(lines[0]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000))}
        score = (r.get("score") or "").strip()
        verdict = (r.get("verdict") or "").strip() or {"1": "pass", "0": "fail"}.get(score, "unscored")
        results.append({"session_id": lines[0]["id"], "task": task, "model": model, "score": score, "verdict": verdict,
                        "detail": (r.get("detail") or "").strip(), "label": label, "trajectory": str(traj_path), "_metrics": metrics})
        print(f"{stem}: {len(lines)} lines" + (f", {n} secret occurrence(s) redacted" if n else ""))

    with (out / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["session_id", "task", "model", "score", "verdict", "detail", "label", "trajectory"])
        w.writeheader()
        w.writerows([{k: v for k, v in x.items() if k != "_metrics"} for x in results])
    print(f"{len(files)} sessions -> {sessions_dir}; scores -> {out / 'results.csv'}; redacted {total_redacted}")

    # The static site's mini-swe-agent page: its projects, and per session the task, model and verifier result.
    reg = HERE.parent / "mswea-projects.json"
    known = json.loads(reg.read_text()) if reg.exists() else {}
    known.setdefault("projects", []); known.setdefault("sessions", {}); known.setdefault("tasks", {})
    if a.tasks:
        known["tasks"].update(json.loads(a.tasks.read_text(encoding="utf-8")))
    if bench not in known["projects"]:
        known["projects"].append(bench)
    known["sessions"] = {k: v for k, v in known["sessions"].items() if v.get("project") != bench}
    for x in results:
        known["sessions"][x["session_id"]] = {"project": bench, "task": x["task"], "model": x["model"],
                                             "verdict": x["verdict"], **({"detail": x["detail"]} if x["detail"] else {}),
                                             **x["_metrics"]}
    reg.write_text(json.dumps(known, indent=1, ensure_ascii=False) + "\n")

    if a.ingest:
        subprocess.run([str(HERE / "pika_serve.sh")], check=True) if a.server.endswith(":7171") else None
        cmd = [sys.executable, "-I", str(HERE / "pika_ingest.py"), "--server", a.server, "--token-file",
               str(a.token_file), "--project", bench, *map(str, files)]
        subprocess.run(cmd, check=True)
        if request_files:
            spec2 = importlib.util.spec_from_file_location("pika_ingest", HERE / "pika_ingest.py")
            ing = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(ing)
            token = a.token_file.read_text().strip()
            for rf in request_files:
                reqs = json.loads(rf.read_text())
                for i in range(0, len(reqs), 200):
                    ing.post(a.server, "api/ingest/v1/batch", token,
                             {"client": {"host": socket.gethostname(), "pikaVersion": "mswea-import/1"}, "requests": reqs[i:i + 200]})
            print(f"uploaded provider timing for {len(request_files)} session(s)")
        print(f"ingested into {a.server} as project {bench!r}; NOT published (run scripts/publish.sh when ready)")


if __name__ == "__main__":
    main()
