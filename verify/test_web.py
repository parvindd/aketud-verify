"""Offline tests for verify.web handlers (Fix 32).

Run: python3 -m unittest verify.test_web -v
Pipeline / callcheck / voice are mocked; no live model is called.
"""
import io
import json
import re
import threading
import unittest
from unittest import mock
from urllib.parse import urlencode

try:
    from verify import web
except ImportError:
    import web


def _post_wait(path, content_type, body):
    """POST, wait for the background job, return (code, ctype, html).

    The html is the progress page followed by the job's result cards,
    i.e. what the browser shows once polling has finished (Fix 39).
    """
    status, ctype, page = web.handle_post(path, content_type, body)
    if status != 200:
        return status, ctype, page
    job_id = re.search(rb'data-job="([0-9a-f]{32})"', page).group(1)
    job_id = job_id.decode()
    web.JOBS[job_id]["thread"].join(10)
    _, _, raw = web.handle_get("/status/" + job_id)
    state = json.loads(raw)
    return (state["code"], ctype,
            page + (state["html"] or "").encode("utf-8"))


def _answer_trace(decision="VERIFIED"):
    return {
        "question": "PED waiting period?",
        "draft": {"claims": [{
            "claim": "PED max 36 months",
            "source_file": "irdai-insurance-products-regulations-2024.pdf",
            "quote": "maximum up to 36 months"}]},
        "claims": [{
            "claim": "PED max 36 months",
            "source_file": "irdai-insurance-products-regulations-2024.pdf",
            "quote": "maximum up to 36 months",
            "evidence": {"exists": True, "found": True},
            "verifier_verdict": "SUPPORTED",
            "verifier_reason": "passage supports it",
            "verifier_model": "meta-models/Muse-Spark-Open-816B-A42B",
            "verifier_fallback": False,
        }],
        "decision": decision,
        "final_answer": "PED max 36 months (Source: irdai)",
        "verifier_model": "meta-models/Muse-Spark-Open-816B-A42B",
        "verifier_fallback": False,
    }


def _call_trace():
    return {
        "transcript": "IRDAI bonus call",
        "claims": [{
            "claim": "Caller claims IRDAI is calling about a bonus",
            "kind": "irdai_calling", "rule": 4,
            "source_file": "mc-insurance-advertisements-2019.pdf",
            "quote": "is not involved in activities like selling",
            "citation": "Master Circular 2019, para 15",
            "evidence": {"exists": True, "found": True},
            "verifier_verdict": "CONTRADICTED",
            "verifier_reason": "rule states opposite",
            "verifier_model": "meta-models/Muse-Spark-Open-816B-A42B",
            "verified_by": "meta-models/Muse-Spark-Open-816B-A42B",
            "extracted_by": "Muse Spark",
            "verdict": "CONTRADICTS RULES",
            "verdict_label": "CONTRADICTS RULES",
            "reason": "IRDAI does not announce bonuses.",
        }],
        "final_block": ("Claim 1: CONTRADICTS RULES — Caller claims IRDAI "
                        "is calling about a bonus\n  IRDAI does not "
                        "announce bonuses.\nSafety advice: Check only "
                        "with your insurer."),
        "safety_advice": "Check only with your insurer.",
        "lang": "en",
        "verifier_model": "meta-models/Muse-Spark-Open-816B-A42B",
    }


class TestGet(unittest.TestCase):
    def test_index_has_form_controls(self):
        status, ctype, body = web.handle_get("/")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn('name="text"', text)
        self.assertIn('name="lang"', text)
        self.assertIn("हिंदी", text)
        self.assertIn('value="call"', text)
        self.assertIn("Check a call", text)
        self.assertIn('name="audio"', text)
        self.assertIn('type="file"', text)
        # No key material is ever rendered.
        self.assertNotIn("META_API_KEY", text)
        self.assertNotIn("VERIFIER_API_KEY", text)

    def test_404(self):
        status, _, _ = web.handle_get("/nope")
        self.assertEqual(status, 404)


