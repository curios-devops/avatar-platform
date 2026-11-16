# Browser lip-sync vs MuseTalk (arena 5, 2026-11-15)

**Question.** Can lip-sync computed in the browser, with no GPU server and no server-side model, replace MuseTalk for a
talking character?

**Answer.** Yes for stylised characters (2D or the three.js human), but only through **visemes timed by the TTS's own
character timestamps** (method C). Audio-only analysis in the browser (lipsync-engine, HeadAudio) does not recover the
mouth shape: its open / closed / rounded classes agree with the text no better than chance on our voices. Plain
amplitude follows the voice better than either. No for a photoreal face: nothing here can paint a real mouth interior,
teeth or skin motion, which is what MuseTalk does.

## What was verified about the library from the chat

`github.com/Amoner/lipsync-engine`, read from the GitHub API and raw files on 2026-11-15 (commit `d4f1d4a`):

| Claim in the chat | What is true |
|---|---|
| MIT | Yes. `LICENSE` is MIT, "Copyright (c) 2025 Beer Digital LLC". |
| About 15 KB minified | Not checkable: there is no `dist/` in the repo. The source is 62 KB with comments; about 32 KB with comments and whitespace stripped (core, worklet, one renderer); about 8 KB gzipped. 15 KB minified is plausible for the core. |
| Web Audio API + AudioWorklet | Half true. The AudioWorklet is only a ring buffer that plays PCM chunks. The viseme classification runs **on the main thread**, once per `requestAnimationFrame`, reading an `AnalyserNode` (FFT 256). |
| Analyses audio, emits viseme events | Yes: five band energies + RMS go through hand-written if/else thresholds (sibilant, fricative, "plosive", nasal, vowels), with a 2-frame hold. |
| Renderer-agnostic | Yes (SVG, Canvas and CSS renderers included). |
| Installable from npm | No. The README says `npm install @beer-digital/lipsync-engine`; neither that nor `lipsync-engine` exists on the npm registry. |
| Maturity | Three commits, all on 2026-02-07 (the day it was created), nothing since. 68 stars, 9 forks, two open pull requests (June and August 2026) without answer. `package.json` declares vitest but the repo has no test files. The repo ships a `CLAUDE.md` and its commits are co-authored by an AI model. README calls it "production-grade"; nothing backs that. |

Two behaviours found by measuring (both reproduced in Node and in Chrome):

- **It closes the lips on loud vowels.** Its "plosive" rule (intensity > 0.6 and a flat spectrum) fires on loud voiced
  frames, so at the library's default gain it shows PP or DD on 19 to 77 % of the loudest quarter of voiced frames (9
  clips). Our voices are mastered loud (ElevenLabs output, greetings at -14 LUFS). Feeding it 6 dB quieter drops that to
  0 to 30 % and lifts its correlation with the voice from 0.18 to 0.85 to 0.75 to 0.92. Its thresholds are absolute, so
  it needs a gain stage matched to each voice.
- **Its behaviour depends on the display's frame rate.** The hold is counted in frames, so on a 120 Hz screen it
  switches visemes about 1.5 times as often as at 60 Hz (11 to 19 vs 8 to 11 events/s).

It was used as method B, vendored unchanged (`vendor/lipsync-engine/`, with its licence).

**HeadAudio** (`github.com/met4citizen/HeadAudio`, MIT, commit `a390f12`) was suggested in parallel research as the
stronger audio-only option and was added as method H: MFCC features and 50 Gaussian prototypes with a Mahalanobis
classifier, running in an AudioWorklet; 34 KB in three files (`headaudio.min.mjs` 6.5 KB, `headworklet.min.mjs` 13 KB,
`model-en-mixed.bin` 14 KB); it has Jest tests and a training pipeline. Its own README says the audio-driven approach "is
less accurate ... than [the] text-driven approach". Its only model is English, trained on four Kokoro (HeadTTS) voices.
Vendored unchanged in `vendor/headaudio/` (dist for the browser, the source modules for Node).

## The methods

All of them produce weights over the 15 Oculus visemes (sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, I, O, U), which
go through the same pose blend and the same attack / release smoothing (`lib/visemes.js`), so only the input differs.

| | Input | Where it runs |
|---|---|---|
| **A** amplitude | RMS of the last ~20 ms, auto-gain, opens the jaw only | AudioWorklet (`lib/rms-worklet.js`) |
| **B** lipsync-engine | AnalyserNode spectrum, its classifier, intensity scales the shape | main thread, every frame |
| **H** HeadAudio | MFCC classifier, its own 120 ms hold and 100 ms ramp | AudioWorklet (main thread only ramps) |
| **C** text-timed | ElevenLabs character timestamps, rule-based grapheme to viseme (`lib/g2v.js`), looked up on the heard-audio clock, 50 ms lead | no audio analysis |

