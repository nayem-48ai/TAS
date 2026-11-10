# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

## [2.2.0] — 2026-11-10

### Changed

- **Renamed the skill from `TTS` to `TAS`** (Text And Speech). Skill folder is
  now `skills/tas/`, the skill `name` is `tas`, the CLI is `scripts/tas.py`,
  and the install artifacts are `tas.skill` / `tas.zip`. The skill still does
  both text-to-speech (`TTS` command) and speech-to-text (`STT` command) — the
  new name just reflects both directions.
- **Online installation** from GitHub: `npx skills add nayem-48ai/TAS` and
  `git clone https://github.com/nayem-48ai/TAS.git`. README install section
  now leads with these one-liners.
- Cache directory renamed `~/.cache/speakee-tts` → `~/.cache/speakee-tas`;
  user agent `speakee-tts-skill` → `speakee-tas-skill`.

## [2.1.0] — 2026-11-10

### Added

- **STT command** (`stt`, `transcribe`, `subtitle`) — speech-to-text with
  word timestamps, automatic long-recording chunking, and SRT/VTT subtitle export.
- Automatic silent-aware chunking (`detect_silences` ffmpeg pass) splits long
  recordings near `--chunk-seconds`; each chunk is re-encoded to 16 kHz mono
  64 kbps MP3 to stay well under the ~4.5 MB upload cap.
- `--chunk-seconds`, `--no-chunk` (max ~3.5 MB), `--workers`, `--max-chars`
  (42), `--max-line-seconds` (6.0), `--no-word-timestamps` fallback, `--vtt`,
  `--srt-path`, and machine-readable STT `--json`.
- Auto-language first chunk, then reuse detected language across all chunks; warns
  on low confidence (< 0.5).
- Whisper English/Bengali transcription; SRT cue grouping and global timing
  clamp; exit code `3` = validation (e.g. upload too large).

## [2.0.0] — 2026-11-10

### Added

- Long-text chunking at sentence boundaries (`।`, `.`, `!`, `?`, `…`) with
  per-chunk caching and automatic merging.
- `verify` command and automatic post-synthesis audio QA: decode, duration,
  integrated loudness (ebur128), true peak/clipping, and silence analysis.
- `--json` machine-readable output for every command.
- Distinct exit codes: 1 error, 2 usage, 3 validation, 4 network/API, 5 QA.
- Voice presets (`news`, `story`, `assistant`, `audiobook`) and `presets`
  command, backed by `assets/presets.json`.
- `--srt` subtitle export for conversation mode.
- `--dry-run` plan output (chunks, requests, voices, output path).
- Text normalization: strips markdown, HTML, URLs, and emoji; `--raw` opt-out.
- ID3 metadata options: `--title`, `--artist`, `--album`.
- `Retry-After` support on HTTP 429; jittered exponential backoff.
- Progressive-disclosure docs: `references/api.md`, `references/voices.md`,
  `references/troubleshooting.md`.
- Repo packaging: README, LICENSE, CONTRIBUTING, CHANGELOG, VERSION,
  `scripts/selftest.sh`, `scripts/build-skill.sh`, `scripts/package.sh`,
  `tas.skill`.
- Public-release readiness: independent-project disclaimer, privacy /
  responsible-use / limitations sections, `SECURITY.md`, and GitHub Actions
  offline CI on Python 3.9/3.11/3.13.
- `.gitignore` keeps the installable `tas.skill` while ignoring build zips.
- Examples: Bengali dialogue, long English article, demo audio.

### Changed

- `SKILL.md` restructured around 10 non-negotiable rules and a 6-step workflow.
- Default speed remains 1.2; presets can override it.
- `--speed`, `--volume`, and `--emotion` now default to `None` internally so
  presets can supply values without overriding explicit user input.
- ffmpeg concat now encodes by output suffix (MP3/WAV/AAC) and always goes
  through a PCM intermediate.
- QA loudness warning range relaxed to −22…−12 LUFS to avoid false warnings on
  short clips.

### Fixed

- ffmpeg `libmp3lame inadequate AVFrame plane padding` failure when stitching
  MP3 segments (PCM intermediate).
- QA parser now uses ebur128's summary value instead of the first per-frame
  `I:` reading (−70 LUFS false failure).
- Conversation auto-mapping assigns distinct voices to non-narrator speakers.
- `--no-cache` temporary directories are always cleaned up.
- Deterministic output filenames (sha1 of content and parameters).

## [1.0.0] — 2026-11-10

### Added

- Initial skill: `tts`, `uid`, `conversation`, `voices`, `suggest`,
  `languages`, `models`, `cache-clear`.
- Parallel synthesis, retries, caching, preflight validation, ffmpeg stitching,
  `--manifest`, `--no-stitch`, `--loudnorm`, `--silence`, `--workers`.
