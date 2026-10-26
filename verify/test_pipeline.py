"""Offline tests for the fail-closed pipeline (hackathon Step 4).

Run: cd verify && python3 -m unittest test_pipeline -v
(or from repo root: python3 -m unittest verify.test_pipeline -v)

Every model call is mocked: the proposer and verifier are fakes
injected into ``pipeline.answer``. No paid API is ever called. The
deterministic evidence check runs against the real PDFs in
``health-corpus/raw/`` (fetched from SOURCES.csv; git-ignored), the
same fixtures the baseline tests require.
"""
import hashlib
import json
import unittest

try:
    from verify.evidence import check_evidence, extract_text
    from verify.pipeline import CORRECTED, REFUSED, VERIFIED, answer
    from verify.verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                                 SUPPORTED, Verifier, verify_claim)
except ImportError:  # cd verify && python3 -m unittest test_pipeline
    from evidence import check_evidence, extract_text
    from pipeline import CORRECTED, REFUSED, VERIFIED, answer
    from verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                          SUPPORTED, Verifier, verify_claim)

PRODUCTS = "irdai-insurance-products-regulations-2024.pdf"
AROGYA = "arogya-sanjeevani-hdfc-ergo.pdf"

PED_QUOTE = (
    "Waiting period for pre-existing diseases disclosed by the persons "
    "to be insured, shall be maximum up to 36 months of continuous "
    "coverage under the Health Insurance policy."
)
AROGYA_48_QUOTE = (
    "Expenses related to the treatment of a pre-existing Disease (PED) "
    "and its direct complications shall be excluded until the expiry of "
    "48 months of continuous coverage after the date of inception of "
    "the first policy with us."
)

SUPERSEDING_REASON = (
    "The Arogya Sanjeevani specimen states 48 months, but the IRDAI "
    "(Insurance Products) Regulations, 2024, Schedule III, Regulation 7 "
    "caps the PED waiting period at a maximum of 36 months; the 2024 "
    "Products Regulations supersede the specimen figure."
)


def fake_proposer(draft):
    return lambda question, lang: draft


def fake_backend(payload):
    if isinstance(payload, str):
        return lambda claim, quote, source_text: payload
    return lambda claim, quote, source_text: json.dumps(payload)


