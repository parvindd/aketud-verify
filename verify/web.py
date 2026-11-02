"""Minimal local web demo (Fix 32).

Run::

    python -m verify.web

then open http://localhost:8000 in a browser.

Stdlib ``http.server`` only (Flask is not installed in this repo and
no new dependency is added). One page: a text box, a language
selector, an "answer / check a call" mode switch and an audio-file
upload for call recordings. The result is shown as the same stages
as :mod:`verify.demo` — draft -> evidence -> verifier -> governing
rule -> final decision — as cards, with the final decision in large
text coloured by outcome.

Fix 39 — live progress: ``POST /check`` starts the check in a
background thread and returns the page at once with a job id; inline
JS polls ``GET /status/<id>`` every second. Stages are ticked from
real ``progress`` events emitted by the pipeline / callcheck (and by
:func:`run_audio` for transcription), never from a timer. Jobs live
in memory only and are dropped 10 minutes after they start. The
server binds to localhost only.

No verification logic lives here: questions go to
:func:`verify.pipeline.answer` and call transcripts / recordings go
to :func:`verify.callcheck.check_call` (with the same live-model
wiring as the CLI demo). API keys are read server-side from ``.env``
via :func:`verify.demo.load_env` and are never sent to the browser.
"""
import html
import json
import os
import re
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from verify.callcheck import (_SAFETY_LABEL, _verified_by_display,
                                  check_call)
    from verify.demo import _call_models, _draft_claims, load_env
    from verify.pipeline import answer
    from verify.voice import transcribe
except ImportError:  # run as top-level module (cd verify)
    from callcheck import _SAFETY_LABEL, _verified_by_display, check_call
    from demo import _call_models, _draft_claims, load_env
    from pipeline import answer
    from voice import transcribe

_LANGS = ("auto", "en", "hi", "hinglish")
_LANG_LABELS = {"auto": "Auto-detect", "en": "English",
                "hi": "हिंदी (Hindi)", "hinglish": "Hinglish"}

_DECISION_COLOURS = {
    "VERIFIED": "#137333",
    "SUPPORTED BY RULES": "#137333",
    "REFUSED": "#b3261e",
    "CONTRADICTS RULES": "#b3261e",
    "CORRECTED": "#b06000",
    "CANNOT BE CONFIRMED (ask insurer)": "#b06000",
    "SUPERSEDED": "#9334e6",
    "APPLIES_TO_OLDER_CONTRACT": "#9334e6",
    "DEPENDS_ON_SALE_DATE": "#b06000",
}


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _colour(outcome):
    return _DECISION_COLOURS.get(str(outcome or "").strip(), "#202124")


def _resolve_lang(lang):
    lang = str(lang or "auto").strip().lower()
    return None if lang in ("", "auto") else lang


# --- Pipeline seams (mocked in tests; no logic duplicated) ------------

def _progress_kwargs(progress):
    return {"progress": progress} if progress is not None else {}


def run_answer(question, lang=None, sale_date=None, progress=None):
    """Answer a question via the pipeline (live models from env)."""
    return answer(question, lang=_resolve_lang(lang),
                  sale_date=sale_date or None,
                  **_progress_kwargs(progress))


def run_call(transcript, lang=None, progress=None):
    """Check a call transcript via callcheck (demo's live wiring)."""
    try:
        proposer, verifier = _call_models()
    except Exception:
        proposer, verifier = None, None
    return check_call(transcript, lang=_resolve_lang(lang),
                      proposer=proposer, verifier=verifier,
                      **_progress_kwargs(progress))


def run_audio(audio_bytes, filename, lang=None, progress=None):
    """Transcribe an uploaded recording, then check the call."""
    suffix = Path(str(filename or "call.wav")).suffix or ".wav"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False) as fh:
            fh.write(audio_bytes)
            tmp = fh.name
        if progress is not None:
            progress("transcribe", None)
        transcript = transcribe(tmp)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    trace = run_call(transcript, lang=lang, **_progress_kwargs(progress))
    trace["transcript"] = transcript
    return trace


