# Voices & Languages

## Discover

```bash
S=/path/to/tts/scripts/tts.py
python3 "$S" languages           # 43 codes
python3 "$S" voices  -l en       # 393 voices for English
python3 "$S" suggest -l bn       # recommended voices marked
python3 "$S" presets             # curated sets
```

Voice specs can be a **name** (case-insensitive, fuzzy) or a **UUID**. The
script resolves names against the live voice list; ambiguous names fail with a
candidate list.

## Recommended voices

| Language | Voices |
|---|---|
| `bn` | `Nayem`, `Rubel - City Guide`, `Pooja - Everyday Assistant`, `News Reader` |
| `en` | `Ailsa - Warm Guide`, `Aarav - Old Time Storyteller`, `Adrian - Explorer` |
| `hi` | `Aarav - Old Time Storyteller` |

Default voice: `ec514ae6-7f63-4b38-b758-fa72b4542136` (bn "News Reader").

Rules of thumb:

- Narration / audiobook: `Aarav - Old Time Storyteller`, `Nayem`.
- Assistant / product demo: `Pooja - Everyday Assistant`, `Ailsa - Warm Guide`.
- News / explainer: `News Reader`, `Ailsa - Warm Guide`.
- Two-speaker dialogue: one warm voice + one clear voice (not two similar ones).

## Custom voice UID

Use when the user has a cloned voice UUID:

```bash
python3 "$S" uid "Text in the cloned voice" \
  -v 123e4567-e89b-12d3-a456-426614174000 -o cloned.mp3
```

- `uid` mode ignores `--language` (sends `language=uid`).
- `--voice_id` must be a UUID; invalid UUIDs fail fast (exit 3).
- Everything else (chunking, caching, QA, metadata) works the same.

## Presets

Presets map a tone to a voice per language plus speed/emotion:

| Preset | Tone | Speed |
|---|---|---|
| `news` | clear, neutral | 1.2 |
| `story` | warm, slower | 1.0 |
| `assistant` | friendly, brisk | 1.25 |
| `audiobook` | even, slow | 1.0 |

```bash
python3 "$S" tts --text-file chapter.md -l en --preset audiobook -o ch1.mp3
```

An explicit `--voice_id`, `--speed`, or `--emotion` overrides the preset.

### Add a preset

Edit `assets/presets.json`:

```json
{
  "presets": {
    "mybrand": {
      "description": "Brand narrator",
      "voices": {"en": "Adrian - Explorer", "bn": "Nayem"},
      "speed": 1.15,
      "emotion": "neutral"
    }
  }
}
```

Then verify:

```bash
python3 "$S" presets
python3 "$S" tts "Test." -l en --preset mybrand --dry-run
```

If a preset voice does not exist for a language, the script falls back to the
preset's `en` voice; an unknown preset fails with exit code 3.

## Conversation auto-mapping

Without `--map`, the script:

1. Prefers voices named in the active preset.
2. Then prefers recommended voices for the language.
3. Assigns the rest in order, one per distinct speaker.
4. Uses the default voice for narration (lines with no `Speaker:` prefix).

Override any speaker explicitly:

```bash
--map "human=Nayem,ai=Pooja - Everyday Assistant"
```

Check the mapping with `--dry-run` before a long run.
