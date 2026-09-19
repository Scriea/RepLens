#!/usr/bin/env python3
"""Feasibility test: AssemblyAI speaker diarization on a local audio file."""
import argparse, json, sys, time
import requests

BASE = "https://api.assemblyai.com"
LOW_CONF = 0.5  # words below this are shown in [brackets]: the model is guessing

def load_key():
    for line in open(".env"):
        line = line.strip()
        if line.startswith("ASSEMBLYAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("ASSEMBLYAI_API_KEY not found in .env")

def main(path, speakers_expected=None, lang="en"):
    hdr = {"authorization": load_key()}

    print(f"[1/3] Uploading {path} ...", flush=True)
    with open(path, "rb") as f:
        up = requests.post(f"{BASE}/v2/upload", headers=hdr, data=f)
    up.raise_for_status()
    audio_url = up.json()["upload_url"]

    print(f"[2/3] Submitting transcript job (speaker_labels=True, lang={lang}) ...", flush=True)
    body = {
        "audio_url": audio_url,
        "speaker_labels": True,
        "speech_models": ["universal-3-5-pro"],
    }
    # Auto language detection made universal-3-5-pro invent phrases on unclear
    # audio (e.g. "free calls to all over the world"). Pin the language instead.
    if lang == "auto":
        body["language_detection"] = True
    else:
        body["language_code"] = lang
    if speakers_expected:
        body["speakers_expected"] = int(speakers_expected)
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
    print(f" done in {time.time()-t0:.0f}s")

    with open("diarization_result.json", "w") as f:
        json.dump(r, f, indent=2)
    return r

def ms(x):
    return f"{int(x)//60000:02d}:{int(x)%60000//1000:02d}"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="?", default="concas.mp3")
    ap.add_argument("speakers", nargs="?", type=int, help="exact speaker count, if known")
    ap.add_argument("--lang", default="en", help="language code, or 'auto' to detect")
    a = ap.parse_args()
    r = main(a.audio, a.speakers, a.lang)
    utts = r.get("utterances") or []
    speakers = sorted({u["speaker"] for u in utts})
    print(f"\n=== SUMMARY ===")
    print(f"language: {r.get('language_code')}  duration: {r.get('audio_duration')}s  "
          f"confidence: {r.get('confidence')}")
    print(f"speakers detected: {len(speakers)} -> {', '.join(speakers)}")
    print(f"utterances: {len(utts)}")
    for s in speakers:
        su = [u for u in utts if u["speaker"] == s]
        talk = sum(u["end"] - u["start"] for u in su) / 1000
        words = sum(len(u["text"].split()) for u in su)
        print(f"  Speaker {s}: {len(su):3d} turns, {talk:7.1f}s talk time, {words:5d} words")

    low = [w for w in r.get("words") or [] if w["confidence"] < LOW_CONF]
    print(f"low-confidence words (<{LOW_CONF}): {len(low)}")

    print(f"\n=== TRANSCRIPT BY TURN  ([word] = confidence < {LOW_CONF}) ===")
    for u in utts:
        text = " ".join(f"[{w['text']}]" if w["confidence"] < LOW_CONF else w["text"]
                        for w in u["words"])
        print(f"[{ms(u['start'])}-{ms(u['end'])}] Speaker {u['speaker']}: {text}")
