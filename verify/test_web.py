"""Offline tests for verify.web handlers (Fix 32).

Run: python3 -m unittest verify.test_web -v
Pipeline / callcheck / voice are mocked; no live model is called.
"""
import unittest
from unittest import mock
from urllib.parse import urlencode

try:
    from verify import web
except ImportError:
    import web


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
            status, _, body = web.handle_post(
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
            status, ctype, body = web.handle_post(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "सवाल?", "lang": "hi",
                           "mode": "answer"}).encode())
        self.assertEqual(status, 200)
        self.assertIn("charset=utf-8", ctype)
        self.assertIn("प्री-एग्ज़िस्टिंग", body.decode("utf-8"))

    def test_refused_is_red(self):
        with mock.patch.object(web, "run_answer",
                               return_value=_answer_trace("REFUSED")):
            _, _, body = web.handle_post(
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
            status, _, body = web.handle_post(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "Q?", "mode": "answer"}).encode())
        self.assertEqual(status, 502)
        self.assertIn("boom", body.decode("utf-8"))
        self.assertNotIn("Traceback", body.decode("utf-8"))


class TestPostCall(unittest.TestCase):
    def test_call_mode_uses_run_call(self):
        with mock.patch.object(web, "run_call",
                               return_value=_call_trace()) as run:
            status, _, body = web.handle_post(
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
            status, _, resp = web.handle_post(
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
            status, _, _ = web.handle_post(
                "/check",
                "multipart/form-data; boundary=%s" % boundary, body)
        self.assertEqual(status, 200)
        run.assert_called_once_with("हिंदी सवाल", lang="auto",
                                    sale_date="")


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
        _, _, body = web.handle_post(
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
            _, _, body = web.handle_post(
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
            status, _, body = web.handle_post(
                "/check", "application/x-www-form-urlencoded",
                urlencode({"text": "PED?", "mode": "answer",
                           "sale_date": "2021-06-15"}).encode())
        self.assertEqual(status, 200)
        run.assert_called_once_with("PED?", lang="auto",
                                    sale_date="2021-06-15")
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
            _, _, body = web.handle_post(
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


if __name__ == "__main__":
    unittest.main()