class TestPostAnswer(unittest.TestCase):
    def test_answer_cards_and_decision_colour(self):
        with mock.patch.object(web, "run_answer",
                               return_value=_answer_trace()) as run:
            status, _, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "PED?", "lang": "hi",
                           "mode": "answer"}).encode())
        self.assertEqual(status, 200)
        run.assert_called_once()
        text = body.decode("utf-8")
        for stage in ("Draft", "Evidence", "FOUND", "Verifier",
                      "Muse-Spark-Open", "Governing rule", "VERIFIED"):
            self.assertIn(stage, text)
        self.assertIn("#137333", text)  # green for VERIFIED

    def test_hindi_text_renders_utf8(self):
        trace = _answer_trace()
        trace["final_answer"] = "प्री-एग्ज़िस्टिंग डिज़ीज़ 36 महीने"
        with mock.patch.object(web, "run_answer", return_value=trace):
            status, ctype, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "सवाल?", "lang": "hi",
                           "mode": "answer"}).encode())
        self.assertEqual(status, 200)
        self.assertIn("charset=utf-8", ctype)
        self.assertIn("प्री-एग्ज़िस्टिंग", body.decode("utf-8"))

    def test_refused_is_red(self):
        with mock.patch.object(web, "run_answer",
                               return_value=_answer_trace("REFUSED")):
            _, _, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "Q?", "mode": "answer"}).encode())
        self.assertIn("#b3261e", body.decode("utf-8"))

    def test_empty_text_is_400(self):
        status, _, body = web.handle_post(
            "/check", "application/x-www-form-urlencoded",
            urlencode({"text": "", "mode": "answer"}).encode())
        self.assertEqual(status, 400)
        self.assertIn("Please enter", body.decode("utf-8"))

    def test_pipeline_error_is_502_not_traceback(self):
        with mock.patch.object(web, "run_answer",
                               side_effect=RuntimeError("boom")):
            status, _, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "Q?", "mode": "answer"}).encode())
        self.assertEqual(status, 502)
        self.assertIn("boom", body.decode("utf-8"))
        self.assertNotIn("Traceback", body.decode("utf-8"))


class TestPostCall(unittest.TestCase):
    def test_call_mode_uses_run_call(self):
        with mock.patch.object(web, "run_call",
                               return_value=_call_trace()) as run:
            status, _, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "IRDAI bonus call", "lang": "en",
                           "mode": "call"}).encode())
        self.assertEqual(status, 200)
        run.assert_called_once()
        text = body.decode("utf-8")
        self.assertIn("CONTRADICTS RULES", text)
        self.assertIn("Governing rule", text)
        self.assertIn("Muse-Spark-Open", text)

    def test_audio_upload_transcribes_then_checks(self):
        boundary = "----testboundary"
        body = (
            ("--%s\r\n" % boundary).encode()
            + b'Content-Disposition: form-data; name="lang"\r\n\r\n'
            + b"en\r\n"
            + ("--%s\r\n" % boundary).encode()
            + b'Content-Disposition: form-data; name="audio"; '
              b'filename="call.wav"\r\n'
              b"Content-Type: audio/wav\r\n\r\n"
            + b"RIFFfakeaudio"
            + ("\r\n--%s--\r\n" % boundary).encode())
        with mock.patch.object(web, "run_audio",
                               return_value=_call_trace()) as run:
            status, _, resp = _post_wait(
                "/check",
                "multipart/form-data; boundary=%s" % boundary, body)
        self.assertEqual(status, 200)
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0], b"RIFFfakeaudio")
        self.assertEqual(args[1], "call.wav")
        self.assertIn("CONTRADICTS RULES", resp.decode("utf-8"))

    def test_multipart_text_fields(self):
        boundary = "----b2"
        body = (
            ("--%s\r\n" % boundary).encode()
            + b'Content-Disposition: form-data; name="text"\r\n\r\n'
            + "हिंदी सवाल".encode("utf-8") + b"\r\n"
            + ("--%s\r\n" % boundary).encode()
            + b'Content-Disposition: form-data; name="mode"\r\n\r\n'
            + b"answer\r\n"
            + ("--%s--\r\n" % boundary).encode())
        with mock.patch.object(web, "run_answer",
                               return_value=_answer_trace()) as run:
            status, _, _ = _post_wait(
                "/check",
                "multipart/form-data; boundary=%s" % boundary, body)
        self.assertEqual(status, 200)
        run.assert_called_once_with("हिंदी सवाल", lang="auto",
                                    sale_date="", progress=mock.ANY)


