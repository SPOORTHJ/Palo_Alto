# Design Documentation — Community Safety AI

---

## Problem Statement

Community messaging groups (WhatsApp, apartment apps) receive a constant mix
of genuine safety alerts and irrelevant noise — personal complaints, rumours,
and vague reports. Forwarding everything causes alert fatigue and erodes trust.
Filtering manually does not scale.

The system needed to answer two questions automatically for every report:
1. Is this actually a safety concern?
2. Is the AI certain enough to act on it?

---

## System Design

### Architecture Overview

```
POST /report
     │
     ▼
ReportInput schema validation (Pydantic)
     │  Rejects: text < 10 chars, > 2000 chars
     ▼
ai_engine.process_with_ai()
     │  Sends report to LLM with structured system prompt
     │  LLM returns JSON: category, severity, is_noise, confidence
     │
     ├── On success  → SafetyCard schema validation
     ├── On bad JSON → _fallback_card() (keyword rules, confidence 0.65)
     └── On API fail → _fallback_card() (keyword rules, confidence 0.65)
     │
     ▼
db.save_card()
     │  ALL cards stored regardless of quality (audit trail)
     ▼
     ├── GET /all    → unfiltered (admin/audit view)
     └── GET /digest → TWO-STAGE FILTER
                         1. is_noise == false
                         2. confidence >= threshold (default 0.6)
                       Sorted: Critical first, then confidence descending
```

### Two-Stage Filter — The Core Design Decision

The digest filter applies two independent checks in sequence:

**Stage 1 — Noise gate (`is_noise`)**
Catches reports that have no community safety value regardless of how
confidently the AI classified them. A high-confidence personal complaint
is still a personal complaint.

**Stage 2 — Confidence gate (`confidence >= 0.6`)**
Catches reports that are safety-adjacent but too vague or speculative
for the AI to act on. Prevents hallucinated or ambiguous alerts from
reaching residents.

Both stages are necessary because they catch different failure modes:
- A noise card can have high confidence (the AI is certain it is irrelevant)
- A low-confidence card can have `is_noise: false` (it might be real, just unverifiable)

### Store Everything, Filter at Read Time

Cards are persisted regardless of confidence or noise status. Filtering
happens in `/digest` at read time, not at write time. This means:
- The threshold can be changed without touching stored data
- Nothing is permanently discarded
- The full audit trail is always available via `/all`
- A card withheld today at 0.6 surfaces if the threshold is lowered to 0.5

---

## Tech Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| API framework | FastAPI | Automatic schema validation, Swagger UI out of the box, async-ready |
| Data validation | Pydantic v2 | Field-level constraints enforced at runtime, not just type hints |
| LLM | Groq (LLaMA 3) | Free tier, low latency, sufficient JSON instruction-following |
| Storage | JSON flat file | Zero dependencies, easy to inspect, swap-out interface via db.py |
| Testing | pytest + TestClient | Mocked AI and DB allow full pipeline testing without live API |

---

## Confidence Threshold — Why 0.6

The 0.6 threshold was chosen based on observed LLM output during testing:

| Range | What the LLM typically produces here |
|-------|--------------------------------------|
| 0.9 – 1.0 | Specific incident: named location, victim, loss amount, timeframe |
| 0.7 – 0.89 | Credible report missing one or two anchoring details |
| 0.6 – 0.69 | Vague but safety-adjacent; single data point |
| 0.5 – 0.59 | Speculative or second-hand; no verifiable details |
| 0.0 – 0.49 | Pure rumour or self-contradicting report |

0.6 is the point where reports below it consistently lacked enough detail
to produce actionable advice. This is not statistically calibrated — it is
a reasonable starting point that operators can tune via `?min_confidence=`.

---

## Fallback Design

When the LLM is unavailable (API down, model deprecated, network error),
`_fallback_card()` applies keyword matching:

```
"scam / fraud / otp / phishing / refund" → Scam/Fraud, High
"theft / stolen / robbery / break-in"    → Theft, High
"fire / flood / accident / injury"       → Infrastructure, Critical
anything else                            → Suspicious Activity, Medium
```

