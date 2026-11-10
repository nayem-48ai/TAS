---
name: tas
description: >-
  Convert text into spoken audio AND transcribe audio/video back into text and
  subtitles using the Speakee API. This skill does BOTH text-to-speech (TTS:
  speak, read aloud, voice-over, audio from text) AND speech-to-text (STT:
  transcribe audio, generate subtitles, SRT/WebVTT, captions, transcript from
  a recording). Use it whenever a user asks to speak, read aloud, pronounce,
  voice-over, generate audio/speech/MP3 from text; wants text-to-speech, TTS,
  voice synthesis, or a sound file; asks which voices or languages are
  available; wants to change the voice or use a custom voice UID; wants a
  multi-speaker conversation / dialogue audio; needs audio of a document,
  message, name, or foreign-language text; OR has an audio/video file and
  wants a transcript, subtitles, captions, an SRT, or the spoken words typed
  out. Also use it when another model produces a long answer the user wants
  to hear instead of read. Always read this skill BEFORE writing any TTS or
  STT code.
license: MIT
---

# TAS — Text & Speech, in Both Directions (Speakee API)

One script does **both** directions:

- **Text → Speech (TTS):** 40+ languages, 100+ voices, custom voice UID,
  long-text chunking, multi-voice conversation mode, ffmpeg stitching, audio QA.
- **Audio → Text (STT):** transcribe any audio/video file into text, word
  timestamps, and SRT/WebVTT subtitles, with automatic long-recording chunking.

Everything is done by the bundled script — **never re-implement it inline and
NEVER install anything** (no whisper, no torch, no faster-whisper, no pip):

```
<skill base dir>/scripts/tas.py
```

Typical install locations:
`~/.config/opencode/skills/tas/scripts/tas.py` (opencode),
`~/.claude/skills/tas/scripts/tas.py` (Claude Code), and
`~/.agents/skills/tas/scripts/tas.py` (the `skills` CLI, `npx skills add`).
The skill is **name `tas`** — load it with the name `tas`, never `tts`.

## Non-negotiable rules (apply to EVERY request)

1. **Use the bundled script.** No ad-hoc curl/python snippets for TTS or STT.
2. **NEVER install anything.** Do not run `pip install faster-whisper`,
   `pip install whisper`, `pip install torch`, or download any model. The
   script does STT entirely through the Speakee API with the Python standard
   library — no local model, no local download, no pip.
3. **Verify before delivering.** `tts` and `conversation` run audio QA
   automatically; a `QA: FAIL` must be fixed, never shipped.
4. **Report the result**: final path, duration, size, and QA status (TTS);
   final SRT/VTT/text path and cue count (STT).
5. **Preflight always.** Language, model, and voice are validated before any
   request; never send a guessed voice.
6. **Keep the cache on** unless the user asks otherwise. It makes re-runs fast
   and resumes failed conversations.
7. **Never guess a voice name.** Resolve it with `voices` / `suggest`, or pass
   the UUID.
8. **Respect the free API**: default `--workers 4`; lower it on HTTP 429.
9. **Let the script normalize text.** Markdown, URLs, HTML, and emoji are
   stripped by default; use `--raw` only when the user wants literal text.
10. **Never pre-split long text.** The script chunks at sentence boundaries and
    merges automatically.
11. **Always pass `-l <code>` for STT** when the language is known. Auto-detect
    is unreliable (Whisper confuses Bengali/Gujarati); `-l bn` is required for
    correct Bengali.
12. **Use `--json`** when another tool or script consumes the result.

## Commands

| Command | Purpose |
|---|---|
| `tts` | synthesize one text block (TTS) |
| `uid` | synthesize with a custom voice UID (`language=uid`) |
| `conversation` | multi-speaker dialogue → one stitched, verified MP3 |
| `stt` | transcribe an audio/video file → text (+ optional SRT/VTT) |
| `transcribe` | alias for `stt` |
| `subtitle` | transcribe and write an SRT |
| `verify` | run audio QA on any file |
| `voices -l <code>` | list voices for a language |
| `suggest -l <code>` | list voices with recommendations marked |
| `presets` | list built-in voice presets |
| `languages` | list supported languages |
| `models` | list models (`sonic-3.5` default) |
| `cache-clear` | delete the synthesis cache |