class TestRunAudio(unittest.TestCase):
    def test_run_audio_transcribes_then_checks(self):
        with mock.patch.object(web, "transcribe",
                               return_value="IRDAI bonus call") as tr, \
                mock.patch.object(
                    web, "run_call",
                    return_value={"claims": [], "final_block": ""}) as rc:
            trace = web.run_audio(b"RIFF", "call.wav", lang="en")
        tr.assert_called_once()
        rc.assert_called_once_with("IRDAI bonus call", lang="en")
        self.assertEqual(trace["transcript"], "IRDAI bonus call")


def _stage(text, n):
    """HTML of the Stage ``n`` card."""
    return text.split("Stage %d" % n)[1].split("</section>")[0]


def _post_call(trace):
    with mock.patch.object(web, "run_call", return_value=trace):
        _, _, body = _post_wait(
            "/check", "application/x-www-form-urlencoded",
            urlencode({"text": "call", "mode": "call"}).encode())
    return body.decode("utf-8")


class TestFix35TidyResult(unittest.TestCase):
    def test_call_stage3_one_verified_by_line_per_claim(self):
        s3 = _stage(_post_call(_call_trace()), 3)
        self.assertNotIn("Verifier (model)", s3)
        self.assertEqual(s3.count("verified by:"), 1)
        self.assertIn(
            "verified by: meta-models/Muse-Spark-Open-816B-A42B", s3)

    def test_call_stage3_rule_only_claim(self):
        trace = _call_trace()
        claim = trace["claims"][0]
        for key in ("verifier_model", "verifier_verdict",
                    "verifier_reason"):
            claim.pop(key)
        claim["verified_by"] = "rule only (no model)"
        trace.pop("verifier_model")
        s3 = _stage(_post_call(trace), 3)
        self.assertEqual(s3.count("verified by:"), 1)
        self.assertIn("verified by: rule only (no model)", s3)

    def test_answer_stage3_one_verified_by_line(self):
        with mock.patch.object(web, "run_answer",
                               return_value=_answer_trace()):
            _, _, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "Q?", "mode": "answer"}).encode())
        s3 = _stage(body.decode("utf-8"), 3)
        self.assertNotIn("Verifier (model)", s3)
        self.assertEqual(s3.count("verified by:"), 1)
        self.assertIn(
            "verified by: meta-models/Muse-Spark-Open-816B-A42B", s3)

    def test_call_stage5_each_verdict_once_with_reason(self):
        trace = _call_trace()
        second = dict(trace["claims"][0],
                      claim="Caller says pay today",
                      verdict="CANNOT BE CONFIRMED (ask insurer)",
                      verdict_label="CANNOT BE CONFIRMED (ask insurer)",
                      reason="Only the insurer can confirm the fee.")
        trace["claims"].append(second)
        s5 = _stage(_post_call(trace), 5)
        self.assertNotIn('class="decision"', s5)
        self.assertNotIn("<pre>", s5)
        self.assertEqual(s5.count("CONTRADICTS RULES"), 1)
        self.assertEqual(s5.count("CANNOT BE CONFIRMED"), 1)
        self.assertEqual(s5.count("IRDAI does not announce bonuses."), 1)
        self.assertEqual(
            s5.count("Only the insurer can confirm the fee."), 1)

    def test_safety_advice_shown_once(self):
        text = _post_call(_call_trace())
        self.assertEqual(text.count("Check only with your insurer."), 1)
        self.assertIn("Safety advice", _stage(text, 5))

    def test_hindi_safety_label(self):
        trace = _call_trace()
        trace["lang"] = "hi"
        self.assertIn("सुरक्षा सलाह", _stage(_post_call(trace), 5))

    def test_no_claims_shows_single_cannot_confirm(self):
        trace = {"claims": [], "safety_advice": "Ask your insurer.",
                 "lang": "en"}
        s5 = _stage(_post_call(trace), 5)
        self.assertEqual(s5.count("CANNOT BE CONFIRMED"), 1)
        self.assertEqual(s5.count("Ask your insurer."), 1)