# --- Rendering ---------------------------------------------------------

def _evidence_label(claim):
    evidence = claim.get("evidence") or {}
    found = bool(evidence.get("exists") and evidence.get("found"))
    return found, evidence


def _verified_by(trace, claim):
    """One Stage 3 line: ``verified by: <model>`` or rule only (Fix 35)."""
    return "verified by: %s" % _esc(_verified_by_display(trace, claim))


def _card(title, body_html):
    return ('<section class="card"><h2>%s</h2>%s</section>'
            % (_esc(title), body_html))


def render_answer_cards(trace):
    """Cards for a pipeline trace: same stages as demo.py."""
    cards = []
    draft_claims = _draft_claims(trace)
    if draft_claims:
        items = "".join(
            "<li>%s &mdash; %s</li>" % (
                _esc(c.get("claim", c.get("text", ""))),
                _esc(c.get("source_file", c.get("source", ""))))
            for c in draft_claims)
        body = "<ol>%s</ol>" % items
    else:
        body = "<p>(no claims in draft)</p>"
    cards.append(_card("Stage 1 — Draft (proposer)", body))

    claims = trace.get("claims") or []
    if claims:
        items = ""
        for idx, claim in enumerate(claims, 1):
            found, evidence = _evidence_label(claim)
            label = "FOUND" if found else "NOT FOUND"
            colour = "#137333" if found else "#b3261e"
            items += (
                "<li>Claim %d: %s<br>Source: %s<br>"
                'Evidence: <strong style="color:%s">%s</strong> '
                "(exists=%s, found=%s)<br>Quote: %s</li>" % (
                    idx, _esc(claim.get("claim", "")),
                    _esc(claim.get("source_file", "")), colour, label,
                    _esc(evidence.get("exists")),
                    _esc(evidence.get("found")),
                    _esc(claim.get("quote", ""))))
        body = "<ol>%s</ol>" % items
    else:
        body = "<p>(no claims to check)</p>"
    cards.append(_card("Stage 2 — Evidence check (found / not found)", body))

    if claims:
        items = ""
        for idx, claim in enumerate(claims, 1):
            verdict = (claim.get("verifier_verdict")
                       or claim.get("verdict") or "(not verified)")
            reason = claim.get("verifier_reason")
            if reason is None:
                reason = claim.get("reason") or ""
            items += (
                "<li>Claim %d: %s &mdash; %s<br>Cited source: %s<br>"
                "%s</li>" % (
                    idx, _esc(verdict), _esc(reason),
                    _esc(claim.get("source_file", "")),
                    _verified_by(trace, claim)))
        body = "<ol>%s</ol>" % items
    else:
        body = "<p>(no claims to verify)</p>"
    cards.append(_card("Stage 3 — Verifier (model named)", body))

    governing = [c for c in claims
                 if c.get("governing_source") or c.get("governing_verdict")]
    if governing:
        items = ""
        for idx, claim in enumerate(claims, 1):
            if not (claim.get("governing_source")
                    or claim.get("governing_verdict")):
                continue
            gov_ev = claim.get("governing_evidence") or {}
            gov_found = bool(gov_ev.get("exists") and gov_ev.get("found"))
            items += (
                "<li>Claim %d: governing source %s (%s, %s)<br>"
                "Governing evidence: %s<br>Governing verdict: %s "
                "&mdash; %s<br>Governing quote: %s</li>" % (
                    idx, _esc(claim.get("governing_source", "")),
                    _esc(claim.get("governing_title", "")),
                    _esc(claim.get("governing_effective_display")
                         or claim.get("governing_effective_date", "")),
                    "FOUND" if gov_found else "NOT FOUND",
                    _esc(claim.get("governing_verdict") or "(none)"),
                    _esc(claim.get("governing_reason") or ""),
                    _esc(claim.get("governing_quote", ""))))
        body = "<ul>%s</ul>" % items
    else:
        body = "<p>(no governing rule applies)</p>"
    cards.append(_card("Stage 4 — Governing rule", body))

    decision = str(trace.get("decision") or "")
    body = ('<p class="decision" style="color:%s">%s</p>'
            % (_colour(decision), _esc(decision)))
    # Fix 36: which sale date was used, and the savings clause check.
    sale = trace.get("sale_date")
    if sale:
        body += "<p>Sale date: %s to %s (%s: %s)</p>" % (
            _esc(sale.get("earliest")), _esc(sale.get("latest")),
            _esc(sale.get("source")), _esc(sale.get("text")))
    if trace.get("sale_date_error"):
        body += "<p>Sale date not used: %s</p>" % _esc(
            trace["sale_date_error"])
    for saving in trace.get("savings") or []:
        ev = saving.get("evidence") or {}
        body += "<p>Savings clause: %s &mdash; evidence %s</p>" % (
            _esc(saving.get("citation")),
            "FOUND" if ev.get("exists") and ev.get("found")
            else "NOT FOUND")
    if trace.get("refusal_reason"):
        body += "<p>Refusal reason: %s</p>" % _esc(trace["refusal_reason"])
    if trace.get("final_answer"):
        body += '<p class="final">%s</p>' % _esc(trace["final_answer"])
    cards.append(_card("Stage 5 — Final decision", body))
    return "\n".join(cards)


