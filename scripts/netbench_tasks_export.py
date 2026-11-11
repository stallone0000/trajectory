#!/root/.local/bin/python3.12
"""Export public NetBench task pages for the static site (Terminal-Bench / Harbor Hub style).

    /root/.local/bin/python3.12 -I scripts/netbench_tasks_export.py > site-extra/netbench-tasks-site.json

Only public material is exported: instruction.md, task.toml and files under environment/. Files under solution/ and
tests/ are listed by name and size only (content withheld to avoid benchmark contamination). Per-task READMEs are the
public drafts in netbench-site/readme/<id>.md.
"""
import json, pathlib, re, sys, tomllib

ROOT = pathlib.Path("/share/network-agent-benchmark-20261107")
HERE = pathlib.Path(__file__).resolve().parent.parent
TASKS = ["29-fast", "19-flowzip", "24-ez-save", "28-oscar", "22-hedge",
         "23-titrate", "27-fizzle", "39-geminet", "41-prvtel", "43-vedrfolnir"]
MAX_TEXT = 200_000
WITHHELD_DIRS = ("solution/", "tests/")
SKIP_PARTS = {"__pycache__"}


def text_or_none(p: pathlib.Path):
    if p.stat().st_size > MAX_TEXT:
        return None
    b = p.read_bytes()
    if b"\0" in b:
        return None
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return None


PROVENANCE_KEYS = re.compile(r"^\s*(source|paper|conference|venue|authors?|doi|paper_url|artifact|implementation)\s*=.*\n?", re.M)


def scrub_toml(text: str) -> str:
    """Seed-paper provenance is internal metadata; the public page shows task.toml without it."""
    return PROVENANCE_KEYS.sub("", text)


def task_entry(tid: str):
    d = ROOT / "tasks" / tid
    toml_text = (d / "task.toml").read_text()
    cfg = tomllib.loads(toml_text)
    t, md, env, agent = cfg.get("task", {}), cfg.get("metadata", {}), cfg.get("environment", {}), cfg.get("agent", {})
    files = []
    for p in sorted(d.rglob("*")):
        if not p.is_file() or SKIP_PARTS & set(p.parts):
            continue
        rel = p.relative_to(d).as_posix()
        if rel == "README.md" or rel.endswith(".pyc"):
            continue  # internal maintenance notes; the public README is served separately
        entry = {"path": rel, "size": p.stat().st_size}
        if rel.startswith(WITHHELD_DIRS):
            entry["withheld"] = True
        elif rel in ("instruction.md", "task.toml", "LICENSE") or rel.startswith("environment/"):
            c = text_or_none(p)
            if c is not None and rel == "task.toml":
                c = scrub_toml(c)
            if c is None:
                entry["binary"] = True
            else:
                entry["content"] = c
        else:
            entry["withheld"] = True
        files.append(entry)
    # Withheld material is summarised per top-level directory: file names can hint at hidden cases.
    shown = [f for f in files if not f.get("withheld")]
    hidden = {}
    for f in files:
        if f.get("withheld"):
            top = f["path"].split("/")[0] + ("/" if "/" in f["path"] else "")
            n, s = hidden.get(top, (0, 0))
            hidden[top] = (n + 1, s + f["size"])
    files = shown + [{"path": top, "withheld": True, "count": n, "size": s} for top, (n, s) in sorted(hidden.items())]
    status = {}
    cs = ROOT / "authoring" / tid / "C-STATUS.json"
    if cs.exists():
        s = json.loads(cs.read_text())
        status = {"score": s.get("score"), "scope": s.get("acceptance_scope")}
    readme_p = HERE / "netbench-site" / "readme" / f"{tid}.md"
    readme = readme_p.read_text() if readme_p.exists() else ""
    description = t.get("description", "")
    if not description:  # fall back to the public README's title
        import re
        m = re.search(r"^# (.+)$", readme, re.M)
        description = m.group(1).strip() if m else ""
    category = md.get("category", "networking")
    keywords = [k for k in dict.fromkeys(t.get("keywords", [])) if k != category]
    return {
        "id": tid,
        "name": f"netbench/{tid}",
        "description": description,
        "keywords": keywords,
        "category": category,
        "hardware": md.get("hardware", ""),
        "resources": {k: env.get(k) for k in ("cpus", "memory_mb", "storage_mb", "gpus", "network_mode", "workdir")},
        "agentTimeoutSec": agent.get("timeout_sec"),
        "review": {"score": status.get("score"), "status": "local-accepted", "formal": "pending Docker/Harbor validation"},
        "readme": readme,
        "instruction": (d / "instruction.md").read_text(),
        "files": files,
    }


def main():
    out = {"benchmark": "NetBench", "batch": "batch-2/3 (2026-11-11)", "tasks": [task_entry(t) for t in TASKS]}
    missing = [t["id"] for t in out["tasks"] if not t["readme"]]
    if missing:
        print(f"warning: no public README for {missing}", file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