class TestFix36SaleDate(unittest.TestCase):
    def test_index_has_sale_date_field(self):
        _, _, body = web.handle_get("/")
        text = body.decode("utf-8")
        self.assertIn('type="date"', text)
        self.assertIn('name="sale_date"', text)

    def test_sale_date_passed_and_shown(self):
        trace = _answer_trace("APPLIES_TO_OLDER_CONTRACT")
        trace["sale_date"] = {"earliest": "2021-06-15",
                              "latest": "2021-06-15",
                              "source": "explicit", "precision": "day",
                              "text": "2021-06-15"}
        trace["savings"] = [{
            "citation": "IRDAI (Insurance Products) Regulations, 2024, "
                        "Regulation 9(3)",
            "evidence": {"exists": True, "found": True}}]
        with mock.patch.object(web, "run_answer",
                               return_value=trace) as run:
            status, _, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "PED?", "mode": "answer",
                           "sale_date": "2021-06-15"}).encode())
        self.assertEqual(status, 200)
        run.assert_called_once_with("PED?", lang="auto",
                                    sale_date="2021-06-15",
                                    progress=mock.ANY)
        text = body.decode("utf-8")
        s5 = text.split("Stage 5")[1]
        self.assertIn("APPLIES_TO_OLDER_CONTRACT", s5)
        self.assertIn("#9334e6", s5)
        self.assertIn("Sale date: 2021-06-15", s5)
        self.assertIn("Regulation 9(3) &mdash; evidence FOUND", s5)
        self.assertIn('value="2021-06-15"', text)  # field keeps value

    def test_depends_on_sale_date_colour(self):
        with mock.patch.object(
                web, "run_answer",
                return_value=_answer_trace("DEPENDS_ON_SALE_DATE")):
            _, _, body = _post_wait(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "PED?", "mode": "answer"}).encode())
        s5 = body.decode("utf-8").split("Stage 5")[1]
        self.assertIn("DEPENDS_ON_SALE_DATE", s5)
        self.assertIn("#b06000", s5)

    def test_run_answer_forwards_sale_date(self):
        with mock.patch.object(web, "answer", return_value={}) as ans:
            web.run_answer("Q?", lang="en", sale_date="2021-01-01")
            web.run_answer("Q?", lang="auto", sale_date="")
        self.assertEqual(ans.call_args_list[0].kwargs,
                         {"lang": "en", "sale_date": "2021-01-01"})
        self.assertEqual(ans.call_args_list[1].kwargs,
                         {"lang": None, "sale_date": None})