`lib/g2v.js` is Spanish first and close to phonemic: v = b (lips closed, not F), silent h, silent u in que / qui / gue /
gui, c and z before e / i are S (TH with `distincion` for Spain), n before p / b / v / m closes the lips, r / rr is a
tongue-tip tap (DD, not the rounded English RR), ll and consonant y are palatal (I). English is a rough approximation
(digraphs, silent final e, magic e, the pronoun I). C0 is the same rules with the text spread evenly over the voiced
span, i.e. what you get with the text but no timestamps.

## Inputs

- Three clips **with** character timestamps, made for this test: ElevenLabs `stream/with-timestamps`, model
  `eleven_v4_turbo` (the runtime's model), MEYA voices: Nova "¡Hola! Pregúntame lo que quieras sobre el espacio." (es),
  Hana "¿Te cuento un cuento? Primero dime tu nombre." (es), Imani "Hi, I'm Imani. What would you like to understand
  today?" (en). 3 requests, 150 characters, on the account's grant tier (under 0.05 USD at list price).
  `fetch_timed.py` also stored when each chunk arrived (all audio arrived within about 300 ms of the first chunk, 0.8 to
  1.0 s after the request).
- Six greetings without timestamps, copied from `ManyMe/apps/web/public/media/voice/` (nova, hana, imani, kai in es;
  nova, hana in en). These were performed with audio tags, so no text timing is used on them.

## Numbers

Offline (`node offline.mjs`, 60 frames/s, 24 kHz; the vendored B and H code runs unchanged in Node, B on an AnalyserNode
emulated to the Web Audio spec). r and lag: mouth opening vs the voice's RMS envelope, best shift within +-250 ms,
positive = mouth late, the same metric as round 4 (`lab/a2f/arena4_metrics.py`). "Agree vs C": share of voiced frames
whose visible class (closed / open / rounded) matches C, with chance level and Cohen's kappa. Clips in the order Nova
es / Hana es / Imani en.

| Method | r vs voice | lag ms | viseme events/s | closed lips on loudest frames | agree vs C (chance) | kappa vs C |
|---|---|---|---|---|---|---|
| A amplitude | 0.92 / 0.92 / 0.93 | 17 / 17 / 17 | 6.6 / 4.8 / 5.3 | 0 / 0 / 0 | 0.73 (0.70) / 0.54 (0.55) / 0.70 (0.70) | 0.11 / -0.01 / -0.01 |
| B lipsync-engine | 0.23 / 0.52 / 0.85 | edge / edge / 33 | 10.6 / 10.9 / 8.2 | 0.58 / 0.55 / 0.19 | 0.59 (0.43) / 0.36 (0.38) / 0.47 (0.46) | 0.27 / -0.03 / 0.02 |
| B at -6 dB | 0.75 / 0.89 / 0.82 | 33 / 33 / 33 | 9.6 / 8.4 / 4.8 | 0.15 / 0 / 0.30 | 0.58 (0.53) / 0.39 (0.38) / 0.27 (0.27) | 0.09 / 0.01 / 0.01 |
| H HeadAudio | 0.18 / 0.32 / 0.42 | edge / edge / 200 | 6.9 / 6.9 / 6.3 | 0.42 / 0 / 0.51 | 0.58 (0.45) / 0.50 (0.52) / 0.48 (0.36) | 0.23 / -0.06 / 0.19 |
| H, already warmed up | 0.34 / 0.34 / 0.38 | 133 / 67 / 100 | 6.6 / 6.9 / 6.6 | 0.12 / 0 / 0.27 | 0.54 (0.49) / 0.55 (0.52) / 0.55 (0.45) | 0.10 / 0.07 / 0.18 |
| C text-timed, no lead | 0.35 / 0.52 / 0.45 | 117 / 67 / -17 | 11.2 / 11.5 / 10.3 | 0.30 / 0 / 0.11 | reference | reference |
| C with 50 ms lead | 0.37 / 0.54 / 0.44 | 67 / 17 / -67 | 11.2 / 11.2 / 10.3 | | 0.77 / 0.66 / 0.73 | 0.46 / 0.41 / 0.38 |
| C0 text, no timestamps | 0.43 / 0.53 / 0.27 | 167 / 67 / 33 | 11.2 / 10.9 / 10.3 | | 0.73 (0.55) / 0.41 (0.46) / 0.60 (0.52) | 0.40 / -0.10 / 0.17 |

"edge" = the best shift sits at the +-250 ms limit, i.e. there is no real alignment to report. Read the table this way:

- **r favours A by construction** (A is the envelope). For the other methods r mostly says whether the mouth opens when
  the voice is loud; text-timed visemes legitimately hold half-open shapes on quiet consonants, so C's 0.35 to 0.54 is
  not a defect. Round 4's three.js visemes reached 0.71 on a call with long silences, which inflate r.
- **Kappa is the shape test.** The row "C with 50 ms lead" is C compared with itself shifted by 50 ms: a perfect answer
  that is merely 50 ms off scores 0.38 to 0.46. Every audio-only method sits at -0.06 to 0.27, and only two clip-method
  pairs pass 0.2, both on Nova (B 0.27, where it gets credit for saying "closed" often, and H 0.23). A (jaw only, never rounded) scores the
  same as B and H.
- **Lip closures** (C enters "closed", mostly P / B / M; only 1 to 4 per clip, so thin): B finds most of them but
  precision is 0.20 to 0.43, i.e. it closes the lips 2 to 5 times as often as the text does. H found 1 of 7. C0 (no
  timestamps) found 2 of 7.
- **ElevenLabs' alignment is good but not perfect.** On Nova the opening "¡" absorbs 0.27 s although the voice starts
  at 0.10 s, so C is late there. Across the three clips C at lead 0 is +117 / +67 / -17 ms (mean +56); with a 50 ms
  lead, +67 / +17 / -67. Round 4 measured +83 ms with whisper timings. A 50 ms lead is the default here.
- Six greetings (A, B, H only): A r 0.82 to 0.94 at +17 ms; B r 0.18 to 0.41 at 0 dB and 0.76 to 0.92 at -6 dB; H r
  0.04 to 0.48.
- Cost in Node per 60 Hz frame: B 12 to 13 us, H 48 to 107 us (128-sample blocks, including MFCC).

**In a real browser** (Chrome, Mac M2 Pro, 120 Hz display, AudioContext at 24 kHz, base latency 5 ms, output latency
32 ms). Two sessions; the saved rows are in `results/browser_runs.json` (A, B, C) and
`results/browser_runs_with_headaudio.json` (A, B, H, C); lag is
measured against the time actually heard (`getOutputTimestamp`), so output latency is included.

| | lag ms | r | viseme events/s | main-thread analysis ms/frame (mean) | draw ms/frame | fps | AudioWorklet |
|---|---|---|---|---|---|---|---|
| A | 17 on every clip | 0.84 to 0.93 | 3 to 7 | 0.007 to 0.013 | 0.04 to 0.07 | 120 | yes |
| B, 0 dB | 0 to 233 | 0.15 to 0.90 | 11 to 19 | 0.017 to 0.031 | 0.03 to 0.04 | 120 | no |
| B, -6 dB | 17 | 0.86 to 0.94 | 7 to 13 | 0.017 to 0.024 | 0.03 | 120 | no |
| H | 67 to 250 | 0.30 to 0.55 | 11 to 15 | 0.013 to 0.023 (ramp only) | 0.03 | 120 | yes |
| C, 50 ms lead | 67 / 17 / -67 (one live run 83) | 0.33 to 0.54 | 10 to 11 | 0.005 to 0.010 | 0.02 to 0.04 | 120 | no analysis |

- C's lag in the browser equals the offline number in every run but one (a live run on Nova: 83 vs 67 ms), which means
  the heard-audio clock works and the offline numbers can be trusted.
- p95 of the analysis cost reads 0.1 ms for everything: that is Chrome's `performance.now()` resolution, not a cost.
  Main-thread cost is negligible for all four.
- Agreement with C in the browser: A 0.54 to 0.76 (chance 0.55 to 0.75), B 0.37 to 0.59 (chance 0.41 to 0.53), H 0.36
  to 0.51 (chance 0.36 to 0.48). Same conclusion as offline: chance level.
- **Live mode** (audio fed through `lib/pcm-queue-worklet.js` as it "arrives"): 100 ms chunks produced just in time
  (1.05 times real time, +-40 ms jitter, 150 ms prebuffer), and the real ElevenLabs arrival schedule. 9 live clip plays,
  0 underruns, C's cues arriving with each chunk; every method's lag was the same as with the whole file.

Screenshots (looked at):
- `results/browser_four_methods_nova_es.png`: one frozen frame at 1.95 s of Nova ("quieras"): A wide open, B lips closed
  on the loud vowel, H a half-open CH, C the text's shape.
- `results/browser_live_jit_nova_es_wide.png`: the same moment in live mode with A, B, C.
- `results/browser_runs_table.png`: 24 runs of the first session with the table.
- `results/browser_idle_sheet.png`: the page and the 15 mouth shapes.

## Can it replace MuseTalk?

- **Stylised 2D and 3D characters: yes, with text-timed visemes (C).** The mouth forms the words' shapes, it is on time
  within about +-70 ms with a 50 ms lead, it works while the audio is still streaming, it costs about 0.01 ms per frame
  on the user's device, and the GPU cost per call drops to zero for these characters (no MuseTalk pod, no video stream).
  The three.js human already speaks this format (`VISEME_TO_ARKIT`; map I / O / U to ih / oh / ou with
  `mouth-driver.js`'s `TO_HUMAN`).
- **Photoreal face: no.** Browser visemes move a drawn or rigged mouth. They cannot synthesise a real mouth interior,
  teeth, tongue or skin motion from a photo, which is exactly what MuseTalk (or Pruna clips) does. Keep MuseTalk only for
  a "photoreal" mode where that fidelity is the product.
- **What it needs in the product.** The runtime calls the plain ElevenLabs endpoint today (`ManyMe/services/runtime/
  src/manyme/voice/elevenlabs.py`, no timestamps). Switch it to `/stream/with-timestamps` (the earlier orchestrator in
  `avatar-platform-human/backend/app/orchestrator/tts.py` already does) and send the alignment with the audio; use the
  Spanish rules from `lib/g2v.js` (the orchestrator's `visemes.py` maps v to FF and r to RR, which is English).
- **Tier order the numbers support:**
  1. **C, text-timed visemes** whenever the TTS gives character timestamps.
  2. **A, amplitude** when it does not (user audio, a voice without timestamps, microphone). It follows the voice best
     (r 0.92, +17 ms) and is no worse than the audio classifiers at shape.
  3. **Audio-only viseme classification is not ready as a tier.** lipsync-engine needs a per-voice gain stage, is
     frame-rate dependent and unmaintained; HeadAudio is well built but its English Kokoro-trained model is at chance on
     our ElevenLabs voices. The original idea (audio analysis as the second tier, amplitude last) is not supported.
  - Text without timestamps (C0) is unreliable (kappa -0.10 to 0.40); do not use it as a tier.

**Next to test:** retrain HeadAudio on our own voices. Its training pipeline takes audio plus phoneme timestamps; the
ElevenLabs character timestamps plus `lib/g2v.js` give exactly that, in Spanish. If a Spanish ElevenLabs model gets
kappa near the 50 ms-shift yardstick (about 0.4), it becomes the fallback tier ahead of amplitude. Also: Safari and
iPhone (only Chrome on a Mac was run), more and longer clips (closure counts here are 1 to 4 per clip).

## Files

| File | What |
|---|---|
| `index.html`, `app.js`, `style.css` | The page: one clip, four drivers on the same audio, four identical faces, live numbers, run table; `window.__lipsync` for scripted runs. |
| `mouth-driver.js` | The adapter: `createMouthDriver({method, context, cues, clock, leadMs})`, `start(audioNode or MediaStream)`, `onViseme(cb)`, `setCues()`, `stop()`, `stats()`. Methods `amplitude`, `engine`, `headaudio`, `text`. Emits weights and a renderer-free pose; does not depend on the face. |
| `face2d.js` | Our own SVG face: blended mouth (open, width, round, press, tuck, tongue, teeth), blinks, small head motion. |
| `lib/visemes.js` | Viseme set, poses, blending, smoothing, `TO_HUMAN`. |
| `lib/g2v.js` | ElevenLabs alignment to viseme cues (Spanish rules, English approximation), even-spread estimate (C0), cue sampler. |
| `lib/amplitude.js`, `lib/rms-worklet.js` | Method A. |
| `lib/methods.js` | How B and H outputs become weights; HeadAudio's hold and ramp reproduced for Node. |
| `lib/pcm-queue-worklet.js` | Live mode: plays PCM as it arrives, reports position and underruns. |
| `lib/analyser-shim.js`, `lib/metrics.js` | AnalyserNode for Node (spec FFT / smoothing / dB), and the metrics. |
| `offline.mjs` | Node run of A, B, B -6 dB, H, H warm, C, C lead, C0 on all clips; `--series` writes per-frame curves. |
| `fetch_timed.py` | The three timed ElevenLabs clips (refuses to run again if they exist). |
| `clips/`, `results/` | Audio and alignment; numbers, curves and screenshots (media, not for git). |
| `vendor/lipsync-engine/`, `vendor/headaudio/` | Third-party code, unchanged, with licences. |

## How to run

```
node lab/arena5/lipsync/offline.mjs        # offline numbers -> results/offline.json and a table (under 1 s, ~85 MB)
cd lab/arena5/lipsync && python3 -m http.server 8790   # then open http://127.0.0.1:8790/ and press Play
```
