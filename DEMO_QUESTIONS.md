# Frozen demo questions

Locked 20 Oct 2026. Validated 22 Oct 2026 against the public corpus in this repo. Do not wait on the unverified v2 set.

Each answer must cite a document that is in `health-corpus/raw/` or the claim-readiness design, and the figure must appear in that document. If it does not, refuse.

## Validation (22 Oct)

| # | Claim | In the corpus? | Usable citation |
|---|---|---|---|
| 1 | PED max 36 months | Yes. Products Regulations 2024, Schedule III, Regulation 7 (Gazette p. 37): “Waiting period for pre-existing diseases disclosed by the persons to be insured, shall be maximum up to 36 months of continuous coverage”. Master Circular PDF has no “36 months”; Arogya Sanjeevani specimen still says 48 months. | IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7. Do not cite the Master Circular for this figure. |
| 2 | Moratorium 60 months | Yes. Master Circular, para 13: “after the completion of the Moratorium Period, i.e. 60 months of continuous coverage”. | Master Circular on Health Insurance Business, 29 May 2024, para 13. |
| 3 | Initial 30 days, except accident | Yes, as a standard-product exclusion. Arogya Sanjeevani prospectus (specimen), Code-Excl03: “Expenses related to the treatment of any illness within 30 days… This waiting period is not applicable in case of accidents.” The 30 days in the Master Circular is free-look, not this. | Arogya Sanjeevani prospectus (specimen), Code-Excl03. Label it as the specimen, not as the Master Circular. |
| 4 | Cosmetic not covered | Yes, with the “unless” qualification. Arogya Sanjeevani prospectus (specimen) §4.5, Code-Excl08 (pp. 2–3): “Expenses for cosmetic or plastic surgery or any treatment to change appearance unless for reconstruction following an Accident, Burn(s) or Cancer or as part of medically necessary treatment to remove a direct and immediate health risk to the insured. For this to be considered a medical necessity, it must be certified by the attending Medical Practitioner.” | Arogya Sanjeevani prospectus (specimen), Code-Excl08. State the exclusion with its “unless” qualification. |
| 5 | PED flag | Design check. Rule verified in #1. | Flag only. Do not say “claim denied.” Cite IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7, and the policy wording. |
| 6 | Room-rent flag | Design check. Master Circular requires disclosure of room-rent limits. | Flag proportionate-deduction risk. Do not compute a payable. |

## Ask (cited or refuse)

1. **PED waiting period.**  
   EN: What is the maximum pre-existing disease waiting period under the 2024 product rules?  
   Expected: maximum up to 36 months of continuous coverage for pre-existing diseases disclosed by the persons to be insured. This is a cap, not a fixed period: insurers may have a lesser pre-existing disease waiting period, so a given policy does not necessarily have a 36-month waiting period. The norm does not apply to Overseas Travel Policies. Cite IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7 (Gazette of India, Extraordinary, Part III—Sec. 4, No. 206, 22 March 2024, p. 37; `health-corpus/raw/irdai-insurance-products-regulations-2024.pdf`). Do not cite the Master Circular for this figure.

2. **Moratorium.**  
   EN: After how many months of continuous cover can a health claim not be contested except for established fraud?  
   HI: लगातार कवर के कितने महीनों के बाद स्वास्थ्य दावा सिद्ध धोखाधड़ी के अलावा चुनौती नहीं दिया जा सकता?  
   Hinglish: Continuous cover ke kitne months baad health claim established fraud ke alawa contest nahi ho sakta?  
   Expected: 60 months. Cite Master Circular on Health Insurance Business, 29 May 2024, para 13.

3. **Initial waiting period.**  
   EN: In the Arogya Sanjeevani specimen, is there a waiting period for illness, and does it apply to accidents?  
   HI: आरोग्य संजीवनी नमूने में बीमारी के लिए प्रतीक्षा अवधि है क्या, और क्या यह दुर्घटना पर लागू होती है?  
   Hinglish: Arogya Sanjeevani specimen mein illness ke liye waiting period hai kya, aur kya yeh accident par lagti hai?  
   Expected: 30 days for illness, not for accident. Cite Arogya Sanjeevani prospectus (specimen), Code-Excl03. Name the specimen.

4. **Refusal.**  
   EN: Does the Arogya Sanjeevani specimen cover cosmetic surgery to change appearance?  
   HI: क्या आरोग्य संजीवनी नमूना दिखावा बदलने के लिए कॉस्मेटिक सर्जरी कवर करता है?  
   Hinglish: Kya Arogya Sanjeevani specimen appearance badalne ke liye cosmetic surgery cover karta hai?  
   Expected: not covered, unless for reconstruction following an Accident, Burn(s) or Cancer, or as part of medically necessary treatment to remove a direct and immediate health risk to the insured (certified by the attending Medical Practitioner). Cite Arogya Sanjeevani prospectus (specimen) §4.5, Code-Excl08. Do not invent a yes, and do not drop the “unless” qualification.

## Health flow (flags, not a decision)

5. **PED flag.** Synthetic: policy started 8 months ago, admission for a declared PED.  
   Expected flag: PED waiting period not completed. Cite IRDAI (Insurance Products) Regulations, 2024, Schedule III, Regulation 7 (disclosed PED waiting period maximum up to 36 months of continuous coverage; Overseas Travel Policies excepted), and the policy wording. Never say “claim denied.”

6. **Room-rent flag.** Synthetic: room category above the eligible limit.  
   Expected flag: proportionate deduction risk. Cite Master Circular 2024 disclosure norms. Never compute a final payable.

## Rules for the demo

- Cite the document name and the clause or rule.
- Same strength in all three languages.
- Never a coverage decision. Flags and citations only.
- If the quote does not contain the figure, do not state the figure.
