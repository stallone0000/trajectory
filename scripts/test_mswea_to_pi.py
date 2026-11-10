#!/usr/bin/env python3
"""Offline tests for mswea_to_pi.py (no network, no pika needed): python3 scripts/test_mswea_to_pi.py"""
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("mswea_to_pi", Path(__file__).with_name("mswea_to_pi.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TEXT_TRAJ = {  # mini-swe-agent 1.x text-based shape
    "info": {"exit_status": "Submitted", "submission": "diff --git a/x b/x",
             "config": {"model": {"model_name": "openai/gpt-x"}}},
    "trajectory_format": "mini-swe-agent-1",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant that can interact with a computer."},
        {"role": "user", "content": "<pr_description>Fix the bug</pr_description>"},
        {"role": "assistant", "content": "THOUGHT: look around.\n\n```bash\nls -la\n```"},
        {"role": "user", "content": "<returncode>0</returncode>\n<output>\na.py\n</output>"},
        {"role": "assistant", "content": "I will do two things.\n```bash\nls\n```\n```bash\npwd\n```"},
        {"role": "user", "content": "Please always provide EXACTLY ONE action in triple backticks, found 2 actions."},
        {"role": "assistant", "content": "THOUGHT: run tests\n\n```bash\npython -m pytest\n```"},
        {"role": "user", "content": "<returncode>1</returncode>\n<output>\nFAILED\n</output>"},
        {"role": "assistant", "content": "Done.\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && git diff\n```"},
        {"role": "user", "content": "<returncode>0</returncode>\n<output>\ndiff --git a/x b/x\n</output>"},
    ],
}

TOOL_TRAJ = {  # mini-swe-agent 2.x tool-calling shape
    "info": {"config": {"model": {"model_name": "z-ai/glm-5.3"}}},
    "trajectory_format": "mini-swe-agent-1.1",
    "messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "reasoning_content": "think",
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{\"command\": \"ls\"}"}},
                        {"id": "c2", "type": "function", "function": {"name": "bash", "arguments": "{\"command\": \"false\"}"}}],
         "extra": {"timestamp": 1000.0, "cost": 0.5, "response": {"id": "r1", "choices": [{"finish_reason": "tool_calls"}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
                             "prompt_tokens_details": {"cached_tokens": 40},
                             "completion_tokens_details": {"reasoning_tokens": 3}}}}},
        {"role": "tool", "tool_call_id": "c1", "content": "<returncode>0</returncode>\n<output>\na\n</output>",
         "extra": {"raw_output": "a\n", "returncode": 0, "timestamp": 1000.5}},
        {"role": "tool", "tool_call_id": "c2", "content": "x", "extra": {"raw_output": "", "returncode": 1, "timestamp": 1000.7}},
        {"role": "user", "content": "Format error: no tool call", "extra": {"timestamp": 1002.0}},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c3", "type": "function",
         "function": {"name": "bash", "arguments": "{\"command\": \"echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\"}"}}],
         "extra": {"timestamp": 1005.0}},
        {"role": "tool", "tool_call_id": "c3", "content": "", "extra": {"raw_output": "", "returncode": 0, "timestamp": 1005.1}},
        {"role": "exit", "content": "", "extra": {"exit_status": "Submitted", "submission": ""}},
    ],
}


def run(traj, **kw):
    opts = dict(name="b/t/m", provider=None, model=None, cwd="/w", thinking=None,
                source_bytes=json.dumps(traj).encode(), fallback_end_ms=2_000_000_000_000)
    opts.update(kw)
    return m.translate(traj, **opts)


def msgs(lines, role):
    return [x["message"] for x in lines if x["type"] == "message" and x["message"]["role"] == role]