class TestFix39LiveProgress(unittest.TestCase):
    def _status(self, job_id):
        code, ctype, raw = web.handle_get("/status/" + job_id)
        self.assertIn("application/json", ctype)
        return code, json.loads(raw)

    def _start(self, fields):
        status, _, page = web.handle_post(
            "/check", "application/x-www-form-urlencoded",
            urlencode(fields).encode())
        self.assertEqual(status, 200)
        text = page.decode("utf-8")
        job_id = re.search(r'data-job="([0-9a-f]{32})"', text).group(1)
        return job_id, text

    def test_post_returns_at_once_and_stages_follow_real_events(self):
        gate = {k: threading.Event() for k in ("evidence", "verify",
                                               "finish")}
        reached = {k: threading.Event() for k in ("draft", "evidence",
                                                  "verify")}

        def slow_answer(text, lang=None, sale_date=None, progress=None):
            progress("draft", None)
            reached["draft"].set()
            gate["evidence"].wait(5)
            progress("evidence", "1 claim(s)")
            reached["evidence"].set()
            gate["verify"].wait(5)
            progress("verify", "1 verifier call(s)")
            reached["verify"].set()
            gate["finish"].wait(5)
            return _answer_trace()

        with mock.patch.object(web, "run_answer", slow_answer):
            job_id, page = self._start({"text": "PED?", "mode": "answer"})
            # The page comes back before the check finishes.
            self.assertIn("/status/", page)
            self.assertIn("setTimeout(poll, 1000)", page)
            self.assertIn("Checking", page)
            self.assertTrue(reached["draft"].wait(5))
            _, st = self._status(job_id)
            self.assertEqual(st["status"], "running")
            self.assertEqual([x["state"] for x in st["stages"]],
                             ["active", "pending", "pending", "pending",
                              "pending"])
            self.assertEqual(st["stages"][0]["label"],
                             "Drafting with Muse Spark")
            gate["evidence"].set()
            self.assertTrue(reached["evidence"].wait(5))
            _, st = self._status(job_id)
            self.assertEqual([x["state"] for x in st["stages"][:3]],
                             ["done", "active", "pending"])
            self.assertEqual(st["stages"][1]["detail"], "1 claim(s)")
            self.assertIsNotNone(st["stages"][0]["elapsed"])
            gate["verify"].set()
            self.assertTrue(reached["verify"].wait(5))
            _, st = self._status(job_id)
            self.assertEqual(st["stages"][2]["state"], "active")
            self.assertIsNone(st["html"])
            gate["finish"].set()
            web.JOBS[job_id]["thread"].join(5)
        code, st = self._status(job_id)
        self.assertEqual(code, 200)
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["code"], 200)
        # Stages never reached (governing, decision) are not faked.
        self.assertEqual([x["state"] for x in st["stages"]],
                         ["done", "done", "done", "skipped", "skipped"])
        self.assertIn("Stage 5 — Final decision", st["html"])
        self.assertIn("VERIFIED", st["html"])

    def test_error_shows_message_not_blank(self):
        def boom(*a, **k):
            raise RuntimeError("model endpoint down")
        with mock.patch.object(web, "run_answer", boom):
            job_id, _ = self._start({"text": "Q?", "mode": "answer"})
            web.JOBS[job_id]["thread"].join(5)
        _, st = self._status(job_id)
        self.assertEqual(st["status"], "error")
        self.assertEqual(st["code"], 502)
        self.assertIn("model endpoint down", st["html"])
        self.assertNotIn("Traceback", st["html"])

    def test_call_text_skips_transcription_and_ticks_callcheck(self):
        def fake_call(text, lang=None, progress=None):
            for key in ("extract", "evidence", "verify", "evidence",
                        "verify", "decision"):
                progress(key, None)
            return _call_trace()
        with mock.patch.object(web, "run_call", fake_call):
            job_id, _ = self._start({"text": "IRDAI call",
                                     "mode": "call"})
            web.JOBS[job_id]["thread"].join(5)
        _, st = self._status(job_id)
        self.assertEqual(
            [x["label"] for x in st["stages"]],
            ["Transcribing with Muse Voice Transcribe",
             "Extracting caller claims (Muse Spark)", "Checking quotes",
             "Verifying with Muse Spark Open", "Decision"])
        self.assertEqual([x["state"] for x in st["stages"]],
                         ["skipped", "done", "done", "done", "done"])
        self.assertEqual(st["stages"][0]["detail"],
                         "text transcript, no recording")
        self.assertIn("CONTRADICTS RULES", st["html"])

    def test_audio_job_reports_transcription_and_transcript(self):
        def fake_transcribe(path):
            return "IRDAI bonus call"

        def fake_call(text, lang=None, progress=None):
            progress("extract", None)
            return _call_trace()
        with mock.patch.object(web, "transcribe", fake_transcribe), \
                mock.patch.object(web, "run_call", fake_call):
            job = web._new_job(web.CALL_STAGES)
            web._run_job(job, "call", "", "en", "",
                         ("call.wav", "audio/wav", b"RIFF"))
        st = web.job_status(job["id"])
        self.assertEqual(st["stages"][0]["state"], "done")
        self.assertEqual(st["transcript"], "IRDAI bonus call")

    def test_unknown_or_bad_id_is_404_json_with_message(self):
        for job_id in ("0" * 32, "../etc", "nope"):
            code, st = self._status(job_id)
            self.assertEqual(code, 404)
            self.assertEqual(st["status"], "error")
            self.assertIn("no longer available", st["html"])

    def test_jobs_dropped_after_ten_minutes(self):
        job = web._new_job(web.ANSWER_STAGES)
        web._prune_jobs(now=job["created"] + 599)
        self.assertIn(job["id"], web.JOBS)
        web._prune_jobs(now=job["created"] + 601)
        self.assertNotIn(job["id"], web.JOBS)

    def test_empty_input_answered_at_once_without_job(self):
        before = len(web.JOBS)
        status, _, _ = web.handle_post(
            "/check", "application/x-www-form-urlencoded",
            urlencode({"text": "", "mode": "answer"}).encode())
        self.assertEqual(status, 400)
        self.assertEqual(len(web.JOBS), before)

    def test_progress_ignores_backwards_and_unknown_events(self):
        job = web._new_job(web.ANSWER_STAGES)
        progress = web._job_progress(job)
        progress("verify", None)
        progress("draft", None)       # backwards: ignored
        progress("nonsense", None)    # unknown: ignored
        states = [x["state"] for x in job["stages"]]
        self.assertEqual(states, ["skipped", "skipped", "active",
                                  "pending", "pending"])

    def test_server_binds_localhost_only(self):
        with mock.patch.object(web, "ThreadingHTTPServer") as srv, \
                mock.patch.object(web, "load_env", lambda: {}), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(web.main(["--host", "0.0.0.0"]), 2)
            srv.assert_not_called()


