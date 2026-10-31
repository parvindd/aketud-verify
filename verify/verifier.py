"""Claim verifier (hackathon Step 2).

``verify_claim(claim, quote, source_text)`` returns one of
``SUPPORTED``, ``CONTRADICTED`` or ``INSUFFICIENT_EVIDENCE`` plus a
reason. The interface is model-agnostic: a :class:`Verifier` wraps a
backend callable ``backend(claim, quote, source_text) -> str | dict``
so the backend can later be Muse Spark Open on Modal/Baseten (or the
Meta Model API) without changing callers.

The backend is expected to emit strict JSON of the form
``{"verdict": "SUPPORTED"|"CONTRADICTED"|"INSUFFICIENT_EVIDENCE",
"reason": "..."}``. Anything malformed — unparseable output, a
non-object, a missing/unknown verdict, or a backend exception —
fails closed to ``INSUFFICIENT_EVIDENCE``. Nothing not proven
``SUPPORTED`` is ever treated as supported.

``make_model_backend()`` builds the live backend from the
environment using ``requests``; it is never called by the offline
tests, which inject fake backends and stub ``requests.post`` for
both backends (see below).

Verifier backend selection (Fix 27 — Muse Spark Open on Modal):

* Primary: the verifier reads its *own* env — ``VERIFIER_BASE_URL``,
  ``VERIFIER_API_KEY`` and ``VERIFIER_MODEL`` — an OpenAI-compatible
  ``/chat/completions`` endpoint (Muse Spark Open on Modal).
* Fallback: if any of ``VERIFIER_*`` is unset (a non-HTTP(S)
  placeholder such as ``PASTE_ENDPOINT_URL/v1`` counts as unset),
  the current Meta Model API verifier is used instead
  (``META_API_KEY`` / ``META_API_BASE_URL`` with
  ``PROPOSER_MODEL`` or :data:`FALLBACK_MODEL`), and the trace says
  so: ``verifier: muse-spark-1.3 (fallback)``.

The proposer is unaffected: it keeps ``META_API_*`` /
``PROPOSER_MODEL`` (see ``verify.pipeline.make_model_proposer``).
"""
import json
import os
import threading
import time

SUPPORTED = "SUPPORTED"
CONTRADICTED = "CONTRADICTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

_VERDICTS = (SUPPORTED, CONTRADICTED, INSUFFICIENT_EVIDENCE)

_PROMPT = (
    "You are a strict claim verifier. Decide whether the claim is "
    "supported by the quoted passage from the source. Reply with "
    'strict JSON only: {{"verdict": "SUPPORTED" | "CONTRADICTED" | '
    '"INSUFFICIENT_EVIDENCE", "reason": "<one or two sentences>"}}. '
    "Use CONTRADICTED when the passage (or a rule it is superseded "
    "by) says the opposite, INSUFFICIENT_EVIDENCE when the passage "
    "does not establish the claim, and SUPPORTED only when the "
    "passage directly establishes the claim.\n\n"
    "Claim: {claim}\nQuote: {quote}\nSource text: {source_text}"
)


