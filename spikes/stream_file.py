#!/usr/bin/env python3
"""M0 spike: AssemblyAI Universal-3-5-Pro STREAMING diarization, replayed from a file.

Owns the WebSocket client directly (not via Pipecat — see docs/PROTOCOL.md for why:
Pipecat 1.8.1's AssemblyAISTTService errors on SpeakerRevision and drops per-word speaker).

What this answers for M0:
  - Per-word / per-turn speaker label accuracy on a real (replayed) sales call.
  - Exact shape of Turn and SpeakerRevision messages on this account/key.
  - End-to-end latency: first partial, first final, revision-at-close overhead.

Usage:
    python3 stream_file.py <audio_file> [--speakers N] [--pace 1.0] [--out fixture.jsonl]

Requires ffmpeg on PATH. Docs: https://www.assemblyai.com/docs/api-reference/streaming-api/universal-3-pro-streaming
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import websockets

SAMPLE_RATE = 16000
CHUNK_MS = 100  # within the documented 50-1000ms range
BYTES_PER_SAMPLE = 2  # PCM16
CHUNK_BYTES = int(SAMPLE_RATE * (CHUNK_MS / 1000) * BYTES_PER_SAMPLE)

WS_BASE = "wss://streaming.assemblyai.com/v3/ws"


def load_key() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("ASSEMBLYAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("ASSEMBLYAI_API_KEY not found in .env")


def ffmpeg_pcm(path: str) -> subprocess.Popen:
    """Decode any input to 16kHz mono s16le PCM on stdout, streamed."""
    return subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-acodec", "pcm_s16le",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        stdout=subprocess.PIPE,
    )


def build_url(speakers: int | None, prompt: str, keyterms: list[str]) -> str:
    params = {
        "sample_rate": SAMPLE_RATE,
        "speech_model": "universal-3-5-pro",  # singular string on streaming (plural array on batch)
        "mode": "balanced",
        "speaker_labels": "true",
        # Verified live 2026-09-19 against the streaming API reference: the pin-language
        # param on streaming is the PLURAL `language_codes` (JSON array), not the singular
        # `language_code` a cached copy of this project's assemblyai-integration skill
        # claimed. See docs/PROTOCOL.md.
        "language_codes": json.dumps(["en"]),
        "prompt": prompt,
        "keyterms_prompt": json.dumps(keyterms),
    }
    if speakers:
        params["max_speakers"] = speakers
    return f"{WS_BASE}?{urlencode(params)}"


async def stream(path: str, speakers: int | None, pace: float, out_path: Path | None,
                  prompt: str, keyterms: list[str]) -> None:
    url = build_url(speakers, prompt, keyterms)
    key = load_key()
    fixture = out_path.open("w") if out_path else None

    def record(direction: str, msg: dict) -> None:
        if fixture:
            fixture.write(json.dumps({"t": time.monotonic(), "dir": direction, "msg": msg}) + "\n")

    t_connect = time.monotonic()
    async with websockets.connect(url, additional_headers={"Authorization": key}) as ws:
        print(f"connected in {time.monotonic() - t_connect:.2f}s", flush=True)

        turns: dict[int, dict] = {}  # turn_order -> latest Turn message
        t_first_partial: float | None = None
        t_first_final: float | None = None
        t_audio_done: float | None = None

        async def send_audio():
            nonlocal t_audio_done
            proc = ffmpeg_pcm(path)
            assert proc.stdout
            try:
                while True:
                    chunk = proc.stdout.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    await ws.send(chunk)
                    await asyncio.sleep((CHUNK_MS / 1000) / pace)
            finally:
                proc.stdout.close()
                proc.wait()
            t_audio_done = time.monotonic()
            print(f"[{t_audio_done - t_connect:6.2f}s] audio sent, sending Terminate", flush=True)
            msg = {"type": "Terminate"}
            record("send", msg)
            await ws.send(json.dumps(msg))

        async def recv_loop():
            nonlocal t_first_partial, t_first_final
            async for raw in ws:
                msg = json.loads(raw)
                record("recv", msg)
                mtype = msg.get("type")
                now = time.monotonic() - t_connect

                if mtype == "Begin":
                    print(f"[{now:6.2f}s] Begin  session={msg['id']}", flush=True)

                elif mtype == "Turn":
                    order = msg["turn_order"]
                    turns[order] = msg
                    final = msg["end_of_turn"]
                    if not final and t_first_partial is None:
                        t_first_partial = now
                    if final and t_first_final is None:
                        t_first_final = now
                    tag = "FINAL" if final else "partial"
                    spk = msg.get("speaker_label", "?")
                    print(f"[{now:6.2f}s] turn={order:<3} {tag:7} spk={spk}  {msg['transcript']!r}",
                          flush=True)

                elif mtype == "SpeechStarted":
                    print(f"[{now:6.2f}s] SpeechStarted", flush=True)

                elif mtype == "SpeakerRevision":
                    print(f"[{now:6.2f}s] SpeakerRevision: {len(msg['revisions'])} turn(s) revised",
                          flush=True)
                    for rev in msg["revisions"]:
                        order = rev["turn_order"]
                        old = turns.get(order, {}).get("speaker_label", "?")
                        new = rev["speaker_label"]
                        print(f"    turn={order}: speaker {old} -> {new}", flush=True)
                        if order in turns:
                            turns[order]["speaker_label"] = new
                            turns[order]["words"] = rev["words"]

                elif mtype == "Termination":
                    print(f"[{now:6.2f}s] Termination: "
                          f"audio={msg.get('audio_duration_seconds')}s "
                          f"session={msg.get('session_duration_seconds')}s", flush=True)
                    return

        await asyncio.gather(send_audio(), recv_loop())

    if fixture:
        fixture.close()
        print(f"\nraw messages saved to {out_path}")

    # --- summary --------------------------------------------------------
    finals = [t for t in turns.values() if t["end_of_turn"]]
    speakers_seen = sorted({t.get("speaker_label") for t in finals if t.get("speaker_label")})
    print("\n=== SUMMARY ===")
    print(f"final turns: {len(finals)}   speakers: {speakers_seen}")
    if t_first_partial:
        print(f"first partial at {t_first_partial:.2f}s into stream")
    if t_first_final:
        print(f"first final turn at {t_first_final:.2f}s into stream")
    print("\n=== FINAL TRANSCRIPT (post speaker-revision) ===")
    for order in sorted(t for t in turns if turns[t]["end_of_turn"]):
        t = turns[order]
        print(f"[spk {t.get('speaker_label', '?')}] {t['transcript']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--speakers", type=int, default=2, help="max_speakers (0 to omit)")
    ap.add_argument("--pace", type=float, default=1.0,
                     help="playback speed multiplier. Docs require audio sent no faster than "
                          "real time, so keep this at 1.0 unless testing that limit deliberately.")
    ap.add_argument("--out", type=Path, default=None, help="save raw messages as JSONL")
    ap.add_argument("--prompt", default="A sales call between a sales representative and a prospective customer.")
    ap.add_argument("--keyterms", nargs="*", default=["postpaid", "prepaid", "monthly rental"])
    args = ap.parse_args()

    asyncio.run(stream(
        args.audio,
        speakers=args.speakers or None,
        pace=args.pace,
        out_path=args.out,
        prompt=args.prompt,
        keyterms=args.keyterms,
    ))