class TestGoverningCardRendering(unittest.TestCase):
    """Regression: the Stage 4 governing card had one format argument
    too many, so every trace with a governing rule raised TypeError
    and the page showed "Check failed" instead of the result."""

    PED_QUOTE = (
        "Waiting period for pre-existing diseases disclosed by the "
        "persons to be insured, shall be maximum up to 36 months of "
        "continuous coverage under the Health Insurance policy.")
    AROGYA_48_QUOTE = (
        "Expenses related to the treatment of a pre-existing Disease "
        "(PED) and its direct complications shall be excluded until the "
        "expiry of 48 months of continuous coverage after the date of "
        "inception of the first policy with us.")

    def _trace(self, sale_date):
        try:
            from verify.pipeline import answer
        except ImportError:
            from pipeline import answer
        draft = {"claims": [{"claim": "PED waiting period is 48 months",
                             "source_file": "arogya-sanjeevani-specimen.pdf",
                             "quote": self.AROGYA_48_QUOTE}]}

        def backend(claim, quote, source_text):
            if quote == self.PED_QUOTE:
                return json.dumps({"verdict": "CONTRADICTED",
                                   "reason": "caps PED at 36 months"})
            return json.dumps({"verdict": "SUPPORTED",
                               "reason": "Arogya says 48."})
        return answer("What is the PED waiting period?", lang="en",
                      proposer=lambda q, lang: draft, verifier=backend,
                      sale_date=sale_date)

    def test_governing_traces_render_without_error(self):
        for sale_date, decision in (
                (None, "DEPENDS_ON_SALE_DATE"),
                ("2021-06-15", "APPLIES_TO_OLDER_CONTRACT"),
                ("2025-01-10", "SUPERSEDED")):
            trace = self._trace(sale_date)
            self.assertEqual(trace["decision"], decision)
            page = web.render_page(trace)  # must not raise
            s4 = page.split("Stage 4")[1].split("</section>")[0]
            self.assertIn("in force from 1 April 2024", s4, decision)
            self.assertIn("Governing evidence: FOUND", s4, decision)
            self.assertIn("Governing verdict: CONTRADICTED", s4, decision)
            self.assertIn(self.PED_QUOTE, s4, decision)
            self.assertIn(decision, page.split("Stage 5")[1])

    def test_effective_date_used_when_display_missing(self):
        trace = _answer_trace("SUPERSEDED")
        trace["claims"][0].update(
            governing_source="irdai-insurance-products-regulations-2024.pdf",
            governing_title="IRDAI (Insurance Products) Regulations, 2024",
            governing_effective_date="2024-04-01",
            governing_verdict="CONTRADICTED",
            governing_evidence={"exists": True, "found": True})
        s4 = web.render_answer_cards(trace).split("Stage 4")[1]
        self.assertIn("(IRDAI (Insurance Products) Regulations, 2024, "
                      "2024-04-01)", s4)


if __name__ == "__main__":
    unittest.main()
