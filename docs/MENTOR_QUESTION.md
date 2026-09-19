**Subject: Need guidance — AssemblyAI speaker diarization merging two speakers**

Hi mentors,

We're building a salesman evaluation agent that scores sales calls from voice, so
reliable speaker separation is the foundation of the whole project. We're stuck on
diarization and would appreciate a pointer before we build on top of it.

**What we tested**
A 45-second, 2-speaker test clip (dual-mono MP3, 48 kHz) through the batch API:

```
POST https://api.assemblyai.com/v2/upload
POST https://api.assemblyai.com/v2/transcript
{
  "audio_url": "<upload_url>",
  "speaker_labels": true,
  "speech_models": ["universal-3-5-pro"],
  "language_detection": true
}
```

**What happened**

1. With `speaker_labels: true` alone, the API returned **1 speaker** and a single
   utterance covering the entire clip, even though there are clearly two voices.

2. Adding `"speakers_expected": 2` did split it into A and B, and the first two
   turns are correct. But one 22-second block is still attributed entirely to
   Speaker A while the text visibly interleaves both speakers:

   > "Visitors can now stay until 9 in the evening... **It serves tea, coffee, and
   > light snacks.** The librarian said, **the owner says** that the lock cards
   > have already..."

   Speaker A is narrating a library story and Speaker B a bakery story, so the
   bolded parts belong to B. Confidence on that utterance dropped to 0.82 versus
   0.97–0.99 on the correctly separated ones.

3. `speaker_options` with `min_speakers_expected: 2` / `max_speakers_expected: 4`
   gave the same result as `speakers_expected: 2`.

We verified independently with pitch tracking that there really are two voices
(roughly 166 Hz vs 140 Hz early on), and that they converge in pitch during the
section that gets merged. We also confirmed the file is dual-mono, so there's no
channel separation for the model to lean on.

**Our questions**

1. Is auto-detection expected to under-count speakers on short clips, or does this
   suggest something wrong in our request? Is there a minimum audio length or
   minimum turn duration for diarization to trigger?

2. `speakers_expected` vs `speaker_options.min/max_speakers_expected` — which is
   the current/recommended parameter for the `universal-3-5-pro` model, and does
   one override the other?

3. Does diarization handle overlapping or rapidly alternating speech at all, or do
   we need to pre-segment the audio ourselves before sending it?

4. Should we be using the `speech_understanding.speaker_identification` block
   (with `speaker_type: "role"` and `effort: "medium"`) instead of raw
   `speaker_labels`? Does the higher effort setting actually improve turn
   boundaries, or only the naming of speakers?

5. For sales calls specifically, is there a recommended capture setup? If we can
   record salesman and customer on separate channels, is there a supported way to
   have AssemblyAI treat each channel as a fixed speaker?

6. Do the hackathon API keys have any tier limits that would silently reduce
   diarization quality?

Happy to share the test clip and our full JSON response if that helps.

Thanks!

---

## Short version (for Slack/Discord)

Hi! Stuck on AssemblyAI speaker diarization for our salesman-evaluation project.

On a 45s clip with two clearly distinct voices, `speaker_labels: true` alone
returns **1 speaker**. Adding `speakers_expected: 2` splits it into A/B, but a
22s block still gets merged into one speaker even though the text obviously
alternates between the two (confidence drops to 0.82 there vs 0.97+ elsewhere).
`speaker_options.min/max_speakers_expected` behaves the same. Audio is dual-mono
so there's no channel hint. Model is `universal-3-5-pro`.

Questions:
1. Is auto speaker-count detection unreliable on short clips, or are we missing a param?
2. `speakers_expected` vs `speaker_options` — which is current for `universal-3-5-pro`?
3. Does diarization handle overlapping/fast-alternating speech, or must we pre-segment?
4. Is `speech_understanding.speaker_identification` (`speaker_type: "role"`,
   `effort: "medium"`) the better path for two-party sales calls?
5. If we record each party on a separate channel, can AssemblyAI pin one speaker per channel?

Can share the clip + full JSON response. Thanks!
