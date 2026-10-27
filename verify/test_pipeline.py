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
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    from verify.evidence import check_evidence, extract_text
    from verify.pipeline import (CORRECTED, REFUSED, SUPERSEDED, VERIFIED,
                                 REFUSAL_EVIDENCE_NOT_FOUND,
                                 REFUSAL_GOVERNING_INSUFFICIENT,
                                 REFUSAL_NO_API_KEY, REFUSAL_NO_CLAIMS,
                                 REFUSAL_PREFIX, REFUSAL_PROPOSER_ERROR,
                                 REFUSAL_VERIFIER_INSUFFICIENT, answer,
                                 make_model_proposer, retrieve)
    from verify.verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                                 SUPPORTED, Verifier, make_model_backend,
                                 verify_claim)
    from verify.verifier import _PROMPT, _context_window
except ImportError:  # cd verify && python3 -m unittest test_pipeline
    from evidence import check_evidence, extract_text
    from pipeline import (CORRECTED, REFUSED, SUPERSEDED, VERIFIED,
                          REFUSAL_EVIDENCE_NOT_FOUND,
                          REFUSAL_GOVERNING_INSUFFICIENT, REFUSAL_NO_API_KEY,
                          REFUSAL_NO_CLAIMS, REFUSAL_PREFIX,
                          REFUSAL_PROPOSER_ERROR,
                          REFUSAL_VERIFIER_INSUFFICIENT, answer,
                          make_model_proposer, retrieve)
    from verifier import (CONTRADICTED, INSUFFICIENT_EVIDENCE,
                          SUPPORTED, Verifier, make_model_backend,
                          verify_claim)
    from verifier import _PROMPT, _context_window

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

