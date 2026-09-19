# What has been verified live against AssemblyAI (and Groq)

Dated findings only. If it isn't here with a date, it hasn't been checked.

## 2026-09-11 — batch transcription feasibility

- `POST /v2/upload` then `POST /v2/transcript` with `speaker_labels: true,
  speech_models: ["universal-3-5-pro"]` round-trips a 45-49s clip in ~6s.
- `speech_model` (singular) is rejected with 400: deprecated, use `speech_models` (plural array).
- **Auto speaker-count detection under-counted on short clips.** A 45s two-speaker clip came
  back as 1 speaker with `speaker_labels: true` alone. Adding `speakers_expected: 2` (or
  `speaker_options.min/max_speakers_expected`) correctly split it into A/B. Docs recommend
  ~30s of continuous speech per speaker for reliable diarization — our second speaker had ~12s,
  which likely explains one mis-attributed 22s block even with the count forced.
- Confirmed independently with pitch-tracking that the merged block really does contain two
  voices (autocorrelation F0 estimate, not a library).
- **`language_detection: true` caused hallucinated words on unclear audio.** Same file,
  auto-detect on, produced a different invented phrase on every run ("all over the world" /
  "any number of people in the United States") in a ~1s span where word `confidence` dropped
  to 0.14-0.43. Pinning `language_code: "en"` reproduced the correct transcript identically
  across 9 runs. `temperature: 0` and a domain `prompt` did not fix it while auto-detect was on.
  Cross-checked against Whisper large-v3 (via Groq), which agreed with the pinned-English output.
  **Action: always pin `language_code`, never `language_detection: true`, on this stack.**
- Word `confidence < 0.5` reliably marks the words the model is guessing at; use as the
  evidence-rejection threshold.

## 2026-09-19 — carried over from `voice-agent-hackathon/`, not yet re-verified here

- Streaming: `wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&speech_model=universal-3-5-pro`.
  Singular `speech_model` string on streaming vs plural `speech_models` array on batch — easy
  to mix up.
- Streaming diarization: `speaker_labels=true` + `max_speakers` (1-10). Adds `speaker_label` to
  Turn events and `speaker` to final words. A late `SpeakerRevision` message (at most once,
  right before `Termination`) refines earlier turns' speaker labels by `turn_order` — must be
  applied retroactively to already-displayed turns.
- Pipecat 1.8.1's `AssemblyAISTTService._parse_message` raises on any message type outside
  Begin/Turn/SpeechStarted/Termination, so it silently errors on `SpeakerRevision`, and its
  `Word` model has no per-word `speaker` field. Decision: talk to the streaming WebSocket
  directly for this project rather than through Pipecat.
- Groq `openai/gpt-oss-20b`: tool-capable, ~0.7s latency, `reasoning_effort: "low"` halves
  completion tokens with no latency penalty. Free tier: 8,000 tokens/minute, 1,000 requests/minute.

## 2026-09-19 — streaming diarization on replayed sales calls (M0)

Ran `spikes/stream_file.py` (own `websockets` client, real-time pace, `speaker_labels=true`,
`max_speakers=2`) against `sales_call_telephone_marketers.wav` (49s, 7 turns) and
`car_negotiation.mp3` (45s, 5 turns, fast back-and-forth negotiation). Raw messages captured
as fixtures: `server/tests/fixtures/streaming/{sales_call_telephone_marketers,car_negotiation}.jsonl`.

- **Live-verified param names differ from the cached skill doc.** The streaming pin-language
  param is the plural `language_codes` (JSON array, e.g. `["en"]`), not the singular
  `language_code` this project's copy of `.claude/skills/assemblyai-integration/SKILL.md`
  Section 9 claimed. Fixed in `stream_file.py`; SKILL.md left as-is (upstream content, not ours
  to edit) but noted here per Operating Rule 12.
- **Connection + first partial:** ~1s to connect, first partial ~1-5s after speech starts,
  first final turn at 11-12s in (after several seconds of continued speech — end-of-turn needs
  silence or a real pause).
- **`SpeakerRevision` always arrived**, once, ~0.4-0.9s after `Terminate` was sent, exactly as
  documented. Revised 3-5 of the 5-7 turns.
- **Critical: turn-level `speaker_label` is unreliable and must not be used directly.** A single
  `Turn` frequently spans a real speaker change — most turns in `car_negotiation.mp3` contain
  both speakers' words, sometimes alternating twice within one turn (fast back-and-forth
  negotiation gives the end-of-turn detector no silence gap to split on). The turn-level
  `speaker_label` is some single value for the whole turn (majority/first-speaker, unconfirmed
  which) and is simply wrong for the minority-speaker portion.
