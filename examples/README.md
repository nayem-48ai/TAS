# Examples

Run these from the repo root. `S` points at the bundled script.

```bash
S=skills/tas/scripts/tas.py
```

## 1. Single voice

```bash
python3 "$S" tts "Hello world, this is a test." -l en -o out/hello.mp3
python3 "$S" verify out/hello.mp3
```

## 2. Long markdown article (auto-chunked)

```bash
python3 "$S" tts --text-file examples/article-en.md -l en \
  --preset news -o out/article.mp3
```

Markdown, URLs, and emoji are stripped automatically. The script splits at
sentence boundaries, synthesizes in parallel chunks, merges, and verifies.

## 3. Bengali dialogue with two voices + subtitles

```bash
python3 "$S" conversation examples/dialog-bn.txt -l bn \
  --map "মানুষ=Nayem,AI=Pooja - Everyday Assistant" \
  --loudnorm --srt out/dialog.srt --manifest out/dialog.json \
  -o out/dialog.mp3
```

## 4. Plan before spending requests

```bash
python3 "$S" conversation examples/dialog-bn.txt -l bn --dry-run --json
```

## 5. Machine-readable output

```bash
python3 "$S" tts "JSON output." -l en -o out/json.mp3 --json > out/result.json
```

## 6. Custom voice UID

```bash
python3 "$S" uid "Cloned voice test." -v <voice-uuid> -o out/cloned.mp3
```

## 7. Speech-to-text (STT)

Transcribe an audio or video file into text with SRT/WebVTT subtitles. Long recordings are split into ~120 s chunks automatically, each re-encoded to 16 kHz mono 64 kbps MP3 so uploads stay under the ~4.5 MB API cap. Word timestamps are optional (SRT timing falls back to per-character estimates when disabled). Language is auto-detected from the first chunk, then reused; pass `-l <code>` if the result looks wrong (auto-detection can be unreliable on short clips).

```bash
S=skills/tas/scripts/tas.py

# Transcribe and write an SRT next to the input
python3 "$S" subtitle demo.mp3 -l en --srt demo.srt

# Transcribe to text + SRT + VTT (machine-readable)
python3 "$S" stt demo.mp3 --json \
  --srt demo.srt --vtt demo.vtt -o demo_transcript.txt

# Estimate word timestamps faster, with smaller chunks
python3 "$S" transcribe demo.mp3 -l bn --no-word-timestamps \
  --chunk-seconds 60 -o bn_transcript.srt

# Plan without real requests
python3 "$S" stt demo.mp3 --dry-run
```

**Limitations:** the underlying model is Whisper-based; automatic language
detection may disagree with your file on short clips, so **always pass
`-l <code>` when you know the language** (use `-l bn` for Bengali — auto-detect
confuses Bengali and Gujarati). **Never install Whisper** — the bundled script
does STT entirely through the Speakee API with the Python standard library.
