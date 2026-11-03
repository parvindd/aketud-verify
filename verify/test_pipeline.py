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
                                 APPLIES_TO_OLDER_CONTRACT,
                                 DEPENDS_ON_SALE_DATE,
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
                          APPLIES_TO_OLDER_CONTRACT, DEPENDS_ON_SALE_DATE,
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
AROGYA = "arogya-sanjeevani-specimen.pdf"

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


# Offline guarantee: the demo's ``.env`` lookup finds nothing and the
# model env vars are cleared for this module, so no test reaches a
# live model even when a real key sits in ``.env``. Explicit
# ``load_env(path)`` (its own tests) still works.
_OFFLINE_PATCHES = []


def setUpModule():
    offline_env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("META_", "VERIFIER_",
                                        "PROPOSER_"))}
    _OFFLINE_PATCHES.append(
        mock.patch.dict(os.environ, offline_env, clear=True))
    for name in ("verify.demo", "demo"):
        try:
            module = __import__(name, fromlist=["_env_candidates"])
        except ImportError:
            continue
        _OFFLINE_PATCHES.append(
            mock.patch.object(module, "_env_candidates", lambda: []))
    for patcher in _OFFLINE_PATCHES:
        patcher.start()


def tearDownModule():
    while _OFFLINE_PATCHES:
        _OFFLINE_PATCHES.pop().stop()


# Fix 36: SUPERSEDED needs a sale date on/after the rule's
# applies_from (2024-04-01); without one the decision is
# DEPENDS_ON_SALE_DATE. Case C tests of the SUPERSEDED path use this.
CURRENT_SALE_DATE = "2024-06-01"


def answer_sold_after_2024(*args, **kwargs):
    kwargs.setdefault("sale_date", CURRENT_SALE_DATE)
    return answer(*args, **kwargs)


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
    def __init__(self, content, model="model-x", usage=None):
        self._content = content
        self._model = model
        self._usage = ({"prompt_tokens": 11, "completion_tokens": 7,
                        "total_tokens": 18}
                       if usage is None else usage)

    def raise_for_status(self):
        return None

    def json(self):
        return {"model": self._model, "usage": self._usage,
                "choices": [{"message": {"content": self._content}}]}


