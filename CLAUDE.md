# Sales Call Evaluator — project brief for Claude Code

> Read whole before touching code. Full design history: `/home/screa/.claude/plans/lets-start-planning-to-sunny-ritchie.md`.

## 1. What this is

An agentic system that evaluates sales reps on real calls. While a call runs, the rep gets live
coaching nudges. When it ends, an autonomous reviewer scores the call against a sales rubric,
backs every judgment with verified evidence, and tracks each rep's trend across calls.

## 2. The rule that defines the design

**Verification is not agentic**, carried over from a sibling project (`voice-agent-hackathon/`,
"Ground Truth"). Concretely:

1. Numbers come from code, never from the LLM: talk ratio, pace, monologue length,
   interruptions, dead air are all computed from word timestamps in `evaluator/signals.py`.
2. Every LLM judgment cites evidence, and code checks it. A cited quote must fuzzy-match the
   transcript, spoken by the cited role, near the cited time (`evaluator/review/evidence.py`).
   Unverified judgments are shown as unverified and excluded from the score, not silently kept.
3. Live is provisional, the report is authoritative. Streaming diarization only self-corrects
   once, at session close (`SpeakerRevision`). The final report re-transcribes in batch mode.
4. Word `confidence < 0.5` is never evidence.

## 3. Stack

- Python 3.11, `uv`, FastAPI + uvicorn, pytest + pytest-asyncio (auto mode).
- STT: AssemblyAI Universal-3-5-Pro. Live = our own streaming WebSocket client (not Pipecat —
  see `docs/PROTOCOL.md` for why). Final = batch REST.
- **Always pin `language_code`, never `language_detection: true`** — verified to hallucinate on
  unclear audio (`docs/PROTOCOL.md`, 2026-09-11).
- LLM: Groq, free tier. `gpt-oss-20b` live, `gpt-oss-120b` for post-call scoring.
- Agent: LangGraph for the post-call reviewer (`evaluator/review/graph.py`).
- Storage: SQLite via SQLModel. Frontend: React + Vite + TS.

## 4. Repo layout

```
server/evaluator/    audio.py, stt/, call/, signals.py, llm.py, live_coach.py, review/, store.py, inbox.py
spikes/               throwaway feasibility scripts (test_diarization.py, stream_file.py)
rubrics/sales.yaml    scoring sections, weights, STT prompt/keyterms
calls/inbox/          drop a file here to start autonomous processing
scripts/make_calls.py synthetic calls with planted flaws + ground truth
docs/PROTOCOL.md      dated, verified-live facts only — don't re-derive, read it
web/                  React dashboard: live call, call report, employee trends
```

## 5. Non-negotiables

- Verify AssemblyAI/Groq/LangGraph APIs by introspecting the installed package or a live probe,
  not from memory — log the finding in `docs/PROTOCOL.md` with a date.
- Never commit `.env`, call audio, or the SQLite DB (see `.gitignore`).
- Every LLM call in the live path must stay inside Groq's free-tier rate limit — see
  `evaluator/llm.py`'s limiter before adding a new call site.
- Simulated/synthetic test calls must carry a ground-truth sidecar (`expected.json`); never
  hand-wave what a synthetic call "should" score.

## 6. Open questions — ask, don't guess

See "Risks" in the plan file: streaming diarization quality on real calls, per-model Groq rate
limits, whether rep/customer role assignment needs a manual override in the UI.
