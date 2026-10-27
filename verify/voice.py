"""Call-recording transcription (verify Fix 23).

``transcribe(wav_path)`` sends a WAV recording to the Muse Voice
transcription endpoint (``POST {META_API_BASE_URL}/asr/transcribe``)
and returns the transcript text.

The request is multipart: a ``request`` part (``application/json``)
with the model/encoding/mode/language-bias JSON, and an ``audio``
part (``audio/wav``) with the file bytes. The live response schema
(observed 27 Oct 2026, one call with ``call.wav``) is::

    {"audioDurationMs": int, "sessionId": str,
     "transcript": str, "turns": [...]}

so the transcript is read from the top-level ``transcript`` field.

Only mono 16-bit WAV at 16 kHz or 24 kHz is accepted; anything else
is refused with a clear message *before* any HTTP call. Offline
tests mock the HTTP call (``requests.post``); no real call is made
unless the defaults are used with the environment configured.
"""
import json
import os
import wave
from pathlib import Path

TRANSCRIBE_MODEL = "muse-voice-transcribe-1.0"
_ALLOWED_SAMPLE_RATES = (16000, 24000)


def _describe(params):
    channel_text = {1: "mono", 2: "stereo"}.get(
        params.nchannels, "%d channels" % params.nchannels)
    return "%s, %d-bit, %d Hz" % (
        channel_text, params.sampwidth * 8, params.framerate)


def validate_wav(wav_path):
    """Validate ``wav_path``; return its ``wave`` params.

    Raises ``ValueError`` with a clear message unless the file is a
    readable mono 16-bit WAV sampled at 16 kHz or 24 kHz.
    """
    path = Path(wav_path)
    if not path.is_file():
        raise ValueError(
            "Refusing to transcribe %s: file not found." % path)
    try:
        with wave.open(str(path), "rb") as wav:
            params = wav.getparams()
    except (wave.Error, EOFError, OSError) as exc:
        raise ValueError(
            "Refusing to transcribe %s: not a valid WAV file (%s). "
            "Expected mono 16-bit WAV at 16 kHz or 24 kHz."
            % (path, exc)) from exc
    problems = []
    if params.nchannels != 1:
        problems.append("must be mono (got %d channel(s))"
                        % params.nchannels)
    if params.sampwidth != 2:
        problems.append("must be 16-bit (got %d-bit)"
                        % (params.sampwidth * 8))
    if params.framerate not in _ALLOWED_SAMPLE_RATES:
        problems.append("must be 16 kHz or 24 kHz (got %d Hz)"
                        % params.framerate)
    if problems:
        raise ValueError(
            "Refusing to transcribe %s: WAV %s. Got %s; expected "
            "mono 16-bit WAV at 16 kHz or 24 kHz."
            % (path, "; ".join(problems), _describe(params)))
    return params


def transcribe(wav_path, *, timeout=120):
    """Transcribe ``wav_path`` and return the transcript text.

    Validates the WAV first (see :func:`validate_wav`), then POSTs
    it to ``{META_API_BASE_URL}/asr/transcribe``. Reads
    ``META_API_KEY`` and ``META_API_BASE_URL`` from the environment;
    raises ``RuntimeError`` if they are unset or if the response has
    no ``transcript`` field.
    """
    path = Path(wav_path)
    validate_wav(path)
    api_key = os.environ.get("META_API_KEY")
    base_url = os.environ.get("META_API_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError(
            "META_API_KEY and META_API_BASE_URL must be set to use "
            "voice transcription.")
    import requests  # allowed dependency; imported lazily

    request_payload = {
        "model": TRANSCRIBE_MODEL,
        "audioEncoding": "WAV",
        "mode": "PUSH_TO_TALK",
        "languageBias": ["hi", "en"],
        "keywords": ["IRDAI", "revival", "revive", "bonus",
                     "lapse", "policy", "premium", "fee"],
    }
    with path.open("rb") as audio_file:
        files = {
            "request": (None, json.dumps(request_payload),
                        "application/json"),
            "audio": (path.name, audio_file, "audio/wav"),
        }
        resp = requests.post(
            base_url.rstrip("/") + "/asr/transcribe",
            headers={"Authorization": "Bearer " + api_key,
                     "Accept": "application/json"},
            files=files,
            timeout=timeout,
        )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) \
            or not isinstance(data.get("transcript"), str) \
            or not data["transcript"].strip():
        keys = sorted(data.keys()) if isinstance(data, dict) else []
        raise RuntimeError(
            "ASR response had no 'transcript' text (keys: %s)."
            % (", ".join(keys) if keys else "not a JSON object"))
    return data["transcript"].strip()
