#!/usr/bin/env python3
"""Upload pi session JSONL files into a pika server through its ingest API.

    python3 pika_ingest.py --server http://127.0.0.1:7171 --token-file ~/pika-data/ingest.token \
        --project pi-trials ~/.pi/agent/sessions/*/*.jsonl

Every session is uploaded under the `--project` name (pika's unit of publication), so a
benchmark run can be published as one gallery. Re-running is safe: pika ignores lines it
already has and appends new ones (offset-based, see pika docs/SPEC.md "Ingest API").
Pass --publish to publish the project afterwards (needs a server running with --auth none).
"""
from __future__ import annotations

import argparse
import gzip
import json
import socket
import sys
import urllib.request
from pathlib import Path

MAX_BATCH_BYTES = 6 * 1024 * 1024


def _opener():
    # Talk to the (local) pika server directly, never through http(s)_proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(server: str, path: str, token: str | None, body: dict, method: str = "POST") -> dict:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if len(data) > 64 * 1024:
        data = gzip.compress(data)
        headers["Content-Encoding"] = "gzip"
    req = urllib.request.Request(server.rstrip("/") + "/" + path.lstrip("/"), data=data, headers=headers, method=method)
    with _opener().open(req, timeout=120) as resp:
        text = resp.read().decode()
    return json.loads(text) if text else {}


def read_header(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        first = json.loads(f.readline())
    if first.get("type") != "session" or "id" not in first:
        raise ValueError(f"{path}: not a pi session file (first line is not a session header)")
    return first


def upload(server: str, token: str, path: Path, project: str | None, host: str) -> int:
    header = read_header(path)
    sid = header["id"]
    meta = {"sessionId": sid, "cwd": header.get("cwd", "")}
    if header.get("parentSession"):
        meta["parentSession"] = header["parentSession"]
    if project:
        meta["project"] = project
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()  # trailing newline
    offset, i, sent = 0, 0, 0
    while i < len(lines) or (i == 0 and not lines):
        batch, size = [], 0
        while i < len(lines) and (not batch or size + len(lines[i]) < MAX_BATCH_BYTES):
            batch.append(lines[i].decode("utf-8"))
            size += len(lines[i]) + 1
            i += 1
        body = {
            "client": {"host": host, "pikaVersion": "trajectory-ingest/1"},
            "streams": [{"key": f"session:{sid}", "kind": "session", "offset": offset,
                         "lines": batch, "path": str(path), "meta": meta}],
        }
        try:
            post(server, "api/ingest/v1/batch", token, body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code == 409:  # gap/conflict: resume from the server's committed length
                info = json.loads(detail)
                if info.get("error") == "conflict":
                    raise SystemExit(f"{path}: server already has different content for {sid}: {detail}")
                committed = int(info["length"])
                acc, j = 0, 0
                while j < len(lines) and acc < committed:
                    acc += len(lines[j]) + 1
                    j += 1
                offset, i = acc, j
                continue
            raise SystemExit(f"{path}: HTTP {e.code}: {detail}")
        offset += size
        sent += len(batch)
        if not lines:
            break
    return sent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--server", default="http://127.0.0.1:7171")
    ap.add_argument("--token-file", type=Path, default=Path("~/pika-data/ingest.token").expanduser())
    ap.add_argument("--project", help="project name to file the sessions under (default: pika derives it from cwd)")
    ap.add_argument("--publish", action="store_true", help="publish --project after uploading (server must run with --auth none)")
    args = ap.parse_args()

    token = args.token_file.expanduser().read_text().strip()
    host = socket.gethostname()
    for f in args.files:
        n = upload(args.server, token, f, args.project, host)
        print(f"uploaded {f.name}: {n} lines")
    if args.publish:
        if not args.project:
            sys.exit("--publish needs --project")
        res = post(args.server, "api/v1/settings/publishing", None, {"project": args.project, "published": True}, method="PATCH")
        print("published:", [p["project"] for p in res.get("projects", []) if p.get("published")])


if __name__ == "__main__":
    main()
