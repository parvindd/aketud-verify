# Aketud Verify — insurance answers that prove themselves, or refuse

**Meta Global AI Developer Hackathon 2026 · Startup track · Build for Your World**

India has over a million insurance intermediaries — agents, POSPs, small brokers — answering policyholders in Hindi, Hinglish and English, often from memory or an outdated brochure. Policyholders meanwhile get calls from fake "agents" and fake "IRDAI officers" demanding revival fees through payment links.

Aketud Verify answers insurance questions and checks suspicious calls **only from official documents**. Every claim is quoted, the quote is checked against the source PDF, an independent model verifies it, and a newer regulation overrides an older document. Anything not proven is refused. **Fail closed.**

## What happens to every answer

1. **Muse Spark** (Meta Model API, `muse-spark-1.3`) drafts claims, each with a source file and a verbatim quote.
2. **Evidence check (deterministic):** the source must exist and the quote must appear in its extracted text. No model can override this.
3. **Independent verifier — Muse Spark Open** (open weights, `meta-models/Muse-Spark-Open-816B-A42B`, served on Modal): rates each claim SUPPORTED / CONTRADICTED / INSUFFICIENT_EVIDENCE against the quoted passage. Strict JSON; malformed output fails closed.
4. **Authority precedence:** if the cited document is superseded on that topic (e.g. a 2021 policy specimen vs the 2024 IRDAI regulation), the claim is re-verified against the governing rule.
5. **Decision:** VERIFIED · SUPERSEDED · CORRECTED · REFUSED — in the user's language.

For calls: **Muse Voice Transcribe** turns a Hindi/Hinglish recording into text, Muse Spark extracts the caller's claims, and each is checked against verified IRDAI rules. Rule verdicts cannot be overturned by a model. The tool never says whether a policy exists — only the insurer can — and always ends with safety advice.

## Demo cases

| | Input | Result |
|---|---|---|
| A | "Maximum pre-existing disease waiting period under the 2024 product rules?" | **VERIFIED** — 36 months, IRDAI (Insurance Products) Regulations 2024, Sch III Reg 7 |
| B | "Does Arogya Sanjeevani cover IVF in Dubai?" (Hindi) | **REFUSED** — nothing in the official documents supports an answer |
| C | "PED waiting period in Arogya Sanjeevani?" (English / Hindi / Hinglish) | **SUPERSEDED** — the specimen says 48 months; the 2024 regulation (in force 1 April 2024) caps it at 36 |
| D | Voice recording of a fake "IRDAI" revival call | Each claim flagged: IRDAI does not announce bonuses; revival period is 5 years (non-linked) / 3 years (linked), not "today"; revival is subject to insurer underwriting, not guaranteed; fee cannot be confirmed without product type |

```
python -m verify.demo "What is the maximum pre-existing disease waiting period under the 2024 product rules?"
python -m verify.demo --lang hi "क्या आरोग्य संजीवनी दुबई में आईवीएफ ट्रीटमेंट कवर करती है?"
python -m verify.demo "What is the pre-existing disease waiting period in the Arogya Sanjeevani policy?"
python -m verify.demo --call-audio call.wav --lang hinglish
python -m verify.demo --lang hinglish --call "<transcript>"
```

## What was built during the hackathon vs before

**Before (tag `baseline-pre-hackathon`, see [BASELINE.md](BASELINE.md)):** a deterministic, no-model lookup for six frozen questions, two synthetic health-readiness flags, and an NHCX/FHIR packager. No language model anywhere.

**During the hackathon (every commit after that tag, 26 Oct – 4 Nov 2026):** everything in `verify/` and `life-corpus/` — the evidence check, the Muse Spark proposer, the Muse Spark Open verifier, authority precedence, SUPERSEDED decisions, Hindi/Hinglish answers, the fake-call checker, Muse Voice Transcribe input, and their tests. `git log baseline-pre-hackathon..HEAD` lists it.

Code was written with **Muse Code**.

## Meta models used

| Model | Role |
|---|---|
| Muse Spark 1.3 (Model API) | Drafts claims; extracts a caller's claims from a transcript |
| Muse Spark Open (open weights, via Modal) | Independent verifier |
| Muse Voice Transcribe (Model API) | Hindi/Hinglish call recordings → text (language bias + keyword hints) |
| Muse Code | Coding agent used to build the project |

## Sources

Official documents only, listed in `health-corpus/SOURCES.csv` and `life-corpus/SOURCES.csv`. Rule text used for call checks is quoted, with paragraph references, in [life-corpus/CASE_D_RULES.md](life-corpus/CASE_D_RULES.md). The PDFs are third-party documents and are **not** redistributed here; download them from the listed URLs into `health-corpus/raw/` and `life-corpus/raw/`.

## Run it

```
python3 -m venv .venv && source .venv/bin/activate
pip install requests
brew install poppler          # pdftotext
cp .env.example .env          # fill in your own keys
python -m unittest discover -s verify -t .
```

`.env` needs `META_API_KEY`, `META_API_BASE_URL=https://api.meta.ai/v1`, `PROPOSER_MODEL=muse-spark-1.3`, and for the open-weights verifier `VERIFIER_BASE_URL`, `VERIFIER_API_KEY`, `VERIFIER_MODEL`. Without the `VERIFIER_*` values the verifier falls back to Muse Spark 1.3 and every trace says so.

## Limits — stated plainly

- Coverage is narrow: a handful of health rules and four life-insurance revival rules. Every rule was read from the source PDF before it was encoded.
- It does not know your policy. It cannot say whether a policy exists, is lapsing, or what you owe. Check only with your insurer's official channels or Bima Bharosa.
- Not legal or financial advice, and not a coverage decision. The insurer decides.
- The IRDAI spurious-call notice is quoted from a 2019 master circular; its status after IRDAI's 2024 consolidation has not been confirmed and it is shown with its date.
- Speech recognition output varies between runs.

## Licence

MIT for the code in this repository. Source documents belong to their issuers.