def render_call_cards(trace):
    """Cards for a call-check trace, in the same stage order."""
    cards = []
    claims = trace.get("claims") or []
    if trace.get("transcript"):
        cards.append(_card(
            "Stage 0 — Transcript",
            "<p>%s</p>" % _esc(trace["transcript"])))
    if claims:
        items = "".join(
            "<li>%s &mdash; rule %s (%s) &mdash; %s<br>"
            "extracted by: %s</li>" % (
                _esc(c.get("claim", "")), _esc(c.get("rule", "?")),
                _esc(c.get("citation", "")),
                _esc(c.get("source_file", "")),
                _esc(c.get("extracted_by", "")))
            for c in claims)
        body = "<ol>%s</ol>" % items
    else:
        body = "<p>(no caller claims extracted)</p>"
    cards.append(_card("Stage 1 — Draft (caller claims extracted)", body))

    if claims:
        items = ""
        for idx, claim in enumerate(claims, 1):
            found, evidence = _evidence_label(claim)
            label = "FOUND" if found else "NOT FOUND"
            colour = "#137333" if found else "#b3261e"
            items += (
                "<li>Claim %d: %s<br>"
                'Evidence: <strong style="color:%s">%s</strong> '
                "(exists=%s, found=%s)<br>Quote: %s</li>" % (
                    idx, _esc(claim.get("claim", "")), colour, label,
                    _esc(evidence.get("exists")),
                    _esc(evidence.get("found")),
                    _esc(claim.get("quote", ""))))
        body = "<ol>%s</ol>" % items
    else:
        body = "<p>(no claims to check)</p>"
    cards.append(_card("Stage 2 — Evidence check (found / not found)", body))

    if claims:
        items = ""
        for idx, claim in enumerate(claims, 1):
            items += (
                "<li>Claim %d: %s &mdash; %s<br>%s</li>" % (
                    idx,
                    _esc(claim.get("verifier_verdict") or "(not run)"),
                    _esc(claim.get("verifier_reason") or ""),
                    _verified_by(trace, claim)))
        body = "<ol>%s</ol>" % items
    else:
        body = "<p>(no claims to verify)</p>"
    cards.append(_card("Stage 3 — Verifier (model named)", body))

    if claims:
        items = "".join(
            "<li>Claim %d: rule %s &mdash; %s (%s)<br>Quote: %s</li>" % (
                idx, _esc(c.get("rule", "?")),
                _esc(c.get("source_file", "")),
                _esc(c.get("citation", "")),
                _esc(c.get("quote", "")))
            for idx, c in enumerate(claims, 1))
        body = "<ul>%s</ul>" % items
    else:
        body = "<p>(no governing rule applies)</p>"
    cards.append(_card("Stage 4 — Governing rule", body))

    # Fix 35: each claim's verdict once, with its reason; the safety
    # advice once (final_block repeats both, so it is not shown).
    if claims:
        items = "".join(
            '<li><strong style="color:%s">%s</strong> &mdash; %s'
            "<br>%s</li>" % (
                _colour(c.get("verdict", "")),
                _esc(c.get("verdict_label") or c.get("verdict", "")),
                _esc(c.get("claim_label") or c.get("claim", "")),
                _esc(c.get("reason") or ""))
            for c in claims)
        body = "<ol>%s</ol>" % items
    else:
        body = ('<p class="decision" style="color:%s">'
                "CANNOT BE CONFIRMED (ask insurer)</p>"
                % _colour("CANNOT BE CONFIRMED (ask insurer)"))
    if trace.get("safety_advice"):
        body += "<p><strong>%s:</strong> %s</p>" % (
            _esc(_SAFETY_LABEL.get(trace.get("lang"), "Safety advice")),
            _esc(trace["safety_advice"]))
    cards.append(_card("Stage 5 — Final decision", body))
    return "\n".join(cards)