class TextMode(unittest.TestCase):
    def setUp(self):
        self.lines = run(TEXT_TRAJ)

    def test_header_and_chain(self):
        h = self.lines[0]
        self.assertEqual((h["type"], h["version"], h["cwd"]), ("session", 3, "/w"))
        parents = [x["parentId"] for x in self.lines[1:]]
        ids = [x["id"] for x in self.lines[1:]]
        self.assertIsNone(parents[0])
        self.assertEqual(parents[1:], ids[:-1])
        self.assertEqual(self.lines[2]["provider"], "openai")

    def test_actions_become_tool_calls(self):
        calls = [b for a in msgs(self.lines, "assistant") for b in a["content"] if b["type"] == "toolCall"]
        self.assertEqual([c["arguments"]["command"] for c in calls],
                         ["ls -la", "python -m pytest", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && git diff"])
        texts = [b["text"] for b in msgs(self.lines, "assistant")[0]["content"] if b["type"] == "text"]
        self.assertEqual(texts, ["THOUGHT: look around."])

    def test_observations_pair_and_errors(self):
        results = msgs(self.lines, "toolResult")
        self.assertEqual(len(results), 3)
        self.assertEqual([r["isError"] for r in results], [False, True, False])
        self.assertIn("FAILED", results[1]["content"][0]["text"])

    def test_format_error_is_feedback_not_prompt(self):
        self.assertEqual(len(msgs(self.lines, "user")), 1)
        fb = [x for x in self.lines if x["type"] == "custom_message" and x["customType"] == "mini-swe-agent.feedback"]
        self.assertEqual(len(fb), 1)
        ex = [x for x in self.lines if x["type"] == "custom_message" and x["customType"] == "mini-swe-agent.exit"]
        self.assertEqual(ex[0]["details"]["exit_status"], "Submitted")

    def test_no_durations_without_timestamps(self):
        self.assertTrue(all("durationMs" not in a for a in msgs(self.lines, "assistant")))

    def test_deterministic(self):
        self.assertEqual(self.lines, run(TEXT_TRAJ))


class ToolMode(unittest.TestCase):
    def setUp(self):
        self.lines = run(TOOL_TRAJ, provider="360")

    def test_assistant_blocks_usage_timing(self):
        a = msgs(self.lines, "assistant")[0]
        self.assertEqual([b["type"] for b in a["content"]], ["thinking", "toolCall", "toolCall"])
        self.assertEqual(a["usage"]["input"], 60)
        self.assertEqual(a["usage"]["cacheRead"], 40)
        self.assertEqual(a["usage"]["cost"]["total"], 0.5)
        self.assertEqual((a["stopReason"], a["responseId"], a["provider"], a["model"]), ("toolUse", "r1", "360", "z-ai/glm-5.3"))
        self.assertNotIn("durationMs", a)  # first call: start unknown
        a2 = msgs(self.lines, "assistant")[1]
        self.assertEqual((a2["timestamp"], a2["durationMs"]), (1_002_000, 3000))

    def test_tool_results(self):
        r = msgs(self.lines, "toolResult")
        self.assertEqual([x["toolCallId"] for x in r], ["c1", "c2", "c3"])
        self.assertEqual([x["isError"] for x in r], [False, True, False])
        self.assertEqual((r[0]["durationMs"], r[1]["durationMs"]), (500, 700))

    def test_feedback_and_exit(self):
        kinds = [x["customType"] for x in self.lines if x["type"] == "custom_message"]
        self.assertEqual(kinds, ["mini-swe-agent.feedback", "mini-swe-agent.exit"])

    def test_session_id_is_uuid7_shaped(self):
        sid = self.lines[0]["id"]
        self.assertRegex(sid, r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class PhysicalRequestsAndPrices(unittest.TestCase):
    def setUp(self):
        traj = json.loads(json.dumps(TOOL_TRAJ))
        traj["messages"][2]["extra"]["adaptive_query_id"] = "q1"
        rows = [
            {"event": "transport_error", "query_id": "q1", "timestamp": "990.0", "duration_s": "30", "error_type": "Timeout",
             "http_status": "504", "message": "gateway timeout"},
            {"event": "response", "query_id": "q1", "timestamp": "999.5", "duration_s": "9.0", "finish_reason": "tool_calls",
             "usage": "{'prompt_tokens': 100, 'completion_tokens': 10}"},
            {"event": "response_accounting", "query_id": "q1"},
            {"event": "transport_error", "query_id": "q9", "timestamp": "1100", "duration_s": "60", "error_type": "Timeout",
             "message": "never answered"},
        ]
        self.lines = run(traj, provider="360", price={"input": 2.0, "output": 10.0}, attempts=rows)

    def test_failed_request_then_measured_answer(self):
        a = msgs(self.lines, "assistant")
        self.assertEqual(a[0]["stopReason"], "error")
        self.assertIn("504", a[0]["errorMessage"])
        self.assertEqual((a[0]["timestamp"], a[0]["durationMs"]), (960_000, 30_000))
        self.assertEqual((a[1]["stopReason"], a[1]["timestamp"], a[1]["durationMs"]), ("toolUse", 990_500, 9000))

    def test_unanswered_query_before_exit(self):
        a = msgs(self.lines, "assistant")
        self.assertEqual((a[-1]["stopReason"], a[-1]["durationMs"]), ("error", 60_000))
        kinds = [x.get("customType") or x.get("message", {}).get("role") for x in self.lines[-2:]]
        self.assertEqual(kinds, ["assistant", "mini-swe-agent.exit"])

    def test_cost_from_price(self):
        u = msgs(self.lines, "assistant")[1]["usage"]
        self.assertAlmostEqual(u["cost"]["total"], (60 * 2 + 40 * 2 + 10 * 10) / 1e6)


if __name__ == "__main__":
    unittest.main()
