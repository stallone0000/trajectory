# trajectory

Static gallery of [pi](https://github.com/earendil-works/pi) coding-agent trajectories, rendered with the
[pika](https://github.com/minhuw/pi-extensions/tree/master/services/pika) web UI (MIT).

```
pi run (server 37) --> ~/.pi/agent/sessions/*.jsonl
                      |  scripts/pika_ingest.py      (ingest API -> local pika server, publish project)
                      v
                local pika server 127.0.0.1:7171     (derives turns, trace, stats; scrubs credentials)
                      |  scripts/pika_snapshot.py    (public API -> site/data/*.json)
                      v
 viewer/ (pika web + static transport) --> site/ --> GitHub --> Render static site
```

## Layout

| Path | What |
| --- | --- |
| `site/` | **The published static site** (Render publish directory). Built output; commit it. |
| `site/data/` | JSON snapshots of pika's public API, one folder per session under `data/s/<id>/`. |
| `viewer/` | pika's web UI, patched to read `data/` instead of a server (`src/lib/staticApi.ts`). |
| `scripts/publish.sh` | One shot: ingest sessions, rebuild `site/`, commit, push. |

## Publish new trajectories (on server 37)

```bash
cd /root/trajectory
scripts/publish.sh --project <benchmark-name> /root/.pi/agent/sessions/--root-pi-runs-xxx--/*.jsonl
```

`--project` groups sessions in the gallery (Project filter). After editing `viewer/`, run
`scripts/build_site.sh --viewer` before publishing.

## mini-swe-agent trajectories

`scripts/mswea_to_pi.py` translates a mini-swe-agent `*.traj.json` (2.x tool-calling and 1.x text-based) into a
pi session JSONL, so pika renders it like a pi run: thinking, bash calls with exit status, per-call duration,
tokens, harness feedback (`mini-swe-agent.feedback`) and the exit status (`mini-swe-agent.exit`). Scores are never
put into the session. Tests: `python3 scripts/test_mswea_to_pi.py`.

Batch import (writes `/root/pi-runs/<benchmark>/sessions/*.jsonl` and `results.csv` with session_id, task, model,
score; `--ingest` uploads to the local pika under project `<benchmark>` but does **not** publish):

```bash
python3 scripts/mswea_import.py --benchmark <benchmark> --manifest manifest.csv --ingest \
    --secret-file /path/to/api.key        # any key file whose contents must never appear (redacted, never printed)
scripts/publish.sh                        # separate, deliberate step: publishes everything in the local pika
```

`manifest.csv` columns: `trajectory,task,model[,provider,score,thinking,label]`. `scripts/netbench_manifest.py` builds
one from the 360 network-benchmark ledger (example adapter). Re-running is idempotent (deterministic session ids).

## Render

Static site. **Build command:** empty. **Publish directory:** `site`. Every route has its own
`index.html`, so no rewrite rule is required; optionally add Rewrite `/*` -> `/index.html`.

## Credits

UI: [pika](https://github.com/minhuw/pi-extensions/tree/master/services/pika) by [@minhuw](https://github.com/minhuw), MIT License (`site/LICENSE-pika.txt`). Model marks from [LobeHub lobe-icons](https://github.com/lobehub/lobe-icons) (MIT); Aileron font (CC0).
