#!/usr/bin/env python3
"""TAS CLI — Speakee speech in both directions (text-to-speech + speech-to-text).

Text-to-speech: 40+ languages, 100+ voices, custom voice UID, long-text
chunking, dialogue synthesis, caching/resume, ffmpeg stitching and audio QA.

Speech-to-text: Whisper transcription with word timestamps, automatic
chunking for long recordings, language detection, and SRT/VTT subtitle export.

Commands:
  tts            synthesize text (single voice)
  uid            synthesize text with a custom voice UID
  conversation   multi-voice dialogue from a "Speaker: text" script file
  stt            transcribe an audio/video file (speech to text)
  transcribe     alias for stt
  subtitle       transcribe and write an SRT
  verify         run audio QA on an existing file
  voices         list voices for a language
  suggest        list voices and mark recommended ones
  presets        list built-in voice presets
  languages      list supported languages
  models         list TTS models
  cache-clear    delete the synthesis cache

Environment:
  SPEAKEE_BASE        API base URL (default: https://speakee.tnxbd.top)
  SPEAKEE_CACHE       cache directory (default: ~/.cache/speakee-tas)
  SPEAKEE_CHUNK_LIMIT max characters per TTS request (default: 1200)
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

VERSION = "1.0.0"

BASE = os.environ.get("SPEAKEE_BASE", "https://speakee.tnxbd.top").rstrip("/")
DEFAULT_MODEL = "sonic-3.5"
DEFAULT_VOICE = "ec514ae6-7f63-4b38-b758-fa72b4542136"  # bn "News Reader"
DEFAULT_SPEED = 1.2
DEFAULT_LANG = "en"
CHUNK_LIMIT = int(os.environ.get("SPEAKEE_CHUNK_LIMIT", "1200"))
CACHE_DIR = Path(os.environ.get("SPEAKEE_CACHE",
                                Path.home() / ".cache" / "speakee-tas"))
SKILL_ROOT = Path(__file__).resolve().parent.parent

STT_MAX_UPLOAD = 3_500_000
STT_CHUNK_SECONDS = 120
STT_MAX_CHARS = 42
STT_MAX_LINE_SECONDS = 6.0
STT_WORKERS = 2
STT_MIME = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".ogg": "audio/ogg", ".oga": "audio/ogg",
    ".opus": "audio/opus", ".webm": "audio/webm", ".flac": "audio/flac",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
}
STT_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga",
                      ".opus", ".webm", ".flac"}
STT_VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".wmv", ".flv"}

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SPEAKER_RE = re.compile(r"^([^\s:]{1,16})\s*:\s*(.*)$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[।.!?…])\s+|\n+")

# Emotions accepted by the API. Inline [Tag] markers and emoji are mapped to
# these names and applied per sentence (see parse_emotion_blocks).
EMOTIONS = frozenset({
    "neutral", "calm", "angry", "content", "sad", "scared",
    "affectionate", "agitated", "alarmed", "amazed", "anticipation",
    "anxious", "apologetic", "bored", "confident", "confused",
    "contemplative", "contempt", "curious", "dejected", "determined",
    "disappointed", "disgusted", "distant", "elated", "enthusiastic",
    "envious", "euphoric", "excited", "flirtatious", "frustrated",
    "grateful", "guilty", "happy", "hesitant", "hurt", "insecure",
    "ironic", "mad", "melancholic", "mysterious", "nostalgic",
    "outraged", "panicked", "peaceful", "proud", "rejected", "resigned",
    "sarcastic", "serene", "skeptical", "surprised", "sympathetic",
    "threatened", "tired", "triumphant", "trust", "wistful",
})

EMOJI_EMOTION = {
    # happy / joyful
    "😀": "happy", "😃": "happy", "😄": "happy", "😁": "happy",
    "😆": "happy", "😊": "happy", "🙂": "happy", "😂": "happy",
    "🤣": "happy", "😹": "happy", "😇": "content", "😌": "serene",
    "☺": "content",
    # love / affection
    "🥰": "affectionate", "😍": "affectionate", "🤗": "affectionate",
    "❤": "affectionate", "💕": "affectionate", "💖": "affectionate",
    "😻": "affectionate",
    # playful
    "😘": "flirtatious", "😉": "flirtatious", "😏": "sarcastic",
    "🙄": "sarcastic",
    # excited
    "🤩": "excited", "🥳": "excited", "😜": "excited", "🤪": "excited",
    "😎": "confident", "😤": "frustrated",
    # sad
    "😢": "sad", "😭": "sad", "😔": "sad", "☹": "sad", "🙁": "sad",
    "😿": "sad", "😥": "sad", "💔": "hurt", "😞": "dejected",
    "😒": "resigned",
    # angry
    "😡": "angry", "😠": "angry", "👿": "angry", "🤬": "outraged",
    # fear / anxiety
    "😨": "scared", "😱": "panicked", "😰": "anxious",
    "😟": "anxious", "😬": "anxious", "😓": "anxious",
    # surprise
    "😮": "surprised", "😯": "surprised", "😳": "surprised",
    "😲": "amazed", "🤯": "amazed",
    # calm / tired
    "🧘": "peaceful", "😴": "tired", "😪": "tired", "🥱": "bored",
    "😑": "bored", "😐": "neutral",
    # disgust / confusion
    "🤢": "disgusted", "🤮": "disgusted", "😖": "disgusted",
    "😕": "confused", "😵": "confused", "🤔": "contemplative",
    # misc
    "🙏": "grateful", "🏆": "triumphant", "💪": "determined",
    "🤞": "anticipation",
}

_EMOJI_KEYS = sorted(EMOJI_EMOTION, key=len, reverse=True)
EMOJI_EMOTION_RE = re.compile("|".join(re.escape(k) for k in _EMOJI_KEYS))
EMO_TAG_RE = re.compile(r"\[([A-Za-z]{3,})\]")


def _emoji_emotion(emoji):
    return EMOJI_EMOTION.get(emoji) or EMOJI_EMOTION.get(
        emoji.replace("\ufe0f", ""))


def parse_emotion_blocks(text, base="neutral"):
    """Split text into [(emotion, text)] using inline [Emotion] tags and emoji.

    A [Tag] applies to the text that follows it until the next [Tag]; the tag
    is removed from the spoken text. An emoji colours the whole sentence it
    sits in (the emoji is removed). Text with no markers is returned unchanged
    as a single block, so behaviour is identical when the feature is unused.
    """
    has_tag = any(m.group(1).lower() in EMOTIONS
                  for m in EMO_TAG_RE.finditer(text))
    if not has_tag and not EMOJI_EMOTION_RE.search(text):
        return [(base, text)]

    spans, cur, pos = [], base, 0
    for m in EMO_TAG_RE.finditer(text):
        tag = m.group(1).lower()
        if tag not in EMOTIONS:
            continue
        chunk = text[pos:m.start()]
        if chunk.strip():
            spans.append((cur, chunk))
        cur, pos = tag, m.end()
    tail = text[pos:]
    if tail.strip():
        spans.append((cur, tail))

    blocks = []
    for emo, span in spans:
        for sent in SENTENCE_SPLIT_RE.split(span):
            if not sent.strip():
                continue
            found = EMOJI_EMOTION_RE.findall(sent)
            if found:
                emo2 = _emoji_emotion(found[-1]) or emo
                sent = EMOJI_EMOTION_RE.sub("", sent)
            else:
                emo2 = emo
            sent = re.sub(r"\s+", " ", sent).strip()
            if sent:
                blocks.append((emo2, sent))

    merged = []
    for emo, txt in blocks:
        if merged and merged[-1][0] == emo:
            merged[-1] = (emo, merged[-1][1] + " " + txt)
        else:
            merged.append((emo, txt))
    return merged or [(base, text)]

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_NETWORK = 4
EXIT_QA = 5

JSON_OUT = False

RECOMMENDED = {
    "bn": ["Nayem", "Rubel - City Guide", "Pooja - Everyday Assistant",
           "News Reader", "Aman Sens"],
    "en": ["Ailsa - Warm Guide", "Aarav - Old Time Storyteller",
           "Adrian - Explorer"],
    "hi": ["Aarav - Old Time Storyteller"],
}

VOICES_FALLBACK = {
    "bn": [
        {"id": "ec514ae6-7f63-4b38-b758-fa72b4542136", "name": "News Reader", "gender": "neutral"},
        {"id": "59ba7dee-8f9a-432f-a6c0-ffb33666b654", "name": "Pooja - Everyday Assistant", "gender": "feminine"},
        {"id": "69911b59-40f7-4a1a-a4e5-24098f449799", "name": "Nayem", "gender": "masculine"},
        {"id": "2ba861ea-0a61-4b5d-9f3a-5c3f4e8b1a2d", "name": "Rubel - City Guide", "gender": "masculine"},
        {"id": "1e319ae8-4969-48a0-575b-9c4d8f6e7a3b", "name": "Aman Sens", "gender": "masculine"},
        {"id": "7fb5c1ef-3d4a-4f2c-8b1a-5e3f6d9c2a1e", "name": "BTV", "gender": "neutral"},
        {"id": "6bea13a8-1c2d-4f3e-8a9b-5c4d6e7f8a9b", "name": "Jubayer", "gender": "masculine"},
        {"id": "c21d76dd-3a4b-4c5d-8e9f-0a1b2c3d4e5f", "name": "Sheikh Hasina", "gender": "feminine"},
        {"id": "b50cd6c0-4a5b-4c6d-8e9f-0a1b2c3d4e5f", "name": "Obaidul Quader", "gender": "masculine"},
        {"id": "790e4182-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Rahat", "gender": "masculine"},
        {"id": "ff97d6c5-ee6e-426e-8438-61669fc6ab7e", "name": "Sohan Ahmed", "gender": "masculine"},
    ],
    "en": [
        {"id": "a6d8f7d1-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Ailsa - Warm Guide", "gender": "feminine"},
        {"id": "d1f5f7d1-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Aarav - Old Time Storyteller", "gender": "masculine"},
        {"id": "e2f6f7d1-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Adrian - Explorer", "gender": "masculine"},
        {"id": "f3g7f7d1-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Sofia - News Anchor", "gender": "feminine"},
        {"id": "76f8f7d1-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Eli - Tech Narrator", "gender": "masculine"},
    ],
    "hi": [
        {"id": "a6d8f7d1-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Aarav - Old Time Storyteller", "gender": "masculine"},
        {"id": "b7d8f7d2-3b4a-4c5d-8e9f-0a1b2c3d4e5f", "name": "Neha - Devotional Voice", "gender": "feminine"},
    ],
}

BUILTIN_PRESETS = {
    "news": {
        "description": "Clear, neutral news-reader delivery",
        "voices": {"bn": "News Reader", "en": "Ailsa - Warm Guide",
                   "hi": "Aarav - Old Time Storyteller"},
        "speed": 1.2, "emotion": "neutral",
    },
    "story": {
        "description": "Warm storytelling pace",
        "voices": {"bn": "Rubel - City Guide",
                   "en": "Aarav - Old Time Storyteller"},
        "speed": 1.0, "emotion": "neutral",
    },
    "assistant": {
        "description": "Friendly everyday assistant",
        "voices": {"bn": "Pooja - Everyday Assistant",
                   "en": "Ailsa - Warm Guide"},
        "speed": 1.25, "emotion": "neutral",
    },
    "audiobook": {
        "description": "Slow, even audiobook narration",
        "voices": {"bn": "Nayem", "en": "Aarav - Old Time Storyteller"},
        "speed": 1.0, "emotion": "neutral",
    },
}


class TtsError(Exception):
    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


def log(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr if JSON_OUT else sys.stdout)
    kwargs.setdefault("flush", True)
    print(*args, **kwargs)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def note(*args):
    """Status/progress output that never pollutes transcript stdout."""
    print(*args, file=sys.stderr, flush=True)


def warn(*args):
    """Warning line (always stderr, prefixed) — never breaks machine output."""
    print("WARNING:", *args, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
_LANG_CACHE = None
_MODEL_CACHE = None
_VOICE_CACHE = {}


def _get_json(path, timeout=30):
    req = urllib.request.Request(BASE + path,
                                 headers={"User-Agent": f"speakee-tas-skill/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


_ONLINE = None


def ensure_online():
    """Fail fast with an actionable message when the API is unreachable."""
    global _ONLINE
    if _ONLINE:
        return
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                BASE + "/api/models",
                headers={"User-Agent": f"speakee-tas-skill/{VERSION}"}),
            timeout=15)
        _ONLINE = True
    except urllib.error.HTTPError:
        _ONLINE = True
    except Exception as e:
        raise TtsError(
            f"Cannot reach {BASE} ({e}). The sandbox network may be blocking "
            f"this domain. Ask the user to allow '{urllib.parse.urlparse(BASE).hostname}' "
            f"in the sandbox's allowed domains, or run the skill in Claude Code, "
            f"opencode, or a local shell where there is no domain allow-list.",
            code=EXIT_NETWORK) from None


def languages():
    global _LANG_CACHE
    if _LANG_CACHE is None:
        try:
            _LANG_CACHE = _get_json("/api/languages")["languages"]
        except Exception as e:
            raise TtsError(f"Could not fetch languages: {e}",
                           code=EXIT_NETWORK) from None
    return _LANG_CACHE


def models():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        try:
            _MODEL_CACHE = _get_json("/api/models")["models"]
        except Exception as e:
            log(f"warning: network unavailable, using default models", file=sys.stderr)
            _MODEL_CACHE = ["sonic-3.5", "sonic-3.6", "sonic-preview", "sonic-3"]
    return _MODEL_CACHE


def voices(lang):
    if lang not in _VOICE_CACHE:
        try:
            _VOICE_CACHE[lang] = _get_json(
                "/api/voices?language=" + urllib.parse.quote(lang))["voices"]
        except Exception as e:
            if lang in VOICES_FALLBACK:
                log(f"warning: network unavailable, using local voice cache for '{lang}'",
                    file=sys.stderr)
                _VOICE_CACHE[lang] = VOICES_FALLBACK[lang]
            else:
                raise TtsError(f"Could not fetch voices for '{lang}': {e}. "
                               f"Use UUIDs directly or run locally for '{lang}' voices",
                               code=EXIT_NETWORK) from None
    return _VOICE_CACHE[lang]


# --------------------------------------------------------------------------- #
# Text normalization / language detection / chunking
# --------------------------------------------------------------------------- #
def normalize_text(text, raw=False):
    """Strip markdown/HTML/URLs/emoji so the model never reads syntax aloud."""
    if raw:
        return re.sub(r"\s+", " ", text).strip()
    text = html.unescape(text)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}", "", text)
    text = re.sub("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF"
                  "\uFE0F\u200D]", "", text)
    text = text.replace("\u2014", ", ").replace("\u2013", ", ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_text(text):
    text = text.strip().strip("\u201c\u201d\"'\u2018\u2019")
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text


def detect_language(text):
    if re.search(r"[\u0980-\u09FF]", text):
        return "bn"
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    return "en"


def split_chunks(text, limit=None):
    """Split long text at sentence boundaries; hard-split runaway sentences."""
    limit = max(100, int(limit or CHUNK_LIMIT))
    if len(text) <= limit:
        return [text]
    parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(text) if p.strip()]
    chunks, cur = [], ""
    for part in parts:
        while len(part) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(part[:limit])
            part = part[limit:]
        if not cur:
            cur = part
        elif len(cur) + 1 + len(part) <= limit:
            cur += " " + part
        else:
            chunks.append(cur)
            cur = part
    if cur:
        chunks.append(cur)
    return chunks or [text[:limit]]


# --------------------------------------------------------------------------- #
# Validation / resolution / presets
# --------------------------------------------------------------------------- #
def validate_language(lang):
    if lang == "uid":
        return
    try:
        codes = {l["code"] for l in languages()}
    except Exception:
        return  # offline: don't block
    if lang not in codes:
        raise TtsError(
            f"Unsupported language '{lang}'. Valid codes: "
            + ", ".join(sorted(codes)), code=EXIT_VALIDATION)


def validate_model(model):
    try:
        names = set(models())
    except Exception:
        return
    if model not in names:
        raise TtsError(
            f"Unknown model '{model}'. Available: " + ", ".join(sorted(names)),
            code=EXIT_VALIDATION)


def resolve_voice(lang, spec):
    """Accept a voice UUID or a (case-insensitive, fuzzy) voice name."""
    if not spec:
        return DEFAULT_VOICE
    if UUID_RE.match(spec):
        return spec
    try:
        vs = voices(lang)
    except Exception as e:
        raise TtsError(
            f"Voice '{spec}' is not a UUID and the voice list could not be "
            f"fetched to resolve it ({e}). Pass a UUID instead.",
            code=EXIT_NETWORK) from None
    exact = [v for v in vs if v["name"].lower() == spec.lower()]
    matches = exact or [v for v in vs if spec.lower() in v["name"].lower()]
    if len(matches) == 1:
        return matches[0]["id"]
    if not matches:
        raise TtsError(f"No voice matching '{spec}' for language '{lang}'.",
                       code=EXIT_VALIDATION)
    names = ", ".join(f"{v['name']} ({v['id']})" for v in matches[:10])
    raise TtsError(f"Ambiguous voice '{spec}'. Candidates: {names}",
                   code=EXIT_VALIDATION)


def load_presets():
    path = SKILL_ROOT / "assets" / "presets.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("presets"), dict):
                return data["presets"]
        except Exception:
            pass
    return BUILTIN_PRESETS


def get_preset(name):
    presets = load_presets()
    if name not in presets:
        raise TtsError(
            f"Unknown preset '{name}'. Available: " + ", ".join(sorted(presets)),
            code=EXIT_VALIDATION)
    return presets[name]


# --------------------------------------------------------------------------- #
# Synthesis with retries + strict validation
# --------------------------------------------------------------------------- #
def _payload(text, language, model, voice_id, fmt, speed, volume, emotion):
    return {
        "language": language,
        "model": model,
        "voice_id": voice_id,
        "text": text,
        "format": fmt,
        "speed": speed,
        "volume": volume,
        "emotion": emotion,
    }


def synthesize(text, language, model, voice_id, fmt, speed, volume, emotion,
               timeout=120, retries=4):
    body = json.dumps(_payload(text, language, model, voice_id, fmt,
                               speed, volume, emotion)).encode("utf-8")
    last = None
    for attempt in range(1, max(1, retries) + 1):
        retry_after = None
        try:
            req = urllib.request.Request(
                BASE + "/api/tts", data=body,
                headers={"Content-Type": "application/json",
                         "User-Agent": f"speakee-tas-skill/{VERSION}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                data = r.read()
            if not data:
                raise TtsError("Empty response body", code=EXIT_NETWORK)
            if not ctype.lower().startswith("audio/"):
                snippet = data[:200].decode("utf-8", "replace")
                raise TtsError(f"Unexpected Content-Type '{ctype}': {snippet}",
                               code=EXIT_NETWORK)
            if fmt == "mp3" and not (data[:3] == b"ID3" or data[:1] == b"\xff"):
                raise TtsError(f"Response is not a valid MP3: {data[:80]!r}",
                               code=EXIT_NETWORK)
            return data
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            # Client errors (except 429) will not succeed on retry.
            if 400 <= e.code < 500 and e.code != 429:
                raise TtsError(f"HTTP {e.code}: {msg}",
                               code=EXIT_NETWORK) from None
            last = TtsError(f"HTTP {e.code}: {msg}", code=EXIT_NETWORK)
            if e.code == 429 and e.headers:
                ra = e.headers.get("Retry-After")
                if ra:
                    try:
                        retry_after = max(0.0, min(float(ra), 30.0))
                    except ValueError:
                        retry_after = None
        except TtsError as e:
            last = e
        except Exception as e:  # timeouts, connection resets, ...
            last = TtsError(str(e), code=EXIT_NETWORK)
        if attempt < retries:
            delay = (retry_after if retry_after is not None
                     else min(2 ** (attempt - 1), 8))
            delay += random.uniform(0, 0.3)
            log(f"  retry {attempt}/{retries - 1} in {delay:.1f}s ({last})")
            time.sleep(delay)
    raise last or TtsError("synthesis failed", code=EXIT_NETWORK)


def _cache_path(payload, fmt):
    key = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                    ensure_ascii=False).encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / "segments" / f"{key}.{fmt}"


def synthesize_cached(text, language, model, voice_id, fmt, speed, volume,
                      emotion, timeout=120, retries=4, use_cache=True,
                      force=False, tmpdir=None):
    """Return (path, was_cached)."""
    payload = _payload(text, language, model, voice_id, fmt, speed, volume, emotion)
    if use_cache:
        path = _cache_path(payload, fmt)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not force and path.exists() and path.stat().st_size > 100:
            return path, True
    else:
        if tmpdir is None:
            raise TtsError("internal: tmpdir required with --no-cache")
        key = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False)
            .encode("utf-8")).hexdigest()[:32]
        path = Path(tmpdir) / f"{key}.{fmt}"

    data = synthesize(text, language, model, voice_id, fmt, speed, volume,
                      emotion, timeout, retries)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path, False


def synthesize_text(text, language, model, voice_id, fmt, speed, volume,
                    emotion, timeout, retries, use_cache, force, tmpdir,
                    chunk_limit=None):
    """Synthesize long text by chunking, then merge. Returns (path, chunks, hits)."""
    chunks = split_chunks(text, chunk_limit)
    paths, hits = [], 0
    for chunk in chunks:
        path, cached = synthesize_cached(
            chunk, language, model, voice_id, fmt, speed, volume, emotion,
            timeout, retries, use_cache, force, tmpdir)
        paths.append(path)
        hits += 1 if cached else 0
    if len(paths) == 1:
        return paths[0], len(chunks), hits
    merged_dir = (CACHE_DIR / "merged") if use_cache else Path(tmpdir)
    merged_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((
        "|".join(chunks)
        + f"|{language}|{voice_id}|{model}|{fmt}|{speed}|{volume}|{emotion}"
    ).encode("utf-8")).hexdigest()[:32]
    out = merged_dir / f"{key}.{fmt}"
    if not (use_cache and not force and out.exists() and out.stat().st_size > 100):
        concat_files(paths, out)
    return out, len(chunks), hits


def synthesize_blocks(blocks, language, model, voice_id, fmt, speed, volume,
                      timeout, retries, use_cache, force, tmpdir,
                      chunk_limit=None):
    """Synthesize ordered [(emotion, text)] blocks, then merge.

    Each block is synthesized with its own emotion (same voice/settings), so a
    passage can change feeling mid-way. Returns (path, chunks, hits).
    """
    paths, chunks, hits = [], 0, 0
    for emo, text in blocks:
        path, n, h = synthesize_text(
            text, language, model, voice_id, fmt, speed, volume, emo,
            timeout, retries, use_cache, force, tmpdir, chunk_limit)
        paths.append(path)
        chunks += n
        hits += h
    if len(paths) == 1:
        return paths[0], chunks, hits
    merged_dir = (CACHE_DIR / "merged") if use_cache else Path(tmpdir)
    merged_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((
        "|".join(f"{e}:{t}" for e, t in blocks)
        + f"|{language}|{voice_id}|{model}|{fmt}|{speed}|{volume}"
    ).encode("utf-8")).hexdigest()[:32]
    out = merged_dir / f"{key}.{fmt}"
    if not (use_cache and not force and out.exists() and out.stat().st_size > 100):
        concat_files(paths, out)
    return out, chunks, hits


# --------------------------------------------------------------------------- #
# ffmpeg helpers
# --------------------------------------------------------------------------- #
def ffmpeg_path():
    return shutil.which("ffmpeg")


def probe_info(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration,size,bit_rate,format_name", "-of", "json", str(path)],
        capture_output=True, text=True)
    try:
        fmt = json.loads(r.stdout)["format"]
        try:
            bit_rate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None
        except (TypeError, ValueError):
            bit_rate = None
        return {
            "duration_s": float(fmt.get("duration", 0) or 0),
            "size_bytes": int(fmt.get("size", 0) or 0),
            "bit_rate": bit_rate,
            "container": fmt.get("format_name"),
        }
    except Exception:
        return {}


def probe_duration(path):
    return probe_info(path).get("duration_s", 0.0)


def _strip_id3(data):
    if data[:3] != b"ID3" or len(data) < 10:
        return data
    size = (((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14)
            | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F))
    return data[10 + size:]


def _silence_file(gap, work):
    path = Path(work) / f"silence_{gap:.2f}.mp3"
    subprocess.run(
        [ffmpeg_path(), "-y", "-f", "lavfi", "-i",
         "anullsrc=r=44100:cl=mono", "-t", str(gap),
         "-c:a", "libmp3lame", "-b:a", "128k", str(path)],
        check=True, capture_output=True)
    return path


def _concat_via_ffmpeg(files, out, gap=0.0, loudnorm=False):
    ffmpeg = ffmpeg_path()
    gap = max(0.0, gap)
    work = Path(tempfile.mkdtemp(prefix="speakee-concat-"))
    try:
        silence = _silence_file(gap, work) if gap > 0 else None
        lines = []
        for i, f in enumerate(files):
            lines.append("file '" + str(Path(f).resolve()).replace("'", "'\\''") + "'")
            if silence and i != len(files) - 1:
                lines.append("file '" + str(silence.resolve()).replace("'", "'\\''") + "'")
        listfile = work / "concat.txt"
        listfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Step 1: decode + concat to PCM WAV. Going through PCM avoids the
        # libmp3lame "inadequate AVFrame plane padding" bug that can occur
        # when concatenating MP3s and re-encoding straight to MP3.
        wav = work / "concat.wav"
        r1 = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
             "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", str(wav)],
            capture_output=True, text=True)
        if r1.returncode != 0:
            raise TtsError(
                f"ffmpeg concat failed (exit {r1.returncode}): "
                + (r1.stderr or "")[-900:].strip())
        # Step 2: encode the WAV with a codec matching the output suffix.
        suffix = Path(out).suffix.lower()
        cmd = [ffmpeg, "-y", "-i", str(wav)]
        if loudnorm:
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        if suffix == ".wav":
            cmd += ["-c:a", "pcm_s16le"]
        elif suffix in (".m4a", ".aac"):
            cmd += ["-c:a", "aac", "-b:a", "128k"]
        else:
            cmd += ["-c:a", "libmp3lame", "-b:a", "128k"]
        cmd.append(str(out))
        r2 = subprocess.run(cmd, capture_output=True, text=True)
        if r2.returncode != 0:
            raise TtsError(
                f"ffmpeg encode failed (exit {r2.returncode}): "
                + (r2.stderr or "")[-900:].strip())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def concat_files(files, out):
    """Merge chunk files. Uses ffmpeg when present, else binary MP3 concat."""
    if ffmpeg_path():
        _concat_via_ffmpeg(files, out, gap=0.0)
        return
    if any(Path(f).suffix.lower() != ".mp3" for f in files):
        raise TtsError(
            "ffmpeg is required to merge non-MP3 chunks. Install ffmpeg.")
    with open(out, "wb") as w:
        for f in files:
            w.write(_strip_id3(Path(f).read_bytes()))


def stitch(files, out, gap=0.35, loudnorm=False):
    if not ffmpeg_path():
        raise TtsError(
            "ffmpeg not found — cannot stitch audio. Install ffmpeg or use "
            "--no-stitch to keep individual segments.")
    _concat_via_ffmpeg(files, out, gap=max(0.0, gap), loudnorm=loudnorm)


def tag_audio(path, title=None, artist=None, album=None):
    if not any((title, artist, album)):
        return
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return
    path = Path(path)
    tmp = path.with_name(path.stem + ".tagged" + path.suffix)
    cmd = [ffmpeg, "-y", "-i", str(path), "-c", "copy"]
    for key, val in (("title", title), ("artist", artist), ("album", album)):
        if val:
            cmd += ["-metadata", f"{key}={val}"]
    cmd.append(str(tmp))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)
        log(f"warning: could not write metadata: {(r.stderr or '')[-200:]}")


# --------------------------------------------------------------------------- #
# Audio QA
# --------------------------------------------------------------------------- #
def analyze_audio(path):
    """Machine-checked QA: decode, loudness, true peak, silence."""
    p = Path(path)
    result = {"path": str(p), "exists": p.exists()}
    if not p.exists():
        result.update({"qa": "fail", "errors": ["file not found"]})
        return result
    result["size_bytes"] = p.stat().st_size
    info = probe_info(p)
    result.update(info)
    duration = info.get("duration_s", 0.0)

    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        result.update({"qa": "skipped", "reason": "ffmpeg not found"})
        return result

    filters = ("ebur128=peak=true,astats=metadata=1:reset=0,"
               "silencedetect=noise=-40dB:d=1.5")
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(p), "-af", filters,
         "-f", "null", "-"], capture_output=True, text=True)
    err = r.stderr or ""

    # ebur128 prints per-frame I: values before the Summary; the summary
    # (last occurrence) is the integrated loudness for the whole file.
    values = [float(x) for x in
              re.findall(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", err)]
    loudness = values[-1] if values else None
    m = re.search(r"Peak:\s+(-?\d+(?:\.\d+)?)\s+dBFS", err)
    peak = float(m.group(1)) if m else None
    if peak is None:
        peaks = [float(x) for x in
                 re.findall(r"Peak level dB:\s*(-?\d+(?:\.\d+)?)", err)]
        peak = max(peaks) if peaks else None

    starts = [float(x) for x in
              re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", err)]
    ends = [float(x) for x in
            re.findall(r"silence_end:\s*(-?\d+(?:\.\d+)?)", err)]
    intervals = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else duration
        start, end = max(0.0, start), min(duration, end)
        if end > start:
            intervals.append((start, end))
    leading = intervals[0][1] if intervals and intervals[0][0] <= 0.05 else 0.0
    trailing = (duration - intervals[-1][0]
                if intervals and intervals[-1][1] >= duration - 0.05 else 0.0)
    middle = intervals
    if leading and middle:
        middle = middle[1:]
    if trailing and middle:
        middle = middle[:-1]
    internal_max = max((e - s for s, e in middle), default=0.0)

    errors, warnings = [], []
    if result["size_bytes"] < 1000:
        errors.append("file is too small to be valid audio")
    if not duration or duration < 0.3:
        errors.append("audio is empty or shorter than 0.3s")
    if loudness is None and peak is None:
        errors.append("could not decode audio: " + err[-300:].strip())
    if loudness is not None:
        if not (-35.0 <= loudness <= -8.0):
            errors.append(f"loudness {loudness:.1f} LUFS outside [-35, -8]")
        elif not (-22.0 <= loudness <= -12.0):
            warnings.append(f"loudness {loudness:.1f} LUFS outside target "
                            "[-22, -12]")
    if peak is not None and peak > -0.1:
        errors.append(f"clipping detected (peak {peak:.1f} dBFS)")
    if leading > 2.0:
        warnings.append(f"leading silence {leading:.1f}s")
    if trailing > 2.0:
        warnings.append(f"trailing silence {trailing:.1f}s")
    if internal_max > 5.0:
        warnings.append(f"long internal silence {internal_max:.1f}s")

    result.update({
        "loudness_lufs": loudness,
        "true_peak_dbfs": peak,
        "leading_silence_s": round(leading, 2),
        "trailing_silence_s": round(trailing, 2),
        "max_internal_silence_s": round(internal_max, 2),
        "errors": errors,
        "warnings": warnings,
        "qa": "fail" if errors else ("warn" if warnings else "pass"),
    })
    return result


def print_qa(result):
    if result.get("qa") == "skipped":
        log(f"QA: skipped ({result.get('reason', 'unavailable')})")
        return
    parts = [f"QA: {result['qa'].upper()}"]
    if result.get("loudness_lufs") is not None:
        parts.append(f"{result['loudness_lufs']:.1f} LUFS")
    if result.get("true_peak_dbfs") is not None:
        parts.append(f"peak {result['true_peak_dbfs']:.1f} dBFS")
    parts.append("silence "
                 f"{result.get('leading_silence_s', 0):.1f}/"
                 f"{result.get('max_internal_silence_s', 0):.1f}/"
                 f"{result.get('trailing_silence_s', 0):.1f}s")
    log(" | ".join(parts))
    for error in result.get("errors", []):
        log(f"  QA error: {error}")
    for warning in result.get("warnings", []):
        log(f"  QA warning: {warning}")


def run_qa(path):
    result = analyze_audio(path)
    print_qa(result)
    if result.get("qa") == "fail":
        raise TtsError("audio QA failed", code=EXIT_QA)
    return result


# --------------------------------------------------------------------------- #
# Conversation parsing / SRT
# --------------------------------------------------------------------------- #
def parse_map(spec):
    mapping = {}
    if not spec:
        return mapping
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise TtsError(f"Invalid --map entry '{pair}' (expected speaker=voice)",
                           code=EXIT_VALIDATION)
        key, val = pair.split("=", 1)
        mapping[key.strip()] = val.strip()
    return mapping


def parse_script(path, known_labels=None, raw=False, keep_markers=False):
    """Return [(speaker_or_None, text)] from a 'Speaker: text' script.

    keep_markers=True preserves inline [Emotion] tags and emoji so the caller
    can map them to per-segment emotions.
    """
    segs = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        src = raw_line.strip()
        line = src if keep_markers else normalize_text(src, raw=raw)
        if not line:
            continue
        m = SPEAKER_RE.match(line)
        if m and (known_labels is None or m.group(1) in known_labels):
            label, text = m.group(1), m.group(2)
        else:
            label, text = None, line
        text = (re.sub(r"\s+", " ", text).strip() if keep_markers
                else clean_text(text))
        if text:
            segs.append((label, text))
    return segs


def fmt_srt_time(seconds):
    ms = max(0, int(round(seconds * 1000)))
    return (f"{ms // 3600000:02d}:{(ms % 3600000) // 60000:02d}:"
            f"{(ms % 60000) // 1000:02d},{ms % 1000:03d}")


def write_srt(entries, path, gap=0.0):
    lines, cursor = [], 0.0
    for i, (speaker, text, duration) in enumerate(entries, 1):
        label = "" if speaker in (None, "narrator") else f"{speaker}: "
        lines += [str(i),
                  f"{fmt_srt_time(cursor)} --> {fmt_srt_time(cursor + duration)}",
                  label + text, ""]
        cursor += duration + gap
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Speech-to-text (STT)
# --------------------------------------------------------------------------- #
def _multipart(fields, file_path, mime):
    boundary = "----speakee" + hashlib.sha256(os.urandom(16)).hexdigest()[:24]
    parts = []
    for name, value in fields.items():
        parts.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
             f"{value}\r\n").encode("utf-8"))
    filename = Path(file_path).name.replace('"', "_")
    parts.append(
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="file"; '
         f'filename="{filename}"\r\n'
         f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        + Path(file_path).read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def stt_upload(path, language="auto", word_timestamps=True, timeout=300,
               retries=3):
    path = Path(path)
    mime = STT_MIME.get(path.suffix.lower(), "application/octet-stream")
    fields = {
        "language": language or "auto",
        "word_timestamps": "1" if word_timestamps else "0",
    }
    last = None
    for attempt in range(1, max(1, retries) + 1):
        retry_after = None
        try:
            body, ctype = _multipart(fields, path, mime)
            req = urllib.request.Request(
                BASE + "/api/stt", data=body,
                headers={"Content-Type": ctype,
                         "User-Agent": f"speakee-tas-skill/{VERSION}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                snippet = raw[:200].decode("utf-8", "replace")
                raise TtsError(f"STT returned non-JSON response: {snippet}",
                               code=EXIT_NETWORK) from None
            if not isinstance(data, dict) or "text" not in data:
                raise TtsError(f"Unexpected STT response: {str(data)[:300]}",
                               code=EXIT_NETWORK)
            return data
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            if e.code == 413:
                raise TtsError(
                    "STT upload too large (HTTP 413). The API accepts roughly "
                    "4.5 MB per request; this chunk is "
                    f"{path.stat().st_size / 1e6:.1f} MB. Use chunking "
                    "(drop --no-chunk) or a smaller --chunk-seconds.",
                    code=EXIT_VALIDATION) from None
            if 400 <= e.code < 500 and e.code != 429:
                raise TtsError(f"STT HTTP {e.code}: {msg}",
                               code=EXIT_NETWORK) from None
            last = TtsError(f"STT HTTP {e.code}: {msg}", code=EXIT_NETWORK)
            if e.code == 429 and e.headers:
                ra = e.headers.get("Retry-After")
                if ra:
                    try:
                        retry_after = max(0.0, min(float(ra), 30.0))
                    except ValueError:
                        retry_after = None
        except TtsError as e:
            last = e
        except Exception as e:  # timeouts, connection resets, ...
            last = TtsError(f"STT request failed: {e}", code=EXIT_NETWORK)
        if attempt < retries:
            delay = (retry_after if retry_after is not None
                     else min(2 ** (attempt - 1), 8))
            delay += random.uniform(0, 0.3)
            note(f"  stt retry {attempt}/{retries - 1} in {delay:.1f}s ({last})")
            time.sleep(delay)
    raise last or TtsError("STT failed", code=EXIT_NETWORK)


def _duration_via_ffmpeg(path):
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return 0.0
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    if not m:
        return 0.0
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
            + float(m.group(3)))


def detect_silences(path, noise="-35dB", min_silence=0.35):
    """Return [(start, end)] silence intervals from ffmpeg silencedetect."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return []
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={noise}:d={min_silence}",
         "-f", "null", "-"], capture_output=True, text=True)
    err = r.stderr or ""
    starts = [float(x) for x in
              re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", err)]
    ends = [float(x) for x in
            re.findall(r"silence_end:\s*(-?\d+(?:\.\d+)?)", err)]
    out = []
    for i, start in enumerate(starts):
        if i >= len(ends):
            break
        start = max(0.0, start)
        if ends[i] > start:
            out.append((start, ends[i]))
    return out


def stt_ranges(duration, chunk_seconds, silences):
    """Split [0, duration] near chunk_seconds, snapping cuts into silences."""
    chunk_seconds = max(10.0, float(chunk_seconds or STT_CHUNK_SECONDS))
    if not duration or duration <= chunk_seconds:
        return [(0.0, max(0.0, duration))]
    mids = [((s + e) / 2.0) for s, e in silences if e - s >= 0.3]
    window = min(20.0, chunk_seconds * 0.25)
    boundaries, target = [], chunk_seconds
    while target < duration - 1.0:
        candidates = [m for m in mids if target - window <= m <= target]
        boundary = max(candidates) if candidates else target
        boundaries.append(boundary)
        target = boundary + chunk_seconds
    edges = [0.0] + boundaries + [duration]
    ranges = [(a, b) for a, b in zip(edges, edges[1:]) if b - a >= 0.05]
    if len(ranges) > 1 and ranges[-1][1] - ranges[-1][0] < 3.0:
        start = ranges[-2][0]
        end = ranges[-1][1]
        ranges[-2:] = [(start, end)]
    return ranges or [(0.0, max(0.0, duration))]


def _extract_stt_chunk(src, start, end, out):
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise TtsError(
            "ffmpeg is required to split audio for transcription. Install "
            "ffmpeg or pass --no-chunk with a file under 3.5 MB.",
            code=EXIT_VALIDATION)
    r = subprocess.run(
        [ffmpeg, "-y", "-ss", f"{start:.3f}",
         "-t", f"{max(0.1, end - start):.3f}", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "libmp3lame", "-b:a", "64k", str(out)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise TtsError(
            "ffmpeg could not prepare the STT chunk: "
            + (r.stderr or "")[-600:].strip())


def prepare_stt_chunks(path, workdir, chunk_seconds, no_chunk=False):
    """Return [{index, path, start, end, converted}] ready for upload."""
    path = Path(path)
    size = path.stat().st_size
    suffix = path.suffix.lower()
    duration = probe_duration(path) or _duration_via_ffmpeg(path)
    direct_ok = suffix in STT_AUDIO_SUFFIXES and size <= STT_MAX_UPLOAD

    if no_chunk:
        if size > STT_MAX_UPLOAD:
            raise TtsError(
                f"File is {size / 1e6:.1f} MB; the STT API rejects large "
                "uploads (HTTP 413). Drop --no-chunk to split it.",
                code=EXIT_VALIDATION)
        if not direct_ok:
            raise TtsError(
                f"'{suffix or 'unknown'}' files cannot be uploaded directly. "
                "Install ffmpeg for conversion or pass a supported audio file.",
                code=EXIT_VALIDATION)
        return [{"index": 0, "path": path, "start": 0.0,
                 "end": duration, "converted": False}]

    if direct_ok and (not duration or duration <= chunk_seconds):
        return [{"index": 0, "path": path, "start": 0.0,
                 "end": duration, "converted": False}]

    if not ffmpeg_path():
        if direct_ok:
            note("warning: ffmpeg not found — uploading the file in one request")
            return [{"index": 0, "path": path, "start": 0.0,
                     "end": duration, "converted": False}]
        raise TtsError(
            "ffmpeg is required to transcribe video or large files. "
            "Install ffmpeg.", code=EXIT_VALIDATION)
    if not duration:
        raise TtsError(
            "Could not determine the audio duration (ffprobe missing?). "
            "Install ffmpeg/ffprobe or use --no-chunk with a file under "
            "3.5 MB.", code=EXIT_VALIDATION)

    silences = detect_silences(path)
    ranges = stt_ranges(duration, chunk_seconds, silences)
    chunks = []
    for i, (start, end) in enumerate(ranges):
        out = Path(workdir) / f"stt_{i:03d}.mp3"
        _extract_stt_chunk(path, start, end, out)
        chunks.append({"index": i, "path": out, "start": start,
                       "end": end, "converted": True})
    return chunks


def _cue_text(items, sep=" "):
    return sep.join(i["text"] for i in items).strip()


def _cue(items, sep=" "):
    start = items[0]["start"]
    return {"start": start, "end": max(items[-1]["end"], start),
            "text": _cue_text(items, sep)}


def _cues_from_words(words, max_chars, max_line_seconds, sep=" "):
    max_chars = max(12, int(max_chars or STT_MAX_CHARS))
    max_line_seconds = max(1.0, float(max_line_seconds or STT_MAX_LINE_SECONDS))
    cues, cur = [], []

    def flush():
        if cur:
            cues.append(_cue(cur, sep))
            cur.clear()

    for item in words:
        text = str(item.get("word", "")).strip()
        if not text:
            continue
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
        except (TypeError, ValueError):
            continue
        if end < start:
            end = start
        if cur:
            candidate = _cue_text(cur, sep) + sep + text
            if (len(candidate) > max_chars
                    or end - cur[0]["start"] > max_line_seconds):
                flush()
        cur.append({"text": text, "start": start, "end": end})
        if (re.search(r"[.!?…।]['\"”’)\]]*$", text)
                and len(_cue_text(cur, sep)) >= max_chars * 0.6):
            flush()
    flush()
    return cues


def _cues_from_text(text, duration, max_chars, max_line_seconds):
    """Estimate cue timing by character share when words are unavailable."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    max_chars = max(12, int(max_chars or STT_MAX_CHARS))
    parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(text) if p.strip()]
    pieces, cur = [], ""
    for part in parts or [text]:
        while len(part) > max_chars:
            if cur:
                pieces.append(cur)
                cur = ""
            cut = part.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            pieces.append(part[:cut].strip())
            part = part[cut:].strip()
        if not cur:
            cur = part
        elif len(cur) + 1 + len(part) <= max_chars:
            cur += " " + part
        else:
            pieces.append(cur)
            cur = part
    if cur:
        pieces.append(cur)
    total = sum(len(p) for p in pieces) or 1
    cues, cursor = [], 0.0
    for piece in pieces:
        end = min(duration, cursor + duration * len(piece) / total)
        if end - cursor >= 0.2:
            cues.append({"start": cursor, "end": end, "text": piece})
        cursor = end
    return cues


def _clamp_cues(cues):
    out, prev_end = [], 0.0
    for cue in cues:
        text = re.sub(r"\s+", " ", cue["text"]).strip()
        if not text:
            continue
        start = max(0.0, cue["start"], prev_end)
        end = max(cue["end"], start + 0.2)
        out.append({"start": start, "end": end, "text": text})
        prev_end = end
    return out


def fmt_vtt_time(seconds):
    ms = max(0, int(round(seconds * 1000)))
    return (f"{ms // 3600000:02d}:{(ms % 3600000) // 60000:02d}:"
            f"{(ms % 60000) // 1000:02d}.{ms % 1000:03d}")


def render_srt_cues(cues):
    lines = []
    for i, cue in enumerate(cues, 1):
        lines += [str(i),
                  f"{fmt_srt_time(cue['start'])} --> {fmt_srt_time(cue['end'])}",
                  cue["text"], ""]
    return "\n".join(lines)


def render_vtt_cues(cues):
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines += [f"{fmt_vtt_time(cue['start'])} --> {fmt_vtt_time(cue['end'])}",
                  cue["text"], ""]
    return "\n".join(lines)


def cmd_stt(args, subtitle=False):
    ensure_online()
    src = Path(args.file)
    if not src.exists():
        raise TtsError(f"File not found: {src}", code=EXIT_VALIDATION)
    if not src.is_file():
        raise TtsError(f"Not a file: {src}", code=EXIT_VALIDATION)

    suffix = src.suffix.lower()
    if suffix not in STT_MIME:
        note(f"warning: unknown extension '{suffix or '(none)'}' — "
             "ffmpeg will try to decode it anyway")

    language = (args.language or "auto").strip() or "auto"
    word_timestamps = not getattr(args, "no_word_timestamps", False)
    size = src.stat().st_size

    srt_path = vtt_path = text_path = None
    if subtitle:
        srt_path = Path(getattr(args, "out", None) or src.with_suffix(".srt"))
        if getattr(args, "vtt", False) or getattr(args, "vtt_path", None):
            vtt_path = Path(getattr(args, "vtt_path", None)
                            or src.with_suffix(".vtt"))
    else:
        if getattr(args, "srt", False) or getattr(args, "srt_path", None):
            srt_path = Path(getattr(args, "srt_path", None)
                            or src.with_suffix(".srt"))
        if getattr(args, "vtt", False) or getattr(args, "vtt_path", None):
            vtt_path = Path(getattr(args, "vtt_path", None)
                            or src.with_suffix(".vtt"))
        if getattr(args, "out", None):
            text_path = Path(args.out)

    if (srt_path or vtt_path) and not word_timestamps:
        note("warning: word timestamps disabled — subtitle timing is estimated")

    duration = probe_duration(src) or _duration_via_ffmpeg(src)

    if getattr(args, "dry_run", False):
        if args.no_chunk:
            if size > STT_MAX_UPLOAD:
                raise TtsError(
                    f"File is {size / 1e6:.1f} MB; the STT API rejects large "
                    "uploads. Drop --no-chunk to split it.",
                    code=EXIT_VALIDATION)
            ranges = [(0.0, duration)]
        elif duration:
            ranges = stt_ranges(duration, args.chunk_seconds, [])
        else:
            ranges = [(0.0, duration)]
        plan = {
            "command": "subtitle" if subtitle else "stt",
            "file": str(src), "language": language,
            "duration_s": round(duration, 2) if duration else None,
            "size_bytes": size, "chunks": len(ranges),
            "estimated": True, "word_timestamps": word_timestamps,
            "srt": str(srt_path) if srt_path else None,
            "vtt": str(vtt_path) if vtt_path else None,
            "out": str(text_path) if text_path else None,
        }
        if JSON_OUT:
            emit(plan)
        else:
            note(f"DRY RUN: {len(ranges)} STT request(s), language={language}, "
                 f"{size / 1e6:.2f} MB, {duration:.1f}s -> "
                 f"{srt_path or text_path or 'stdout'}")
        return

    with tempfile.TemporaryDirectory(prefix="speakee-stt-") as tmp:
        chunks = prepare_stt_chunks(src, tmp, args.chunk_seconds, args.no_chunk)
        n = len(chunks)
        note(f"Transcribing {n} chunk(s), language={language}")

        results = [None] * n
        detected = None if language == "auto" else language

        def work(idx, lang):
            results[idx] = stt_upload(chunks[idx]["path"], lang,
                                      word_timestamps, args.timeout,
                                      args.retries)

        if language == "auto" and n > 1:
            work(0, "auto")
            first = results[0] or {}
            detected = (first.get("language") or "").strip() or None
            conf = first.get("detection_confidence")
            if detected:
                extra = (f" (confidence {conf:.2f})"
                         if isinstance(conf, (int, float)) else "")
                note(f"  detected language: {detected}{extra}")
                if isinstance(conf, (int, float)) and conf < 0.5:
                    note("  warning: low confidence — pass -l <code> if the "
                         "transcript looks wrong")
            rest = list(range(1, n))
            if rest:
                with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                    futures = [pool.submit(work, i, detected or "auto")
                               for i in rest]
                    for done, fut in enumerate(as_completed(futures), 1):
                        fut.result()
                        note(f"  {done}/{len(rest)} chunk(s) transcribed")
        else:
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                futures = [pool.submit(work, i, language) for i in range(n)]
                for done, fut in enumerate(as_completed(futures), 1):
                    fut.result()
                    note(f"  {done}/{n} chunk(s) transcribed")

        if any(r is None for r in results):
            raise TtsError("Some STT chunks failed.", code=EXIT_NETWORK)
        if detected is None and results:
            detected = (results[0] or {}).get("language")

        sep = "" if detected in {"zh", "ja", "yue", "th", "lo", "my",
                                 "km"} else " "
        texts, words_all, cues, chunk_meta = [], [], [], []
        for chunk, data in zip(chunks, results):
            text = str(data.get("text") or "").strip()
            if text:
                texts.append(text)
            offset = float(chunk["start"])
            chunk_words = data.get("words") or []
            if word_timestamps and chunk_words:
                for w in chunk_words:
                    try:
                        s = float(w.get("start", 0.0))
                        e = float(w.get("end", s))
                    except (TypeError, ValueError):
                        continue
                    words_all.append({"start": round(s + offset, 3),
                                      "end": round(e + offset, 3),
                                      "word": str(w.get("word", ""))})
                local = _cues_from_words(chunk_words, args.max_chars,
                                         args.max_line_seconds, sep=sep)
                cues.extend({"start": c["start"] + offset,
                             "end": c["end"] + offset,
                             "text": c["text"]} for c in local)
            elif text:
                span = max(0.0, float(chunk["end"]) - float(chunk["start"]))
                cues.extend({"start": c["start"] + offset,
                             "end": c["end"] + offset,
                             "text": c["text"]}
                            for c in _cues_from_text(text, span,
                                                     args.max_chars,
                                                     args.max_line_seconds))
            chunk_meta.append({
                "index": chunk["index"],
                "start": round(float(chunk["start"]), 3),
                "end": round(float(chunk["end"]), 3),
                "language": data.get("language"),
                "detection_confidence": data.get("detection_confidence"),
                "duration_s": data.get("duration"),
                "engine": data.get("engine"),
                "text_chars": len(text),
                "words": len(chunk_words),
                "converted": chunk["converted"],
            })
        cues = _clamp_cues(cues)
        transcript = " ".join(texts).strip()
        if not transcript and not cues:
            raise TtsError("STT returned an empty transcript (silent or "
                           "unsupported audio?).", code=EXIT_VALIDATION)

        if text_path:
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(transcript + "\n", encoding="utf-8")
        if srt_path:
            srt_path.parent.mkdir(parents=True, exist_ok=True)
            srt_path.write_text(render_srt_cues(cues), encoding="utf-8")
        if vtt_path:
            vtt_path.parent.mkdir(parents=True, exist_ok=True)
            vtt_path.write_text(render_vtt_cues(cues), encoding="utf-8")

        if JSON_OUT:
            emit({
                "command": "subtitle" if subtitle else "stt",
                "file": str(src),
                "language": language,
                "detected_language": detected,
                "duration_s": round(duration, 3) if duration else None,
                "size_bytes": size,
                "chunks": chunk_meta,
                "text": transcript,
                "word_count": len(words_all),
                "words": words_all,
                "out": str(text_path) if text_path else None,
                "srt": str(srt_path) if srt_path else None,
                "vtt": str(vtt_path) if vtt_path else None,
                "cues": len(cues),
            })
            return

        if text_path:
            note(f"OUT: {text_path} ({len(transcript)} chars)")
        elif not subtitle:
            print(transcript)
        if srt_path:
            note(f"SRT: {srt_path} ({len(cues)} cues)")
        if vtt_path:
            note(f"VTT: {vtt_path} ({len(cues)} cues)")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def default_out(prefix, key, fmt):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}.{fmt}"


def read_raw_text(args):
    if getattr(args, "text_file", None):
        return Path(args.text_file).read_text(encoding="utf-8")
    return " ".join(args.text or [])


def read_text_arg(args):
    text = read_raw_text(args)
    return clean_text(normalize_text(text, raw=getattr(args, "raw", False)))


def _resolve_style(args, preset):
    speed = args.speed if args.speed is not None else (
        preset.get("speed", DEFAULT_SPEED) if preset else DEFAULT_SPEED)
    volume = args.volume if args.volume is not None else 1.0
    emotion = args.emotion if args.emotion is not None else (
        preset.get("emotion", "neutral") if preset else "neutral")
    return speed, volume, emotion


def cmd_tts(args, uid_mode=False):
    raw = read_raw_text(args)
    if not raw.strip():
        raise TtsError("No text provided (pass text or --text-file).",
                       code=EXIT_VALIDATION)
    if not args.dry_run:
        ensure_online()
    preset = get_preset(args.preset) if args.preset else None

    if uid_mode:
        language = "uid"
        if not args.voice_id:
            raise TtsError("uid mode requires --voice_id <custom-voice-uuid>",
                           code=EXIT_VALIDATION)
        if not args.no_validate and not UUID_RE.match(args.voice_id):
            raise TtsError("--voice_id must be a valid UUID in uid mode.",
                           code=EXIT_VALIDATION)
        voice_id = args.voice_id
    else:
        language = args.language or detect_language(raw)
        if not args.no_validate:
            validate_language(language)
            validate_model(args.model)
        spec = args.voice_id
        if not spec and preset:
            spec = (preset["voices"].get(language)
                    or preset["voices"].get("en"))
        voice_id = resolve_voice(language, spec)

    speed, volume, emotion = _resolve_style(args, preset)
    if getattr(args, "no_emotion", False):
        blocks = [(emotion, clean_text(normalize_text(raw, raw=args.raw)))]
    else:
        blocks = []
        for emo, frag in parse_emotion_blocks(raw, emotion):
            t = clean_text(normalize_text(frag, raw=args.raw))
            if t:
                blocks.append((emo, t))
        if not blocks:
            blocks = [(emotion,
                       clean_text(normalize_text(raw, raw=args.raw)))]
    text = " ".join(t for _, t in blocks)
    multi = len({e for e, _ in blocks}) > 1
    chunks = (sum(len(split_chunks(t, args.chunk_limit)) for _, t in blocks)
              if multi else len(split_chunks(text, args.chunk_limit)))
    key = f"{language}|{voice_id}|{args.model}|{speed}|{text}"
    out = Path(args.out or default_out("tts", key, args.format))

    if args.dry_run:
        plan = {
            "command": "tts", "language": language, "voice_id": voice_id,
            "model": args.model, "speed": speed, "volume": volume,
            "emotion": emotion, "chunks": chunks, "requests": chunks,
            "out": str(out), "text_chars": len(text),
        }
        if multi:
            plan["emotions"] = [[e, t] for e, t in blocks]
        if JSON_OUT:
            emit(plan)
        else:
            log(f"DRY RUN: {plan['requests']} request(s), language={language}, "
                f"voice={voice_id}, chunks={plan['chunks']} -> {out}")
            if multi:
                log("Emotions: " + ", ".join(e for e, _ in blocks))
        return

    with tempfile.TemporaryDirectory(prefix="speakee-") as tmp:
        if multi:
            path, nchunks, hits = synthesize_blocks(
                blocks, language, args.model, voice_id, args.format, speed,
                volume, args.timeout, args.retries,
                use_cache=not args.no_cache, force=args.force,
                tmpdir=tmp if args.no_cache else None,
                chunk_limit=args.chunk_limit)
        else:
            path, nchunks, hits = synthesize_text(
                text, language, args.model, voice_id, args.format, speed,
                volume, blocks[0][0], args.timeout, args.retries,
                use_cache=not args.no_cache, force=args.force,
                tmpdir=tmp if args.no_cache else None,
                chunk_limit=args.chunk_limit)
        out.parent.mkdir(parents=True, exist_ok=True)
        if Path(path).resolve() != out.resolve():
            shutil.copyfile(path, out)

    tag_audio(out, args.title, args.artist, args.album)
    qa = None if args.no_verify else run_qa(out)
    info = probe_info(out)
    if JSON_OUT:
        payload = {
            "command": "tts", "out": str(out), "language": language,
            "voice_id": voice_id, "model": args.model, "speed": speed,
            "chunks": nchunks, "cache_hits": hits,
            "duration_s": info.get("duration_s"),
            "size_bytes": info.get("size_bytes"),
            "qa": qa,
        }
        if multi:
            payload["emotions"] = [[e, t] for e, t in blocks]
        emit(payload)
    else:
        log(f"OUT: {out} ({nchunks} chunk(s), "
            f"{info.get('duration_s', 0):.1f}s, "
            f"{info.get('size_bytes', 0) / 1e6:.2f} MB)")


def _dedupe_voices(items):
    seen, out = set(), []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            out.append(item)
    return out


def cmd_conversation(args):
    if not args.dry_run:
        ensure_online()
    preset = get_preset(args.preset) if args.preset else None
    mapping = parse_map(args.map)
    known = set(mapping.keys()) or None
    speed, volume, emotion = _resolve_style(args, preset)
    detect = not getattr(args, "no_emotion", False)
    authored = parse_script(args.script, known, raw=args.raw,
                            keep_markers=detect)
    if not mapping:
        label_lines = [lab for lab, _ in authored if lab is not None]
        distinct = set(label_lines)
        if len(distinct) < 2 or len(label_lines) < 3:
            warn("Not enough multi-speaker dialogue detected — using one "
                 "voice. Use `tts` for plain text, or --map to force "
                 "speaker voices.")
            if len(distinct) == 1 and len(label_lines) == 1:
                authored = parse_script(args.script, set(), raw=args.raw,
                                        keep_markers=detect)
            else:
                authored = [(None, text) for _, text in authored]
    segs = []
    for label, rawtext in authored:
        if detect:
            for emo, frag in parse_emotion_blocks(rawtext, emotion):
                t = clean_text(normalize_text(frag, raw=args.raw))
                if t:
                    segs.append((label, t, emo))
        else:
            t = clean_text(normalize_text(rawtext, raw=args.raw))
            if t:
                segs.append((label, t, emotion))
    if not segs:
        raise TtsError(f"No dialogue found in {args.script}",
                       code=EXIT_VALIDATION)

    language = args.language or detect_language(
        " ".join(t for _, t, _ in segs[:25]))
    if not args.no_validate:
        validate_language(language)
        validate_model(args.model)

    labels = []
    for label, _, _ in segs:
        if label not in labels:
            labels.append(label)

    voice_ids = {}
    if mapping:
        for label, spec in mapping.items():
            voice_ids[label] = resolve_voice(language, spec)
        log("Voice mapping:")
    else:
        vs = voices(language)
        rec = RECOMMENDED.get(language, [])
        preset_names = list(preset["voices"].values()) if preset else []
        ordered = _dedupe_voices(
            [v for v in vs if v["name"] in preset_names]
            + [v for v in vs if any(v["name"].startswith(r) for r in rec)]
            + [v for v in vs if not any(v["name"].startswith(r) for r in rec)])
        if not ordered:
            ordered = [{"id": DEFAULT_VOICE}]
        narrator = DEFAULT_VOICE
        if preset and preset["voices"].get(language):
            narrator = resolve_voice(language, preset["voices"][language])
        n = 0
        for label in labels:
            if label is None:
                voice_ids[label] = narrator
            else:
                voice_ids[label] = ordered[n % len(ordered)]["id"]
                n += 1
        log("Auto voice mapping (override with --map):")
    for label in labels:
        voice_ids.setdefault(label, DEFAULT_VOICE)
        log(f"  {label if label is not None else '(narrator)'} -> {voice_ids[label]}")
    _seen = {}
    for label in labels:
        vid = voice_ids[label]
        disp = label if label is not None else "narrator"
        if vid in _seen and _seen[vid] != disp:
            warn(f"'{_seen[vid]}' and '{disp}' share voice {vid}: "
                 f"voices are NOT distinct. Map each speaker to a different "
                 f"voice with --map (e.g. --map \"narrator=VoiceA,{disp}=VoiceB\").")
        else:
            _seen[vid] = disp

    total_chunks = sum(len(split_chunks(t, args.chunk_limit))
                       for _, t, _ in segs)
    out = Path(args.out or default_out(
        "conversation", "|".join(t for _, t, _ in segs), "mp3"))

    if args.dry_run:
        plan = {
            "command": "conversation", "language": language,
            "model": args.model, "speed": speed, "segments": len(segs),
            "chunks": total_chunks, "requests": total_chunks,
            "emotions": sorted({e for _, _, e in segs}),
            "voices": {(k if k is not None else "narrator"): v
                        for k, v in voice_ids.items()},
            "out": str(out), "srt": args.srt, "manifest": args.manifest,
        }
        if JSON_OUT:
            emit(plan)
        else:
            log(f"DRY RUN: {len(segs)} segment(s), {total_chunks} request(s), "
                f"language={language} -> {out}")
        return

    use_cache = not args.no_cache
    tmp_ctx = tempfile.TemporaryDirectory(prefix="speakee-") if not use_cache else None
    tmpdir = tmp_ctx.name if tmp_ctx else None
    try:
        results = [None] * len(segs)

        def job(idx):
            label, text, emo = segs[idx]
            return idx, synthesize_text(
                text, language, args.model, voice_ids[label], args.format,
                speed, volume, emo, args.timeout, args.retries,
                use_cache, args.force, tmpdir, args.chunk_limit)

        workers = max(1, args.workers)
        step = max(1, len(segs) // 10)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(job, i): i for i in range(len(segs))}
            done = 0
            for fut in as_completed(futures):
                idx, (path, _, _) = fut.result()
                results[idx] = path
                done += 1
                if done % step == 0 or done == len(segs):
                    log(f"  {done}/{len(segs)} synthesized")
        if any(r is None for r in results):
            raise TtsError("Some segments failed to synthesize.")

        manifest = {
            "source": str(Path(args.script).resolve()),
            "language": language,
            "model": args.model,
            "speed": speed,
            "segments": [
                {"index": i, "speaker": (lab if lab is not None else "narrator"),
                 "voice_id": voice_ids[lab], "emotion": emo, "text": text,
                 "file": str(path)}
                for i, ((lab, text, emo), path) in enumerate(zip(segs, results))
            ],
        }
        if args.manifest:
            Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
            Path(args.manifest).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8")

        if args.srt:
            entries, durations_ok = [], True
            for (lab, text, _), path in zip(segs, results):
                duration = probe_duration(path)
                durations_ok = durations_ok and duration > 0
                entries.append((lab if lab is not None else "narrator",
                                text, duration))
            if durations_ok:
                write_srt(entries, args.srt,
                          args.silence if not args.no_stitch else 0.0)
            else:
                log("warning: --srt skipped (ffprobe unavailable)")

        if args.no_stitch:
            outdir = Path(args.out or "segments")
            outdir.mkdir(parents=True, exist_ok=True)
            for i, ((lab, _, _), path) in enumerate(zip(segs, results)):
                shutil.copyfile(path, outdir / f"{i:04d}_{lab or 'narrator'}.{args.format}")
            if JSON_OUT:
                emit({"command": "conversation", "out": str(outdir),
                      "segments": len(segs), "chunks": total_chunks,
                      "srt": args.srt, "manifest": args.manifest})
            else:
                log(f"{len(segs)} segments -> {outdir}")
            return

        out.parent.mkdir(parents=True, exist_ok=True)
        stitch(results, out, args.silence, args.loudnorm)
        tag_audio(out, args.title, args.artist, args.album)
        qa = None if args.no_verify else run_qa(out)
        info = probe_info(out)
        if JSON_OUT:
            emit({
                "command": "conversation", "out": str(out),
                "segments": len(segs), "chunks": total_chunks,
                "duration_s": info.get("duration_s"),
                "size_bytes": info.get("size_bytes"),
                "srt": args.srt, "manifest": args.manifest,
                "voices": {(k if k is not None else "narrator"): v
                        for k, v in voice_ids.items()},
                "qa": qa,
            })
        else:
            log(f"FINAL: {out} ({len(segs)} segments, {total_chunks} chunk(s), "
                f"{info.get('duration_s', 0):.1f}s, "
                f"{info.get('size_bytes', 0) / 1e6:.2f} MB)")
    finally:
        if tmp_ctx:
            tmp_ctx.cleanup()


def cmd_verify(args):
    result = analyze_audio(args.file)
    print_qa(result)
    if JSON_OUT:
        emit(result)
    if result.get("qa") == "fail":
        raise TtsError("audio QA failed", code=EXIT_QA)


def cmd_voices(args, suggest=False):
    vs = voices(args.language)
    rec = RECOMMENDED.get(args.language, [])
    if JSON_OUT:
        emit({"language": args.language, "recommended": rec, "voices": vs})
        return
    log(f"Voices for '{args.language}' ({len(vs)}):")
    for v in vs:
        mark = ("  <== RECOMMENDED"
                if suggest and any(v["name"].startswith(r) for r in rec) else "")
        log(f"  {v['name']}  [{v['gender']}]  id={v['id']}{mark}")


def main():
    parser = argparse.ArgumentParser(
        prog="tas.py",
        description="Speakee TTS + STT — speech synthesis, transcription, "
                    "and subtitles.",
        epilog="Exit codes: 0 ok, 1 error, 2 usage, 3 validation, "
               "4 network/API, 5 audio QA failed. Use --json for "
               "machine-readable output.")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-l", "--language", default=None,
                        help="ISO code or 'uid' (auto-detected if omitted)")
        sp.add_argument("-m", "--model", default=DEFAULT_MODEL)
        sp.add_argument("-v", "--voice_id", default=None,
                        help="voice name or UUID")
        sp.add_argument("-f", "--format", default="mp3")
        sp.add_argument("-s", "--speed", type=float, default=None,
                        help=f"0.5-2.0 (default {DEFAULT_SPEED})")
        sp.add_argument("--volume", type=float, default=None)
        sp.add_argument("-e", "--emotion", default=None,
                        help="base emotion (58 values, default neutral)")
        sp.add_argument("--no-emotion", action="store_true",
                        help="ignore inline [Emotion] tags and emoji")
        sp.add_argument("--preset", default=None,
                        help="built-in preset: news, story, assistant, audiobook")
        sp.add_argument("--chunk-limit", type=int, default=CHUNK_LIMIT,
                        help=f"characters per request (default {CHUNK_LIMIT})")
        sp.add_argument("--timeout", type=float, default=120)
        sp.add_argument("--retries", type=int, default=4)
        sp.add_argument("--workers", type=int, default=4)
        sp.add_argument("--no-cache", action="store_true")
        sp.add_argument("--force", action="store_true")
        sp.add_argument("--no-validate", action="store_true")
        sp.add_argument("--no-verify", action="store_true",
                        help="skip post-synthesis audio QA")
        sp.add_argument("--raw", action="store_true",
                        help="do not strip markdown/emoji")
        sp.add_argument("--dry-run", action="store_true")
        sp.add_argument("--json", action="store_true",
                        help="machine-readable JSON output")

    def output_args(sp):
        sp.add_argument("-o", "--out")
        sp.add_argument("--title")
        sp.add_argument("--artist")
        sp.add_argument("--album")

    sp = sub.add_parser("tts", help="synthesize text")
    common(sp)
    output_args(sp)
    sp.add_argument("text", nargs="*")
    sp.add_argument("--text-file")

    sp = sub.add_parser("uid", help="synthesize with a custom voice UID")
    common(sp)
    output_args(sp)
    sp.add_argument("text", nargs="*")
    sp.add_argument("--text-file")

    sp = sub.add_parser("conversation", help="multi-voice dialogue")
    common(sp)
    output_args(sp)
    sp.add_argument("script", help="file with 'Speaker: text' lines")
    sp.add_argument("--map", default=None,
                    help='speaker=voice pairs, e.g. "human=Nayem,ai=Pooja"')
    sp.add_argument("--silence", type=float, default=0.35)
    sp.add_argument("--no-stitch", action="store_true")
    sp.add_argument("--loudnorm", action="store_true")
    sp.add_argument("--manifest", default=None)
    sp.add_argument("--srt", default=None,
                    help="write an SRT subtitle file for the dialogue")

    def stt_args(sp):
        sp.add_argument("file", help="audio or video file")
        sp.add_argument("-l", "--language", default="auto",
                        help="language code, or 'auto' (default)")
        sp.add_argument("--chunk-seconds", type=float,
                        default=STT_CHUNK_SECONDS,
                        help="audio seconds per upload "
                             f"(default {STT_CHUNK_SECONDS})")
        sp.add_argument("--no-chunk", action="store_true",
                        help="upload in one request (max ~3.5 MB)")
        sp.add_argument("--workers", type=int, default=STT_WORKERS,
                        help=f"parallel uploads (default {STT_WORKERS})")
        sp.add_argument("--max-chars", type=int, default=STT_MAX_CHARS,
                        help=f"max cue characters (default {STT_MAX_CHARS})")
        sp.add_argument("--max-line-seconds", type=float,
                        default=STT_MAX_LINE_SECONDS,
                        help="max cue seconds "
                             f"(default {STT_MAX_LINE_SECONDS})")
        sp.add_argument("--timeout", type=float, default=300)
        sp.add_argument("--retries", type=int, default=3)
        sp.add_argument("--dry-run", action="store_true")
        sp.add_argument("--json", action="store_true",
                        help="machine-readable JSON output")

    sp = sub.add_parser("stt", help="transcribe audio/video (speech to text)")
    stt_args(sp)
    sp.add_argument("-o", "--out", default=None,
                    help="write the transcript to this file (default: stdout)")
    sp.add_argument("--srt", action="store_true",
                    help="write subtitles next to the input")
    sp.add_argument("--srt-path", default=None,
                    help="write the SRT to this path")
    sp.add_argument("--vtt", action="store_true",
                    help="write a WebVTT next to the input")
    sp.add_argument("--vtt-path", default=None,
                    help="write the WebVTT to this path")
    sp.add_argument("--no-word-timestamps", action="store_true",
                    help="faster, but subtitle timing is estimated")

    sp = sub.add_parser("transcribe", help="alias for stt")
    stt_args(sp)
    sp.add_argument("-o", "--out", default=None,
                    help="write the transcript to this file (default: stdout)")
    sp.add_argument("--srt", action="store_true",
                    help="write subtitles next to the input")
    sp.add_argument("--srt-path", default=None,
                    help="write the SRT to this path")
    sp.add_argument("--vtt", action="store_true",
                    help="write a WebVTT next to the input")
    sp.add_argument("--vtt-path", default=None,
                    help="write the WebVTT to this path")
    sp.add_argument("--no-word-timestamps", action="store_true",
                    help="faster, but subtitle timing is estimated")

    sp = sub.add_parser("subtitle",
                        help="transcribe and write an SRT subtitle file")
    stt_args(sp)
    sp.add_argument("-o", "--out", default=None,
                    help="SRT path (default: <input>.srt)")
    sp.add_argument("--vtt", action="store_true",
                    help="also write a WebVTT")
    sp.add_argument("--vtt-path", default=None,
                    help="WebVTT path (implies --vtt)")

    sp = sub.add_parser("verify", help="run audio QA on a file")
    sp.add_argument("file")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("voices", help="list voices for a language")
    sp.add_argument("-l", "--language", default=DEFAULT_LANG)
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("suggest", help="list voices with recommendations")
    sp.add_argument("-l", "--language", default=DEFAULT_LANG)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("presets", help="list built-in voice presets")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("languages", help="list languages")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("models", help="list models")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("cache-clear", help="delete the synthesis cache")
    sp.add_argument("--json", action="store_true")

    args = parser.parse_args()
    global JSON_OUT
    JSON_OUT = getattr(args, "json", False)

    try:
        if args.cmd == "tts":
            cmd_tts(args)
        elif args.cmd == "uid":
            cmd_tts(args, uid_mode=True)
        elif args.cmd == "conversation":
            cmd_conversation(args)
        elif args.cmd in ("stt", "transcribe"):
            cmd_stt(args)
        elif args.cmd == "subtitle":
            cmd_stt(args, subtitle=True)
        elif args.cmd == "verify":
            cmd_verify(args)
        elif args.cmd == "voices":
            cmd_voices(args)
        elif args.cmd == "suggest":
            cmd_voices(args, suggest=True)
        elif args.cmd == "presets":
            presets = load_presets()
            if JSON_OUT:
                emit(presets)
            else:
                for name, data in presets.items():
                    log(f"  {name:10s} {data.get('description', '')}")
                    log(f"             voices: " + ", ".join(
                        f"{lang}={voice}" for lang, voice in
                        data.get("voices", {}).items()))
        elif args.cmd == "languages":
            data = languages()
            if JSON_OUT:
                emit(data)
            else:
                for item in data:
                    log(f"  {item['code']:6s} {item['name']}")
        elif args.cmd == "models":
            data = models()
            if JSON_OUT:
                emit(data)
            else:
                for item in data:
                    log(" ", item)
        elif args.cmd == "cache-clear":
            if CACHE_DIR.exists():
                shutil.rmtree(CACHE_DIR)
            if JSON_OUT:
                emit({"cache": str(CACHE_DIR), "cleared": True})
            else:
                log(f"cache cleared: {CACHE_DIR}")
    except TtsError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()
