# Community Safety AI

Responsible AI pipeline that filters community safety reports using an LLM,
then applies a confidence threshold before surfacing alerts to residents.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # add GROQ_API_KEY (free at console.groq.com)
cd backend
uvicorn main:app --reload     # API docs at http://localhost:8000/docs
```

## Run Tests

```bash
pytest tests/ -v
```

---

## Architecture

```
POST /report
    │
    ▼
ai_engine.process_with_ai()
    │  LLM → SafetyCard JSON (category, severity, is_noise, confidence 0–1)
    │  On any failure → _fallback_card() (keyword rules, confidence=0.65)
    ▼
db.save_card()          ← stores ALL cards regardless of confidence
    │
    ▼
GET /digest  ← TWO-STAGE FILTER
    1. is_noise == False
    2. confidence >= 0.6 (tunable via ?min_confidence=)
    │
    ▼
Community-visible alerts only
```

Storing everything and filtering at read-time keeps raw data auditable via
`GET /all` without ever surfacing uncertain alerts to residents.

---

## Tradeoffs

**Precision vs. Recall**
The 0.6 confidence threshold prioritises precision. A borderline real alert may
occasionally be withheld (lower recall), but false alarms — which erode trust in
a safety tool — are minimised. The threshold is a single constant in `main.py`
and is exposed as a query parameter so operators can tune it without a deploy.

**Fallback confidence (0.65)**
The rule-based fallback is set above the 0.6 threshold intentionally: if the LLM
is offline, essential keyword-matched safety alerts still reach residents. The
value is deliberately below 0.7 so the card is distinguishable from high-quality
LLM output in the admin view.

**JSON file storage vs. a database**
A flat JSON file keeps the project runnable with zero dependencies. The tradeoff
is no concurrent write safety. Replacing `db.py` with SQLite or Postgres requires
changing only that one file.

**LLM temperature = 0.2**
Lower temperature reduces JSON parse failures and confidence inflation at the cost
of slightly less nuanced classification. Preferred here because pipeline reliability
outweighs marginal classification quality.

---

## Demo Script (video walkthrough)

1. Submit: `"I heard a weird noise, maybe a scam?"`
   - AI returns `confidence: ~0.4`
   - `/digest` is empty
   - *"The AI didn't label this noise, but 0.4 confidence is below 0.6 — it never
     reaches residents. We prevent alert fatigue."*

2. Submit: `"Watch out for Refund scam calls in Whitefield — my neighbour lost ₹40k."`
   - AI returns `confidence: ~0.88, severity: High`
   - Alert appears in `/digest`
   - *"Specific, actionable report → high confidence → published."*