class TestEvidence(unittest.TestCase):
    def test_real_quote_found_with_stable_hash(self):
        r1 = check_evidence(PRODUCTS, PED_QUOTE)
        r2 = check_evidence(PRODUCTS, PED_QUOTE)
        self.assertTrue(r1["exists"])
        self.assertTrue(r1["found"])
        text = extract_text(PRODUCTS)
        self.assertEqual(
            r1["page_text_hash"],
            hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(r1, r2)

    def test_absent_quote_and_missing_file_fail_closed(self):
        self.assertFalse(
            check_evidence(PRODUCTS, "no such passage exists")["found"])
        r = check_evidence("does-not-exist.pdf", PED_QUOTE)
        self.assertEqual(
            r, {"exists": False, "found": False, "page_text_hash": None})
        self.assertFalse(check_evidence(PRODUCTS, "")["found"])


class TestVerifierParsing(unittest.TestCase):
    def test_valid_verdicts_pass_through(self):
        for verdict in (SUPPORTED, CONTRADICTED, INSUFFICIENT_EVIDENCE):
            r = verify_claim("c", "q", "src", backend=fake_backend(
                {"verdict": verdict, "reason": "because"}))
            self.assertEqual(r, {"verdict": verdict, "reason": "because"})

    def test_malformed_outputs_fail_closed(self):
        for bad in ("not json", "", '{"verdict": "MAYBE"}',
                    '{"reason": "no verdict"}', '["SUPPORTED"]', None, 42):
            backend = (lambda b: lambda c, q, s: b)(bad)
            r = verify_claim("c", "q", "src", backend=backend)
            self.assertEqual(r["verdict"], INSUFFICIENT_EVIDENCE, repr(bad))

    def test_backend_exception_and_missing_backend_fail_closed(self):
        def boom(claim, quote, source_text):
            raise RuntimeError("backend down")

        self.assertEqual(
            Verifier(boom).verify("c", "q", "src")["verdict"],
            INSUFFICIENT_EVIDENCE)
        self.assertEqual(
            verify_claim("c", "q", "src")["verdict"],
            INSUFFICIENT_EVIDENCE)


class TestPipelineScenarios(unittest.TestCase):
    def test_a_supported_ped_cap_is_verified(self):
        draft = {"claims": [{
            "claim": "The PED waiting period is maximum up to 36 months "
                     "of continuous coverage.",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        trace = answer(
            "What is the maximum PED waiting period?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED,
                 "reason": "The quote states the 36-month cap directly."}))
        self.assertEqual(trace["decision"], VERIFIED)
        self.assertEqual(trace["question"],
                         "What is the maximum PED waiting period?")
        self.assertEqual(trace["draft"], draft)
        self.assertEqual(len(trace["claims"]), 1)
        claim = trace["claims"][0]
        self.assertTrue(claim["evidence"]["exists"])
        self.assertTrue(claim["evidence"]["found"])
        self.assertTrue(claim["evidence"]["page_text_hash"])
        self.assertEqual(claim["verdict"], SUPPORTED)
        self.assertIn("36 months", trace["final_answer"])

    def test_b_unsupported_claim_is_refused(self):
        draft = {"claims": [{
            "claim": "Maternity cover has a 9-month waiting period.",
            "source_file": PRODUCTS,
            "quote": "Maternity benefits shall be payable after nine "
                     "months of continuous coverage."}]}
        trace = answer(
            "What is the maternity waiting period?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "should not matter"}))
        self.assertEqual(trace["decision"], REFUSED)
        self.assertIsNone(trace["final_answer"])
        self.assertFalse(trace["claims"][0]["evidence"]["found"])
        self.assertIsNone(trace["claims"][0]["verdict"])

    def test_c_contradicted_ped_48_is_corrected(self):
        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": CONTRADICTED, "reason": SUPERSEDING_REASON}))
        self.assertEqual(trace["decision"], CORRECTED)
        self.assertEqual(trace["claims"][0]["verdict"], CONTRADICTED)
        self.assertTrue(trace["claims"][0]["evidence"]["found"])
        blob = json.dumps(trace)
        # Trace names the superseding regulation and the true cap.
        self.assertIn("Insurance Products) Regulations, 2024", blob)
        self.assertIn("36 months", blob)
        self.assertIn("supersede", blob)
        self.assertIn("48 months", trace["correction"])

    def test_d_misleading_quote_is_not_verified(self):
        # Quote exists verbatim, but it does not support the claim:
        # the 36-month norm expressly does not apply to Overseas
        # Travel Policies, so it cannot support this claim.
        draft = {"claims": [{
            "claim": "The 36-month PED cap applies to Overseas Travel "
                     "Policies.",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        trace = answer(
            "Does the PED cap apply to overseas travel policies?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": INSUFFICIENT_EVIDENCE,
                 "reason": "The quote states the cap but not its "
                           "application to Overseas Travel Policies."}))
        self.assertNotEqual(trace["decision"], VERIFIED)
        self.assertEqual(trace["decision"], REFUSED)
        self.assertTrue(trace["claims"][0]["evidence"]["found"])
        self.assertEqual(
            trace["claims"][0]["verdict"], INSUFFICIENT_EVIDENCE)
        self.assertIsNone(trace["final_answer"])

    def test_e_fabricated_quote_refused_despite_supported_verdict(self):
        calls = []

        def backend(claim, quote, source_text):
            calls.append(claim)
            return json.dumps(
                {"verdict": SUPPORTED, "reason": "Looks fine."})

        draft = {"claims": [{
            "claim": "The PED waiting period is 12 months.",
            "source_file": PRODUCTS,
            "quote": "The waiting period for pre-existing diseases "
                     "shall be twelve months exactly."}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft), verifier=backend)
        self.assertEqual(trace["decision"], REFUSED)
        self.assertIsNone(trace["final_answer"])
        self.assertFalse(trace["claims"][0]["evidence"]["found"])
        # Evidence gate runs first; verifier never consulted/overrides.
        self.assertEqual(calls, [])
        self.assertIsNone(trace["claims"][0]["verdict"])

    def test_f_malformed_verifier_output_is_refused(self):
        draft = {"claims": [{
            "claim": "The PED waiting period is maximum up to 36 months "
                     "of continuous coverage.",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        for bad in ("not json at all", '{"verdict": "PROBABLY"}', ""):
            trace = answer(
                "What is the maximum PED waiting period?",
                proposer=fake_proposer(draft), verifier=fake_backend(bad))
            self.assertEqual(trace["decision"], REFUSED, repr(bad))
            self.assertIsNone(trace["final_answer"])
            self.assertEqual(
                trace["claims"][0]["verdict"], INSUFFICIENT_EVIDENCE)

    def test_empty_draft_and_proposer_failure_are_refused(self):
        self.assertEqual(
            answer("Anything?", proposer=fake_proposer({"claims": []}),
                   verifier=fake_backend(
                       {"verdict": SUPPORTED, "reason": "x"}))["decision"],
            REFUSED)
        self.assertEqual(
            answer("Anything?", proposer=fake_proposer("not json"),
                   verifier=fake_backend(
                       {"verdict": SUPPORTED, "reason": "x"}))["decision"],
            REFUSED)

        def boom(question, lang):
            raise RuntimeError("proposer down")

        trace = answer("Anything?", proposer=boom,
                       verifier=fake_backend(
                           {"verdict": SUPPORTED, "reason": "x"}))
        self.assertEqual(trace["decision"], REFUSED)
        self.assertIsNone(trace["final_answer"])


if __name__ == "__main__":
    unittest.main()