Fallback confidence is set to **0.65** — above the 0.6 threshold so
keyword-matched alerts still surface during an outage, but below 0.7 so
they are distinguishable from real AI output in the admin view.

The fallback never crashes. The pipeline degrades gracefully.

---

## Sample Dataset

`sample_dataset.json` contains 10 synthetic reports covering all
classification outcomes. No real personal data is used.

| ID | Category | Severity | is_noise | confidence | Reaches Digest |
|----|----------|----------|----------|------------|----------------|
| demo0001 | Scam/Fraud | High | false | 0.90 | ✅ Yes |
| demo0002 | Theft | High | false | 0.88 | ✅ Yes |
| demo0003 | Suspicious Activity | Medium | false | 0.75 | ✅ Yes |
| demo0004 | Scam/Fraud | High | false | 0.85 | ✅ Yes |
| demo0005 | Infrastructure | Critical | false | 0.95 | ✅ Yes |
| demo0006 | Noise/Nuisance | Low | **true** | 0.92 | ❌ Noise |
| demo0007 | Scam/Fraud | Low | false | **0.35** | ❌ Low confidence |
| demo0008 | Health | Medium | false | 0.78 | ✅ Yes |
| demo0009 | Suspicious Activity | Medium | false | 0.72 | ✅ Yes |
| demo0010 | Infrastructure | Low | false | 0.70 | ✅ Yes |

The dataset deliberately includes one noise card (demo0006) and one
low-confidence card (demo0007) to demonstrate both filter stages.

---

## Future Enhancements

### High Priority

**1. Deduplication**
If the same scam is reported ten times, ten cards appear in the digest.
The next version would cluster cards by semantic similarity and merge
them into a single alert with a `report_count` field. Multiple
independent reports of the same incident should also increase confidence
organically — corroboration is a strong signal.

**2. Human Review Queue**
Cards between confidence 0.4 and 0.6 are currently silently withheld.
A moderation UI would surface these for a human to approve or reject
before they reach residents. This closes the gap between "too uncertain
for AI" and "discarded entirely".

**3. Authentication**
`/all` and `/clear` are currently open endpoints. Production requires
JWT-based auth on admin routes and rate limiting on `/report` to prevent
flooding.

### Medium Priority

**4. Persistent Storage**
Replace the JSON flat file with SQLite. The storage interface is already
isolated to `db.py` — this is a contained change that adds concurrent
write safety and query capability without touching any other file.

**5. Confidence Calibration**
The 0.6 threshold was set by observation, not statistical calibration.
With enough labelled data, a calibration curve could validate whether
the model's self-reported confidence actually correlates with accuracy.

**6. Multilingual Support**
The system prompt and keyword fallback assume English. Whitefield has a
large population that communicates in Kannada, Hindi, and Hinglish.
Extending the system prompt and fallback keywords to handle these would
significantly improve coverage.

### Lower Priority

**7. Confidence Drift Monitoring**
Track how average confidence scores distribute over time. A sustained
drop in average confidence likely means the model is encountering
report types outside its training distribution, which is a signal to
update the system prompt.

**8. Push Notifications**
Critical-severity cards that pass the digest filter should trigger
immediate push notifications rather than waiting for residents to
poll the digest.

---

## Known Limitations

| Limitation | Impact | Mitigation in Current Version |
|------------|--------|-------------------------------|
| Fallback cards have fixed confidence 0.65 | A vague report and a specific report look identical during an outage | Reasoning field explicitly states "AI offline — fallback triggered" |
| No concurrent write safety | Simultaneous POST requests may lose one card | Acceptable for prototype; db.py interface makes SQLite swap straightforward |
| LLM confidence is self-reported | No external calibration | Threshold set conservatively at 0.6 based on observed output |
| No deduplication | Same incident reported ten times appears ten times | Scoped out for time; highest priority next feature |
| English only | Non-English reports misclassified or low confidence | System prompt could be extended; fallback keywords could be transliterated |
| Model deprecation | Groq retires models without long notice | MODEL is a single constant in ai_engine.py; easy to update |
