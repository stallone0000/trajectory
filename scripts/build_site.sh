#!/usr/bin/env bash
# Rebuild the static site in ./site from the local pika server and the patched viewer.
#   scripts/build_site.sh            # snapshot + assemble (reuses the last viewer build)
#   scripts/build_site.sh --viewer   # also rebuild the viewer (after editing viewer/)
set -euo pipefail
cd "$(dirname "$0")/.."
PIKA_SERVER="${PIKA_SERVER:-http://127.0.0.1:7171}"

if [[ "${1:-}" == "--viewer" || ! -d site-build ]]; then
  (cd viewer && { [[ -d node_modules ]] || npm ci --no-audit --no-fund; } && npm run build)
fi

rm -rf site.tmp && mkdir site.tmp
cp -r site-build/. site.tmp/
python3 -I scripts/pika_snapshot.py --server "$PIKA_SERVER" --out site.tmp/data
# Projects translated from mini-swe-agent (scripts/mswea_import.py) get their own page in the viewer.
if [[ -f mswea-projects.json ]]; then cp mswea-projects.json site.tmp/data/mswea-projects.json; else echo '{"projects": []}' > site.tmp/data/mswea-projects.json; fi

# NetBench public task pages (scripts/netbench_tasks_export.py -> netbench-site/netbench-tasks-site.json).
if [[ -f netbench-site/netbench-tasks-site.json ]]; then cp netbench-site/netbench-tasks-site.json site.tmp/data/; else echo '{"tasks": []}' > site.tmp/data/netbench-tasks-site.json; fi

# Deep links work on any static host: every client route gets its own copy of index.html.
for route in public public/mswea public/benchmark public/tasks public/statistics public/search; do
  mkdir -p "site.tmp/$route" && cp site.tmp/index.html "site.tmp/$route/index.html"
done
python3 -I - <<PY
import json, pathlib, shutil
root = pathlib.Path("site.tmp")
for s in json.loads((root / "data/sessions.json").read_text())["items"]:
    d = root / "public/s" / s["id"]
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(root / "index.html", d / "index.html")
PY
python3 -I - <<PY
import json, pathlib, shutil
root = pathlib.Path("site.tmp")
for t in json.loads((root / "data/netbench-tasks-site.json").read_text()).get("tasks", []):
    d = root / "public/tasks" / t["id"]
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(root / "index.html", d / "index.html")
PY
cp viewer/LICENSE-pika site.tmp/LICENSE-pika.txt
rm -rf site && mv site.tmp site
echo "site ready: $(find site -type f | wc -l) files, $(du -sh site | cut -f1)"
