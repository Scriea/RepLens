#!/usr/bin/env python3
"""M0 spike: batch speech_understanding.speaker_identification with speaker_type='role'.

Question: can AssemblyAI assign "sales representative" / "customer" directly, instead of
generic A/B labels we then have to map ourselves?

Usage: python3 batch_roles.py <audio_file>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://api.assemblyai.com"


def load_key() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("ASSEMBLYAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("ASSEMBLYAI_API_KEY not found in .env")


def main(path: str) -> None:
    hdr = {"authorization": load_key()}

    print(f"[1/3] Uploading {path} ...", flush=True)
    with open(path, "rb") as f:
        up = requests.post(f"{BASE}/v2/upload", headers=hdr, data=f)
    up.raise_for_status()
    audio_url = up.json()["upload_url"]

    body = {
        "audio_url": audio_url,
        "speaker_labels": True,
        "speakers_expected": 2,
        "speech_models": ["universal-3-5-pro"],
        "language_code": "en",
        "speech_understanding": {
            "request": {
                "speaker_identification": {
                    "speaker_type": "role",
                    "speakers": [
                        {"role": "sales representative"},
                        {"role": "customer"},
                    ],
                }
            }
        },
    }
    print("[2/3] Submitting with speech_understanding.speaker_identification (role) ...", flush=True)
    job = requests.post(f"{BASE}/v2/transcript", headers=hdr, json=body)
    if job.status_code != 200:
        print("API error:", job.status_code, job.text)
        job.raise_for_status()
    tid = job.json()["id"]
    print(f"      transcript id: {tid}", flush=True)

    print("[3/3] Polling ...", end="", flush=True)
    t0 = time.time()
    while True:
        r = requests.get(f"{BASE}/v2/transcript/{tid}", headers=hdr).json()
        if r["status"] == "completed":
            break
        if r["status"] == "error":
            sys.exit(f"\nERROR: {r.get('error')}")
        print(".", end="", flush=True)
        time.sleep(3)
    print(f" done in {time.time() - t0:.0f}s")

    out = Path("spikes/out") / f"batch_roles_{Path(path).stem}.json"
    out.write_text(json.dumps(r, indent=2))
    print(f"full response saved to {out}\n")

    utts = r.get("utterances") or []
    print("=== per-utterance speaker field ===")
    for u in utts:
        print(f"  speaker={u['speaker']!r:30} {u['text'][:70]}")

    su = r.get("speech_understanding") or {}
    print("\n=== speech_understanding block (top-level keys) ===")
    print(list(su.keys()) if su else "(none / empty)")
    if su:
        print(json.dumps(su, indent=2)[:3000])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sales_call_telephone_marketers.wav")