---

# Workflow A — Text to Speech (TTS)

### Step 1 — Scope
Identify: language (or let auto-detect work), tone (news / story / assistant /
audiobook), single speaker or dialogue, desired output path, and whether
subtitles (`--srt`) or metadata (`--title/--artist`) are needed.

### Step 2 — Choose language and voice
```bash
python3 "$S" languages                 # 43 codes
python3 "$S" suggest -l bn             # recommended voices first
python3 "$S" presets                   # curated voice sets
```
If the user has a custom voice UID, use `uid` mode. Otherwise prefer a preset
or a recommended voice over the default.

### Step 3 — Synthesize
Single speaker:
```bash
python3 "$S" tts "আপনার টেক্সট" -l bn -o out.mp3
python3 "$S" tts --text-file article.md -l en --preset news -o article.mp3
```
Dialogue:
```bash
python3 "$S" conversation dialog.txt -l bn \
  --map "মানুষ=Nayem,AI=Pooja - Everyday Assistant" \
  --loudnorm --srt dialog.srt -o dialog.mp3
```
Use `--dry-run` first for long or expensive runs.

### Step 4 — Verify
QA runs automatically. To re-check any file:
```bash
python3 "$S" verify out.mp3
```
Checks: decodes, duration, integrated loudness (ebur128), true peak/clipping,
and leading/trailing/internal silence. Exit code 5 means FAIL.

### Step 5 — Deliver
Report:
```
out.mp3 — 2.8s, 0.04 MB, QA PASS (-18.9 LUFS, peak -4.2 dBFS)
```
Do not paste raw JSON unless asked.

### Step 6 — Reuse
Re-runs hit the cache (`~/.cache/speakee-tas`). Use `--force` to regenerate,
`cache-clear` to wipe.

---

# Workflow B — Speech to Text (STT)

Use this when the user has an **audio or video file** and wants a transcript,
subtitles, captions, or an SRT. **Do not install Whisper** — the bundled script
calls the Speakee `/api/stt` endpoint directly.

### Step 1 — Confirm the file
```bash
python3 "$S" verify /path/to/audio.mp3   # optional: confirm it decodes
ls -la /path/to/audio.mp3
```

### Step 2 — Choose the language
```bash
# Auto-detect (unreliable — Whisper confuses Bengali/Gujarati):
python3 "$S" stt audio.mp3

# ALWAYS prefer explicit language when known:
python3 "$S" stt audio.mp3 -l bn
```
**Important:** pass `-l <code>` for the correct script. For Bengali use
`-l bn`; auto-detect returns Gujarati for Bengali audio. Low-confidence
(`< 0.5`) warnings mean the detected language is probably wrong.

### Step 3 — Transcribe + make subtitles
```bash
# Write SRT + VTT next to the input, and save the transcript:
python3 "$S" stt audio.mp3 -l bn \
  --srt --srt-path audio.srt --vtt --vtt-path audio.vtt \
  -o audio.txt

# Shorthand: just the SRT (subtitle command):
python3 "$S" subtitle audio.mp3 -l bn -o audio.srt

# Machine-readable JSON (for other tools):
python3 "$S" stt audio.mp3 -l bn --json -o result.json

# Long recordings: auto-chunked ~120s; force smaller chunks or one upload:
python3 "$S" stt audio.mp3 -l bn --chunk-seconds 60
python3 "$S" stt audio.mp3 -l bn --no-chunk     # only if < ~3.5 MB
```

### Step 4 — Deliver
Report:
```
audio.srt — 111 cues (8.05 min, Bengali)
audio.txt — transcript saved
```
STT flags: `--srt`, `--srt-path`, `--vtt`, `--vtt-path`, `--no-word-timestamps`
(faster, estimated timing), `--chunk-seconds`, `--no-chunk`, `--workers`,
`--max-chars`, `--max-line-seconds`.

