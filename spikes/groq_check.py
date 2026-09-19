#!/usr/bin/env python3
"""M0 spike: Groq rate limits and structured-output support for the models this project plans
to use (gpt-oss-20b live, gpt-oss-120b post-call).

Checks, per model:
  - x-ratelimit-* response headers (are limits per-model or account-wide?)
  - JSON-schema structured output via response_format={"type": "json_schema", ...}
  - latency for a small, realistic-shaped request

Usage: python3 groq_check.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://api.groq.com/openai/v1"
MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

#: Found live 2026-09-19: default reasoning effort burns 150-200+ hidden "reasoning_tokens"
#: per call on both models before the JSON answer, and a too-small max_completion_tokens
#: truncates mid-reasoning with an opaque json_validate_failed (empty failed_generation).
#: "low" cuts that to ~20-45 tokens with no observed quality loss on this task.
REASONING_EFFORT = "low"
MAX_COMPLETION_TOKENS = 400

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "nudge",
        "schema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": ["opening", "discovery", "pitch", "objection_handling", "close"]},
                "nudge": {"type": ["string", "null"]},
            },
            "required": ["stage", "nudge"],
            "additionalProperties": False,
        },
    },
}


def load_key() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("GROQ_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("GROQ_API_KEY not found in .env")


def probe(model: str, key: str) -> None:
    print(f"\n=== {model} ===")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You analyze one turn of a sales call and return the call stage and an optional coaching nudge."},
            {"role": "user", "content": "Rep: 'So the price would be $50 a month plus a $30 setup fee.' Customer: 'That's more than I expected.'"},
        ],
        "response_format": SCHEMA,
        "temperature": 0.2,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "reasoning_effort": REASONING_EFFORT,
    }
    t0 = time.time()
    r = requests.post(f"{BASE}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)
    dt = time.time() - t0

    print(f"status={r.status_code}  latency={dt:.2f}s")
    for h in r.headers:
        if h.lower().startswith("x-ratelimit"):
            print(f"  {h}: {r.headers[h]}")

    if r.status_code != 200:
        print("error body:", r.text[:500])
        return

    data = r.json()
    content = data["choices"][0]["message"]["content"]
    print("raw content:", content)
    try:
        parsed = json.loads(content)
        print("parsed JSON OK:", parsed)
    except json.JSONDecodeError as e:
        print("JSON PARSE FAILED:", e)
    usage = data.get("usage", {})
    print(f"usage: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")


if __name__ == "__main__":
    key = load_key()
    for m in MODELS:
        probe(m, key)
