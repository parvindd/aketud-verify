# MIT License
# Copyright (c) 2026 Parvind — deterministic demo lookup tests.
"""Tests for ask.py. Stdlib unittest only.

Run: python3 -m unittest test_ask -v

Citation integrity is checked independently here: each test re-extracts
the cited PDF itself (pdftotext -raw, whitespace removed) and confirms
the returned quote's evidence segments appear in it. That check is not
shared with ask.py's matching code.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from ask import DISCLAIMER, ask

RAW = Path(__file__).resolve().parents[1] / "raw"

Q_PED = "What is the maximum pre-existing disease waiting period under the 2024 product rules?"
Q_MORATORIUM_EN = "After how many months of continuous cover can a health claim not be contested except for established fraud?"
Q_MORATORIUM_HINGLISH = "Continuous cover ke kitne months baad health claim established fraud ke alawa contest nahi ho sakta?"
Q_INITIAL_EN = "In the Arogya Sanjeevani specimen, is there a waiting period for illness, and does it apply to accidents?"
Q_COSMETIC_EN = "Does the Arogya Sanjeevani specimen cover cosmetic surgery to change appearance?"
Q_COSMETIC_HINGLISH = "Kya Arogya Sanjeevani specimen appearance badalne ke liye cosmetic surgery cover karta hai?"
Q_PED_FLAG = "Synthetic: policy started 8 months ago, admission for a declared PED."
Q_ROOM_FLAG = "Synthetic: room category above the eligible limit."

ALL_QUESTIONS = (
    Q_PED, Q_MORATORIUM_EN, Q_INITIAL_EN, Q_COSMETIC_EN,
    Q_PED_FLAG, Q_ROOM_FLAG,
)


def pdf_squashed(filename):
    out = subprocess.run(
        ["pdftotext", "-raw", str(RAW / filename), "-"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0
    return re.sub(r"\s+", "", out.stdout).lower()


class TestSixFrozenQuestions(unittest.TestCase):
    def test_ped_maximum_with_overseas_exception(self):
        r = ask(Q_PED)
        self.assertEqual(r.status, "answered")
        self.assertEqual(r.question_id, "ped_maximum")
        self.assertIn("36 months", r.answer)
        self.assertIn("Overseas Travel Policies", r.answer)
        self.assertIn("cap, not a fixed period", r.answer)
        self.assertIn("Schedule III, Regulation 7", r.citation)
        self.assertIn("p. 37", r.citation)
        self.assertIn("36 months", r.quote)

    def test_moratorium_60_months(self):
        for q in (Q_MORATORIUM_EN, Q_MORATORIUM_HINGLISH):
            r = ask(q)
            self.assertEqual(r.status, "answered", q)
            self.assertEqual(r.question_id, "moratorium")
            self.assertIn("60 months", r.answer)
            self.assertIn("established fraud", r.answer)
            self.assertIn("para 13", r.citation)
            self.assertIn("60 months", r.quote)

    def test_initial_waiting_period_accident_exception(self):
        r = ask(Q_INITIAL_EN)
        self.assertEqual(r.status, "answered")
        self.assertIn("30 days", r.answer)
        self.assertIn("accident", r.answer)
        self.assertIn("Code-Excl03", r.citation)
        self.assertIn("specimen", r.source_title)

    def test_cosmetic_exclusion_keeps_unless_qualification(self):
        for q in (Q_COSMETIC_EN, Q_COSMETIC_HINGLISH):
            r = ask(q)
            self.assertEqual(r.status, "answered", q)
            self.assertEqual(r.question_id, "cosmetic_exclusion")
            self.assertIn("Not covered", r.answer)
            self.assertIn("unless", r.answer)
            self.assertIn("Accident, Burn(s) or Cancer", r.answer)
            self.assertIn(
                "direct and immediate health risk", r.answer)
            self.assertIn("Medical Practitioner", r.answer)
            self.assertIn("Code-Excl08", r.citation)
            self.assertIn("unless", r.quote)

    def test_ped_flag_is_flag_only(self):
        r = ask(Q_PED_FLAG)
        self.assertEqual(r.status, "answered")
        self.assertIn("Flag:", r.answer)
        self.assertIn("not completed", r.answer)
        self.assertIn("policy wording", r.citation)
        blob = (r.answer + r.quote).lower()
        self.assertNotIn("claim denied", blob)
        self.assertNotIn("denied", blob)

    def test_room_rent_flag_no_payable(self):
        r = ask(Q_ROOM_FLAG)
        self.assertEqual(r.status, "answered")
        self.assertIn("Flag:", r.answer)
        self.assertIn("proportionate-deduction risk", r.answer)
        self.assertIn("no payable amount is computed", r.answer)
        self.assertIn("Customer Information Sheet", r.citation)

    def test_every_answer_has_title_citation_and_quote(self):
        for q in ALL_QUESTIONS:
            r = ask(q)
            self.assertEqual(r.status, "answered", q)
            self.assertTrue(r.source_title, q)
            self.assertTrue(r.citation, q)
            self.assertTrue(r.quote, q)


class TestCitationIntegrity(unittest.TestCase):
    # Evidence segments of each returned quote, stated independently
    # of ask.py's probe list. For the cosmetic quote the PDF splits
    # the sentence across pp. 2-3, so it is checked in two segments.
    SEGMENTS = {
        "ped_maximum": (
            "irdai-insurance-products-regulations-2024.pdf",
            ("maximum up to 36 months of continuous coverage",
             "shall not be applicable for Overseas Travel Policies"),
        ),
        "moratorium": (
            "master-circular-health-2024.pdf",
            ("Moratorium Period, i.e. 60 months of continuous coverage",),
        ),
        "initial_waiting_period": (
            "arogya-sanjeevani-specimen.pdf",
            ("within 30 days from the first policy commencement date",),
        ),
        "cosmetic_exclusion": (
            "arogya-sanjeevani-specimen.pdf",
            ("unless for reconstruction following an Accident, Burn(s) or",
             "direct and immediate health risk to the insured"),
        ),
        "ped_flag": (
            "irdai-insurance-products-regulations-2024.pdf",
            ("maximum up to 36 months of continuous coverage",),
        ),
        "room_rent_flag": (
            "master-circular-health-2024.pdf",
            ("sub-limits (a pre-defined limit above which insurance "
             "company will not pay)",),
        ),
    }

    def test_quotes_found_verbatim_in_cited_pdfs(self):
        questions = {
            "ped_maximum": Q_PED, "moratorium": Q_MORATORIUM_EN,
            "initial_waiting_period": Q_INITIAL_EN,
            "cosmetic_exclusion": Q_COSMETIC_EN,
            "ped_flag": Q_PED_FLAG, "room_rent_flag": Q_ROOM_FLAG,
        }
        texts = {}
        for qid, question in questions.items():
            filename, segments = self.SEGMENTS[qid]
            if filename not in texts:
                texts[filename] = pdf_squashed(filename)
            r = ask(question)
            self.assertEqual(r.status, "answered", qid)
            for segment in segments:
                self.assertIn(
                    re.sub(r"\s+", "", segment).lower(),
                    texts[filename], qid + ": " + segment,
                )
                # The displayed quote itself carries the key figure.
            self.assertTrue(r.quote)


class TestRefusal(unittest.TestCase):
    def refused(self, q):
        r = ask(q)
        self.assertEqual(r.status, "refused", repr(q))
        self.assertIsNone(r.answer)
        self.assertIsNone(r.citation)
        self.assertIsNone(r.quote)
        self.assertIn("Refused", r.reason)
        return r

    def test_unsupported_questions(self):
        self.refused("What is the capital of France?")
        self.refused("Will my claim be approved?")
        self.refused("How much will the insurer pay for my surgery?")
        self.refused("What is the waiting period for maternity cover?")

    def test_resembling_question_is_not_answered(self):
        # Same topic as a frozen question, different wording: refuse,
        # never infer.
        r = self.refused(
            "What is the maximum PED waiting period in months?")
        self.assertIn("ambiguous", r.reason)
        r = self.refused("Is cosmetic surgery covered?")
        self.assertIn("ambiguous", r.reason)
        r = self.refused("Tell me about the moratorium period.")
        self.assertIn("ambiguous", r.reason)

    def test_ambiguous_multi_topic_and_fragment(self):
        r = self.refused(
            "Does cosmetic surgery after an accident get covered "
            "under the moratorium?")
        self.assertIn("ambiguous", r.reason)
        self.refused("waiting period?")
        self.refused("60 months")
        self.refused("")

    def test_empty_and_none(self):
        self.assertEqual(ask("").status, "refused")
        self.assertEqual(ask("   ").status, "refused")
        self.assertEqual(ask(None).status, "refused")


class TestMissingEvidence(unittest.TestCase):
    def test_missing_source_pdf_gives_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = ask(Q_MORATORIUM_EN, raw_dir=Path(tmp))
        self.assertEqual(r.status, "needs_review")
        self.assertIsNone(r.answer)
        self.assertIsNone(r.citation)
        self.assertIsNone(r.quote)
        self.assertIn("unavailable", r.reason)

    def test_source_without_passage_gives_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "master-circular-health-2024.pdf").write_bytes(
                b"not a real pdf")
            r = ask(Q_MORATORIUM_EN, raw_dir=Path(tmp))
        self.assertEqual(r.status, "needs_review")
        self.assertIsNone(r.answer)


class TestRepeatability(unittest.TestCase):
    def test_repeated_calls_are_equal(self):
        for q in ALL_QUESTIONS + ("Will my claim be approved?", ""):
            self.assertEqual(ask(q), ask(q), repr(q))

    def test_inputs_not_mutated_and_result_shape(self):
        q = Q_COSMETIC_EN
        r = ask(q)
        self.assertEqual(q, Q_COSMETIC_EN)
        d = r.to_dict()
        self.assertEqual(
            set(d),
            {"status", "question_id", "answer", "source_title",
             "citation", "quote", "reason"},
        )
        self.assertIn("not a connected language model", DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
