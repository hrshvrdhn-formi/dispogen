# Script normalisation

You convert romanised Hindi in call transcripts into Devanagari. You are not
translating and not rewriting — the words, the register, the disfluencies and the
speaker's meaning stay exactly as they are. Only the script changes.

---

## What to convert

- **Romanised Hindi/Urdu → Devanagari.** `maine bank mein jama kar diya` becomes
  `मैंने बैंक में जमा कर दिया`.

## What to leave alone

- **Text already in Devanagari.** Do not re-spell it, do not "correct" it.
- **English words used as English**, which in this register is most technical and
  commercial vocabulary: policy, premium, branch, link, payment, receipt, agent,
  bank statement, due date, cheque, ECS, SIP, UPI, OTP, WhatsApp, email, SMS,
  network, call, confirm, cancel, update, status, portal, account.
  Indian speakers code-switch to English for these; forcing them into Devanagari
  produces text no call in this corpus contains.
- **Proper nouns in Latin script**, brand and product names, and place names that
  appear in Latin.
- **Numbers, dates, currency, policy numbers, phone numbers, email addresses.**
- **Production markers** such as `</interrupted>`, `<silence-detected/>`,
  `<end-call-silence-detection/>` — byte for byte.
- **The `speaker` field.** Only `text` changes.

The result should read like natural Hinglish as actually written: Devanagari for
the Hindi matrix, Latin for the English insertions.

## The constraint that matters

Each case carries `decisive_evidence`, and an FP case also carries a
`trap_phrase`. Each is a **verbatim substring** of one of that case's transcript
`text` values, and downstream validation checks that by exact string containment.

So when you convert a transcript turn, you must return the converted form of any
span drawn from it, **character for character as it now appears in the converted
turn**. Copy the span out of your own converted text rather than converting the
span separately — converting it twice independently is how the two drift apart
by a matra or a space and the case is rejected.

If a span is empty or null, return it unchanged.

## Output

Return **one JSON object and nothing else**. No prose, no markdown fence. Same
case ids, same order, same number of transcript turns per case:

```json
{
  "cases": [
    {
      "test_case_id": "<unchanged>",
      "transcript": [
        {"speaker": "agent", "text": "<converted>"},
        {"speaker": "customer", "text": "<converted>"}
      ],
      "decisive_evidence": "<converted, verbatim substring of a text above>",
      "trap_phrase": "<converted, verbatim substring of a text above, or null>"
    }
  ]
}
```

---

## Cases

```json
{{CASES}}
```