def _stub_requests(captured, content='{"verdict": "SUPPORTED", '
                                      '"reason": "ok"}'):
    fake = types.ModuleType("requests")

    def post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured.setdefault("calls", []).append(
            {"url": url, "headers": headers, "json": json})
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
        # Fix 27 primary backend: VERIFIER_* (Modal), mocked post.
        captured = {}
        env = {"VERIFIER_API_KEY": "verifier-key",
               "VERIFIER_MODEL": "model-x",
               "VERIFIER_BASE_URL": "https://example.invalid/v1",
               "META_API_KEY": "meta-key",
               "META_API_BASE_URL": "https://meta.invalid/v1"}
        with mock.patch.dict(os.environ, env, clear=True), \
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
        self.assertEqual(
            captured["url"], "https://example.invalid/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"],
                         "Bearer verifier-key")


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
        env = {"VERIFIER_API_KEY": "verifier-key",
               "VERIFIER_MODEL": "model-x",
               "VERIFIER_BASE_URL": "https://example.invalid/v1"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            backend = make_model_backend()
            backend("The PED cap is 36 months.", PED_QUOTE, source)
        prompt = captured["json"]["messages"][0]["content"]
        self.assertIn(PED_QUOTE, prompt)
        # Windowed source is ~4000 chars, far below the old 20000 cap
        # plus prompt overhead would still miss a quote at 25000.
        self.assertLess(len(prompt), 20000)


class TestFix27VerifierBackends(unittest.TestCase):
    """Fix 27: verifier env split, fallback trace, demo display."""

    _MODAL_ENV = {
        "VERIFIER_BASE_URL": "https://modal.invalid/v1",
        "VERIFIER_API_KEY": "modal-key",
        "VERIFIER_MODEL": "meta-models/Muse-Spark-Open-816B-A42B",
        "META_API_KEY": "meta-key",
        "META_API_BASE_URL": "https://api.meta.ai/v1",
        "PROPOSER_MODEL": "muse-spark-1.3",
    }

    def _demo(self):
        try:
            import verify.demo as demo
        except ImportError:
            import demo
        return demo

    def test_primary_backend_uses_verifier_env_only(self):
        captured = {}
        with mock.patch.dict(os.environ, self._MODAL_ENV, clear=True), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            backend = make_model_backend()
            backend("c", PED_QUOTE, "source text")
        self.assertEqual(
            captured["url"], "https://modal.invalid/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"],
                         "Bearer modal-key")
        self.assertEqual(captured["json"]["model"],
                         "meta-models/Muse-Spark-Open-816B-A42B")
        self.assertFalse(backend.is_fallback)
        self.assertEqual(
            backend.verifier_label,
            "verifier: meta-models/Muse-Spark-Open-816B-A42B")
        self.assertEqual(backend.last_usage["total_tokens"], 18)
        self.assertIsNotNone(backend.last_latency_s)

    def test_fallback_backend_uses_meta_env_and_labels_fallback(self):
        captured = {}
        env = {"META_API_KEY": "meta-key",
               "META_API_BASE_URL": "https://api.meta.ai/v1",
               "PROPOSER_MODEL": "muse-spark-1.3"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            backend = make_model_backend()
            backend("c", PED_QUOTE, "source text")
        self.assertEqual(
            captured["url"], "https://api.meta.ai/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"],
                         "Bearer meta-key")
        self.assertEqual(captured["json"]["model"], "muse-spark-1.3")
        self.assertTrue(backend.is_fallback)
        self.assertEqual(backend.verifier_label,
                         "verifier: muse-spark-1.3 (fallback)")

    def test_placeholder_verifier_url_counts_as_unset(self):
        captured = {}
        env = dict(self._MODAL_ENV,
                   VERIFIER_BASE_URL="PASTE_ENDPOINT_URL/v1")
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            backend = make_model_backend()
            backend("c", PED_QUOTE, "source text")
        self.assertEqual(
            captured["url"], "https://api.meta.ai/v1/chat/completions")
        self.assertTrue(backend.is_fallback)
        self.assertEqual(backend.verifier_label,
                         "verifier: muse-spark-1.3 (fallback)")

    def test_proposer_keeps_meta_env(self):
        captured = {}
        with mock.patch.dict(os.environ, self._MODAL_ENV, clear=True), \
                mock.patch.dict(sys.modules, {"requests": _stub_requests(
                    captured, content='{"claims": []}')}):
            make_model_proposer()("What is the PED waiting period?", "en")
        self.assertEqual(
            captured["url"], "https://api.meta.ai/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"],
                         "Bearer meta-key")
        self.assertEqual(captured["json"]["model"], "muse-spark-1.3")

    def test_pipeline_trace_and_demo_show_modal_verifier(self):
        captured = {}
        draft = {"claims": [{
            "claim": "The PED waiting period is maximum up to 36 months "
                     "of continuous coverage.",
            "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        with mock.patch.dict(os.environ, self._MODAL_ENV), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            # Proposer injected; default verifier = mocked Modal backend.
            trace = answer("What is the maximum PED waiting period?",
                           proposer=fake_proposer(draft))
        self.assertEqual(trace["decision"], VERIFIED)
        self.assertEqual(
            trace["verifier"],
            "verifier: meta-models/Muse-Spark-Open-816B-A42B")
        self.assertEqual(trace["verifier_model"],
                         "meta-models/Muse-Spark-Open-816B-A42B")
        self.assertFalse(trace["verifier_fallback"])
        claim = trace["claims"][0]
        self.assertEqual(claim["verifier_model"],
                         "meta-models/Muse-Spark-Open-816B-A42B")
        self.assertEqual(claim["verifier_usage"]["total_tokens"], 18)
        self.assertIsNotNone(claim["verifier_latency_s"])
        text = self._demo().format_trace(trace, color=False)
        s4 = text.split("Stage 4")[1].split("Stage 5")[0]
        self.assertIn("meta-models/Muse-Spark-Open-816B-A42B", s4)
        self.assertIn("Verifier:", s4)

    def test_pipeline_trace_and_demo_show_fallback_verifier(self):
        captured = {}
        env = {"META_API_KEY": "meta-key",
               "META_API_BASE_URL": "https://api.meta.ai/v1",
               "PROPOSER_MODEL": "muse-spark-1.3",
               "VERIFIER_BASE_URL": "", "VERIFIER_API_KEY": "",
               "VERIFIER_MODEL": ""}
        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        # Cited quote SUPPORTED, governing quote CONTRADICTED (case C).
        def content_for(json_payload):
            prompt = json_payload["messages"][0]["content"]
            if PED_QUOTE in prompt and "48 months" in prompt:
                return ('{"verdict": "CONTRADICTED", "reason": '
                        '"Governing passage caps PED at 36 months."}')
            return ('{"verdict": "SUPPORTED", "reason": '
                    '"The Arogya quote states 48 months."}')
        fake = types.ModuleType("requests")

        def post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse(content_for(json))

        fake.post = post
        with mock.patch.dict(os.environ, env), \
                mock.patch.dict(sys.modules, {"requests": fake}):
            trace = answer_sold_after_2024("What is the PED waiting period?",
                           proposer=fake_proposer(draft))
        self.assertEqual(trace["decision"], SUPERSEDED)
        self.assertEqual(trace["verifier"],
                         "verifier: muse-spark-1.3 (fallback)")
        self.assertTrue(trace["verifier_fallback"])
        self.assertEqual(trace["claims"][0]["verifier_model"],
                         "muse-spark-1.3")
        text = self._demo().format_trace(trace, color=False)
        s4 = text.split("Stage 4")[1].split("Stage 5")[0]
        s5 = text.split("Stage 5")[1].split("Stage 6")[0]
        self.assertIn("Verifier: muse-spark-1.3 (fallback)", s4)
        self.assertIn("Verifier: muse-spark-1.3 (fallback)", s5)

    def test_callcheck_stage3_4_show_verifier_model(self):
        try:
            import verify.callcheck as cc
        except ImportError:
            import callcheck as cc
        backend = fake_backend(
            {"verdict": CONTRADICTED, "reason": "Rule says opposite."})
        backend.model = "meta-models/Muse-Spark-Open-816B-A42B"
        backend.is_fallback = False
        backend.verifier_label = (
            "verifier: meta-models/Muse-Spark-Open-816B-A42B")
        trace = cc.check_call(
            "IRDAI is calling about your bonus", verifier=backend)
        self.assertEqual(
            trace["verifier_model"],
            "meta-models/Muse-Spark-Open-816B-A42B")
        text = cc.format_call_trace(trace)
        s3 = text.split("Stage 3")[1].split("Stage 4")[0]
        s4 = text.split("Stage 4")[1]
        self.assertIn("meta-models/Muse-Spark-Open-816B-A42B", s3)
        self.assertIn("meta-models/Muse-Spark-Open-816B-A42B", s4)


class TestFix28VerifierCheapParallel(unittest.TestCase):
    """Fix 28: json_object/low/300 payload, parallel verifier calls."""

    def test_backend_payload_is_cheap_json_mode(self):
        captured = {}
        env = {"VERIFIER_API_KEY": "verifier-key",
               "VERIFIER_MODEL": "model-x",
               "VERIFIER_BASE_URL": "https://example.invalid/v1"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.dict(sys.modules,
                                {"requests": _stub_requests(captured)}):
            backend = make_model_backend()
            raw = backend("c", PED_QUOTE, "source text")
        self.assertEqual(json.loads(raw)["verdict"], SUPPORTED)
        payload = captured["json"]
        self.assertEqual(payload["response_format"],
                         {"type": "json_object"})
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_tokens"], 600)

    def test_case_c_calls_run_in_parallel_with_per_call_usage(self):
        import threading
        import time as time_mod
        state = {"active": 0, "max_active": 0}
        lock = threading.Lock()

        class Resp:
            def __init__(self, content, usage):
                self._content = content
                self._usage = usage

            def raise_for_status(self):
                return None

            def json(self):
                return {"model": "model-x", "usage": self._usage,
                        "choices": [{"message": {
                            "content": self._content}}]}

        fake = types.ModuleType("requests")

        def post(url, headers=None, json=None, timeout=None):
            with lock:
                state["active"] += 1
                state["max_active"] = max(
                    state["max_active"], state["active"])
            try:
                time_mod.sleep(0.25)
                prompt = json["messages"][0]["content"]
                if ("Quote: " + PED_QUOTE) in prompt:
                    return Resp(
                        '{"verdict": "CONTRADICTED", "reason": '
                        '"Governing passage caps PED at 36 months."}',
                        {"prompt_tokens": 20, "completion_tokens": 2,
                         "total_tokens": 22})
                return Resp(
                    '{"verdict": "SUPPORTED", "reason": '
                    '"The Arogya quote states 48 months."}',
                    {"prompt_tokens": 10, "completion_tokens": 1,
                     "total_tokens": 11})
            finally:
                with lock:
                    state["active"] -= 1

        fake.post = post
        env = {"VERIFIER_API_KEY": "verifier-key",
               "VERIFIER_MODEL": "model-x",
               "VERIFIER_BASE_URL": "https://example.invalid/v1"}
        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        started = time_mod.monotonic()
        with mock.patch.dict(os.environ, env), \
                mock.patch.dict(sys.modules, {"requests": fake}):
            trace = answer_sold_after_2024("What is the PED waiting period?",
                           proposer=fake_proposer(draft))
        elapsed = time_mod.monotonic() - started
        self.assertEqual(trace["decision"], SUPERSEDED)
        self.assertGreaterEqual(state["max_active"], 2)
        self.assertLess(elapsed, 5)
        claim = trace["claims"][0]
        self.assertEqual(claim["verdict"], SUPPORTED)
        self.assertEqual(claim["governing_verdict"], CONTRADICTED)
        # Per-call tokens kept separate despite parallel calls.
        self.assertEqual(claim["verifier_usage"]["total_tokens"], 11)
        self.assertEqual(
            claim["governing_verifier_usage"]["total_tokens"], 22)
        self.assertIsNotNone(claim["verifier_latency_s"])
        self.assertIsNotNone(claim["governing_verifier_latency_s"])

    def test_malformed_parallel_output_still_fails_closed(self):
        draft = {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}
        trace = answer(
            "What is the PED waiting period?",
            proposer=fake_proposer(draft),
            verifier=fake_backend("not json"))
        self.assertEqual(trace["decision"], REFUSED)


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
        trace = answer_sold_after_2024(
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
        trace = answer_sold_after_2024(
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
        trace = answer_sold_after_2024(
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
        trace = answer_sold_after_2024(
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
        trace = answer_sold_after_2024(
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
        trace = answer_sold_after_2024(
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
        trace = answer_sold_after_2024("What is the PED waiting period?",
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


class TestCaseDCallCheck(unittest.TestCase):
    """Case D fake revival-call tests (Fix 19, offline)."""

    def _callcheck(self):
        try:
            import verify.callcheck as callcheck
        except ImportError:
            import callcheck
        return callcheck

    # Hinglish fake-call transcript; no insurer is named.
    _HINGLISH = (
        "Namaste, main IRDAI se bol raha hoon, aapke bonus ke "
        "baare mein call hai. Aaj hi revive karo warna policy "
        "hamesha ke liye lapse ho jayegi. Revive today or lapse "
        "forever. Abhi ₹2,000 revival fee pay karo.")

    def test_revive_today_or_lapse_forever_contradicts(self):
        cc = self._callcheck()
        for transcript, years in (
                ("Revive today or lapse forever, jaldi karo",
                 "five consecutive"),
                ("ULIP policy hai, revive today or lapse forever",
                 "three consecutive")):
            trace = cc.check_call(transcript, lang="hinglish")
            deadline = [c for c in trace["claims"]
                        if c["kind"] == "revival_deadline"]
            self.assertEqual(len(deadline), 1, transcript)
            self.assertEqual(deadline[0]["verdict"],
                             cc.CONTRADICTS_RULES)
            self.assertEqual(deadline[0]["rule"], 2)
            self.assertIn(years, deadline[0]["quote"])
            self.assertTrue(deadline[0]["evidence"]["found"])

    def test_irdai_calling_about_bonus_contradicts(self):
        cc = self._callcheck()
        trace = cc.check_call(
            "IRDAI is calling about your bonus, claim karo abhi",
            lang="hinglish")
        claims = [c for c in trace["claims"]
                  if c["kind"] == "irdai_calling"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["verdict"], cc.CONTRADICTS_RULES)
        self.assertEqual(claims[0]["rule"], 4)
        self.assertIn("is not involved in activities like selling",
                      claims[0]["quote"])
        self.assertTrue(claims[0]["evidence"]["found"])

    def test_revival_fee_unknown_product_cannot_be_confirmed(self):
        cc = self._callcheck()
        trace = cc.check_call(
            "Pay ₹2,000 revival fee abhi, policy revive ho jayegi",
            lang="hinglish")
        fees = [c for c in trace["claims"]
                if c["kind"] == "revival_fee"]
        self.assertEqual(len(fees), 1)
        self.assertEqual(trace["product_type"], "unknown")
        self.assertEqual(fees[0]["verdict"], cc.CANNOT_BE_CONFIRMED)
        self.assertNotEqual(fees[0]["verdict"], cc.CONTRADICTS_RULES)

    def test_revival_fee_nonlinked_cannot_be_confirmed(self):
        cc = self._callcheck()
        trace = cc.check_call(
            "Non-linked policy ke liye ₹2,000 revival fee pay karo",
            lang="hinglish")
        fees = [c for c in trace["claims"]
                if c["kind"] == "revival_fee"]
        self.assertEqual(len(fees), 1)
        self.assertEqual(trace["product_type"], "non-linked")
        self.assertEqual(fees[0]["verdict"], cc.CANNOT_BE_CONFIRMED)

    def test_revival_fee_ulip_contradicts(self):
        cc = self._callcheck()
        trace = cc.check_call(
            "Pay ₹2,000 revival fee for your ULIP policy",
            lang="hinglish")
        fees = [c for c in trace["claims"]
                if c["kind"] == "revival_fee"]
        self.assertEqual(len(fees), 1)
        self.assertEqual(trace["product_type"], "linked")
        self.assertEqual(fees[0]["verdict"], cc.CONTRADICTS_RULES)
        self.assertEqual(fees[0]["rule"], 3)
        self.assertEqual(fees[0]["scope"], "linked products only")
        self.assertIn("without charging any interest or fee",
                      fees[0]["quote"])
        self.assertTrue(fees[0]["evidence"]["found"])

    def test_fee_unknown_never_supported_even_if_verifier_supports(self):
        cc = self._callcheck()
        trace = cc.check_call(
            "Pay ₹2,000 revival fee abhi",
            proposer=lambda t, lang: {"claims": [{
                "claim": "Caller claims a revival fee must be paid",
                "kind": "revival_fee", "rule": 3,
                "source_file": "mc-life-insurance-products-2024.pdf",
                "quote": "shall collect all due and unpaid premiums "
                         "without charging any interest or fee"}]},
            verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "should not win"}))
        self.assertEqual(trace["claims"][0]["verdict"],
                         cc.CANNOT_BE_CONFIRMED)

    def test_injected_proposer_and_verifier_are_used(self):
        cc = self._callcheck()
        try:
            from verify.authority import REGISTRY
        except ImportError:
            from authority import REGISTRY
        rule4 = [r for r in REGISTRY if r.get("rule") == 4][0]
        trace = cc.check_call(
            "kuch call aaya tha",
            proposer=lambda t, lang: {"claims": [{
                "claim": "Caller claims IRDAI is calling about "
                         "your bonus",
                "kind": "irdai_calling", "rule": 4,
                "source_file": rule4["source_file"],
                "quote": rule4["quote"]}]},
            verifier=fake_backend(
                {"verdict": CONTRADICTED, "reason": "Rule 4."}))
        self.assertEqual(trace["claims"][0]["verdict"],
                         cc.CONTRADICTS_RULES)
        self.assertEqual(trace["claims"][0]["verifier_verdict"],
                         CONTRADICTED)
        self.assertTrue(trace["claims"][0]["evidence"]["found"])

    _FULL_TRANSCRIPT = (
        "Sir main IRDAI se bol raha hoon. Aapki policy aaj lapse "
        "ho jayegi, aaj hi revive karna padega warna hamesha ke "
        "liye khatam. Aapka bonus bhi pending hai. Revival fee "
        "2,000 rupaye is link pe abhi pay kar dijiye, revival "
        "guaranteed hai.")

    def test_fix20_full_transcript_yields_4_claims(self):
        cc = self._callcheck()
        trace = cc.check_call(self._FULL_TRANSCRIPT)
        self.assertEqual(len(trace["claims"]), 4, trace["claims"])
        kinds = [c["kind"] for c in trace["claims"]]
        self.assertIn("revival_guaranteed", kinds)
        guaranteed = [c for c in trace["claims"]
                      if c["kind"] == "revival_guaranteed"][0]
        self.assertEqual(guaranteed["verdict"], cc.CONTRADICTS_RULES)
        self.assertEqual(guaranteed["rule"], 1)

    # Exact ASR transcript from a real call (Fix 25).
    _ASR_TRANSCRIPT = (
        "Hi, Sash. Uh, I already बोल रहा हूँ और आपकी एक पॉलिसी है "
        "जो आज लैप्स हो जाएगी, आज ही उसको रिवाइव करना पड़ेगा और "
        "हमेशा के लिए नहीं तो वो खत्म हो जाएगी. आपके बोनस भी अभी "
        "पेंडिंग है. रिवाइवल फी दो हज़ार है सर और मैं आपको एक लिंक "
        "भेज रहा हूँ आप आप उसकी पेमेंट कर दीजिए रिवाइवल गारंटीड है.!")

    def test_fix25_asr_transcript_devanagari_coverage(self):
        cc = self._callcheck()
        trace = cc.check_call(self._ASR_TRANSCRIPT)
        by_kind = {c["kind"]: c for c in trace["claims"]}
        self.assertEqual(by_kind["irdai_calling"]["rule"], 4)
        self.assertEqual(by_kind["irdai_calling"]["verdict"],
                         cc.CONTRADICTS_RULES)
        self.assertEqual(by_kind["revival_guaranteed"]["rule"], 1)
        self.assertEqual(by_kind["revival_guaranteed"]["verdict"],
                         cc.CONTRADICTS_RULES)
        self.assertEqual(by_kind["payment_link"]["verdict"],
                         cc.CANNOT_BE_CONFIRMED)
        self.assertEqual(by_kind["revival_deadline"]["rule"], 2)
        self.assertEqual(by_kind["revival_fee"]["verdict"],
                         cc.CANNOT_BE_CONFIRMED)

    def test_fix20_keyword_pass_covers_empty_proposer(self):
        cc = self._callcheck()
        trace = cc.check_call(
            self._FULL_TRANSCRIPT,
            proposer=lambda t, lang: {"claims": []})
        self.assertEqual(len(trace["claims"]), 4, trace["claims"])
        kinds = {c["kind"] for c in trace["claims"]}
        self.assertIn("revival_guaranteed", kinds)
        self.assertIn("revival_fee", kinds)

    def test_fix20_keyword_variants(self):
        cc = self._callcheck()
        for text, kind in (
                ("Revival pakka hai", "revival_guaranteed"),
                ("रिवाइवल गारंटी है", "revival_guaranteed"),
                ("Turant revive karo", "revival_deadline"),
                ("Revival shulk bharo", "revival_fee"),
                ("Is link pe pay karo", "payment_link")):
            trace = cc.check_call(text)
            self.assertIn(kind, [c["kind"] for c in trace["claims"]],
                          text)

    def test_fix21_specific_reasons_with_citation(self):
        cc = self._callcheck()
        trace = cc.check_call(self._FULL_TRANSCRIPT)
        self.assertEqual(len(trace["claims"]), 4)
        for claim in trace["claims"]:
            self.assertNotIn("The mapped rule states the opposite",
                             claim["reason"])
            self.assertTrue(claim["citation"] in claim["reason"]
                            or claim["kind"] == "payment_link",
                            claim)
        by_kind = {c["kind"]: c for c in trace["claims"]}
        self.assertIn("not guaranteed",
                      by_kind["revival_guaranteed"]["reason"])
        self.assertIn("1.10", by_kind["revival_guaranteed"]["reason"])
        self.assertIn("IRDAI is not involved",
                      by_kind["irdai_calling"]["reason"])
        self.assertIn("5 years (non-linked) or 3 years (linked) "
                      "from the first unpaid premium",
                      by_kind["revival_deadline"]["reason"])
        self.assertIn("Schedule I",
                      by_kind["revival_deadline"]["reason"])
        # Formatted output shows the specific reason too.
        text = cc.format_call_trace(trace)
        self.assertIn("5 years (non-linked) or 3 years (linked)",
                      text)

    def test_fix21_revival_period_known_product(self):
        cc = self._callcheck()
        trace = cc.check_call(
            "ULIP policy hai, revive today or lapse forever")
        deadline = [c for c in trace["claims"]
                    if c["kind"] == "revival_deadline"][0]
        self.assertIn("3 years (linked)", deadline["reason"])
        self.assertNotIn("5 years (non-linked) or", deadline["reason"])

    def test_hinglish_transcript_and_safety_advice_always(self):
        cc = self._callcheck()
        demo = TestDemo()._demo()
        transcripts = [
            self._HINGLISH,
            "Revive today or lapse forever",
            "IRDAI is calling about your bonus",
            "Pay ₹2,000 revival fee abhi",
            "Pay ₹2,000 revival fee for your ULIP policy",
            "Hello, kaise ho aap",
        ]
        for transcript in transcripts:
            trace = cc.check_call(transcript, lang="hinglish")
            self.assertTrue(
                trace["final_block"].endswith(
                    cc.safety_advice_for("hinglish")), transcript)
            self.assertIn("Safety advice:", trace["final_block"])
            self.assertIn("Hum aapki policy nahi dekh sakte",
                          trace["final_block"])
            text = cc.format_call_trace(trace)
            self.assertTrue(text.rstrip().endswith(
                cc.safety_advice_for("hinglish")))
            # English default keeps the original safety advice.
            en_trace = cc.check_call(transcript, lang="en")
            self.assertTrue(
                en_trace["final_block"].endswith(cc.SAFETY_ADVICE))
        # Combined Hinglish call: all three verdict kinds appear.
        trace = cc.check_call(self._HINGLISH, lang="hinglish")
        verdicts = [c["verdict"] for c in trace["claims"]]
        self.assertIn(cc.CONTRADICTS_RULES, verdicts)
        self.assertIn(cc.CANNOT_BE_CONFIRMED, verdicts)
        # Demo --call mode prints the same final block.
        stream = io.StringIO()
        self.assertEqual(
            demo.main(["--call", self._HINGLISH, "--lang", "hinglish"],
                      stream=stream), 0)
        out = stream.getvalue()
        self.assertIn("Caller claims", out)
        self.assertIn(cc.verdict_label(
            cc.CONTRADICTS_RULES, "hinglish"), out)
        self.assertIn(cc.verdict_label(
            cc.CANNOT_BE_CONFIRMED, "hinglish"), out)
        self.assertTrue(out.rstrip().endswith(
            cc.safety_advice_for("hinglish")))

    def test_fix22_lang_applies_to_labels_reasons_safety(self):
        cc = self._callcheck()
        for lang, label_part, safety_part in (
                ("hinglish", "Rules ke khilaf", "Hum aapki policy"),
                ("hi", "नियमों के विपरीत", "हम आपकी पॉलिसी")):
            trace = cc.check_call(self._FULL_TRANSCRIPT, lang=lang)
            self.assertIn(label_part, trace["final_block"])
            self.assertIn(safety_part, trace["final_block"])
            for claim in trace["claims"]:
                self.assertEqual(
                    claim["verdict_label"],
                    cc.verdict_label(claim["verdict"], lang))
                # Quotes and citations stay English.
                self.assertTrue(claim["quote"])
                if claim["citation"]:
                    self.assertIn(claim["citation"], claim["reason"])
            text = cc.format_call_trace(trace)
            self.assertIn(label_part, text)
        hi_trace = cc.check_call(self._FULL_TRANSCRIPT, lang="hi")
        # Hindi reasons use Devanagari (English terms transliterated).
        self.assertIn("रिवाइवल", hi_trace["claims"][1]["reason"])
        hinglish_trace = cc.check_call(
            self._FULL_TRANSCRIPT, lang="hinglish")
        self.assertNotIn("नियमों के विपरीत",
                         hinglish_trace["final_block"])
        self.assertIn("Revival period pehle unpaid premium se "
                      "5 years (non-linked) ya 3 years (linked)",
                      hinglish_trace["claims"][1]["reason"])

    def test_fix22_demo_options_any_order(self):
        demo = TestDemo()._demo()
        cc = self._callcheck()
        for argv in (
                ["--lang", "hinglish", "--call", self._HINGLISH],
                ["--call", self._HINGLISH, "--lang", "hinglish"],
                ["--call=%s" % self._HINGLISH, "--lang=hinglish"],
                ["--lang=hinglish", "--call=%s" % self._HINGLISH]):
            stream = io.StringIO()
            self.assertEqual(demo.main(argv, stream=stream), 0, argv)
            self.assertIn("Rules ke khilaf", stream.getvalue())
        # Question mode: options after the question too.
        trace = TestDemo()._verified_trace()
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
                ["Waiting period kitna hai?", "--lang", "hinglish"],
                stream=io.StringIO()), 0)
            self.assertEqual(captured["lang"], "hinglish")
            self.assertEqual(demo.main(
                ["--lang", "fr", "Bonjour?"], stream=io.StringIO()), 2)


class _FakeAsrResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _write_wav(path, *, channels=1, sampwidth=2, rate=16000, frames=160):
    import wave as wave_mod
    with wave_mod.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sampwidth)
        wav.setframerate(rate)
        wav.writeframes(b"\x00" * (channels * sampwidth * frames))


def _stub_asr_requests(captured, payload):
    fake = types.ModuleType("requests")

    def post(url, headers=None, files=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["files"] = files
        captured["timeout"] = timeout
        return _FakeAsrResponse(payload)

    fake.post = post
    return fake


class TestFix23CallcheckPolish(unittest.TestCase):
    """Fix 23 callcheck polish: Hinglish ya, spaces, final labels."""

    def _callcheck(self):
        try:
            import verify.callcheck as callcheck
        except ImportError:
            import callcheck
        return callcheck

    def test_hinglish_reasons_use_ya_not_or(self):
        cc = self._callcheck()
        trace = cc.check_call(
            TestCaseDCallCheck._FULL_TRANSCRIPT, lang="hinglish")
        for claim in trace["claims"]:
            self.assertNotIn(" or ", claim["reason"], claim)
        deadline = [c for c in trace["claims"]
                    if c["kind"] == "revival_deadline"][0]
        self.assertIn("5 years (non-linked) ya 3 years (linked)",
                      deadline["reason"])
        # English reasons keep "or"; citations stay English.
        en_trace = cc.check_call(
            TestCaseDCallCheck._FULL_TRANSCRIPT, lang="en")
        en_deadline = [c for c in en_trace["claims"]
                       if c["kind"] == "revival_deadline"][0]
        self.assertIn("5 years (non-linked) or 3 years (linked)",
                      en_deadline["reason"])

    def test_no_missing_space_joins_in_outputs(self):
        cc = self._callcheck()
        for lang in ("en", "hinglish", "hi"):
            trace = cc.check_call(
                TestCaseDCallCheck._FULL_TRANSCRIPT, lang=lang)
            text = trace["final_block"] + "\n" + cc.format_call_trace(
                trace)
            for bad in ("latefee", "Callerke", "PartC",
                        "hai;product"):
                self.assertNotIn(bad, text, (lang, bad))
            self.assertIn("Part C, para 40", text)
        hinglish = cc.check_call(
            TestCaseDCallCheck._FULL_TRANSCRIPT, lang="hinglish")
        self.assertIn("Caller ke bheje hue link", hinglish["final_block"])
        self.assertIn("product type unknown hai",
                      [c for c in hinglish["claims"]
                       if c["kind"] == "revival_fee"][0]["reason"])
        # Rule 1 quote keeps "late fee" spaced in Stage 2 output.
        self.assertIn("late fee",
                      cc.format_call_trace(hinglish))

    def test_final_block_claim_labels_localised(self):
        cc = self._callcheck()
        hinglish = cc.check_call(
            TestCaseDCallCheck._HINGLISH, lang="hinglish")
        self.assertIn(
            "Caller ka daava: IRDAI bonus ke baare mein call kar "
            "raha hai", hinglish["final_block"])
        self.assertNotIn("Caller claims IRDAI is calling",
                         hinglish["final_block"])
        for claim in hinglish["claims"]:
            self.assertEqual(
                claim["claim_label"],
                cc.claim_label(claim, "hinglish"))
            self.assertTrue(
                claim["claim_label"].startswith("Caller ka daava:"),
                claim)
        hi = cc.check_call(TestCaseDCallCheck._HINGLISH, lang="hi")
        self.assertIn("कॉलर का दावा:", hi["final_block"])
        en = cc.check_call(TestCaseDCallCheck._HINGLISH, lang="en")
        self.assertIn("Caller claims IRDAI is calling",
                      en["final_block"])
        self.assertNotIn("Caller ka daava", en["final_block"])


class TestVoiceTranscribe(unittest.TestCase):
    """Fix 23 voice transcription tests (offline, HTTP mocked)."""

    def _voice(self):
        try:
            import verify.voice as voice
        except ImportError:
            import voice
        return voice

    _ASR_PAYLOAD = {
        "audioDurationMs": 1000, "sessionId": "test-session",
        "transcript": "Revive today or lapse forever",
        "turns": [],
    }

    def test_transcribe_posts_multipart_and_reads_transcript(self):
        voice = self._voice()
        captured = {}
        env = {"META_API_KEY": "test-key",
               "META_API_BASE_URL": "https://example.invalid/v1"}
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "call.wav"
            _write_wav(wav_path)
            with mock.patch.dict(os.environ, env), \
                    mock.patch.dict(sys.modules, {
                        "requests": _stub_asr_requests(
                            captured, self._ASR_PAYLOAD)}):
                text = voice.transcribe(wav_path)
        self.assertEqual(text, "Revive today or lapse forever")
        self.assertEqual(
            captured["url"], "https://example.invalid/v1/asr/transcribe")
        self.assertEqual(captured["headers"]["Accept"],
                         "application/json")
        self.assertEqual(captured["headers"]["Authorization"],
                         "Bearer test-key")
        request_part = captured["files"]["request"]
        self.assertEqual(request_part[2], "application/json")
        self.assertEqual(json.loads(request_part[1]), {
            "model": "muse-voice-transcribe-1.0",
            "audioEncoding": "WAV", "mode": "PUSH_TO_TALK",
            "languageBias": ["hi", "en"],
            "keywords": ["IRDAI", "revival", "revive", "bonus",
                         "lapse", "policy", "premium", "fee"]})
        audio_part = captured["files"]["audio"]
        self.assertEqual(audio_part[0], "call.wav")
        self.assertEqual(audio_part[2], "audio/wav")

    def test_transcribe_accepts_24khz_mono_16bit(self):
        voice = self._voice()
        captured = {}
        env = {"META_API_KEY": "k",
               "META_API_BASE_URL": "https://example.invalid"}
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "call.wav"
            _write_wav(wav_path, rate=24000)
            with mock.patch.dict(os.environ, env), \
                    mock.patch.dict(sys.modules, {
                        "requests": _stub_asr_requests(
                            captured, self._ASR_PAYLOAD)}):
                self.assertEqual(
                    voice.transcribe(wav_path),
                    "Revive today or lapse forever")

    def test_transcribe_refuses_bad_wav_before_http(self):
        voice = self._voice()
        captured = {}
        env = {"META_API_KEY": "k",
               "META_API_BASE_URL": "https://example.invalid"}
        cases = [
            ({"channels": 2}, "mono"),
            ({"sampwidth": 1}, "16-bit"),
            ({"rate": 44100}, "16 kHz or 24 kHz"),
            ({"rate": 8000}, "16 kHz or 24 kHz"),
        ]
        for kwargs, needle in cases:
            with tempfile.TemporaryDirectory() as tmp:
                wav_path = Path(tmp) / "call.wav"
                _write_wav(wav_path, **kwargs)
                with mock.patch.dict(os.environ, env), \
                        mock.patch.dict(sys.modules, {
                            "requests": _stub_asr_requests(
                                captured, self._ASR_PAYLOAD)}):
                    with self.assertRaises(ValueError) as ctx:
                        voice.transcribe(wav_path)
                self.assertIn(needle, str(ctx.exception))
                self.assertIn("Refusing to transcribe",
                              str(ctx.exception))
        self.assertNotIn("url", captured)
        with self.assertRaises(ValueError):
            voice.transcribe("/nonexistent/call.wav")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "call.wav"
            bad.write_bytes(b"not a wav")
            with self.assertRaises(ValueError):
                voice.transcribe(bad)

    def test_transcribe_missing_transcript_field_fails(self):
        voice = self._voice()
        captured = {}
        env = {"META_API_KEY": "k",
               "META_API_BASE_URL": "https://example.invalid"}
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "call.wav"
            _write_wav(wav_path)
            with mock.patch.dict(os.environ, env), \
                    mock.patch.dict(sys.modules, {
                        "requests": _stub_asr_requests(
                            captured, {"sessionId": "x", "turns": []})}):
                with self.assertRaises(RuntimeError) as ctx:
                    voice.transcribe(wav_path)
        self.assertIn("transcript", str(ctx.exception))

    def test_demo_call_audio_shows_stage0_then_callcheck(self):
        demo = TestDemo()._demo()
        voice = self._voice()
        transcript = TestCaseDCallCheck._HINGLISH
        stream = io.StringIO()
        with mock.patch.object(voice, "transcribe",
                               return_value=transcript) as mock_tr:
            self.assertEqual(demo.main(
                ["--call-audio", "call.wav", "--lang", "hinglish"],
                stream=stream), 0)
        mock_tr.assert_called_once_with("call.wav")
        out = stream.getvalue()
        self.assertIn("Stage 0 — Muse Voice Transcribe", out)
        self.assertIn(transcript, out)
        # Fix 26: transcript shown once (Stage 0 only).
        self.assertEqual(out.count(transcript), 1)
        self.assertIn("Stage 1 — Call transcript", out)
        self.assertIn("from Stage 0", out)
        self.assertIn("Rules ke khilaf", out)
        self.assertTrue(out.rstrip().endswith(
            "Caller ke bheje hue link se payment na karein."))

    def test_demo_call_audio_transcription_failure_returns_1(self):
        demo = TestDemo()._demo()
        voice = self._voice()
        with mock.patch.object(
                voice, "transcribe",
                side_effect=ValueError(
                    "Refusing to transcribe x.wav: WAV must be mono")):
            self.assertEqual(demo.main(
                ["--call-audio", "x.wav"], stream=io.StringIO()), 1)
        self.assertEqual(demo.main(
            ["--call-audio", "x.wav", "extra question"],
            stream=io.StringIO()), 2)


class TestFix26DisplayNormalisation(unittest.TestCase):
    """Fix 26: joined text normalised in displayed quotes/citations."""

    def test_call_trace_normalises_joined_quote_and_citation(self):
        try:
            import verify.callcheck as cc
        except ImportError:
            import callcheck as cc
        quote = ("requested tolodge a complaint on the basis of "
                 "the information,documents furnished")
        trace = {
            "transcript": "hello", "lang": "en", "final_block": "",
            "claims": [{
                "claim": "Caller claims a fee", "kind": "revival_fee",
                "rule": 1, "source_file": "x.pdf", "quote": quote,
                "citation": "Schedule I, 1.39 (non-linked) and1.28 "
                            "(linked) linkse",
                "evidence": {"exists": True, "found": True},
                "verifier_verdict": "CONTRADICTED",
                "verdict": cc.CONTRADICTS_RULES,
                "verdict_label": cc.CONTRADICTS_RULES,
                "reason": "Schedule I, 1.39 and1.28 applies",
            }],
        }
        text = cc.format_call_trace(trace)
        self.assertIn("to lodge", text)
        self.assertIn("information, documents", text)
        self.assertIn("and 1.28", text)
        self.assertIn("link se", text)
        for bad in ("tolodge", "information,documents", "and1.28",
                    "linkse"):
            self.assertNotIn(bad, text)
        # Display only: stored quote unchanged.
        self.assertEqual(trace["claims"][0]["quote"], quote)

    def test_demo_trace_normalises_joined_quote(self):
        demo = TestDemo()._demo()
        trace = {
            "question": "q?", "draft": {"claims": []},
            "decision": "VERIFIED",
            "claims": [{
                "claim": "c", "source_file": "x.pdf",
                "quote": "requested tolodge it",
                "evidence": {"exists": True, "found": True},
                "verifier_verdict": "SUPPORTED",
            }],
        }
        text = demo.format_trace(trace)
        self.assertIn("to lodge", text)
        self.assertNotIn("tolodge", text)
        self.assertEqual(trace["claims"][0]["quote"],
                         "requested tolodge it")

    def test_fix29_remaining_joins_call_and_demo(self):
        try:
            import verify.callcheck as cc
            import verify.demo as demo
        except ImportError:
            import callcheck as cc
            import demo
        joined = ("ScheduleI withall benefits after 36 monthsof "
                  "coverage. Check karein.Caller sent it")
        for func in (cc.normalise_display_text,
                     demo.normalise_display_text):
            out = func(joined)
            for bad in ("ScheduleI", "withall", "karein.Caller",
                        "monthsof"):
                self.assertNotIn(bad, out)
            self.assertIn("Schedule I", out)
            self.assertIn("with all", out)
            self.assertIn("karein. Caller", out)
            self.assertIn("months of", out)
        # Display only through the call formatter; stored unchanged.
        trace = {
            "transcript": "hello", "lang": "en", "final_block": "",
            "claims": [{
                "claim": "Caller claims a fee", "kind": "revival_fee",
                "rule": 1, "source_file": "x.pdf", "quote": joined,
                "citation": "ScheduleI",
                "evidence": {"exists": True, "found": True},
                "verifier_verdict": "CONTRADICTED",
                "verdict": cc.CONTRADICTS_RULES,
                "verdict_label": cc.CONTRADICTS_RULES,
                "reason": joined,
            }],
        }
        text = cc.format_call_trace(trace)
        for bad in ("ScheduleI", "withall", "karein.Caller",
                    "monthsof"):
            self.assertNotIn(bad, text)
        self.assertEqual(trace["claims"][0]["quote"], joined)
        demo_trace = {
            "question": "q?", "draft": {"claims": []},
            "decision": "VERIFIED",
            "claims": [{
                "claim": "c", "source_file": "x.pdf",
                "quote": joined,
                "evidence": {"exists": True, "found": True},
                "verifier_verdict": "SUPPORTED",
            }],
        }
        demo_text = demo.format_trace(demo_trace)
        for bad in ("ScheduleI", "withall", "karein.Caller",
                    "monthsof"):
            self.assertNotIn(bad, demo_text.split("Quote:")[1])
        self.assertEqual(demo_trace["claims"][0]["quote"], joined)


class TestFix34RobustVerifierJson(unittest.TestCase):
    """Fix 34: lenient fence stripping, one retry, raw output logged."""

    def _counting(self, outputs):
        calls = {"n": 0}

        def backend(claim, quote, source_text):
            out = outputs[min(calls["n"], len(outputs) - 1)]
            calls["n"] += 1
            return out
        return backend, calls

    def test_fenced_json_parses(self):
        for raw in ('```json\n{"verdict": "SUPPORTED", "reason": "ok"}\n```',
                    'Here is my answer:\n{"verdict": "CONTRADICTED", '
                    '"reason": "no"} thanks'):
            backend, calls = self._counting([raw])
            r = Verifier(backend).verify("c", "q", "src")
            self.assertIn(r["verdict"], (SUPPORTED, CONTRADICTED), raw)
            self.assertNotIn("raw_output", r)
            self.assertEqual(calls["n"], 1)

    def test_fenced_unknown_verdict_still_rejected(self):
        for raw in ('```json\n{"verdict": "supported"}\n```',
                    '{"verdict": "LIKELY_SUPPORTED", "reason": "x"}'):
            r = Verifier(lambda c, q, s, _r=raw: _r).verify("c", "q", "src")
            self.assertEqual(r["verdict"], INSUFFICIENT_EVIDENCE, raw)

    def test_truncated_json_retries_then_fails_closed(self):
        truncated = '{"verdict": "SUPPORTED", "reason": "The passage dir'
        backend, calls = self._counting([truncated])
        r = Verifier(backend).verify("c", "q", "src")
        self.assertEqual(r["verdict"], INSUFFICIENT_EVIDENCE)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(r["attempts"], 2)
        self.assertEqual(r["raw_output"], truncated)

    def test_retry_recovers_when_second_reply_is_valid(self):
        backend, calls = self._counting(
            ["not json", '{"verdict": "SUPPORTED", "reason": "ok"}'])
        r = Verifier(backend).verify("c", "q", "src")
        self.assertEqual(r, {"verdict": SUPPORTED, "reason": "ok"})
        self.assertEqual(calls["n"], 2)

    def test_retry_count_capped_at_one(self):
        backend, calls = self._counting(["bad"] * 10)
        r = Verifier(backend).verify("c", "q", "src")
        self.assertEqual(r["verdict"], INSUFFICIENT_EVIDENCE)
        self.assertEqual(calls["n"], 2)

    def test_raw_output_truncated_to_500_chars(self):
        raw = "x" * 2000
        r = Verifier(lambda c, q, s: raw).verify("c", "q", "src")
        self.assertEqual(len(r["raw_output"]), 500)

    def test_backend_exception_is_not_retried(self):
        calls = {"n": 0}

        def boom(claim, quote, source_text):
            calls["n"] += 1
            raise RuntimeError("down")
        r = Verifier(boom).verify("c", "q", "src")
        self.assertEqual(r["verdict"], INSUFFICIENT_EVIDENCE)
        self.assertEqual(calls["n"], 1)

    def test_usage_summed_over_retry(self):
        class Backend:
            last_latency_s = 0.5
            last_response_model = "m"

            def __init__(self):
                self.n = 0

            def __call__(self, claim, quote, source_text):
                self.n += 1
                self.last_usage = {"prompt_tokens": 10,
                                   "completion_tokens": 3,
                                   "total_tokens": 13}
                return "bad" if self.n == 1 else (
                    '{"verdict": "SUPPORTED", "reason": "ok"}')
        v = Verifier(Backend())
        v.verify("c", "q", "src")
        self.assertEqual(v.last_usage["total_tokens"], 26)
        self.assertAlmostEqual(v.last_latency_s, 1.0)

    def test_raw_output_logged_in_pipeline_trace(self):
        draft = {"claims": [{"claim": "PED waiting period is at most "
                             "36 months.", "source_file": PRODUCTS,
                             "quote": PED_QUOTE}]}
        trace = answer("PED waiting period?", lang="en",
                       proposer=fake_proposer(draft),
                       verifier=Verifier(lambda c, q, s: '{"verdict": '))
        self.assertEqual(trace["decision"], REFUSED)
        claim = trace["claims"][0]
        self.assertEqual(claim["verdict"], INSUFFICIENT_EVIDENCE)
        self.assertEqual(claim["verifier_raw_output"], '{"verdict": ')


class TestFix36SaleDatePrecedence(unittest.TestCase):
    """Fix 36: sale-date aware precedence (reg 9(3) savings clause)."""

    SAVINGS = ("Unless otherwise mentioned herein, nothing in these "
               "regulations shall be deemed to invalidate the insurance "
               "contracts entered into prior to these regulations coming "
               "into force.")

    def _draft(self):
        return {"claims": [{
            "claim": "PED waiting period is 48 months",
            "source_file": AROGYA, "quote": AROGYA_48_QUOTE}]}

    def _backend(self):
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return json.dumps({"verdict": CONTRADICTED,
                                   "reason": "caps PED at 36 months"})
            return json.dumps({"verdict": SUPPORTED,
                               "reason": "Arogya says 48."})
        return backend

    def _ask(self, question="What is the PED waiting period?", lang="en",
             **kwargs):
        return answer(question, lang=lang,
                      proposer=fake_proposer(self._draft()),
                      verifier=self._backend(), **kwargs)

    # --- registry -----------------------------------------------------

    def test_registry_savings_quote_is_verbatim_and_found(self):
        from verify.authority import REGISTRY
        ped = REGISTRY[0]
        self.assertEqual(ped["applies_from"], "2024-04-01")
        self.assertEqual(ped["savings_quote"], self.SAVINGS)
        ev = check_evidence(ped["savings_source"], ped["savings_quote"])
        self.assertTrue(ev["exists"] and ev["found"])

    # --- three branches -----------------------------------------------

    def test_sold_on_or_after_applies_from_is_superseded(self):
        for sale in ("2024-04-01", "2025-01-10"):
            trace = self._ask(sale_date=sale)
            self.assertEqual(trace["decision"], SUPERSEDED, sale)
            self.assertEqual(trace["sale_date_branch"], ["current"])

    def test_sold_before_applies_from_is_older_contract(self):
        trace = self._ask(sale_date="2024-03-31")
        self.assertEqual(trace["decision"], APPLIES_TO_OLDER_CONTRACT)
        msg = trace["final_answer"]
        for text in ("48 months", "36 months", "Reg 9(3)", "Reg 7",
                     "31 March 2024", "Check your policy document",
                     AROGYA_48_QUOTE, PED_QUOTE, self.SAVINGS,
                     "Arogya Sanjeevani prospectus",
                     "IRDAI (Insurance Products) Regulations, 2024"):
            self.assertIn(text, msg)
        self.assertTrue(trace["savings"][0]["evidence"]["found"])

    def test_no_sale_date_depends_on_sale_date(self):
        trace = self._ask()
        self.assertEqual(trace["decision"], DEPENDS_ON_SALE_DATE)
        self.assertIsNone(trace["sale_date"])
        msg = trace["final_answer"]
        self.assertTrue(msg.startswith(
            "From 1 April 2024: max 36 months (Reg 7). Policies bought "
            "earlier keep their contract terms (Reg 9(3)); the specimen "
            "says 48 months."), msg)
        self.assertIn(PED_QUOTE, msg)
        self.assertIn(self.SAVINGS, msg)

    def test_year_straddling_applies_from_depends(self):
        trace = self._ask("I bought Arogya Sanjeevani in 2024. PED "
                          "waiting period?")
        self.assertEqual(trace["sale_date"]["earliest"], "2024-01-01")
        self.assertEqual(trace["decision"], DEPENDS_ON_SALE_DATE)

    def test_question_text_sale_date_used(self):
        trace = self._ask("PED waiting period? I bought it in 2021.")
        self.assertEqual(trace["decision"], APPLIES_TO_OLDER_CONTRACT)
        self.assertIn("(sale date: 2021)", trace["final_answer"])

    def test_explicit_sale_date_wins_over_text(self):
        trace = self._ask("PED waiting period? I bought it in 2021.",
                          sale_date="2025-02-01")
        self.assertEqual(trace["decision"], SUPERSEDED)

    def test_invalid_explicit_date_fails_closed_to_depends(self):
        trace = self._ask(sale_date="2021-13-40")
        self.assertEqual(trace["decision"], DEPENDS_ON_SALE_DATE)
        self.assertTrue(trace["sale_date_error"])

    def test_languages(self):
        hi = self._ask("प्रतीक्षा अवधि क्या है?", lang="hi")
        self.assertEqual(hi["decision"], DEPENDS_ON_SALE_DATE)
        self.assertIn("1 अप्रैल 2024 से: अधिकतम 36 महीने (Reg 7)",
                      hi["final_answer"])
        self.assertIn("स्पेसिमेन में 48 महीने", hi["final_answer"])
        hi_old = self._ask("मैंने पॉलिसी 2022 में ली थी। प्रतीक्षा अवधि?",
                           lang="hi")
        self.assertEqual(hi_old["decision"], APPLIES_TO_OLDER_CONTRACT)
        self.assertIn("अपना पॉलिसी डॉक्यूमेंट देखें", hi_old["final_answer"])
        hg = self._ask("Waiting period kitna hai?", lang="hinglish")
        self.assertEqual(hg["decision"], DEPENDS_ON_SALE_DATE)
        self.assertIn("1 April 2024 se: maximum 36 months (Reg 7)",
                      hg["final_answer"])
        hg_old = self._ask("Maine policy 2021 mein li thi, waiting "
                           "period kitna hai?", lang="hinglish")
        self.assertEqual(hg_old["decision"], APPLIES_TO_OLDER_CONTRACT)
        self.assertIn("Apna policy document check karein",
                      hg_old["final_answer"])

    # --- fail closed unchanged ----------------------------------------

    def test_never_verified_and_refusals_unchanged(self):
        for sale in (None, "2019-05-05", "2025-05-05"):
            trace = self._ask(sale_date=sale)
            self.assertNotEqual(trace["decision"], VERIFIED, sale)
        fabricated = {"claims": [{
            "claim": "PED waiting period is 12 months",
            "source_file": AROGYA, "quote": "12 months waiting period"}]}
        for sale in (None, "2019-05-05"):
            trace = answer("PED waiting period?", lang="en",
                           proposer=fake_proposer(fabricated),
                           verifier=self._backend(), sale_date=sale)
            self.assertEqual(trace["decision"], REFUSED)
            self.assertEqual(trace["refusal_reason"],
                             REFUSAL_EVIDENCE_NOT_FOUND)

    def test_governing_insufficient_still_refuses_with_old_date(self):
        def backend(claim, quote, source_text):
            if quote == PED_QUOTE:
                return "not json"
            return json.dumps({"verdict": SUPPORTED, "reason": "48"})
        trace = answer("PED waiting period?", lang="en",
                       proposer=fake_proposer(self._draft()),
                       verifier=backend, sale_date="2020-01-01")
        self.assertEqual(trace["decision"], REFUSED)

    def test_savings_evidence_failure_refuses(self):
        try:
            import verify.pipeline as pipeline_mod
        except ImportError:
            import pipeline as pipeline_mod
        real = pipeline_mod.check_evidence

        def fake(source_file, quote, **kwargs):
            if quote == self.SAVINGS:
                return {"exists": True, "found": False,
                        "page_text_hash": None}
            return real(source_file, quote, **kwargs)
        with mock.patch.object(pipeline_mod, "check_evidence", fake):
            for sale in (None, "2020-01-01"):
                trace = self._ask(sale_date=sale)
                self.assertEqual(trace["decision"], REFUSED, sale)
                self.assertEqual(trace["refusal_reason"],
                                 REFUSAL_GOVERNING_INSUFFICIENT)
            # A current-rule sale does not need the savings clause.
            self.assertEqual(self._ask(sale_date="2025-01-01")
                             ["decision"], SUPERSEDED)

    def test_direct_regulation_question_unaffected(self):
        draft = {"claims": [{"claim": "PED max is 36 months",
                             "source_file": PRODUCTS, "quote": PED_QUOTE}]}
        trace = answer("What is the maximum PED waiting period under the "
                       "2024 product rules?", lang="en",
                       proposer=fake_proposer(draft),
                       verifier=fake_backend({"verdict": SUPPORTED,
                                              "reason": "ok"}))
        self.assertIsNone(trace["sale_date"])
        self.assertEqual(trace["decision"], VERIFIED)


class TestFix36DateParsing(unittest.TestCase):
    def setUp(self):
        try:
            from verify import saledate
        except ImportError:
            import saledate
        self.sd = saledate

    def _range(self, text):
        sale = self.sd.parse_text(text)
        return sale and (sale["earliest"].isoformat(),
                         sale["latest"].isoformat())

    def test_english(self):
        self.assertEqual(self._range("I bought it in 2021."),
                         ("2021-01-01", "2021-12-31"))
        self.assertEqual(self._range("purchased in March 2021"),
                         ("2021-03-01", "2021-03-31"))
        self.assertEqual(self._range("I took the policy on 15 March 2024"),
                         ("2024-03-15", "2024-03-15"))
        self.assertEqual(self._range("Policy taken in Feb 2023"),
                         ("2023-02-01", "2023-02-28"))

    def test_hinglish_and_hindi(self):
        self.assertEqual(self._range("Maine policy 2025 mein li thi"),
                         ("2025-01-01", "2025-12-31"))
        self.assertEqual(self._range("March 2021 mein kharidi"),
                         ("2021-03-01", "2021-03-31"))
        self.assertEqual(self._range("मैंने पॉलिसी 2022 में ली थी"),
                         ("2022-01-01", "2022-12-31"))
        self.assertEqual(self._range("पॉलिसी २०२० में खरीदी"),
                         ("2020-01-01", "2020-12-31"))

    def test_no_purchase_word_is_not_a_sale_date(self):
        for text in ("What is the max PED under the 2024 product rules?",
                     "What changed since 2021?", "IRDAI 2024 regulations",
                     "", None):
            self.assertIsNone(self.sd.parse_text(text), text)

    def test_explicit_iso(self):
        sale, err = self.sd.resolve("2023-03-31")
        self.assertIsNone(err)
        self.assertEqual(sale["precision"], "day")
        for bad in ("31/03/2023", "2023-3-31", "yesterday", "2023-02-30"):
            sale, err = self.sd.resolve(bad)
            self.assertIsNone(sale, bad)
            self.assertTrue(err, bad)

    def test_classify(self):
        c = self.sd.classify
        r = self.sd.resolve
        self.assertEqual(c(r("2024-04-01")[0], "2024-04-01"), "current")
        self.assertEqual(c(r("2024-03-31")[0], "2024-04-01"), "older")
        self.assertEqual(c(None, "2024-04-01"), "unknown")
        self.assertEqual(c(self.sd.parse_text("bought in 2024"),
                           "2024-04-01"), "unknown")
        self.assertEqual(c(self.sd.parse_text("bought in March 2024"),
                           "2024-04-01"), "older")
        self.assertEqual(c(self.sd.parse_text("bought in April 2024"),
                           "2024-04-01"), "current")


class TestFix36DemoSaleDate(unittest.TestCase):
    def _demo(self):
        try:
            from verify import demo
        except ImportError:
            import demo
        return demo

    def test_sale_date_flag_reaches_answer_and_is_shown(self):
        demo = self._demo()
        trace = {"question": "Q", "decision": "APPLIES_TO_OLDER_CONTRACT",
                 "claims": [], "final_answer": "older contract",
                 "sale_date": {"earliest": "2021-06-15",
                               "latest": "2021-06-15",
                               "source": "explicit", "precision": "day",
                               "text": "2021-06-15"},
                 "savings": [{"citation": "Reg 9(3) cite",
                              "evidence": {"exists": True,
                                           "found": True}}]}
        stream = io.StringIO()
        with mock.patch("verify.pipeline.answer",
                        return_value=trace) as ans:
            code = demo.main(["--sale-date", "2021-06-15", "PED?"],
                             stream=stream)
        self.assertEqual(code, 0)
        self.assertEqual(ans.call_args.kwargs["sale_date"], "2021-06-15")
        out = stream.getvalue()
        self.assertIn("FINAL DECISION: APPLIES_TO_OLDER_CONTRACT", out)
        self.assertIn("Sale date: 2021-06-15", out)
        self.assertIn("Savings clause: Reg 9(3) cite — evidence FOUND", out)

    def test_invalid_sale_date_is_usage_error(self):
        demo = self._demo()
        with mock.patch("verify.pipeline.answer") as ans, \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            code = demo.main(["--sale-date", "15/06/2021", "PED?"],
                             stream=io.StringIO())
        self.assertEqual(code, 2)
        ans.assert_not_called()


class TestFix37DirectGoverningCitation(unittest.TestCase):
    """Fix 37: sale-date check when a claim cites Reg 7 directly."""

    SAVINGS = TestFix36SaleDatePrecedence.SAVINGS

    def _ask(self, question, lang="en", **kwargs):
        draft = {"claims": [{"claim": "PED waiting period is at most "
                             "36 months", "source_file": PRODUCTS,
                             "quote": PED_QUOTE}]}
        return answer(question, lang=lang,
                      proposer=fake_proposer(draft),
                      verifier=fake_backend({"verdict": SUPPORTED,
                                             "reason": "ok"}), **kwargs)

    def test_2021_direct_citation_is_older_contract_en(self):
        trace = self._ask("I bought my policy in 2021. Max PED waiting "
                          "period?")
        self.assertEqual(trace["decision"], APPLIES_TO_OLDER_CONTRACT)
        msg = trace["final_answer"]
        self.assertTrue(msg.startswith(
            "The 36-month cap applies to contracts from 1 April 2024 "
            "(Reg 7); a policy bought in 2021 keeps its contract terms "
            "(Reg 9(3)) — check your policy document."), msg)
        self.assertIn(PED_QUOTE, msg)
        self.assertIn(self.SAVINGS, msg)
        kinds = {c["kind"]: c["evidence"]["found"]
                 for c in trace["savings"]}
        self.assertEqual(kinds, {"governing rule": True,
                                 "savings clause": True})

    def test_explicit_day_uses_on(self):
        trace = self._ask("Max PED waiting period?",
                          sale_date="2021-06-15")
        self.assertEqual(trace["decision"], APPLIES_TO_OLDER_CONTRACT)
        self.assertIn("a policy bought on 15 June 2021 keeps",
                      trace["final_answer"])

    def test_2021_direct_citation_hi_and_hinglish(self):
        hi = self._ask("मैंने पॉलिसी 2021 में ली थी। अधिकतम वेटिंग "
                       "पीरियड?", lang="hi")
        self.assertEqual(hi["decision"], APPLIES_TO_OLDER_CONTRACT)
        self.assertIn("36 महीने की अधिकतम सीमा 1 अप्रैल 2024 से",
                      hi["final_answer"])
        self.assertIn("अपना पॉलिसी डॉक्यूमेंट देखें", hi["final_answer"])
        hg = self._ask("Maine policy 2021 mein li thi, maximum waiting "
                       "period kitna hai?", lang="hinglish")
        self.assertEqual(hg["decision"], APPLIES_TO_OLDER_CONTRACT)
        self.assertIn("36 months ki maximum limit 1 April 2024 se",
                      hg["final_answer"])
        self.assertIn("apna policy document check karein",
                      hg["final_answer"])

    def test_2025_direct_citation_is_verified(self):
        for kwargs in ({"sale_date": "2025-01-10"}, {}):
            trace = self._ask("Maine policy 2025 mein li thi, waiting "
                              "period?", lang="hinglish", **kwargs)
            self.assertEqual(trace["decision"], VERIFIED, kwargs)

    def test_no_sale_date_direct_citation_unchanged(self):
        trace = self._ask("What is the maximum PED waiting period under "
                          "the 2024 product rules?")
        self.assertIsNone(trace["sale_date"])
        self.assertEqual(trace["decision"], VERIFIED)
        self.assertEqual(trace["savings"], [])

    def test_straddling_year_depends(self):
        trace = self._ask("I bought it in 2024. Max PED waiting period?")
        self.assertEqual(trace["decision"], DEPENDS_ON_SALE_DATE)
        self.assertIn("depends on the exact sale date",
                      trace["final_answer"])

    def test_unrelated_regulation_quote_not_date_checked(self):
        draft = {"claims": [{"claim": "Products regs are in force",
                             "source_file": PRODUCTS,
                             "quote": "These regulations may be called"}]}
        trace = answer("Policy bought in 2021: what are these rules?",
                       lang="en", proposer=fake_proposer(draft),
                       verifier=fake_backend({"verdict": SUPPORTED,
                                              "reason": "ok"}))
        self.assertNotEqual(trace["decision"], APPLIES_TO_OLDER_CONTRACT)

    def test_evidence_failure_refuses(self):
        try:
            import verify.pipeline as pipeline_mod
        except ImportError:
            import pipeline as pipeline_mod
        real = pipeline_mod.check_evidence
        for missing in (PED_QUOTE, self.SAVINGS):
            calls = {"n": 0}

            def fake(source_file, quote, _m=missing, **kwargs):
                # The claim's own (first) check of PED_QUOTE passes;
                # the Fix 37 re-check of the missing quote fails.
                if quote == _m:
                    calls["n"] += 1
                    if _m != PED_QUOTE or calls["n"] > 1:
                        return {"exists": True, "found": False,
                                "page_text_hash": None}
                return real(source_file, quote, **kwargs)
            with mock.patch.object(pipeline_mod, "check_evidence", fake):
                trace = self._ask("Max PED period?",
                                  sale_date="2021-01-01")
            self.assertEqual(trace["decision"], REFUSED, missing[:20])
            self.assertEqual(trace["refusal_reason"],
                             REFUSAL_GOVERNING_INSUFFICIENT)


class TestFix39ProgressEvents(unittest.TestCase):
    def test_answer_emits_stages_in_order(self):
        events = []
        trace = answer("PED?", lang="en",
                       proposer=fake_proposer({"claims": [{
                           "claim": "PED max 36 months",
                           "source_file": PRODUCTS, "quote": PED_QUOTE}]}),
                       verifier=fake_backend({"verdict": SUPPORTED,
                                              "reason": "ok"}),
                       progress=lambda k, d: events.append(k))
        self.assertEqual(trace["decision"], VERIFIED)
        self.assertEqual(events, ["draft", "evidence", "verify",
                                  "governing", "decision"])

    def test_answer_proposer_failure_stops_after_draft(self):
        events = []

        def broken(question, lang):
            raise RuntimeError("down")
        trace = answer("PED?", lang="en", proposer=broken,
                       verifier=fake_backend({"verdict": SUPPORTED,
                                              "reason": "ok"}),
                       progress=lambda k, d: events.append(k))
        self.assertEqual(trace["decision"], REFUSED)
        self.assertEqual(events, ["draft"])

    def test_broken_progress_callback_cannot_change_result(self):
        def bad(stage, detail):
            raise ValueError("display broke")
        kwargs = dict(proposer=fake_proposer({"claims": [{
            "claim": "PED max 36 months", "source_file": PRODUCTS,
            "quote": PED_QUOTE}]}), verifier=fake_backend(
                {"verdict": SUPPORTED, "reason": "ok"}))
        with_cb = answer("PED?", lang="en", progress=bad, **kwargs)
        without = answer("PED?", lang="en", **kwargs)
        self.assertEqual(with_cb["decision"], without["decision"])
        self.assertEqual(with_cb["final_answer"], without["final_answer"])

    def test_callcheck_emits_stages(self):
        try:
            from verify import callcheck as cc
        except ImportError:
            import callcheck as cc
        events = []
        backend = fake_backend({"verdict": CONTRADICTED, "reason": "no"})
        cc.check_call("IRDAI is calling about your bonus", lang="en",
                      verifier=backend,
                      progress=lambda k, d: events.append(k))
        self.assertEqual(events[0], "extract")
        self.assertEqual(events[1], "evidence")
        self.assertIn("verify", events)
        self.assertEqual(events[-1], "decision")


if __name__ == "__main__":
    unittest.main()
