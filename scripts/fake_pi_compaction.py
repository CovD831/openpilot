#!/usr/bin/env python3
"""Fake Pi RPC process for compaction E2E: replays deterministic responses,
logs every received prompt message to $OP0_FAKE_LOG, and emits a large
usage figure so the engine's budget trigger fires within a few turns."""

import json
import re
import sys

args = sys.argv[1:]
log_path = args[args.index("--log") + 1] if "--log" in args else ""
usage_tokens = int(args[args.index("--usage") + 1]) if "--usage" in args else 30000
reply = args[args.index("--reply") + 1] if "--reply" in args else "ack"
echo_marker = "--echo-marker" in args  # reply with MARKER-*-N extracted from the prompt

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    request_id = request.get("id")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": request_id, "message": request.get("message")}, ensure_ascii=False) + "\n")
    outgoing = reply
    if echo_marker:
        found = re.search(r"MARKER-[A-Z]+-\d+", str(request.get("message") or ""))
        outgoing = found.group(0) if found else "marker not found"
    sys.stdout.write(json.dumps({"id": request_id, "type": "response", "success": True}) + "\n")
    message_end = {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "stopReason": "end_turn",
            "content": [{"type": "text", "text": outgoing}],
            "usage": {"input_tokens": usage_tokens},
        },
    }
    sys.stdout.write(json.dumps(message_end) + "\n")
    sys.stdout.write(json.dumps({"type": "agent_end"}) + "\n")
    sys.stdout.flush()
