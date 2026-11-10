#!/usr/bin/env python3
"""Translate mini-swe-agent trajectories into pi session JSONL that pika can ingest and render.

    python3 mswea_to_pi.py RUN/trajectory.traj.json -o out.jsonl \
        --name "netbench/05-emicro/glm-5.3" --provider 360 --model z-ai/glm-5.3

Supported inputs
  * mini-swe-agent 2.x tool-calling trajectories (``trajectory_format: mini-swe-agent-1.1``):
    roles system / user / assistant (``tool_calls``) / tool / exit.
  * mini-swe-agent 1.x text-based trajectories (``mini-swe-agent-1``, and the text-based model of 2.x):
    the action is the fenced ```bash (or ```mswea_bash_command) block of the assistant message and the
    observation is the next user message (``<returncode>..</returncode><output>..</output>``).

Mapping (pi session format v3, see pi docs / pika docs/SPEC.md)
  header ``session``  -> id (deterministic UUIDv7-shaped id from the start time and file hash), cwd
  ``session_info``     -> --name (the gallery title)
  ``model_change``     -> --provider / --model (default: the model in the trajectory config)
  system message       -> pi ``system`` message (hidden in the UI, kept for completeness)
  first user message   -> pi ``user`` message (the turn's prompt)
  assistant            -> pi ``assistant``: reasoning -> ``thinking`` block, text -> ``text`` block, each bash
                          action -> ``toolCall`` {name: bash, arguments: {command}}; usage, stopReason,
                          responseId, timestamp (request start) and durationMs (start -> response)
  tool / observation   -> pi ``toolResult`` (isError when the return code is non-zero or an exception occurred)
  other user messages  -> ``custom_message`` ``mini-swe-agent.feedback`` (format errors, timeouts, ...): they
                          are harness feedback, not new human prompts, so they stay inside the turn
  exit / info          -> ``custom_message`` ``mini-swe-agent.exit`` (exit status; never a score)

Timing: mini-swe-agent stamps each assistant/tool message when it is appended. A model call is taken to start
when the previous message ended (the agent queries immediately), so ``durationMs`` includes transport retries.
Trajectories without timestamps get synthetic, evenly spaced times and no durations.

The translation is deterministic: the same input and options always produce byte-identical output, so
re-ingesting is a no-op for pika. Credentials are not added; scrubbing remains pika's and publish.sh's job.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

TRANSLATOR_VERSION = "mswea_to_pi/3"
ACTION_RE = re.compile(r"```(?:bash|mswea_bash_command)\s*\n(.*?)\n```", re.DOTALL)
RETURNCODE_RE = re.compile(r"<returncode>\s*(-?\d+)\s*</returncode>")
OUTPUT_RE = re.compile(r"<output>\n?(.*?)\n?</output>", re.DOTALL)
STOP_REASONS = {"tool_calls": "toolUse", "function_call": "toolUse", "stop": "stop", "length": "length",
                "content_filter": "error"}


def iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def uuid7_like(ms: int, digest: bytes) -> str:
    """A UUIDv7-shaped id (time-ordered like pi's) whose random bits come from the content digest."""
    rand = int.from_bytes(digest[:10], "big")
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | (rand >> 68 & 0xFFF) << 64 | 0b10 << 62 | rand & ((1 << 62) - 1)
    h = f"{value:032x}"
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def text_of(content) -> str:
    """mini-swe-agent content is a string, or an OpenAI-style list of parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                out.append(part.get("text") or "")
            elif isinstance(part, str):
                out.append(part)
        return "\n".join(x for x in out if x)
    return str(content)


def ts_ms(message: dict) -> int | None:
    t = (message.get("extra") or {}).get("timestamp")
    if isinstance(t, (int, float)) and t > 0:
        return int(round(t * 1000 if t < 1e11 else t))
    return None


def parse_observation(text: str) -> tuple[str, int | None]:
    rc = RETURNCODE_RE.search(text)
    out = OUTPUT_RE.search(text)
    body = out.group(1) if out else text
    return body, int(rc.group(1)) if rc else None


def usage_of(u, price: dict | None, cost: float | None = None) -> dict | None:
    """pi usage from an OpenAI-style usage dict. With a price ({input, output} USD per 1M tokens) the cost is
    computed from the tokens (cached input billed as input); otherwise the trajectory's own cost is kept."""
    if isinstance(u, str):
        try:
            u = json.loads(u)
        except json.JSONDecodeError:
            try:
                import ast
                u = ast.literal_eval(u)
            except (ValueError, SyntaxError):
                return None
    if not isinstance(u, dict):
        return None
    prompt = int(u.get("prompt_tokens") or 0)
    output = int(u.get("completion_tokens") or 0)
    details = u.get("prompt_tokens_details") or {}
    cached = int((details.get("cached_tokens") if isinstance(details, dict) else 0) or u.get("prompt_cache_hit_tokens") or 0)
    cached = min(cached, prompt)
    reasoning = int(((u.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0)
    if price:
        c_in = (prompt - cached) * price["input"] / 1e6
        c_cache = cached * price.get("cacheRead", price["input"]) / 1e6
        c_out = output * price["output"] / 1e6
        cost_obj = {"input": c_in, "output": c_out, "cacheRead": c_cache, "cacheWrite": 0,
                    "total": c_in + c_cache + c_out, "totalFromProvider": False}
    else:
        cost_obj = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": float(cost or 0.0),
                    "totalFromProvider": False}
    return {"input": prompt - cached, "output": output, "cacheRead": cached, "cacheWrite": 0,
            "totalTokens": int(u.get("total_tokens") or prompt + output), "reasoning": reasoning, "cost": cost_obj}


def physical_requests(rows: list[dict]) -> dict[str, list[dict]]:
    """Group a model-attempts.jsonl (one row per physical HTTP request) by logical query id, in file order.
    Each item: {start_ms, end_ms, ok, cap, finish, usage, error}."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("event") not in ("response", "transport_error") or not r.get("query_id"):
            continue
        try:
            end = float(r["timestamp"]); dur = float(r.get("duration_s") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        err = None
        if r["event"] == "transport_error":
            status = f"HTTP {r['http_status']} " if r.get("http_status") not in (None, "", "None") else ""
            err = f"{r.get('error_type') or 'Error'}: {status}{(r.get('message') or '').strip()}"[:500]
        out.setdefault(r["query_id"], []).append({
            "start_ms": int(round((end - dur) * 1000)), "end_ms": int(round(end * 1000)), "ok": r["event"] == "response",
            "cap": r.get("cap"), "finish": r.get("finish_reason"), "usage": r.get("usage"), "error": err})
    return out


class Writer:
    def __init__(self, digest: bytes):
        self.lines: list[dict] = []
        self.parent: str | None = None
        self.digest = digest
        self.n = 0

    def entry_id(self) -> str:
        self.n += 1
        return hashlib.sha256(self.digest + self.n.to_bytes(4, "big")).hexdigest()[:8]

    def add(self, entry: dict, at_ms: int) -> dict:
        eid = self.entry_id()
        line = {"type": entry.pop("type"), "id": eid, "parentId": self.parent, "timestamp": iso(at_ms), **entry}
        self.parent = eid
        self.lines.append(line)
        return line


def translate(traj: dict, *, name: str, provider: str | None, model: str | None, cwd: str,
              thinking: str | None, source_bytes: bytes, fallback_end_ms: int,
              price: dict | None = None, attempts: list[dict] | None = None) -> list[dict]:
    messages = traj.get("messages")
    if messages is None and isinstance(traj.get("trajectory"), list):
        raise SystemExit("SWE-agent style trajectories (``trajectory`` steps) are not supported; use mini-swe-agent output")
    if not isinstance(messages, list) or not messages:
        raise SystemExit("no messages in trajectory")
    info = traj.get("info") or {}
    config = info.get("config") or {}
    cfg_model = ((config.get("model") or {}).get("model_name")) or None
    model = model or cfg_model or "unknown-model"
    if provider is None:
        provider = model.split("/", 1)[0] if "/" in model else "mini-swe-agent"

    # Timestamps: real ones where present; otherwise evenly spaced, ending at fallback_end_ms.
    stamps = [ts_ms(m) for m in messages]
    known = [t for t in stamps if t is not None]
    timed = bool(known)
    phys_starts = [r["start_ms"] for reqs in physical_requests(attempts or []).values() for r in reqs]
    if timed:
        first = min(known + phys_starts)  # a failed first request can start well before any message stamp
        start_ms = first - 1000
    else:
        start_ms = fallback_end_ms - 1000 * len(messages)
    # The version is part of the id: pika discards re-uploads of a deleted session id, so a changed translation
    # must get new ids (delete the old sessions first, then ingest).
    digest = hashlib.sha256(source_bytes + json.dumps([TRANSLATOR_VERSION, name, provider, model, cwd]).encode()).digest()
    sid = uuid7_like(start_ms, digest)
    w = Writer(digest)
    w.lines.append({"type": "session", "version": 3, "id": sid, "timestamp": iso(start_ms), "cwd": cwd})
    w.add({"type": "session_info", "name": name}, start_ms)
    w.add({"type": "model_change", "provider": provider, "modelId": model}, start_ms)
    if thinking:
        w.add({"type": "thinking_level_change", "thinkingLevel": thinking}, start_ms)

    clock = start_ms                      # end time of the previous message
    pending_calls: list[tuple[str, int]] = []  # text-based mode: (call id, call time) awaiting an observation
    seen_prompt = False
    call_counter = 0
    exit_info = None
    physical = physical_requests(attempts or [])
    used_queries: set[str] = set()
    query_order = list(physical)

    def failed_requests(reqs: list[dict]) -> None:
        """Requests that did not produce the final answer: transport errors and superseded (e.g. capped) responses."""
        for r in reqs:
            msg = {"role": "assistant", "content": [], "api": "openai-completions", "provider": provider, "model": model}
            if r["ok"]:
                usage = usage_of(r["usage"], price)
                if usage:
                    msg["usage"] = usage
                msg["stopReason"] = "length" if r["finish"] == "length" else "error"
                msg["errorMessage"] = (f"Response stopped at the {r['cap']}-token output cap; the request was retried"
                                       if r["finish"] == "length" else f"Response discarded ({r['finish']}); the request was retried")
            else:
                msg["stopReason"] = "error"
                msg["errorMessage"] = f"{r['error']} (request retried)"
            msg["timestamp"] = r["start_ms"]
            msg["durationMs"] = max(0, r["end_ms"] - r["start_ms"])
            w.add({"type": "message", "message": msg}, r["end_ms"])

    def unanswered(before_ms: int | None) -> None:
        """Queries that never produced an assistant message (e.g. every retry timed out) and ended before `before_ms`."""
        for q in query_order:
            reqs = physical[q]
            if q in used_queries or (before_ms is not None and reqs[-1]["end_ms"] > before_ms):
                continue
            used_queries.add(q)
            for r in reqs:
                msg = {"role": "assistant", "content": [], "api": "openai-completions", "provider": provider,
                       "model": model, "stopReason": "error", "errorMessage": r["error"] or "request failed",
                       "timestamp": r["start_ms"], "durationMs": max(0, r["end_ms"] - r["start_ms"])}
                w.add({"type": "message", "message": msg}, r["end_ms"])

    for i, m in enumerate(messages):
        role = m.get("role")
        extra = m.get("extra") or {}
        t = stamps[i] if timed else start_ms + 1000 * (i + 1)
        if t is None:
            t = clock
        t = max(t, clock)
        content = text_of(m.get("content"))

        if role == "system":
            w.add({"type": "message", "message": {"role": "system", "content": content}}, t)
        elif role == "user" and not seen_prompt:
            seen_prompt = True
            w.add({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": content}],
                                                   "timestamp": t}}, t)
        elif role == "assistant":
            if physical:
                unanswered_before = (physical.get(extra.get("adaptive_query_id") or "") or [{"start_ms": t}])[0]["start_ms"]
                unanswered(unanswered_before)
            blocks = []
            reasoning = m.get("reasoning_content") or (m.get("provider_specific_fields") or {}).get("reasoning_content")
            if not reasoning and isinstance(m.get("thinking_blocks"), list):
                reasoning = "\n\n".join(b.get("thinking", "") for b in m["thinking_blocks"] if isinstance(b, dict))
            if reasoning:
                blocks.append({"type": "thinking", "thinking": text_of(reasoning)})
            tool_calls = m.get("tool_calls") or []
            calls = []
            if tool_calls:
                if content.strip():
                    blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    raw_args = fn.get("arguments")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except json.JSONDecodeError:
                        args = {"raw": raw_args}
                    if not isinstance(args, dict):
                        args = {"value": args}
                    call_counter += 1
                    cid = tc.get("id") or f"mswea_call_{call_counter}"
                    blocks.append({"type": "toolCall", "id": cid, "name": fn.get("name") or "bash", "arguments": args})
                    calls.append(cid)
            else:
                actions = ACTION_RE.findall(content)
                thought = ACTION_RE.sub("", content).strip() if actions else content
                if thought:
                    blocks.append({"type": "text", "text": thought})
                if len(actions) == 1:  # mini-swe-agent executes exactly one action, otherwise a format error
                    call_counter += 1
                    cid = f"mswea_call_{call_counter}"
                    blocks.append({"type": "toolCall", "id": cid, "name": "bash", "arguments": {"command": actions[0]}})
                    calls.append(cid)
            response = extra.get("response") if isinstance(extra.get("response"), dict) else {}
            choice = (response.get("choices") or [{}])[0] if response.get("choices") else {}
            finish = choice.get("finish_reason") if isinstance(choice, dict) else None
            stop = "toolUse" if calls else STOP_REASONS.get(finish or "", "stop")
            msg = {"role": "assistant", "content": blocks, "api": "openai-completions", "provider": provider,
                   "model": model}
            usage = usage_of(response.get("usage"), price, extra.get("cost"))
            if usage:
                msg["usage"] = usage
            msg["stopReason"] = stop
            msg["timestamp"] = clock if timed else t
            if response.get("id"):
                msg["responseId"] = str(response["id"])
            if timed and clock > start_ms:  # the first call's start is unknown
                msg["durationMs"] = max(0, t - clock)
            timing = extra.get("timing") if isinstance(extra.get("timing"), dict) else {}
            reqs = physical.get(extra.get("adaptive_query_id") or "", [])
            if reqs:  # measured physical requests: failed/superseded ones first, then the answer's own timing
                used_queries.add(extra["adaptive_query_id"])
                final = reqs[-1] if reqs[-1]["ok"] else None
                failed_requests(reqs[:-1] if final else reqs)
                if final:
                    msg["timestamp"] = final["start_ms"]
                    msg["durationMs"] = max(0, final["end_ms"] - final["start_ms"])
            elif isinstance(timing.get("sent_at"), (int, float)):  # recorded by a timing-aware model wrapper
                msg["timestamp"] = int(timing["sent_at"] * 1000)
                end = timing.get("end_at") or (t / 1000)
                msg["durationMs"] = max(0, int(end * 1000) - msg["timestamp"])
            w.add({"type": "message", "message": msg}, t)
            pending_calls = [(c, t) for c in calls]
        elif role == "tool":
            cid = m.get("tool_call_id") or (pending_calls[0][0] if pending_calls else f"mswea_orphan_{i}")
            started = next((ct for c, ct in pending_calls if c == cid), clock)
            pending_calls = [(c, ct) for c, ct in pending_calls if c != cid]
            raw = extra.get("raw_output")
            rc = extra.get("returncode")
            if raw is None:
                raw, rc2 = parse_observation(content)
                rc = rc if rc is not None else rc2
            exc = extra.get("exception_info")
            is_error = bool(exc) or (isinstance(rc, int) and rc != 0)
            text = raw if raw else content
            if exc and exc not in text:
                text = f"{text}\n{exc}".strip()
            if rc is not None and rc != 0:
                text = f"{text}\n\n[exit code {rc}]".lstrip()
            w.add({"type": "message", "message": {
                "role": "toolResult", "toolCallId": cid, "toolName": "bash",
                "content": [{"type": "text", "text": text}], "isError": is_error,
                **({"durationMs": max(0, t - started)} if timed else {}), "timestamp": t}}, t)
        elif role == "user" and pending_calls:
            # Text-based mode: the observation of the single pending action.
            cid, started = pending_calls.pop(0)
            body, rc = parse_observation(content)
            is_error = rc is not None and rc != 0
            if rc is not None and rc != 0:
                body = f"{body}\n\n[exit code {rc}]"
            w.add({"type": "message", "message": {
                "role": "toolResult", "toolCallId": cid, "toolName": "bash",
                "content": [{"type": "text", "text": body}], "isError": is_error,
                **({"durationMs": max(0, t - started)} if timed else {}), "timestamp": t}}, t)
        elif role == "user":
            w.add({"type": "custom_message", "customType": "mini-swe-agent.feedback", "content": content,
                   "display": True}, t)
        elif role == "exit":
            unanswered(None)
            exit_info = {"exit_status": extra.get("exit_status"), "message": content}
            w.add({"type": "custom_message", "customType": "mini-swe-agent.exit",
                   "content": f"Agent exited: {extra.get('exit_status') or 'unknown'}" +
                              (f" — {content}" if content and content != extra.get("exit_status") else ""),
                   "display": True, "details": {"exit_status": extra.get("exit_status")}}, t)
        else:
            w.add({"type": "custom_message", "customType": f"mini-swe-agent.{role or 'unknown'}", "content": content,
                   "display": False}, t)
        clock = t

    unanswered(None)
    if exit_info is None and info.get("exit_status"):
        w.add({"type": "custom_message", "customType": "mini-swe-agent.exit",
               "content": f"Agent exited: {info.get('exit_status')}", "display": True,
               "details": {"exit_status": info.get("exit_status")}}, clock)
    return w.lines


def load_price(prices_path: Path | None, model: str) -> dict | None:
    """USD per 1M tokens for `model` from a prices JSON (see prices_360.py), or None."""
    if not prices_path:
        return None
    table = json.loads(Path(prices_path).read_text(encoding="utf-8"))
    row = table.get("models", {}).get(model)
    if not row:
        return None
    rate = float(table.get("usd_per_cny", 1.0)) if table.get("currency") == "CNY" else 1.0
    price = {"input": row["input_cny_per_m"] * rate if "input_cny_per_m" in row else row["input"],
             "output": row["output_cny_per_m"] * rate if "output_cny_per_m" in row else row["output"]}
    # Cache hits are billed at a fraction of the input price (360: one tenth) unless the table gives a price.
    if "cache_read_cny_per_m" in row:
        price["cacheRead"] = row["cache_read_cny_per_m"] * rate
    else:
        price["cacheRead"] = price["input"] * float(table.get("cache_read_ratio", 1.0))
    return price


def load_attempts(traj_path: Path, explicit: Path | None = None) -> list[dict] | None:
    """Per-request records (model-attempts.jsonl next to the trajectory, as written by the adaptive model wrapper)."""
    p = explicit or traj_path.with_name("model-attempts.jsonl")
    if not p.is_file():
        return None
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            x = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(x, dict):
            rows.append(x)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trajectory", type=Path, help="mini-swe-agent *.traj.json")
    ap.add_argument("-o", "--output", type=Path, help="output .jsonl (default: stdout)")
    ap.add_argument("--name", help="session title, e.g. <benchmark>/<task>/<model> (default: file stem)")
    ap.add_argument("--provider", help="provider shown in pika (default: model prefix)")
    ap.add_argument("--model", help="model id (default: info.config.model.model_name)")
    ap.add_argument("--thinking", help="optional thinking level note, e.g. high")
    ap.add_argument("--cwd", default="/workspace", help="working directory recorded in the session header")
    ap.add_argument("--prices", type=Path, help="prices JSON (e.g. scripts/prices-360.json) to compute costs")
    ap.add_argument("--attempts", type=Path, help="per-request log (default: model-attempts.jsonl beside the trajectory)")
    a = ap.parse_args()
    raw = a.trajectory.read_bytes()
    traj = json.loads(raw)
    end_ms = int(os.stat(a.trajectory).st_mtime * 1000)
    model = a.model or ((traj.get("info") or {}).get("config") or {}).get("model", {}).get("model_name")
    lines = translate(traj, name=a.name or a.trajectory.stem, provider=a.provider, model=a.model, cwd=a.cwd,
                      thinking=a.thinking, source_bytes=raw, fallback_end_ms=end_ms,
                      price=load_price(a.prices, model or ""), attempts=load_attempts(a.trajectory, a.attempts))
    text = "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in lines)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text, encoding="utf-8")
        print(f"{a.output}: {len(lines)} lines, session {lines[0]['id']}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