- **The per-word `speaker` field inside `words[]` is correct where the turn-level label is not.**
  Verified by hand: reconstructing contiguous same-speaker runs from `words[].speaker` recovers
  the true alternating dialogue in both files, matching what a human reading the transcript
  would attribute to each speaker. Confirmed even for `SpeakerRevision`'s replacement `words[]`.
- **Action: `CallState` must build speaker segments from `words[].speaker`, never from the
  turn-level `speaker_label`.** The turn-level label is only a fallback for the rare word
  missing a `speaker` field. This was already the plan's design (segments "split by per-word
  speaker") — this spike is the empirical justification, not a new decision.
- Some words carry low confidence during the first pass and are corrected in `SpeakerRevision`
  (e.g. "Incorporated." 0.32 -> later confirmed correct) — consistent with the confidence-based
  evidence-rejection rule already adopted.
- No hallucinated phrases observed with `language_codes` pinned (unlike the batch
  `language_detection: true` hallucination found 2026-09-11) — small sample, keep watching.

## 2026-09-19 — batch role identification works, replaces our own A/B->role mapping

`spikes/batch_roles.py` on `sales_call_telephone_marketers.wav`, batch `/v2/transcript` with
`speech_understanding.request.speaker_identification = {speaker_type: "role", speakers:
[{role: "sales representative"}, {role: "customer"}]}`:

- `utterances[].speaker` came back as the literal strings `"sales representative"` /
  `"customer"`, correctly assigned (Mike -> rep, Nancy -> customer), matching ground truth on
  all 8 turns.
- `speech_understanding.response.speaker_identification` also returns the underlying mapping
  explicitly: `{"mapping": {"A": "sales representative", "B": "customer"}, "effort": "low",
  "status": "success"}` — useful to cross-check against the streaming A/B labels for
  live/batch agreement, without re-deriving it ourselves.
- **Action: `finalize_transcript` (post-call reviewer, node 1) uses this directly.** No LLM
  call needed to infer which speaker is the rep — drop that from the design.

## 2026-09-19 — Groq: shared rate-limit bucket, and reasoning tokens eat the JSON budget

`spikes/groq_check.py` + follow-up probes, `openai/gpt-oss-20b` and `openai/gpt-oss-120b`,
`response_format={"type": "json_schema", ...}`.

- **The 8,000 tokens/min and 1,000 requests/min limits are one account-wide bucket, not
  per-model.** Both models returned identical `x-ratelimit-remaining-*` headers on
  back-to-back calls. **Action: `evaluator/llm.py`'s rate limiter must be a single shared
  limiter used by both the live coach (20b) and the post-call reviewer (120b), not one per
  model** — they compete for the same budget.
- **Both models spend a large, variable share of `completion_tokens` on hidden
  `reasoning_tokens` before emitting the JSON answer**, at default reasoning effort: 159-198
  reasoning tokens out of ~210-255 total, on a trivial one-turn classification prompt.
  `max_completion_tokens=200` (my first, naive guess) truncated `gpt-oss-120b` mid-reasoning
  and produced `json_validate_failed` with an **empty** `failed_generation` — i.e. it failed
  silently with no diagnosable output, not a partial JSON string.
- **`reasoning_effort: "low"` fixes this and is not optional for this project.** Confirms and
  extends the boilerplate's finding (`voice-agent-hackathon/docs/PROTOCOL.md`, 2026-09-10,
  which measured 74->36 completion tokens on one case):

  | model | reasoning_effort | completion tokens | reasoning tokens |
  |---|---|---|---|
  | gpt-oss-20b | low | 65 | 21 |
  | gpt-oss-20b | medium | 236 | 186 |
  | gpt-oss-20b | (default) | **400 error** at a 300-token cap | — |
  | gpt-oss-120b | low | 118 | 44 |
  | gpt-oss-120b | medium | 231 | 177 |
  | gpt-oss-120b | (default) | 214 | 159 |

  **Action: every structured-output call sets `reasoning_effort: "low"` and
  `max_completion_tokens >= 400`** (generous headroom, since a too-small cap fails the whole
  call rather than truncating gracefully). At `low`, one live-coach call costs roughly 300-400
  tokens all in (prompt + completion) — call it ~20 calls/minute headroom shared across both
  models, which the limiter should budget against, not the naive "8000/big-prompt-size" math.
- `response_format={"type": "json_object"}` (the non-schema mode) requires the literal word
  "json" somewhere in the messages, or it 400s. Not used here (we use `json_schema` with an
  explicit schema), noted only because it's an easy trap if simplified later.
- Both models parsed correctly against a schema with a `["string", "null"]` union type — no
  issue there once `reasoning_effort` and the token cap were fixed.
