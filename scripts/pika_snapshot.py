#!/usr/bin/env python3
"""Snapshot pika's anonymous read API (published projects only) into static JSON files.

    python3 pika_snapshot.py --server http://127.0.0.1:7171 --out site/data

The patched pika web UI (web/src/lib/staticApi.ts) answers every `api/public/v1/*` request
from these files, so the published site needs no backend. Layout:

    data/health.json, facets.json, sessions.json (every published session)
    data/s/<id>/{session,trace,tree,turns,entries,updates}.json, data/s/<id>/raw/<seq>.json
    data/stats/statistics_<days>_<exclude>.json
    data/stats/usage_<days>_<by>_<interval>_<exclude>.json
    data/search.json   (per-session text documents for client-side search)

Everything the public API returns is already credential-scrubbed by pika; secrets listed in
~/.config/trajectory-render/redact.txt (if present) are masked on top of that.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

DAYS = ["7", "30", "90", "all"]
EXCLUDE = ["false", "true"]
BY = ["", "model", "project"]


def load_literals() -> list:
    p = Path(os.environ.get("TRAJECTORY_REDACT_FILE", "~/.config/trajectory-render/redact.txt")).expanduser()
    if not p.is_file():
        return []
    vals = [l.strip() for l in p.read_text().splitlines() if l.strip() and not l.startswith("#") and len(l.strip()) >= 6]
    return sorted(set(vals), key=len, reverse=True)


class Client:
    def __init__(self, server: str):
        self.base = server.rstrip("/") + "/"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path: str, **params) -> object:
        q = {k: v for k, v in params.items() if v not in (None, "")}
        url = self.base + path + ("?" + urllib.parse.urlencode(q) if q else "")
        with self.opener.open(url, timeout=120) as r:
            return json.loads(r.read().decode())

    def pages(self, path: str, limit: int = 200, **params) -> list:
        items, cursor = [], None
        while True:
            page = self.get(path, limit=limit, cursor=cursor, **params)
            items.extend(page.get("items", []))
            cursor = page.get("nextCursor")
            if not cursor:
                return items


def message_text(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    out = []
    for b in c or []:
        t = b.get("type")
        if t == "text":
            out.append(b.get("text", ""))
        elif t == "thinking":
            out.append(b.get("thinking", ""))
        elif t == "toolCall":
            args = b.get("arguments") or {}
            out.extend(str(v) for v in (args.values() if isinstance(args, dict) else [args]))
    return "\n".join(out)


SEARCH_KIND = {"user": "user", "assistant": "assistant", "toolResult": "tool-result"}


def search_docs(entries: list) -> list:
    docs = []
    for e in entries:
        raw = e.get("raw")
        try:
            line = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        if not isinstance(line, dict):
            continue
        if line.get("type") == "message":
            msg = line.get("message") or {}
            kind = SEARCH_KIND.get(msg.get("role"))
            if not kind:
                continue
            text = message_text(msg)
        elif line.get("type") == "compaction":
            kind, text = "compaction", line.get("summary", "")
        else:
            continue
        if text.strip():
            docs.append({"seq": e['seq'], "entryId": e.get("id"), "kind": kind, "at": e.get("timestamp"), "text": text[:20000]})
    return docs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:7171")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    api = Client(args.server)
    pub = "api/public/v1/"
    out: Path = args.out
    if out.exists():
        shutil.rmtree(out)
    files: dict = {}

    def put(rel: str, obj) -> None:
        files[rel] = obj

    put("health.json", api.get("api/health"))
    put("facets.json", api.get(pub + "facets"))
    sessions = api.pages(pub + "sessions")
    put("sessions.json", {"items": sessions})

    search = []
    for s in sessions:
        sid = s["id"]
        d = f"s/{sid}/"
        put(d + "session.json", api.get(pub + f"sessions/{sid}"))
        put(d + "trace.json", api.get(pub + f"sessions/{sid}/trace"))
        put(d + "tree.json", api.get(pub + f"sessions/{sid}/tree"))
        put(d + "turns.json", {"items": api.pages(pub + f"sessions/{sid}/turns")})
        entries = api.get(pub + f"sessions/{sid}/entries", **{"from": 0, "limit": 1_000_000})["items"]
        put(d + "entries.json", {"items": entries})
        for e in entries:  # the UI links to raw lines directly (Inspector "raw" link)
            put(d + f"raw/{e['seq']}.json", e.get("raw"))
        put(d + "updates.json", api.get(pub + f"sessions/{sid}/updates", since=10**9))
        search.append({"sessionId": sid, "sessionTitle": s.get("title"), "project": s.get("project"),
                       "lastAt": s.get("lastAt"), "docs": search_docs(entries)})
    put("search.json", {"sessions": search})

    for days in DAYS:
        for ex in EXCLUDE:
            put(f"stats/statistics_{days}_{ex}.json", api.get(pub + "statistics", days=days, excludeUnpublished=ex))
            for by in BY:
                put(f"stats/usage_{days}_{by or 'total'}_default_{ex}.json",
                    api.get(pub + "usage", days=days, by=by, excludeUnpublished=ex))
    put("stats/usage_all_model_month_false.json", api.get(pub + "usage", days="all", by="model", interval="month", excludeUnpublished="false"))

    literals = load_literals()
    total = 0
    for rel, obj in files.items():
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        for lit in literals:
            text = text.replace(lit, "[REDACTED]")
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        total += len(text.encode())
    print(f"wrote {len(files)} files, {total / 1024:.0f} KiB, {len(sessions)} sessions -> {out}")


if __name__ == "__main__":
    main()
