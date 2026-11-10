# API Reference — Speakee

Base URL: `https://speakee.tnxbd.top` (override with `SPEAKEE_BASE`).

All calls are made by `scripts/tas.py`; this file documents what the script
does so failures can be diagnosed without reading all 1,100 lines.

## Endpoints

| Method | Path | Returns |
|---|---|---|
| `POST` | `/api/tts` | `audio/mpeg` |
| `GET` | `/api/languages` | `{"languages": [{"code", "name"}, ...]}` |
| `GET` | `/api/voices?language=<code>` | `{"voices": [{"id", "name", "gender"}, ...]}` |
| `GET` | `/api/models` | `{"models": ["sonic-3.5", ...]}` |
| `POST` | `/api/stt` | `{"text", "language", "words": [...]}` |

## Speech-to-text (STT) payload

`POST /api/stt` accepts `multipart/form-data`:

| Field | Value |
|---|---|
| `file` | the audio/video binary |
| `language` | ISO code or `auto` (default `auto`) |
| `word_timestamps` | `1` or `0` |

The response is JSON:

```json
{
  "text": "transcribed words",
  "language": "gu",
  "detection_confidence": 0.38,
  "engine": "whisper-large-v3-turbo",
  "duration": 8.28,
  "words": [{"word": "hello", "start": 0.0, "end": 0.5}, ...]
}
```

**Language caveat:** auto-detection is unreliable. The Whisper model confuses
Bengali and Gujarati — Bengali audio is detected as `gu` (~0.38 confidence) and
transcribed in Gujarati script. Passing `-l bn` produces correct Bengali.
Passing a wrong hint (`-l en`/`-l hi`) forces the wrong script while the
server echoes your requested language with confidence 1.0. **Always pass
`-l <code>` when you know the language.**

**Upload limit:** ~4.5 MB per request (HTTP 413 above it). The script splits
long recordings into `--chunk-seconds` (default 120) chunks and re-encodes
each to 16 kHz mono 64 kbps MP3, so uploads stay small.

## Synthesis payload

```json
{
  "language": "bn",
  "model": "sonic-3.5",
  "voice_id": "ec514ae6-7f63-4b38-b758-fa72b4542136",
  "text": "আপনার টেক্সট",
  "format": "mp3",
  "speed": 1.2,
  "volume": 1.0,
  "emotion": "neutral"
}
```

Custom voice UID mode sends `"language": "uid"` and the cloned voice UUID in
`voice_id`.

## Response validation

The script rejects a response unless all of these hold:

1. Body is non-empty.
2. `Content-Type` starts with `audio/`.
3. For MP3, the body starts with `ID3` or an MP3 frame sync (`0xFF`).

This prevents an HTML/JSON error page from being saved as `.mp3`.

## Retries and rate limits

| Condition | Behavior |
|---|---|
| `429 Too Many Requests` | waits for `Retry-After` (capped at 30 s) |
| `5xx`, timeout, connection reset | exponential backoff: 1, 2, 4, 8 s + jitter |
| other `4xx` | fails immediately with the server message |
| attempts | `--retries` (default 4) |

Lower `--workers` if 429s persist. The service is free — be polite.

## Chunking

- Text longer than `--chunk-limit` (default 1200 chars) is split at sentence
  boundaries (`।`, `.`, `!`, `?`, `…`, newlines) and hard-split only when a
  single sentence exceeds the limit.
- Each chunk is synthesized and cached separately, then merged in order.
- Merging uses ffmpeg when available (PCM intermediate, then encode); without
  ffmpeg, MP3 chunks are concatenated after stripping ID3 tags.
- `--dry-run` reports the chunk/request count before spending requests.

## Cache layout

```
~/.cache/speakee-tas/
├── segments/<sha256>.<fmt>   # one file per chunk
└── merged/<sha256>.<fmt>     # merged long-text outputs
```

- Key = hash of the full payload (text, language, model, voice, format, speed,
  volume, emotion), so any parameter change is a cache miss.
- Cache hits are counted and reported (`cache_hits` in `--json`).
- `--force` regenerates; `--no-cache` uses a temporary directory and cleans it
  up; `cache-clear` deletes everything.
- Override the location with `SPEAKEE_CACHE`.

## Audio QA (`verify`)

One ffmpeg pass with chained filters:

```
ebur128=peak=true,astats=metadata=1:reset=0,silencedetect=noise=-40dB:d=1.5
```

| Check | Pass | Warn | Fail |
|---|---|---|---|
| file size | ≥ 1 KB | — | < 1 KB |
| duration | ≥ 0.3 s | — | empty/short |
| integrated loudness | −35…−8 LUFS | outside −22…−12 | outside −35…−8 |
| true peak | ≤ −0.1 dBFS | — | > −0.1 (clipping) |
| leading/trailing silence | ≤ 2 s | > 2 s | — |
| internal silence | ≤ 5 s | > 5 s | — |
| decode | must succeed | — | no loudness/peak measured |

- QA runs automatically after `tts` and `conversation` (unless `--no-verify`).
- `verify FILE` re-checks any audio file.
- Exit code `5` = QA failed; warnings do not fail the run.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error |
| 2 | usage error (argparse) |
| 3 | validation (language, model, voice, preset, empty text) |
| 4 | network / API error |
| 5 | audio QA failed |

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `SPEAKEE_BASE` | `https://speakee.tnxbd.top` | API host |
| `SPEAKEE_CACHE` | `~/.cache/speakee-tas` | cache directory |
| `SPEAKEE_CHUNK_LIMIT` | `1200` | default chunk size |