_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aketud Verify — demo</title>
<style>
body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;
padding:0 1rem;color:#202124}
.card{border:1px solid #dadce0;border-radius:8px;padding:1rem;
margin:1rem 0}
.decision{font-size:2rem;font-weight:700;margin:.5rem 0}
label{display:block;margin:.6rem 0 .2rem;font-weight:600}
textarea{width:100%}pre{white-space:pre-wrap}
#stages{list-style:none;padding-left:0}#stages li{margin:.25rem 0}
#stages .done{color:#137333}#stages .active{font-weight:700}
#stages .pending,#stages .skipped{color:#5f6368}
.final{white-space:pre-wrap}
.error{border-color:#b3261e;color:#b3261e}
</style></head><body>
<h1>Aketud Verify</h1>
<p>Answers only from official documents — or refuses. Keys stay on
the server.</p>
<form method="post" action="/check" enctype="multipart/form-data">
<label for="text">Question or call transcript</label>
<textarea id="text" name="text" rows="5">__TEXT__</textarea>
<label for="lang">Language</label>
<select id="lang" name="lang">__LANG_OPTIONS__</select>
<label for="sale_date">Policy sale date (optional, questions only)</label>
<input type="date" id="sale_date" name="sale_date" value="__SALE_DATE__">
<label>Mode</label>
<label style="font-weight:400"><input type="radio" name="mode"
value="answer"__ANSWER_CHECKED__> Ask a question</label>
<label style="font-weight:400"><input type="radio" name="mode"
value="call"__CALL_CHECKED__> Check a call</label>
<label for="audio">Call recording (audio file, .wav)</label>
<input type="file" id="audio" name="audio" accept="audio/*,.wav,.m4a">
<p><button type="submit">Run check</button></p>
</form>
__RESULT__
</body></html>"""


def render_page(trace=None, *, mode="answer", text="", lang="auto",
                error=None, sale_date="", result_html=None):
    """Render the single page, optionally with result cards."""
    lang_options = "".join(
        '<option value="%s"%s>%s</option>' % (
            code, " selected" if code == lang else "",
            _esc(_LANG_LABELS[code]))
        for code in _LANGS)
    result = ""
    if result_html is not None:
        result = result_html
    elif error:
        result = _card("Error", '<p class="error">%s</p>' % _esc(error))
        result = result.replace('<section class="card">',
                                '<section class="card error">')
    elif trace is not None:
        if mode == "call":
            result = render_call_cards(trace)
        else:
            result = render_answer_cards(trace)
    page = _PAGE.replace("__TEXT__", _esc(text))
    page = page.replace("__LANG_OPTIONS__", lang_options)
    page = page.replace("__SALE_DATE__", _esc(sale_date))
    page = page.replace("__ANSWER_CHECKED__",
                        " checked" if mode != "call" else "")
    page = page.replace("__CALL_CHECKED__",
                        " checked" if mode == "call" else "")
    page = page.replace("__RESULT__", result)
    return page


# --- Request parsing / handling (tested without sockets) ---------------

def parse_urlencoded(body):
    parsed = parse_qs(body.decode("utf-8", "replace"))
    return {k: v[0] for k, v in parsed.items()}, {}


def parse_multipart(body, content_type):
    """Minimal multipart/form-data parser (stdlib only)."""
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[len("boundary="):].strip().strip('"')
    fields, files = {}, {}
    if not boundary:
        return fields, files
    marker = b"--" + boundary.encode()
    for chunk in body.split(marker):
        if not chunk or chunk in (b"--", b"--\r\n", b"\r\n"):
            continue
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].rstrip(b"\r\n")
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = {}
        for line in head.decode("utf-8", "replace").split("\r\n"):
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        disposition = headers.get("content-disposition", "")
        params = {}
        for item in disposition.split(";")[1:]:
            k, _, v = item.strip().partition("=")
            params[k.strip()] = v.strip().strip('"')
        name = params.get("name")
        if not name:
            continue
        if "filename" in params:
            files[name] = (params.get("filename", ""),
                           headers.get("content-type", ""), data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


def parse_request(content_type, body):
    if "multipart/form-data" in (content_type or ""):
        return parse_multipart(body or b"", content_type or "")
    return parse_urlencoded(body or b"")


# --- Background jobs with live progress (Fix 39) ----------------------

ANSWER_STAGES = (
    ("draft", "Drafting with Muse Spark"),
    ("evidence", "Checking quotes in source PDFs"),
    ("verify", "Verifying with Muse Spark Open"),
    ("governing", "Checking governing rules"),
    ("decision", "Decision"),
)
CALL_STAGES = (
    ("transcribe", "Transcribing with Muse Voice Transcribe"),
    ("extract", "Extracting caller claims (Muse Spark)"),
    ("evidence", "Checking quotes"),
    ("verify", "Verifying with Muse Spark Open"),
    ("decision", "Decision"),
)
JOB_TTL_S = 600

JOBS = {}
_JOBS_LOCK = threading.Lock()
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _prune_jobs(now=None):
    """Drop jobs started more than :data:`JOB_TTL_S` seconds ago."""
    now = time.monotonic() if now is None else now
    with _JOBS_LOCK:
        for job_id in [k for k, j in JOBS.items()
                       if now - j["created"] > JOB_TTL_S]:
            del JOBS[job_id]


def _new_job(stages):
    job = {"id": uuid.uuid4().hex, "created": time.monotonic(),
           "finished": None, "status": "running", "code": None,
           "html": None, "transcript": None, "thread": None,
           "stages": [{"key": k, "label": label, "state": "pending",
                       "started": None, "ended": None, "detail": None}
                      for k, label in stages]}
    with _JOBS_LOCK:
        JOBS[job["id"]] = job
    return job


def _skip(stage, detail=None):
    stage["state"] = "skipped"
    if detail:
        stage["detail"] = detail


def _job_progress(job):
    """``(stage, detail)`` callback that ticks ``job``'s stages.

    Stages only move forward: an event for an earlier stage (callcheck
    alternates evidence/verify per claim) just updates nothing, and
    stages jumped over (e.g. no verifier call) are marked skipped.
    """
    def progress(key, detail=None):
        now = time.monotonic()
        with _JOBS_LOCK:
            stages = job["stages"]
            keys = [st["key"] for st in stages]
            if key not in keys:
                return
            idx = keys.index(key)
            active = next((i for i, st in enumerate(stages)
                           if st["state"] == "active"), None)
            if active is not None and idx < active:
                return
            if active == idx:
                if detail:
                    stages[idx]["detail"] = detail
                return
            for st in stages[:idx]:
                if st["state"] == "active":
                    st["state"] = "done"
                    st["ended"] = now
                elif st["state"] == "pending":
                    _skip(st)
            stages[idx].update(state="active", started=now)
            if detail:
                stages[idx]["detail"] = detail
    return progress


def _finish_job(job, status, code, result_html, transcript=None):
    now = time.monotonic()
    with _JOBS_LOCK:
        for st in job["stages"]:
            if st["state"] == "active":
                st["state"] = "done" if status == "done" else "failed"
                st["ended"] = now
            elif st["state"] == "pending":
                _skip(st)
        job.update(status=status, code=code, html=result_html,
                   transcript=transcript, finished=now)


def _run_job(job, mode, text, lang, sale_date, audio):
    """Thread body: run the check, then store the rendered cards."""
    progress = _job_progress(job)
    try:
        if audio is not None:
            trace = run_audio(audio[2], audio[0], lang=lang,
                              progress=progress)
            cards = render_call_cards(trace)
            transcript = trace.get("transcript")
        elif mode == "call":
            trace = run_call(text, lang=lang, progress=progress)
            cards = render_call_cards(trace)
            transcript = None
        else:
            trace = run_answer(text, lang=lang, sale_date=sale_date,
                               progress=progress)
            cards = render_answer_cards(trace)
            transcript = None
    except Exception as exc:  # fail visibly, never leak keys/tracebacks
        _finish_job(job, "error", 502, _error_card(
            "Check failed: %s" % exc))
        return
    _finish_job(job, "done", 200, cards, transcript)


def _error_card(message):
    card = _card("Error", '<p class="error">%s</p>' % _esc(message))
    return card.replace('<section class="card">',
                        '<section class="card error">')


def job_status(job_id):
    """JSON-safe status for ``job_id``; ``None`` if unknown/expired."""
    _prune_jobs()
    with _JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        now = job["finished"] or time.monotonic()
        stages = []
        for st in job["stages"]:
            elapsed = None
            if st["started"] is not None:
                elapsed = round((st["ended"] or now) - st["started"], 1)
            stages.append({"key": st["key"], "label": st["label"],
                           "state": st["state"], "detail": st["detail"],
                           "elapsed": elapsed})
        return {"id": job["id"], "status": job["status"],
                "code": job["code"],
                "elapsed": round(now - job["created"], 1),
                "stages": stages, "html": job["html"],
                "transcript": job["transcript"]}


_PROGRESS_HTML = """<section class="card" id="job" data-job="__JOB_ID__">
<h2 id="job-title">Checking&hellip;</h2>
<ol id="stages"></ol>
<p id="elapsed"></p>
<noscript><p>Enable JavaScript to see live progress, or open
<a href="/status/__JOB_ID__">/status/__JOB_ID__</a>.</p></noscript>
</section>
<div id="result"></div>
<script>
(function () {
  var id = "__JOB_ID__";
  var marks = {done: "✓", active: "…", pending: "○",
               skipped: "–", failed: "✗"};
  function draw(s) {
    var ol = document.getElementById("stages");
    ol.innerHTML = "";
    (s.stages || []).forEach(function (st) {
      var li = document.createElement("li");
      li.className = st.state;
      li.textContent = marks[st.state] + " " + st.label
        + (st.elapsed !== null ? " (" + st.elapsed.toFixed(1) + " s)" : "")
        + (st.detail ? " — " + st.detail : "");
      ol.appendChild(li);
    });
    document.getElementById("elapsed").textContent =
      "Elapsed: " + (s.elapsed || 0).toFixed(0) + " s";
  }
  function poll() {
    fetch("/status/" + id, {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (s) {
        draw(s);
        if (s.status === "running") { setTimeout(poll, 1000); return; }
        document.getElementById("job-title").textContent =
          s.status === "done" ? "Done" : "Check failed";
        document.getElementById("result").innerHTML = s.html || "";
        if (s.transcript) {
          document.getElementById("text").value = s.transcript;
        }
      })
      .catch(function (e) {
        document.getElementById("elapsed").textContent =
          "Lost contact with the server (" + e + "); retrying…";
        setTimeout(poll, 2000);
      });
  }
  poll();
})();
</script>"""


def progress_html(job_id):
    return _PROGRESS_HTML.replace("__JOB_ID__", _esc(job_id))


def handle_get(path):
    """Return (status, content_type, body_bytes) for a GET."""
    route = urlparse(path).path
    if route in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", \
            render_page().encode("utf-8")
    if route == "/health":
        return 200, "text/plain; charset=utf-8", b"ok"
    if route.startswith("/status/"):
        job_id = route[len("/status/"):]
        status = (job_status(job_id) if _JOB_ID_RE.match(job_id)
                  else None)
        if status is None:
            status = {"id": job_id, "status": "error", "code": 404,
                      "elapsed": 0, "stages": [], "transcript": None,
                      "html": _error_card(
                          "This check is no longer available (jobs "
                          "are kept for 10 minutes). Please run it "
                          "again.")}
            return 404, "application/json; charset=utf-8", \
                json.dumps(status).encode("utf-8")
        return 200, "application/json; charset=utf-8", \
            json.dumps(status).encode("utf-8")
    return 404, "text/plain; charset=utf-8", b"not found"


def handle_post(path, content_type, body):
    """Start a check in the background; return the progress page.

    Returns (status, content_type, body_bytes). Bad input is answered
    at once (400) without starting a job.
    """
    route = urlparse(path).path
    if route not in ("/", "/check"):
        return 404, "text/plain; charset=utf-8", b"not found"
    fields, files = parse_request(content_type, body)
    text = (fields.get("text") or "").strip()
    lang = fields.get("lang") or "auto"
    if lang not in _LANGS:
        lang = "auto"
    mode = fields.get("mode") or "answer"
    if mode not in ("answer", "call"):
        mode = "answer"
    sale_date = (fields.get("sale_date") or "").strip()
    audio = files.get("audio")
    if not (audio and audio[0] and audio[2]):
        audio = None
    if audio is None and not text:
        page = render_page(mode=mode, text=text, lang=lang,
                           sale_date=sale_date,
                           error="Please enter a question or call "
                                 "transcript, or upload a recording.")
        return 400, "text/html; charset=utf-8", page.encode("utf-8")
    if audio is not None:
        mode = "call"
    _prune_jobs()
    job = _new_job(CALL_STAGES if mode == "call" else ANSWER_STAGES)
    if mode == "call" and audio is None:
        _skip(job["stages"][0], "text transcript, no recording")
    thread = threading.Thread(
        target=_run_job, args=(job, mode, text, lang, sale_date, audio),
        daemon=True)
    job["thread"] = thread
    thread.start()
    page = render_page(mode=mode, text=text, lang=lang,
                       sale_date=sale_date,
                       result_html=progress_html(job["id"]))
    return 200, "text/html; charset=utf-8", page.encode("utf-8")


class WebHandler(BaseHTTPRequestHandler):
    """HTTP handler delegating to handle_get / handle_post."""

    def do_GET(self):  # noqa: N802 (http.server API)
        status, ctype, body = handle_get(self.path)
        self._send(status, ctype, body)

    def do_POST(self):  # noqa: N802 (http.server API)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        status, ctype, payload = handle_post(
            self.path, self.headers.get("Content-Type", ""), body)
        self._send(status, ctype, payload)

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the demo terminal clean
        pass


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="python -m verify.web")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args(argv)
    if args.host not in LOCAL_HOSTS:
        print("Refusing to bind %s: this demo serves localhost only "
              "(%s)." % (args.host, ", ".join(LOCAL_HOSTS)))
        return 2
    load_env()
    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    print("Aketud Verify demo: http://%s:%d" % (args.host, args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
