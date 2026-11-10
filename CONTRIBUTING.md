# Contributing

Thanks for improving the TAS skill. Keep changes small, tested, and documented.

## Ground rules

1. **No Python dependencies.** The CLI must run on a stock `python3`.
2. **Keep the agent contract stable.** `SKILL.md` is read by the model; do not
   remove rules or commands without updating `README.md`, `CHANGELOG.md`, and
   `references/`.
3. **Never weaken verification.** QA must stay mandatory by default.
4. **Cache keys must include every synthesis parameter.** Changing text, voice,
   model, speed, volume, emotion, or format must be a cache miss.
5. **Fail fast on validation.** Bad language/model/voice/preset input exits 3
   before any network request.

## Add a preset

1. Pick a voice with `python3 skills/tas/scripts/tas.py voices -l <code>`.
2. Add it to `tts/assets/presets.json`:

```json
"mybrand": {
  "description": "One line describing the tone",
  "voices": {"en": "Adrian - Explorer", "bn": "Nayem"},
  "speed": 1.15,
  "emotion": "neutral"
}
```

3. Check it:

```bash
python3 skills/tas/scripts/tas.py presets
python3 skills/tas/scripts/tas.py tts "Test." -l en --preset mybrand --dry-run
```

## Add a recommended voice

Edit `RECOMMENDED` in `skills/tas/scripts/tas.py` and the table in
`tts/references/voices.md`. Verify the exact name with `voices -l <code>`.

## Test

```bash
scripts/selftest.sh            # offline, no API calls
scripts/selftest.sh --online   # one short synthesis + QA
```

CI runs `scripts/selftest.sh` on Python 3.9, 3.11, and 3.13 — keep it green.

Manual checks before a PR:

```bash
python3 skills/tas/scripts/tas.py tts "Hello" -l en -o /tmp/t.mp3
python3 skills/tas/scripts/tas.py verify /tmp/t.mp3
python3 skills/tas/scripts/tas.py conversation examples/dialog-bn.txt -l bn --dry-run
python3 skills/tas/scripts/tas.py tts --text-file examples/article-en.md -l en --dry-run
```

## Style

- Standard library only; no f-strings with nested quotes that break 3.9.
- Keep functions small and names descriptive.
- Progress output goes through `log()`; machine output through `emit()`.
- Errors: raise `TtsError(message, code=...)`; never `sys.exit()` inside helpers.
- Update `CHANGELOG.md` for user-visible changes.

## Rebuild the install artifact

```bash
scripts/build-skill.sh   # tas.skill only
scripts/package.sh       # tas.skill + tas.zip
```

Commit `tas.skill` only when the skill contents changed.