AROGYA_30_QUOTE = (
    "Expenses related to the treatment of any illness within 30 days "
    "from the first policy commencement date shall be excluded except "
    "claims arising due to an accident, provided the same are covered."
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


class _FakeResponse:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _stub_requests(captured, content='{"verdict": "SUPPORTED", '
                                      '"reason": "ok"}'):
    fake = types.ModuleType("requests")

    def post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(content)

    fake.post = post
    return fake


class TestPromptFormatting(unittest.TestCase):
    def test_prompt_format_does_not_raise(self):
        prompt = _PROMPT.format(
            claim="The PED cap is 36 months.",
            quote=PED_QUOTE, source_text="some source text")
        self.assertIn("The PED cap is 36 months.", prompt)
        self.assertIn(PED_QUOTE, prompt)
        self.assertIn("some source text", prompt)
        # Literal JSON instruction survives formatting.
        self.assertIn('{"verdict":', prompt)
        self.assertIn('"INSUFFICIENT_EVIDENCE"', prompt)

    def test_real_backend_builds_prompt_with_stubbed_post(self):
        captured = {}
        env = {"META_API_KEY": "test-key", "VERIFIER_MODEL": "model-x",
               "META_API_BASE_URL": "https://example.invalid"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            backend = make_model_backend()
            raw = backend("The PED cap is 36 months.", PED_QUOTE,
                          "full source text")
        self.assertEqual(
            json.loads(raw), {"verdict": SUPPORTED, "reason": "ok"})
        prompt = captured["json"]["messages"][0]["content"]
        self.assertIn("The PED cap is 36 months.", prompt)
        self.assertIn(PED_QUOTE, prompt)
        self.assertIn("full source text", prompt)
        self.assertIn('{"verdict":', prompt)
        self.assertEqual(captured["json"]["model"], "model-x")


class TestAuthority(unittest.TestCase):
    def test_registry_first_entry_is_ped_governing_rule(self):
        try:
            from verify.authority import REGISTRY, governing_for
        except ImportError:
            from authority import REGISTRY, governing_for
        self.assertTrue(REGISTRY)
        first = REGISTRY[0]
        for key in ("topic", "source_file", "quote", "issuer",
                    "effective_date", "supersedes"):
            self.assertIn(key, first)
        self.assertEqual(first["source_file"], PRODUCTS)
        self.assertEqual(first["quote"], PED_QUOTE)
        self.assertEqual(first["value"], "36 months")
        self.assertEqual(first["extracted_value"], "36 months")
        self.assertIn(AROGYA, first["supersedes"])
        self.assertIn("PED", first["topic"])
        self.assertTrue(first["issuer"])
        self.assertTrue(first["effective_date"])
        rules = governing_for(AROGYA, text="PED waiting period")
        self.assertEqual([r["source_file"] for r in rules], [PRODUCTS])
        self.assertEqual(governing_for(PRODUCTS), [])

    def test_ped_rule_dates_and_displayed_date(self):
        try:
            from verify.authority import REGISTRY, effective_display
        except ImportError:
            from authority import REGISTRY, effective_display
        first = REGISTRY[0]
        self.assertEqual(first["effective_date"], "2024-04-01")
        self.assertEqual(first["published"], "2024-03-22")
        self.assertEqual(first["signed"], "2024-03-20")
        self.assertIn("206", first["gazette"])
        # Displayed date is the in-force (effective) date,
        # not the published or signed date.
        self.assertEqual(
            effective_display(first), "in force from 1 April 2024")
        self.assertEqual(
            effective_display(first["effective_date"]),
            "in force from 1 April 2024")


class TestLifeAuthority(unittest.TestCase):
    def test_rules_1_to_4_present_with_exact_quotes(self):
        try:
            from verify.authority import REGISTRY
        except ImportError:
            from authority import REGISTRY
        by_rule = {}
        for entry in REGISTRY:
            by_rule.setdefault(entry.get("rule"), []).append(entry)
        for rule in (1, 2, 3, 4):
            self.assertIn(rule, by_rule)
        rule3 = by_rule[3][0]
        self.assertEqual(rule3["scope"], "linked products only")
        self.assertEqual(
            rule3["source_file"], "mc-life-insurance-products-2024.pdf")
        self.assertIn("without charging any interest or fee",
                      rule3["quote"])
        rule4 = by_rule[4][0]
        # Only the clean span is quoted for rule 4.
        self.assertEqual(
            rule4["quote"],
            "is not involved in activities like selling insurance "
            "policies, announcing bonus or investment of premiums. "
            "Public receiving such phone calls are requested to "
            "lodge a police complaint.")
        self.assertIn("2019", rule4["citation"])

    def test_life_evidence_and_retrieval(self):
        try:
            from verify.authority import REGISTRY
        except ImportError:
            from authority import REGISTRY
        for entry in REGISTRY:
            if entry.get("rule") is None:
                continue
            result = check_evidence(entry["source_file"],
                                    entry["quote"])
            self.assertTrue(result["exists"], entry["topic"])
            self.assertTrue(result["found"], entry["topic"])
        passages = retrieve("How long to revive a ULIP policy?")
        self.assertTrue(any(
            p["source_file"] == "mc-life-insurance-products-2024.pdf"
            for p in passages))
        passages = retrieve("IRDAI calling about bonus")
        self.assertTrue(any(
            p["source_file"] == "mc-insurance-advertisements-2019.pdf"
            for p in passages))


class TestGroundedProposer(unittest.TestCase):
    def test_retrieve_returns_source_passages(self):
        passages = retrieve("What is the PED waiting period?")
        self.assertTrue(passages)
        for passage in passages:
            self.assertIn("source_file", passage)
            self.assertIn("quote", passage)
            self.assertTrue(passage["quote"].strip())
        quotes = [p["quote"] for p in passages]
        self.assertTrue(any("36 months" in q for q in quotes))
        # Authority passage is among the candidates.
        self.assertTrue(any(
            p["source_file"] == PRODUCTS and PED_QUOTE in p["quote"]
            for p in passages))

    def test_retrieve_matches_other_ask_topics(self):
        passages = retrieve(
            "After how many months can a claim not be contested "
            "except for established fraud?")
        self.assertTrue(any("60 months" in p["quote"]
                            for p in passages))

    def test_proposer_prompt_contains_passages(self):
        captured = {}
        env = {"META_API_KEY": "test-key",
               "PROPOSER_MODEL": "proposer-x",
               "META_API_BASE_URL": "https://example.invalid"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.dict(sys.modules, {"requests": _stub_requests(
                    captured, content='{"claims": []}')}):
            proposer = make_model_proposer()
            proposer("What is the PED waiting period?", "en")
        prompt = captured["json"]["messages"][0]["content"]
        # Passages themselves, not just file names, are in the prompt.
        self.assertIn(PED_QUOTE, prompt)
        self.assertIn(PRODUCTS, prompt)
        self.assertIn("quote only", prompt.lower())
        for passage in retrieve("What is the PED waiting period?"):
            self.assertIn(passage["quote"], prompt)


class TestContextWindow(unittest.TestCase):
    def test_window_centres_on_quote_past_20000(self):
        source = "A" * 25000 + PED_QUOTE + "B" * 5000
        self.assertGreater(source.find(PED_QUOTE), 20000)
        windowed = _context_window(source, PED_QUOTE)
        self.assertIn(PED_QUOTE, windowed)
        self.assertLessEqual(len(windowed), 4000)
        # Context around the quote, not just the document start.
        self.assertFalse(windowed.startswith("A" * 4000))

    def test_window_falls_back_to_start_if_not_found(self):
        source = "X" * 10000
        self.assertEqual(
            _context_window(source, "no such quote"), source[:4000])
        short = "short text"
        self.assertEqual(_context_window(short, PED_QUOTE), short)

    def test_real_backend_sees_quote_context_past_20000(self):
        captured = {}
        source = "A" * 25000 + PED_QUOTE + "B" * 5000
        env = {"META_API_KEY": "test-key", "VERIFIER_MODEL": "model-x",
               "META_API_BASE_URL": "https://example.invalid"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            backend = make_model_backend()
            backend("The PED cap is 36 months.", PED_QUOTE, source)
        prompt = captured["json"]["messages"][0]["content"]
        self.assertIn(PED_QUOTE, prompt)
        # Windowed source is ~4000 chars, far below the old 20000 cap
        # plus prompt overhead would still miss a quote at 25000.
        self.assertLess(len(prompt), 20000)


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
        self.assertEqual(
            trace["final_answer"],
            "The PED waiting period is maximum up to 36 months of "
            "continuous coverage. (Source: "
            "irdai-insurance-products-regulations-2024.pdf)")

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
        self.assertTrue(trace["final_answer"].startswith(REFUSAL_PREFIX))
        self.assertEqual(trace["refusal_reason"], REFUSAL_EVIDENCE_NOT_FOUND)
        self.assertFalse(trace["claims"][0]["evidence"]["found"])
        self.assertIsNone(trace["claims"][0]["verdict"])
        self.assertEqual(
            trace["final_answer"],
            "I can't confirm this from the official documents I "
            "have. The cited evidence was not found in the official "
            "documents.")

    def test_c_superseded_ped_48_is_superseded(self):
        # The fake supports the claim against the Arogya quote and
        # contradicts it only against the governing quote: the catch
        # comes from authority precedence, so SUPERSEDED.
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": CONTRADICTED,
                    "reason": "Governing passage caps PED at 36 months."})
            return json.dumps({
                "verdict": SUPPORTED,
                "reason": "The Arogya quote states 48 months."})

        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft), verifier=backend)
        self.assertEqual(trace["decision"], SUPERSEDED)
        self.assertNotEqual(trace["decision"], CORRECTED)
        # Cited-source verdict stays SUPPORTED; only decision is
        # SUPERSEDED (governing verdict kept separately).
        self.assertEqual(trace["claims"][0]["verdict"], SUPPORTED)
        self.assertEqual(
            trace["claims"][0]["verifier_verdict"], SUPPORTED)
        self.assertNotEqual(trace["claims"][0]["verdict"], SUPERSEDED)
        self.assertTrue(trace["claims"][0]["evidence"]["found"])
        blob = json.dumps(trace)
        self.assertIn("36 months", blob)
        self.assertIn("48 months", trace["final_answer"])
        msg = trace["final_answer"]
        self.assertEqual(trace["correction"], msg)
        self.assertEqual(
            msg,
            "Current rule: maximum 36 months (IRDAI (Insurance "
            "Products) Regulations, 2024, Schedule III, Regulation "
            "7). Arogya Sanjeevani prospectus (HDFC ERGO specimen) "
            "still says 48 months, but the 2024 regulation overrides "
            "it.\n" + PED_QUOTE)
        self.assertNotIn(AROGYA_48_QUOTE, msg)
        self.assertNotIn("Governing passage caps PED at 36 months.", msg)
        self.assertEqual(
            trace["claims"][0]["governing_source"], PRODUCTS)
        self.assertEqual(
            trace["claims"][0]["governing_verdict"], CONTRADICTED)
        self.assertTrue(
            trace["claims"][0]["governing_evidence"]["found"])

    def _superseded_backend(self):
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": CONTRADICTED,
                    "reason": "Governing passage caps PED at 36 months."})
            return json.dumps({
                "verdict": SUPPORTED,
                "reason": "The Arogya quote states 48 months."})
        return backend

    def test_fix14_hindi_claim_arogya48_is_superseded(self):
        draft = {"claims": [{
            "claim": "प्री-एग्ज़िस्टिंग डिज़ीज़ के लिए वेटिंग पीरियड "
                     "48 महीने है",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "प्री-एग्ज़िस्टिंग डिज़ीज़ के लिए प्रतीक्षा अवधि क्या है?",
            proposer=fake_proposer(draft),
            verifier=self._superseded_backend())
        self.assertEqual(trace["decision"], SUPERSEDED)
        self.assertEqual(trace["claims"][0]["verdict"], SUPPORTED)
        self.assertEqual(
            trace["claims"][0]["governing_verdict"], CONTRADICTED)
        self.assertIn("36 महीने", trace["final_answer"])
        self.assertIn("ओवरराइड करता है", trace["final_answer"])
        self.assertNotIn("रद्द करता है", trace["final_answer"])

    def test_fix14_hinglish_claim_arogya48_is_superseded(self):
        # No English PED keyword and no Devanagari keyword in the
        # claim/question: only the cited (English) quote touches
        # the governed topic, yet the governing check must run.
        draft = {"claims": [{
            "claim": "Purani bimari ke liye waiting period "
                     "48 months hai",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "Purani bimari ke liye waiting period kitne months hai?",
            proposer=fake_proposer(draft),
            verifier=self._superseded_backend())
        self.assertEqual(trace["decision"], SUPERSEDED)
        self.assertEqual(
            trace["claims"][0]["governing_verdict"], CONTRADICTED)

    def test_fix14_quote_only_topic_triggers_governing(self):
        # Claim/question carry no topic keyword in any language;
        # the quote alone (pre-existing/PED) triggers the check.
        draft = {"claims": [{
            "claim": "The period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the period?",
            proposer=fake_proposer(draft),
            verifier=self._superseded_backend())
        self.assertEqual(trace["decision"], SUPERSEDED)

    def test_fix14_devanagari_keywords_match_governing(self):
        try:
            from verify.authority import governing_for
        except ImportError:
            from authority import governing_for
        for text in ("प्री-एग्ज़िस्टिंग 48 महीने",
                     "पूर्व-मौजूदा बीमारी 48 महीने",
                     "पीईडी 48 महीने",
                     "वेटिंग पीरियड 48 महीने",
                     "प्रतीक्षा अवधि 48 महीने"):
            self.assertTrue(governing_for(AROGYA, text=text), text)
        # Quote-only matching via the governing_for quote argument.
        self.assertTrue(governing_for(
            AROGYA, text="कोई जानकारी", quote=AROGYA_48_QUOTE))

    def test_fix14_uncertain_superseded_topic_is_not_verified(self):
        # Hindi claim citing a superseded source, no topic keyword
        # in claim/question/quote: fail closed, never VERIFIED.
        draft = {"claims": [{
            "claim": "कुछ स्वास्थ्य जानकारी 30 दिन है",
            "source_file": AROGYA, "quote": AROGYA_30_QUOTE}]}
        trace = answer(
            "कुछ स्वास्थ्य जानकारी क्या है?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "ok"}))
        self.assertEqual(trace["decision"], REFUSED)
        self.assertNotEqual(trace["decision"], VERIFIED)
        self.assertEqual(
            trace["refusal_reason"], REFUSAL_GOVERNING_INSUFFICIENT)

    def test_fix14_english_arogya_nonped_unchanged(self):
        # Certain English non-PED topic on a superseded source:
        # no governing rule, no uncertainty, still VERIFIED.
        draft = {"claims": [{
            "claim": "Illness treatment within 30 days is excluded "
                     "except accidents",
            "source_file": AROGYA, "quote": AROGYA_30_QUOTE}]}
        trace = answer(
            "Is illness in the first 30 days excluded?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "ok"}))
        self.assertEqual(trace["decision"], VERIFIED)

    def test_c_own_source_contradiction_stays_corrected(self):
        # Both the cited source and the governing passage contradict
        # the claim: not faithful to its own source, so CORRECTED.
        def backend(claim, quote, source_text):
            return json.dumps({
                "verdict": CONTRADICTED,
                "reason": "The passage does not say 48 months."})

        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft), verifier=backend)
        self.assertEqual(trace["decision"], CORRECTED)
        self.assertEqual(trace["claims"][0]["verdict"], CONTRADICTED)

    def test_g_governing_insufficient_is_refused(self):
        # Arogya quote SUPPORTED, governing INSUFFICIENT_EVIDENCE:
        # never fall back to the superseded verdict.
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": INSUFFICIENT_EVIDENCE,
                    "reason": "Governing passage does not establish "
                              "this claim."})
            return json.dumps({
                "verdict": SUPPORTED,
                "reason": "The Arogya quote states 48 months."})

        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft), verifier=backend)
        self.assertEqual(trace["decision"], REFUSED)
        self.assertTrue(trace["final_answer"].startswith(REFUSAL_PREFIX))
        self.assertEqual(trace["refusal_reason"], REFUSAL_GOVERNING_INSUFFICIENT)
        self.assertIsNone(trace["correction"])
        self.assertEqual(
            trace["claims"][0]["governing_verdict"],
            INSUFFICIENT_EVIDENCE)
        # Cited verdict unchanged (SUPPORTED); refusal comes from
        # the governing verdict alone.
        self.assertEqual(trace["claims"][0]["verdict"], SUPPORTED)
        self.assertEqual(
            trace["claims"][0]["verifier_verdict"], SUPPORTED)
        self.assertEqual(
            trace["claims"][0]["governing_source"], PRODUCTS)

    def test_g_governing_malformed_is_refused(self):
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return "not json"
            return json.dumps(
                {"verdict": SUPPORTED, "reason": "Arogya says 48."})

        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft), verifier=backend)
        self.assertEqual(trace["decision"], REFUSED)
        self.assertTrue(trace["final_answer"].startswith(REFUSAL_PREFIX))
        self.assertEqual(trace["refusal_reason"], REFUSAL_GOVERNING_INSUFFICIENT)
        self.assertEqual(
            trace["claims"][0]["governing_verdict"],
            INSUFFICIENT_EVIDENCE)

    def test_g_governing_supported_governs_over_superseded(self):
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": SUPPORTED,
                    "reason": "Governing passage supports this."})
            return json.dumps({
                "verdict": INSUFFICIENT_EVIDENCE,
                "reason": "Superseded passage alone is insufficient."})

        draft = {"claims": [{
            "claim": "PED waiting period is maximum up to 36 months "
                     "of continuous coverage.",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft), verifier=backend)
        self.assertEqual(trace["decision"], VERIFIED)
        # Cited verdict unchanged; governing SUPPORTED governs.
        self.assertEqual(
            trace["claims"][0]["verdict"], INSUFFICIENT_EVIDENCE)
        self.assertEqual(
            trace["claims"][0]["verifier_verdict"],
            INSUFFICIENT_EVIDENCE)
        self.assertEqual(
            trace["claims"][0]["governing_verdict"], SUPPORTED)

    def test_h_contradicted_without_governing_uses_reason_only(self):
        # CORRECTED final_answer is built from structured fields
        # (extracted value + quote + title), never claim/reason text.
        reason = "The passage caps PED at 36 months, not 12."
        draft = {"claims": [{
            "claim": "PED waiting period is 12 months",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": CONTRADICTED, "reason": reason}))
        self.assertEqual(trace["decision"], CORRECTED)
        self.assertEqual(trace["claims"][0]["verdict"], CONTRADICTED)
        self.assertEqual(
            trace["final_answer"],
            "The cited source (IRDAI (Insurance Products) "
            "Regulations, 2024, Schedule III, Regulation 7) says "
            "the maximum is 36 months.\n" + PED_QUOTE)
        self.assertNotIn(reason, trace["final_answer"])
        self.assertNotIn("PED waiting period is 12 months",
                         trace["final_answer"])
        self.assertEqual(trace["final_answer"], trace["correction"])

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
        self.assertTrue(trace["final_answer"].startswith(REFUSAL_PREFIX))
        self.assertEqual(trace["refusal_reason"], REFUSAL_VERIFIER_INSUFFICIENT)

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
        self.assertTrue(trace["final_answer"].startswith(REFUSAL_PREFIX))
        self.assertEqual(trace["refusal_reason"], REFUSAL_EVIDENCE_NOT_FOUND)
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
            self.assertTrue(trace["final_answer"].startswith(REFUSAL_PREFIX))
            self.assertEqual(trace["refusal_reason"], REFUSAL_VERIFIER_INSUFFICIENT)
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
        self.assertTrue(trace["final_answer"].startswith(REFUSAL_PREFIX))
        self.assertEqual(trace["refusal_reason"], REFUSAL_PROPOSER_ERROR)
        self.assertEqual(trace["exception_type"], "RuntimeError")


class TestAnswerLanguage(unittest.TestCase):
    def _a_draft(self):
        return {"claims": [{
            "claim": "The PED waiting period is maximum up to 36 "
                     "months of continuous coverage.",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}

    def _c_draft(self):
        return {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}

    def _c_backend(self):
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": CONTRADICTED,
                    "reason": "Governing passage caps PED at 36 months."})
            return json.dumps({
                "verdict": SUPPORTED, "reason": "Arogya says 48."})
        return backend

    def test_fix15_a_hi_verified_template(self):
        trace = answer(
            "अधिकतम प्रतीक्षा अवधि क्या है?", lang="hi",
            proposer=fake_proposer(self._a_draft()),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "ok"}))
        self.assertEqual(trace["decision"], VERIFIED)
        self.assertEqual(trace["lang"], "hi")
        self.assertEqual(
            trace["final_answer"],
            "प्री-एग्ज़िस्टिंग डिज़ीज़ के लिए वेटिंग पीरियड अधिकतम "
            "36 महीने है। (Source: "
            "irdai-insurance-products-regulations-2024.pdf)")
        self.assertIn("वेटिंग पीरियड", trace["final_answer"])
        self.assertIn("36 महीने", trace["final_answer"])
        self.assertNotIn("36 months", trace["final_answer"])

    def test_fix15_a_hinglish_verified_template(self):
        trace = answer(
            "Maximum waiting period kitna hai?", lang="hinglish",
            proposer=fake_proposer(self._a_draft()),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "ok"}))
        self.assertEqual(trace["decision"], VERIFIED)
        self.assertEqual(
            trace["final_answer"],
            "Pre-existing disease ke liye waiting period maximum "
            "36 months hai. (Source: "
            "irdai-insurance-products-regulations-2024.pdf)")
        self.assertNotIn("वेटिंग", trace["final_answer"])

    def test_fix15_b_hi_refused(self):
        draft = {"claims": [{
            "claim": "Maternity cover has a 9-month waiting period.",
            "source_file": PRODUCTS,
            "quote": "Maternity benefits shall be payable after nine "
                     "months of continuous coverage."}]}
        trace = answer(
            "Maternity waiting period क्या है?", lang="hi",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "x"}))
        self.assertEqual(trace["decision"], REFUSED)
        self.assertTrue(trace["final_answer"].startswith(
            "मैं इसकी पुष्टि"))
        self.assertIn("उद्धृत साक्ष्य", trace["final_answer"])
        self.assertNotIn(REFUSAL_PREFIX, trace["final_answer"])

    def test_fix15_b_hinglish_refused(self):
        draft = {"claims": [{
            "claim": "Maternity cover has a 9-month waiting period.",
            "source_file": PRODUCTS,
            "quote": "Maternity benefits shall be payable after nine "
                     "months of continuous coverage."}]}
        trace = answer(
            "Maternity waiting period kitna hai?", lang="hinglish",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "x"}))
        self.assertEqual(trace["decision"], REFUSED)
        self.assertTrue(trace["final_answer"].startswith("Main iski"))
        self.assertIn(
            "Cited evidence official documents mein nahi mila.",
            trace["final_answer"])
        self.assertNotIn(REFUSAL_PREFIX, trace["final_answer"])

    def test_fix15_c_hi_superseded(self):
        trace = answer(
            "प्रतीक्षा अवधि क्या है?", lang="hi",
            proposer=fake_proposer(self._c_draft()),
            verifier=self._c_backend())
        self.assertEqual(trace["decision"], SUPERSEDED)
        msg = trace["final_answer"]
        self.assertIn("वेटिंग पीरियड", msg)
        self.assertIn("प्री-एग्ज़िस्टिंग डिज़ीज़", msg)
        self.assertIn("आईआरडीएआई", msg)
        self.assertIn("36 महीने", msg)
        self.assertIn("48 महीने", msg)
        self.assertIn("ओवरराइड करता है", msg)
        self.assertNotIn("रद्द करता है", msg)
        self.assertNotIn("36 months है", msg)
        self.assertIn(PED_QUOTE, msg)  # quote stays English
        self.assertIn(
            "IRDAI (Insurance Products) Regulations, 2024", msg)
        self.assertNotIn("Current rule:", msg)

    def test_fix15_c_hinglish_superseded(self):
        trace = answer(
            "Waiting period kitna hai?", lang="hinglish",
            proposer=fake_proposer(self._c_draft()),
            verifier=self._c_backend())
        self.assertEqual(trace["decision"], SUPERSEDED)
        msg = trace["final_answer"]
        self.assertIn("waiting period", msg)
        self.assertIn("Pre-existing disease", msg)
        self.assertIn("IRDAI", msg)
        self.assertIn("36 months", msg)
        self.assertIn("48 months", msg)
        self.assertIn(PED_QUOTE, msg)
        self.assertNotIn("वेटिंग पीरियड", msg)
        self.assertNotIn("Current rule: maximum", msg)