---

## Conversation mode (TTS)

Script format, one turn per line:

```
The show begins.                <- no "Speaker:" prefix -> narrator voice
মানুষ: ভাই, ২+২ কত?
AI: আপনার প্রশ্নটি গ্রহণ করা হয়েছে।
```

- Speaker labels are short tokens before `:` (≤16 chars, no spaces).
- Lines with **no** `Speaker:` prefix are the narrator / commenter. The narrator
  is mapped with the special key `narrator`, so a 3rd distinct voice is
  `--map "narrator=VoiceC,মানুষ=VoiceA,AI=VoiceB"`.
- `--map "speaker=voice"` accepts a voice name (fuzzy) or UUID.
- Without `--map`, distinct voices are assigned automatically.
- **Voices must be distinct.** If two speakers resolve to the same voice, the
  script prints a `WARNING`; map each speaker to a different voice. Always give
  the AI and the human different voices (and a 3rd voice for the narrator when a
  commenter/narrator line is present).
- `--silence 0.35` gap between turns; `--loudnorm` normalizes to −16 LUFS.
- `--manifest FILE` records every segment; `--srt FILE` writes subtitles.
- `--no-stitch` keeps individual segment files instead of one MP3.
- `--workers` controls parallel requests (default 4).

## Options (most used)

| Flag | Default | Meaning |
|---|---|---|
| `-l, --language` | auto-detect | ISO code or `uid` |
| `-m, --model` | `sonic-3.5` | `sonic-3.5` / `sonic-3` / `sonic-turbo` / `sonic-2` |
| `-v, --voice_id` | preset/default | voice name or UUID |
| `-o, --out` | auto | output file / directory (`--no-stitch`) |
| `-s, --speed` | `1.2` | 0.5–2.0 |
| `--preset` | — | `news`, `story`, `assistant`, `audiobook` |
| `--chunk-limit` | `1200` | characters per request |
| `--retries` | `4` | retries with exponential backoff |
| `--workers` | `4` | parallel requests |
| `--no-cache` / `--force` | off | bypass cache / regenerate |
| `--no-verify` | off | skip automatic QA (not recommended) |
| `--dry-run` | off | print the plan, make no requests |
| `--json` | off | machine-readable output |

## STT options

| Flag | Default | Meaning |
|---|---|---|
| `-l, --language` | `auto` | ISO code (use `bn` for Bengali) |
| `--chunk-seconds` | `120` | audio seconds per upload |
| `--no-chunk` | off | one request (max ~3.5 MB) |
| `--workers` | `2` | parallel uploads |
| `--srt` / `--srt-path` | off | write an SRT |
| `--vtt` / `--vtt-path` | off | write a WebVTT |
| `--no-word-timestamps` | off | faster; subtitle timing is estimated |
| `--max-chars` | `42` | max cue characters |
| `--max-line-seconds` | `6.0` | max cue seconds |
| `--timeout` / `--retries` | `300` / `3` | per-request timeout / retries |

## Caching and safety

- Segments are cached by content hash in `~/.cache/speakee-tas`; re-runs and
  retries resume automatically.
- Temporary concat files are always removed; `--no-cache` temp dirs are cleaned
  on exit.
- Responses are validated (`Content-Type: audio/*` + MP3 header), so error JSON
  is never saved as audio.
- HTTP 429 honors `Retry-After`; 5xx/timeouts retry with backoff; permanent 4xx
  fail immediately with the server message.
- STT runs entirely in-process with the Python standard library — no network
  install, no model download, no pip.
- Exit codes: `0` ok, `1` error, `2` usage, `3` validation, `4` network/API,
  `5` audio QA failed.

## Reference files

- `references/api.md` — endpoints, payload, validation, retries, caching.
- `references/voices.md` — language/voice catalog, UID mode, presets.
- `references/troubleshooting.md` — symptoms, fixes, common failure modes.
- `assets/presets.json` — curated voice presets (edit to add your own).
