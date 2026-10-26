# MIT License
# Copyright (c) 2026 Parvind — deterministic demo lookup.
"""Runnable demo for the deterministic Ask path.

Shows two frozen questions: the Hinglish moratorium question, then
the cosmetic-surgery question with its "unless" qualification.
Deterministic lookup only — no network, no API, no language model.
Run: python3 demo_ask.py
"""
import json

from ask import DISCLAIMER, ask

DEMO_QUESTIONS = (
    "Continuous cover ke kitne months baad health claim established "
    "fraud ke alawa contest nahi ho sakta?",
    "Kya Arogya Sanjeevani specimen appearance badalne ke liye "
    "cosmetic surgery cover karta hai?",
)


def build_demo():
    return {
        "disclaimer": DISCLAIMER,
        "results": [
            dict({"question": q}, **ask(q).to_dict())
            for q in DEMO_QUESTIONS
        ],
    }


if __name__ == "__main__":
    print(json.dumps(build_demo(), indent=2, ensure_ascii=False))