class TestRefusalReasons(unittest.TestCase):
    def assert_refused(self, trace, reason):
        self.assertEqual(trace["decision"], REFUSED)
        self.assertEqual(trace["refusal_reason"], reason)
        self.assertIsNotNone(trace["final_answer"])
        self.assertTrue(
            trace["final_answer"].startswith(REFUSAL_PREFIX + " "))
        self.assertNotIn("\n", trace["final_answer"])
        self.assertGreater(len(trace["final_answer"]),
                           len(REFUSAL_PREFIX) + 1)
        self.assertIsNone(trace["correction"])

    def test_no_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            trace = answer("What is the PED waiting period?")
        self.assert_refused(trace, REFUSAL_NO_API_KEY)
        self.assertEqual(trace["exception_type"], "RuntimeError")

    def test_proposer_error(self):
        def boom(question, lang):
            raise RuntimeError("proposer down")

        trace = answer("Anything?", proposer=boom,
                       verifier=fake_backend(
                           {"verdict": SUPPORTED, "reason": "x"}))
        self.assert_refused(trace, REFUSAL_PROPOSER_ERROR)
        self.assertEqual(trace["exception_type"], "RuntimeError")

    def test_no_claims(self):
        for draft in ({"claims": []}, "not json"):
            trace = answer(
                "Anything?", proposer=fake_proposer(draft),
                verifier=fake_backend(
                    {"verdict": SUPPORTED, "reason": "x"}))
            self.assert_refused(trace, REFUSAL_NO_CLAIMS)

    def test_evidence_not_found(self):
        draft = {"claims": [{
            "claim": "The PED waiting period is 12 months.",
            "source_file": PRODUCTS,
            "quote": "The waiting period shall be twelve months."}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "x"}))
        self.assert_refused(trace, REFUSAL_EVIDENCE_NOT_FOUND)

    def test_verifier_insufficient(self):
        draft = {"claims": [{
            "claim": "The PED cap applies to Overseas Travel Policies.",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        trace = answer(
            "Does the PED cap apply to overseas travel policies?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": INSUFFICIENT_EVIDENCE, "reason": "no"}))
        self.assert_refused(trace, REFUSAL_VERIFIER_INSUFFICIENT)

    def test_governing_insufficient(self):
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": INSUFFICIENT_EVIDENCE, "reason": "no"})
            return json.dumps(
                {"verdict": SUPPORTED, "reason": "Arogya says 48."})

        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft), verifier=backend)
        self.assert_refused(trace, REFUSAL_GOVERNING_INSUFFICIENT)


