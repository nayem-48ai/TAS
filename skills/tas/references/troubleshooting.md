# Troubleshooting

## Quick fixes

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot reach https://speakee.tnxbd.top` / `Name or service not known` | sandbox blocks the domain (DNS allow-list) | add `speakee.tnxbd.top` to allowed domains, or run the skill in Claude Code / opencode / a local shell |
| `Unsupported language 'xx'` | invalid code | `languages`, then use a valid code |
| `No voice matching ...` | wrong name/language | `voices -l <code>` or pass the UUID |
| `Ambiguous voice ...` | fuzzy name matches many | pass the exact UUID |
| `HTTP 429` | rate limited | retries handle it; lower `--workers` |
| `HTTP 4xx` | invalid request | read the server message; fix language/voice/text |
| `audio QA failed` | bad output | see QA lines; re-run with `--force` |
| `ffmpeg not found` | no ffmpeg | install ffmpeg or use `--no-stitch` |
| `could not decode audio` | corrupt/empty file | regenerate with `--force` |
| `--srt skipped` | no ffprobe | install ffmpeg/ffprobe |

## Sandboxed agents (claude.ai, CI runners)

The script needs outbound HTTPS to `speakee.tnxbd.top`. Some sandboxes allow
only a fixed domain list (`pypi.org`, `github.com`, `npmjs.org`, …), so DNS
fails with `Name or service not known`. The script detects this up front and
prints `Cannot reach https://speakee.tnxbd.top …`. Do not retry or rewrite the
script — either allow the domain in the sandbox settings, or run the skill in
an environment without a domain allow-list.

## STT-specific failure modes

- **Wrong script / language (Bengali → Gujarati)** – the Whisper model behind
  the Speakee STT API misdetects Bengali as Gujarati (`gu`, confidence ~0.38)
  and produces Gujarati script. This is a **server-side limitation, not a
  skill bug**. **Always pass `-l bn` for Bengali.** Passing `-l en`/`-l hi`
  forces the wrong script while echoing your language back with confidence 1.0.
- **Low confidence language detection** – auto-detection confidence < 0.5 on short clips. Pass `-l <code>` to force a language.
- **Empty transcript** – file too short (< 1 s) or contains no speech. Use `--no-verify` for testing, then verify manually.
- **Upload too large** – files > ~4.5 MB exceed the API limit. Split long recordings with `--chunk-seconds` or use `--no-chunk`.
- **Silence detection issues** – ffmpeg may misclassify silence, causing chunks to be too small. Adjust `--silence` (conversation mode) or ensure audio has clear gaps.
- **Word timestamps not generated** – word timestamps are on by default; only `--no-word-timestamps` turns them off. There is no `--word-timestamps` flag — omit the `--no-` flag to keep them.
- **Audio QA fails** – low loudness or clipping. The script runs `ebur128` QA; if it fails, check the transcript for obvious issues.
- **Bengali chunks time out silently** – the server is slower for Bengali; a 5-chunk parallel run can die after chunk 1 with no error. Use `--workers 1 --timeout 600 --retries 3` for long Bengali recordings.
- **Agent tries to `pip install whisper`** – **do not allow it.** The bundled
  script does STT entirely through the Speakee API with the Python standard
  library. No local model, no download, no pip. Point the agent at
  `scripts/tas.py stt`.

## Common failure modes to avoid

- **Reading markdown aloud.** `**bold**`, `#`, links, and emoji are stripped by default. Use `--raw` to keep them literal.
- **Pre-splitting long text.** The script chunks at sentence boundaries; manual splits create awkward pauses. Just pass the whole text or `--text-file`.
- **Guessing a voice.** English has 393 voices; a guessed name usually fails or picks something wrong. Use `suggest`/`voices` or a preset.
- **Shipping without QA.** A file can exist, be 0 bytes, be silent, or clip. The script verifies automatically — do not add `--no-verify` to "save time".
- **Wrong speaker mapping.** Labels are short tokens before `:` (≤16 chars, no spaces). A line like `The AI: said...` becomes a narrator line unless `AI` is a known label. Run `--dry-run` to inspect the mapping.
- **Forgetting `--loudnorm` in dialogue.** Mixed voices can differ by several LU; normalize to −16 LUFS for a consistent result.
- **Stale cache confusion.** If a file seems outdated, `--force` regenerates it. Cache keys include every parameter, so changes are cache misses anyway.
- **Huge parallel runs.** 139 segments at `--workers 12` can trigger 429s. Default 4 is polite; 6 is usually fine.

## Reading QA output

```
QA: PASS | -18.9 LUFS | peak -4.2 dBFS | silence 0.0/0.0/0.0s
```

The silence triple is **leading / max internal / trailing** in seconds.

| Status | Meaning |
|---|---|
| `PASS` | all checks passed |
| `WARN` | delivered, but loudness is outside the target or silence is long |
| `FAIL` | do not deliver; fix or regenerate |

Exit codes: `3` validation, `4` network/API, `5` QA failed.

## Debugging a specific segment

`--manifest FILE` records each segment (speaker, voice, text, file). Open the
manifest to find the exact cached file, then:

```bash
python3 "$S" verify /path/from/manifest.mp3
```

To regenerate only that turn, remove its cache file or run with `--force`.

## Network notes

- The API is public and free; no key is required.
- Corporate proxies may block `speakee.tnxbd.top`; set `SPEAKEE_BASE` to a
  mirror if one exists.
- Offline preflight is tolerant: if the language list cannot be fetched, the
  script does not block, but voice-name resolution still needs the network.
