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

No real model is wired here. ``make_model_backend()`` builds a
backend from the environment (``META_API_KEY``, ``VERIFIER_MODEL``,
``META_API_BASE_URL``) using ``requests``; it is never called by the
offline tests, which inject fake backends.
"""
import json
import os

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


def _insufficient(reason):
    return {"verdict": INSUFFICIENT_EVIDENCE, "reason": reason}


def _parse_backend_output(raw):
    """Validate strict-JSON backend output; fail closed if malformed."""
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return _insufficient(
                "Verifier output was not valid JSON; failing closed.")
    else:
        return _insufficient(
            "Verifier output had an unexpected type; failing closed.")
    if not isinstance(data, dict):
        return _insufficient(
            "Verifier output was not a JSON object; failing closed.")
    verdict = data.get("verdict")
    if verdict not in _VERDICTS:
        return _insufficient(
            "Verifier output had no valid verdict; failing closed.")
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        return _insufficient(
            "Verifier reason was not a string; failing closed.")
    return {"verdict": verdict,
            "reason": reason or "Verifier gave no reason."}


class Verifier:
    """Wraps a backend callable with strict, fail-closed parsing."""

    def __init__(self, backend=None):
        self._backend = backend

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
        try:
            raw = self._backend(claim, quote, source_text)
        except Exception as exc:  # backend failure must fail closed
            return _insufficient(
                "Verifier backend failed (%s); failing closed."
                % type(exc).__name__)
        return _parse_backend_output(raw)


def verify_claim(claim, quote, source_text, backend=None):
    """Verify one claim against its quote and full source text.

    ``backend`` is a callable ``(claim, quote, source_text)`` returning
    strict JSON (``str`` or already-parsed ``dict``). With no backend,
    fails closed to ``INSUFFICIENT_EVIDENCE``.
    """
    return Verifier(backend).verify(claim, quote, source_text)


def make_model_backend(model=None, *, timeout=60):
    """Build a Meta Model API backend from the environment.

    Reads ``META_API_KEY``, ``VERIFIER_MODEL`` and
    ``META_API_BASE_URL`` from the environment; no secret or model id
    is hard-coded. Raises ``RuntimeError`` if they are unset. Not
    called by offline tests.
    """
    api_key = os.environ.get("META_API_KEY")
    model_id = model or os.environ.get("VERIFIER_MODEL")
    base_url = os.environ.get("META_API_BASE_URL")
    if not api_key or not model_id or not base_url:
        raise RuntimeError(
            "META_API_KEY, VERIFIER_MODEL and META_API_BASE_URL must "
            "be set to use the model verifier backend.")

    def backend(claim, quote, source_text):
        import requests  # allowed dependency; imported lazily

        prompt = _PROMPT.format(
            claim=claim, quote=quote, source_text=str(source_text)[:20000])
        resp = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"},
            json={"model": model_id,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return backend