def _context_window(source_text, quote, window=4000):
    """Return a ``window``-char slice of ``source_text`` around ``quote``.

    Falls back to the start of the text only if the quote is not
    found. Matching tries an exact search first, then a
    whitespace-insensitive search (PDF extraction drops spaces).
    """
    text = str(source_text)
    if len(text) <= window:
        return text
    pos = -1
    qlen = 0
    if quote:
        pos = text.find(str(quote))
        qlen = len(str(quote))
    if pos < 0 and quote:
        # Whitespace-insensitive search with an index map back to
        # the original text.
        squashed_chars = []
        index_map = []
        for i, ch in enumerate(text):
            if not ch.isspace():
                squashed_chars.append(ch.lower())
                index_map.append(i)
        squashed = "".join(squashed_chars)
        needle = "".join(
            ch.lower() for ch in str(quote) if not ch.isspace())
        spos = squashed.find(needle) if needle else -1
        if spos >= 0:
            pos = index_map[spos]
            end_idx = spos + len(needle) - 1
            qlen = index_map[end_idx] - pos + 1 if end_idx < len(
                index_map) else qlen
    if pos < 0:
        return text[:window]
    center = pos + qlen // 2
    start = max(0, min(center - window // 2, len(text) - window))
    return text[start:start + window]


# Alias for discoverability.
context_window = _context_window


def _insufficient(reason):
    return {"verdict": INSUFFICIENT_EVIDENCE, "reason": reason}


# Fix 34: a malformed reply is retried at most this many times.
MAX_MALFORMED_RETRIES = 1
RAW_OUTPUT_LOG_CHARS = 500


def _loads_lenient(text):
    """Parse JSON, tolerating ```json fences and leading/trailing text.

    Tries the text as-is, then the first ``{...}`` object found in it
    (which covers fenced output and a chatty preamble). Raises
    ``ValueError`` if no JSON value can be decoded.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in verifier output")
    data, _end = json.JSONDecoder().raw_decode(text[start:])
    return data


def _parse_backend_output(raw):
    """Validate strict-JSON backend output; fail closed if malformed.

    Returns ``(result, malformed)``. The verdict must be exactly one
    of the three allowed values; anything else is malformed.
    """
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        try:
            data = _loads_lenient(raw)
        except (ValueError, TypeError):
            return (_insufficient(
                "Verifier output was not valid JSON; failing closed."),
                True)
    else:
        return (_insufficient(
            "Verifier output had an unexpected type; failing closed."),
            True)
    if not isinstance(data, dict):
        return (_insufficient(
            "Verifier output was not a JSON object; failing closed."),
            True)
    verdict = data.get("verdict")
    if verdict not in _VERDICTS:
        return (_insufficient(
            "Verifier output had no valid verdict; failing closed."),
            True)
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        return (_insufficient(
            "Verifier reason was not a string; failing closed."), True)
    return ({"verdict": verdict,
             "reason": reason or "Verifier gave no reason."}, False)


def _sum_usage(a, b):
    """Add two ``usage`` dicts (token counts); ``None`` if both absent."""
    if not isinstance(a, dict):
        return b
    if not isinstance(b, dict):
        return a
    total = dict(a)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in a or key in b:
            total[key] = int(a.get(key) or 0) + int(b.get(key) or 0)
    return total


FALLBACK_MODEL = "muse-spark-1.3"


def _is_http_url(value):
    return bool(value) and str(value).strip().lower().startswith(
        ("http://", "https://"))


def resolve_verifier_config(env=None):
    """Resolve verifier backend config from the environment.

    Returns ``{base_url, api_key, model, fallback}``. The primary
    (Modal) backend is used only when ``VERIFIER_BASE_URL`` (an
    HTTP(S) URL), ``VERIFIER_API_KEY`` and ``VERIFIER_MODEL`` are
    all set; otherwise the Meta Model API fallback is returned with
    ``fallback=True`` (its model is ``PROPOSER_MODEL`` or
    :data:`FALLBACK_MODEL`, never the Modal model id).
    """
    env = os.environ if env is None else env
    v_base = (env.get("VERIFIER_BASE_URL") or "").strip()
    v_key = (env.get("VERIFIER_API_KEY") or "").strip()
    v_model = (env.get("VERIFIER_MODEL") or "").strip()
    if _is_http_url(v_base) and v_key and v_model:
        return {"base_url": v_base, "api_key": v_key,
                "model": v_model, "fallback": False}
    return {
        "base_url": (env.get("META_API_BASE_URL") or "").strip() or None,
        "api_key": (env.get("META_API_KEY") or "").strip() or None,
        "model": ((env.get("PROPOSER_MODEL") or "").strip()
                  or FALLBACK_MODEL),
        "fallback": True,
    }


def verifier_label(model=None, fallback=None, env=None):
    """Trace label, e.g. ``verifier: muse-spark-1.3 (fallback)``."""
    cfg = resolve_verifier_config(env)
    model_id = model or cfg["model"]
    is_fallback = cfg["fallback"] if fallback is None else fallback
    label = "verifier: %s" % model_id
    if is_fallback:
        label += " (fallback)"
    return label


class Verifier:
    """Wraps a backend callable with strict, fail-closed parsing.

    ``model`` / ``fallback`` / ``label`` identify which model
    verified claims (read from the backend's ``model`` /
    ``is_fallback`` / ``verifier_label`` attributes when not given
    explicitly). After each live call, ``last_usage``,
    ``last_latency_s`` and ``last_response_model`` mirror the
    backend's recorded response data (``None`` for fake backends).
    Those three are thread-local so one ``Verifier`` may be shared
    by the pipeline's thread pool without calls overwriting each
    other's usage/latency.
    """

    @property
    def last_usage(self):
        return getattr(self._local, "last_usage", None)

    @last_usage.setter
    def last_usage(self, value):
        self._local.last_usage = value

    @property
    def last_latency_s(self):
        return getattr(self._local, "last_latency_s", None)

    @last_latency_s.setter
    def last_latency_s(self, value):
        self._local.last_latency_s = value

    @property
    def last_response_model(self):
        return getattr(self._local, "last_response_model", None)

    @last_response_model.setter
    def last_response_model(self, value):
        self._local.last_response_model = value

    def __init__(self, backend=None, *, model=None, fallback=None,
                 label=None):
        self._local = threading.local()
        self._backend = backend
        backend_model = None
        backend_fallback = None
        backend_label = None
        if backend is not None:
            backend_model = (getattr(backend, "model", None)
                             or getattr(backend, "verifier_model", None))
            if hasattr(backend, "is_fallback"):
                backend_fallback = getattr(backend, "is_fallback")
            elif hasattr(backend, "fallback"):
                backend_fallback = getattr(backend, "fallback")
            backend_label = (getattr(backend, "verifier_label", None)
                             or getattr(backend, "label", None))
        self.model = model or backend_model
        self.fallback = (backend_fallback if fallback is None
                         else fallback)
        self._label = label or backend_label
        self.last_usage = None
        self.last_latency_s = None
        self.last_response_model = None

    @property
    def label(self):
        """Trace label for this verifier (see :func:`verifier_label`)."""
        if self._label:
            return self._label
        if self.model:
            return verifier_label(self.model, self.fallback)
        if self._backend is None:
            return "verifier: (not configured)"
        return "verifier: (injected backend)"

    def verify(self, claim, quote, source_text):
        if self._backend is None:
            return _insufficient(
                "No verifier backend configured; failing closed.")
        if claim is None or not str(claim).strip():
            return _insufficient("Empty claim; nothing to verify.")
        if quote is None or not str(quote).strip():
            return _insufficient("Empty quote; no evidence to verify.")
        if source_text is None or not str(source_text).strip():
            return _insufficient(
                "No source text available; failing closed.")
        # Fix 34: a malformed reply is retried once with the same
        # request; usage and latency cover every attempt. If the
        # retry is malformed too, the result fails closed and carries
        # the raw text (truncated) for the trace.
        usage = None
        latency = None
        for attempt in range(1 + MAX_MALFORMED_RETRIES):
            try:
                raw = self._backend(claim, quote, source_text)
            except Exception as exc:  # backend failure must fail closed
                return _insufficient(
                    "Verifier backend failed (%s); failing closed."
                    % type(exc).__name__)
            usage = _sum_usage(
                usage, getattr(self._backend, "last_usage", None))
            step = getattr(self._backend, "last_latency_s", None)
            if step is not None:
                latency = (latency or 0.0) + step
            self.last_usage = usage
            self.last_latency_s = latency
            self.last_response_model = getattr(
                self._backend, "last_response_model", None)
            result, malformed = _parse_backend_output(raw)
            if not malformed:
                return result
        result["raw_output"] = (
            raw[:RAW_OUTPUT_LOG_CHARS] if isinstance(raw, str)
            else repr(raw)[:RAW_OUTPUT_LOG_CHARS])
        result["attempts"] = attempt + 1
        return result


def verify_claim(claim, quote, source_text, backend=None):
    """Verify one claim against its quote and full source text.

    ``backend`` is a callable ``(claim, quote, source_text)`` returning
    strict JSON (``str`` or already-parsed ``dict``). With no backend,
    fails closed to ``INSUFFICIENT_EVIDENCE``.
    """
    return Verifier(backend).verify(claim, quote, source_text)


def make_model_backend(model=None, *, timeout=60):
    """Build the live verifier backend from the environment.

    Primary (Fix 27): ``VERIFIER_BASE_URL`` / ``VERIFIER_API_KEY`` /
    ``VERIFIER_MODEL`` (OpenAI-compatible ``/chat/completions``,
    Muse Spark Open on Modal). If any of ``VERIFIER_*`` is unset,
    falls back to the Meta Model API verifier (``META_API_KEY`` /
    ``META_API_BASE_URL``, model ``PROPOSER_MODEL`` or
    ``muse-spark-1.3``); the returned backend then carries
    ``is_fallback=True`` and label ``verifier: muse-spark-1.3
    (fallback)``. Raises ``RuntimeError`` if the selected backend's
    env is incomplete. Not called by offline tests (both backends
    are mocked there).

    The backend records ``last_usage`` (the response ``usage``
    object), ``last_latency_s`` and ``last_response_model`` after
    each call, and exposes ``model`` / ``is_fallback`` /
    ``verifier_label`` for the trace and demo.
    """
    cfg = resolve_verifier_config()
    model_id = model or cfg["model"]
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    is_fallback = cfg["fallback"]
    if not api_key or not model_id or not base_url:
        raise RuntimeError(
            "VERIFIER_BASE_URL, VERIFIER_API_KEY and VERIFIER_MODEL "
            "(or the META_API_KEY / META_API_BASE_URL fallback) must "
            "be set to use the verifier backend.")
    label = verifier_label(model_id, is_fallback)
    return _ModelBackend(model_id, base_url, api_key, is_fallback,
                         label, timeout)


class _ModelBackend:
    """OpenAI-compatible verifier backend (Fix 28).

    Sends ``response_format`` json_object, ``reasoning_effort``
    ``"low"`` and ``max_tokens`` 600 (Fix 34; was 300) — parsing
    stays strict / fail-closed in :class:`Verifier`. ``last_*`` are thread-local
    so parallel calls each keep their own usage/latency.
    """

    def __init__(self, model_id, base_url, api_key, is_fallback,
                 label, timeout=60):
        self.model = model_id
        self.verifier_model = model_id
        self.is_fallback = is_fallback
        self.fallback = is_fallback
        self.verifier_label = label
        self.label = label
        self.base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._local = threading.local()

    @property
    def last_usage(self):
        return getattr(self._local, "last_usage", None)

    @last_usage.setter
    def last_usage(self, value):
        self._local.last_usage = value

    @property
    def last_latency_s(self):
        return getattr(self._local, "last_latency_s", None)

    @last_latency_s.setter
    def last_latency_s(self, value):
        self._local.last_latency_s = value

    @property
    def last_response_model(self):
        return getattr(self._local, "last_response_model", None)

    @last_response_model.setter
    def last_response_model(self, value):
        self._local.last_response_model = value

    def __call__(self, claim, quote, source_text):
        import requests  # allowed dependency; imported lazily

        prompt = _PROMPT.format(
            claim=claim, quote=quote,
            source_text=_context_window(source_text, quote))
        started = time.monotonic()
        resp = requests.post(
            self.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + self._api_key,
                     "Content-Type": "application/json"},
            json={"model": self.model,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0,
                  "response_format": {"type": "json_object"},
                  "reasoning_effort": "low",
                  "max_tokens": 600},
            timeout=self._timeout,
        )
        self.last_latency_s = time.monotonic() - started
        resp.raise_for_status()
        payload = resp.json()
        self.last_usage = payload.get("usage")
        self.last_response_model = payload.get("model")
        return payload["choices"][0]["message"]["content"]


# Alias for discoverability (Fix 27).
make_verifier_backend = make_model_backend