class TestDemo(unittest.TestCase):
    def _demo(self):
        try:
            import verify.demo as demo
        except ImportError:
            import demo
        return demo

    def _verified_trace(self):
        draft = {"claims": [{
            "claim": "The PED waiting period is maximum up to 36 months "
                     "of continuous coverage.",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        return answer(
            "What is the maximum PED waiting period?",
            proposer=fake_proposer(draft),
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "ok"}))

    def test_format_trace_labels_every_stage(self):
        demo = self._demo()
        text = demo.format_trace(self._verified_trace(), color=False)
        self.assertIn("Stage 1", text)
        self.assertIn("Question", text)
        self.assertIn("Muse Spark draft", text)
        self.assertIn("Evidence check", text)
        self.assertIn("FOUND", text)
        self.assertIn(PRODUCTS, text)
        self.assertIn("Verifier verdict", text)
        self.assertIn("SUPPORTED", text)
        self.assertIn("Final decision", text)
        self.assertIn("VERIFIED", text)
        self.assertNotIn("\033[", text)

    def test_format_trace_shows_governing_and_superseded(self):
        demo = self._demo()

        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": CONTRADICTED,
                    "reason": "Governing passage caps PED at 36 months."})
            return json.dumps(
                {"verdict": SUPPORTED, "reason": "Arogya says 48."})

        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer("What is the PED waiting period?",
                       proposer=fake_proposer(draft), verifier=backend)
        text = demo.format_trace(trace, color=False)
        self.assertIn("Governing check", text)
        self.assertIn("SUPERSEDED", text)
        self.assertIn("Current rule:", text)
        # Stage 4 cited verdict, Stage 5 governing, Stage 6 decision.
        s4 = text.split("Stage 4")[1].split("Stage 5")[0]
        s5 = text.split("Stage 5")[1].split("Stage 6")[0]
        s6 = text.split("Stage 6")[1]
        self.assertIn("SUPPORTED", s4)
        self.assertNotIn("SUPERSEDED", s4)
        self.assertIn("CONTRADICTED", s5)
        self.assertIn("SUPERSEDED", s6)

    def test_format_trace_shows_in_force_from_1_april_2024(self):
        demo = self._demo()

        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({
                    "verdict": CONTRADICTED,
                    "reason": "Governing passage caps PED at 36 months."})
            return json.dumps(
                {"verdict": SUPPORTED, "reason": "Arogya says 48."})

        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer("What is the PED waiting period?",
                       proposer=fake_proposer(draft), verifier=backend)
        self.assertEqual(
            trace["claims"][0]["governing_effective_date"], "2024-04-01")
        text = demo.format_trace(trace, color=False)
        self.assertIn("in force from 1 April 2024", text)

    def test_format_trace_refused_shows_reason_and_message(self):
        demo = self._demo()
        trace = answer(
            "Anything?", proposer=fake_proposer({"claims": []}),
            verifier=fake_backend({"verdict": SUPPORTED, "reason": "x"}))
        text = demo.format_trace(trace, color=False)
        self.assertIn("REFUSED", text)
        self.assertIn("no claims", text)
        self.assertIn(REFUSAL_PREFIX, text)

    def test_format_trace_stage2_readable_claim_lines(self):
        demo = self._demo()
        trace = self._verified_trace()
        text = demo.format_trace(trace, color=False)
        s2 = text.split("Stage 2")[1].split("Stage 3")[0]
        # Each claim as a line: claim — source; raw JSON hidden.
        self.assertIn(
            "1. The PED waiting period is maximum up to 36 months "
            "of continuous coverage. — "
            "irdai-insurance-products-regulations-2024.pdf", s2)
        self.assertNotIn('"claims"', s2)
        self.assertNotIn('"source_file"', s2)
        self.assertIn("--raw", s2)
        raw_text = demo.format_trace(trace, color=False, raw=True)
        s2_raw = raw_text.split("Stage 2")[1].split("Stage 3")[0]
        self.assertIn('"claims"', s2_raw)
        self.assertIn("1. The PED waiting period", s2_raw)

    def test_colour_only_when_requested(self):
        demo = self._demo()
        coloured = demo.format_trace(
            self._verified_trace(), color=True)
        self.assertIn("\033[", coloured)
        fake_tty = io.StringIO()
        fake_tty.isatty = lambda: True
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(demo.supports_color(fake_tty))
            self.assertFalse(demo.supports_color(io.StringIO()))

    def test_load_env_reads_file_without_overwriting(self):
        demo = self._demo()
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "# comment\nDEMO_TEST_KEY=from-env-file\n"
                "export DEMO_TEST_OTHER='quoted'\n",
                encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = demo.load_env(env_file)
                self.assertEqual(loaded["DEMO_TEST_KEY"],
                                 "from-env-file")
                self.assertEqual(os.environ["DEMO_TEST_OTHER"],
                                 "quoted")
            with mock.patch.dict(
                    os.environ, {"DEMO_TEST_KEY": "real"}, clear=True):
                demo.load_env(env_file)
                self.assertEqual(os.environ["DEMO_TEST_KEY"], "real")

    def test_main_prints_trace_and_usage(self):
        demo = self._demo()
        stream = io.StringIO()
        trace = self._verified_trace()
        try:
            import verify.pipeline as pipeline_mod
        except ImportError:
            import pipeline as pipeline_mod
        with mock.patch.object(pipeline_mod, "answer",
                               return_value=trace):
            self.assertEqual(
                demo.main(["What is the PED waiting period?"],
                          stream=stream), 0)
        out = stream.getvalue()
        self.assertIn("Muse Spark draft", out)
        self.assertIn("VERIFIED", out)
        self.assertEqual(demo.main([], stream=io.StringIO()), 2)

    def test_main_lang_flag_and_autodetect(self):
        demo = self._demo()
        trace = self._verified_trace()
        try:
            import verify.pipeline as pipeline_mod
        except ImportError:
            import pipeline as pipeline_mod
        captured = {}

        def fake_answer(question, lang=None):
            captured["question"] = question
            captured["lang"] = lang
            return trace

        with mock.patch.object(pipeline_mod, "answer", fake_answer):
            self.assertEqual(demo.main(
                ["--lang", "hinglish", "Waiting period kitna hai?"],
                stream=io.StringIO()), 0)
            self.assertEqual(captured["lang"], "hinglish")
            self.assertEqual(
                captured["question"], "Waiting period kitna hai?")
            self.assertEqual(demo.main(
                ["--lang=hi", "प्रतीक्षा अवधि क्या है?"],
                stream=io.StringIO()), 0)
            self.assertEqual(captured["lang"], "hi")
            # No --lang: Devanagari question auto-detects to hi.
            self.assertEqual(demo.main(
                ["प्रतीक्षा अवधि क्या है?"], stream=io.StringIO()), 0)
            self.assertEqual(captured["lang"], "hi")
            self.assertEqual(demo.main(
                ["What is it?"], stream=io.StringIO()), 0)
            self.assertEqual(captured["lang"], "en")
        self.assertEqual(
            demo.main(["--lang", "fr", "Bonjour?"],
                      stream=io.StringIO()), 2)


if __name__ == "__main__":
    unittest.main()
