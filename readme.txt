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

# Community Safety AI — Complete Walkthrough

## What This System Does

This is a **Responsible AI pipeline**. The core problem it solves:

> Community WhatsApp groups are flooded with both real safety alerts ("active scam in Whitefield") and noise ("the uncle upstairs plays loud music"). If you forward everything to residents, they stop trusting alerts. If you filter too aggressively, real threats get missed.

The system uses an LLM to classify reports, then applies a **confidence threshold** before anything reaches the community digest. Two questions are asked before every alert goes public:
1. Is this actually a safety concern? (`is_noise`)
2. Is the AI certain enough to act on it? (`confidence >= 0.6`)

---

## Step 0 — Prerequisites

**Get your free Groq API key:**
1. Go to [console.groq.com/keys](https://console.groq.com/keys)
2. Sign up and create a key
3. Create a file called `.env` inside your `backend/` folder:

```
GROQ_API_KEY=your_key_here
```

Then restart the server:
```powershell
$env:GROQ_API_KEY="your_key_here"
uvicorn main:app --reload
```

---

## Step 1 — Open the Docs UI

Go to:
```
http://127.0.0.1:8000/docs
```

This is **Swagger UI** — auto-generated from your FastAPI code. Every endpoint is listed here and you can run live requests directly from the browser. No Postman needed.

---

## Step 2 — Submit a Clear, High-Confidence Alert

Click **`POST /report`** → **Try it out** → paste this body:

```json
{
  "text": "Watch out for Refund Scam calls in Whitefield! Caller pretends to be HDFC, asks for OTP. My neighbour lost 40,000 rupees yesterday. Please warn seniors.",
  "location": "Whitefield"
}
```

Click **Execute**.

**What happens in the background:**

```
Your text
    │
    ▼
ai_engine.py sends it to Groq (LLaMA 3)
with a system prompt that says:
"Return JSON. Be honest about confidence.
 0.9+ = verified. 0.5-0.69 = vague. <0.5 = speculative."
    │
    ▼
LLM returns something like:
{
  "category": "Scam/Fraud",
  "severity": "High",
  "is_noise": false,
  "confidence": 0.88   ← specific details = high certainty
}
    │
    ▼
Pydantic validates it
(confidence must be between 0 and 1 — enforced at the model level)
    │
    ▼
Saved to data/digest.json regardless of confidence
(everything is stored for audit — filtering happens at read time)
```

**What to look for in the response:**
- `confidence` should be **0.75 or higher** — the report is specific, has a real loss amount, names a location
- `is_noise` should be **false**
- `severity` should be **High**

---

## Step 3 — Check the Community Digest

Click **`GET /digest`** → **Try it out** → **Execute**

**What happens in the background:**

```
Loads all stored cards
    │
    ▼
TWO-STAGE FILTER (this is the core Responsible AI logic):

  Stage 1: is_noise == false
           → removes personal rants, off-topic complaints
  
  Stage 2: confidence >= 0.6
           → removes hallucinated or speculative alerts
    │
    ▼
Remaining cards sorted: Critical first, then by confidence descending
    │
    ▼
Returns:
{
  "active_alerts": 1,
  "filtered_noise": 0,
  "filtered_low_confidence": 0,
  "alerts": [ your scam card ]
}
```

**Why 0.6 specifically?**
It's the tradeoff point between precision and recall. Below 0.6 the LLM is essentially guessing. Above 0.6 it has enough signal to be useful. The threshold is a single named constant in `main.py` — not a magic number buried in a filter expression — so it can be tuned without touching business logic.

---

## Step 4 — Submit a Noise Report

Click **`POST /report`** → **Try it out** → paste:

```json
{
  "text": "The uncle in flat 304 plays loud music every single night. Management does nothing. I pay 40k rent for this??",
  "location": "Apartment"
}
```

**What to look for in the response:**
- `is_noise` should be **true** — this is a personal complaint, not a community safety issue
- `confidence` may still be high (the AI is *certain* it's noise)

Now check **`GET /digest`** again.

**What you should see:**
```json
"active_alerts": 1,
"filtered_noise": 1
```

The scam alert is still there. The noise card is counted but never shown. This is the key behaviour — **even a high-confidence noise card never reaches residents** because the first filter stage catches it before confidence is even checked.

---

## Step 5 — Submit an Ambiguous, Low-Confidence Report

Click **`POST /report`** → **Try it out** → paste:

```json
{
  "text": "I think I heard something weird outside last night. Maybe a scam or someone suspicious? Not sure, could be nothing.",
  "location": "Unknown"
}
```

**What happens in the background:**

```
LLM reads this and sees:
  - No specific details
  - No location
  - No victim or loss
  - Pure speculation ("I think", "maybe", "not sure")

Returns:
{
  "is_noise": false,      ← it's technically safety-related
  "confidence": 0.35      ← but the AI is not certain enough
}
```

Now check **`GET /digest`** again.

**What you should see:**
```json
"active_alerts": 1,
"filtered_low_confidence": 1
```

The digest is unchanged. This is the critical insight: **the report wasn't labelled noise, but it still didn't reach residents** because confidence was below 0.6. This is what prevents AI hallucinations from causing alert fatigue.

---

## Step 6 — See Everything (Admin View)

Click **`GET /all`** → **Try it out** → **Execute**

This returns every stored card — noise, low confidence, and active — with no filtering. This is the audit trail. In a real deployment this endpoint would be behind authentication.

You should now see all 3 cards you submitted:
| Card | is_noise | confidence | Appears in /digest? |
|------|----------|------------|---------------------|
| Scam alert | false | ~0.88 | ✅ Yes |
| Loud music | true | ~0.85 | ❌ No — noise |
| Vague report | false | ~0.35 | ❌ No — low confidence |

---

## Step 7 — Test the Confidence Threshold Control

**`GET /digest`** accepts a `min_confidence` parameter. Try:

```
http://127.0.0.1:8000/digest?min_confidence=0.9
```

The scam alert may disappear if its confidence was 0.88. This shows that the threshold is tunable at runtime — an operator can tighten it during high alert-fatigue periods without changing any code.

Try the opposite:
```
http://127.0.0.1:8000/digest?min_confidence=0.3
```

The vague report now appears. This demonstrates the precision/recall tradeoff directly: lowering the threshold increases recall (more alerts surface) but reduces precision (some may be speculative).

---

## Step 8 — See What Happens Without a Groq API Key

Stop the server. Remove the API key. Restart and submit any report.

**What happens:**

```
Groq call fails with auth error
    │
    ▼
_fallback_card() is called in ai_engine.py
    │
    ▼
Keyword matching runs on your text:
  "scam/otp/fraud"     → category: Scam/Fraud, severity: High
  "theft/robbery"      → category: Theft, severity: High
  "fire/flood"         → category: Infrastructure, severity: Critical
  anything else        → category: Suspicious Activity, severity: Medium
    │
    ▼
Returns a card with confidence: 0.65
```

**Why 0.65?** It's intentionally above 0.6 so fallback cards still reach residents when the LLM is offline. It's below 0.7 so they're distinguishable from high-quality AI output in the admin view. The pipeline never hard-crashes — it degrades gracefully.

---

## What the Tests Verify

Run from the project root:
```powershell
pytest tests/ -v
```

The tests are grouped into 5 sections:

| Section | What it checks |
|---------|---------------|
| `TestSafetyCardModel` | Pydantic rejects confidence outside 0–1, text too short/long |
| `TestDigestFilter` | The filter logic in isolation — boundary cases like 0.59 vs 0.60 |
| `TestAIEngineFallback` | Keyword routing, fallback confidence, no crash on bad JSON or API failure |
| `TestAPIEndpoints` | Full request/response cycle with mocked AI and DB |
| `TestEdgeCases` | Empty DB, threshold query param validation, optional location field |

The filter logic tests are the most important — they prove that the 0.6 boundary behaves exactly as designed, that noise is excluded regardless of confidence, and that the two demo scenarios from the video produce the correct outcomes.


////////////////////
# Understanding the AI's Response Fields

## The Three Key Fields

When you submit a report, the AI returns a `SafetyCard`. Three fields tell you everything about how the system classified it and whether it will reach residents.

---

## `severity` — How Urgent Is the Threat?

Severity answers: **"How fast should residents act?"**

It is not about how upsetting the report is. It is about **imminence and impact**.

---

### 🔴 Critical
**Definition:** Immediate physical danger or active crime happening right now.

**Conditions that trigger Critical:**
- Someone is in danger at this moment
- An incident is actively unfolding, not already over
- Infrastructure failure that directly endangers lives (gas leak, building collapse, live electrical wire)
- Medical emergency affecting multiple people

**Example reports that should return Critical:**
```
"There is a fire on the 3rd floor of Prestige Tower right now, 
people are trapped"

"Armed robbery in progress at SBI ATM on Whitefield Main Road"

"Gas leak smell coming from the building basement, evacuate now"
```

**What it means for the digest:**
These cards are sorted to the very top, above all other alerts. In a real system, Critical cards would trigger push notifications.

**What it does NOT mean:**
A scam that happened yesterday is not Critical even if the loss was large. Critical requires the threat to be **active and present**.

---

### 🟠 High
**Definition:** Confirmed threat pattern with real harm already documented.

**Conditions that trigger High:**
- A scam with a named victim and specific loss amount
- Theft that has already occurred with details (location, time, method)
- A pattern reported by multiple people (recurring fraud call scheme)
- Infrastructure failure that is dangerous but not immediately life-threatening

**Example reports that should return High:**
```
"Watch out for Refund Scam calls — caller pretends to be HDFC, 
asks for OTP. My neighbour lost 40,000 rupees yesterday."

"Two-wheeler stolen from Brookfield Signal parking at 2am. 
Dark Honda Activa. Already filed FIR at Whitefield PS."

"Phishing SMS going around impersonating BESCOM asking for 
account update. Three residents in our building received it."
```

**What it means:**
The threat is real, documented, and actionable. Residents should be warned and can take specific steps. This is the most common severity level for genuine community alerts.

**Why your scam report returned High and not Critical:**
The incident already happened (past tense). The neighbour already lost the money. There is no active danger right now — the risk is that it happens to someone else. That is High, not Critical.

---

### 🟡 Medium
**Definition:** Suspicious or potentially risky situation without confirmed harm.

**Conditions that trigger Medium:**
- Something suspicious was observed but no crime has been confirmed
- A risk exists but residents have time to take precautions
- Single report with no corroboration yet

**Example reports that should return Medium:**
```
"Unfamiliar person has been photographing cars in our parking 
lot for the past two evenings around 7pm"

"Suspicious van parked outside the school gate for the last 
three days, different driver each time"

"Someone knocked on multiple doors in Block C claiming to be 
from the electricity department without an ID card"
```

**What it means:**
Worth alerting the community, but residents should observe and report rather than panic. The AI does not have enough to call it confirmed harm.

---

### ⚪ Low
**Definition:** General advisory with a safety angle but no immediate or confirmed risk.

**Conditions that trigger Low:**
- General awareness information ("it is festival season, be alert for pickpockets")
- Minor nuisance that has a safety dimension but is not threatening
- Precautionary advice with no specific incident

**Example reports that should return Low:**
```
"Reminder: street lights on the stretch between Metro station 
and our gate have been out for a week. Walk carefully at night."

"It is Diwali week. Keep pets indoors and be cautious with 
crackers near the dry grass behind Block D."
```

**What it means:**
Informational. Useful to surface but not urgent. These appear at the bottom of the digest.

---

## `is_noise` — Is This Even a Safety Issue?

`is_noise` answers: **"Should this ever reach the community digest at all?"**

This is a hard gate. If `is_noise` is `true`, the card never reaches residents regardless of how high the confidence is.

---

### `is_noise: false` — Safety-Relevant
The report has some connection to community safety, even if vague or unverifiable. It should proceed to the confidence check.

**Reports that return `is_noise: false`:**
- Any mention of crime, scam, fraud, suspicious behaviour
- Infrastructure issues with safety implications
- Health hazards
- Even vague reports like "I think I saw someone suspicious" — these are safety-adjacent even if uncertain

---

### `is_noise: true` — Not Safety-Relevant
The report has no actionable community safety value. The AI identifies it as a personal complaint, off-topic rant, or irrelevant content.

**Conditions that trigger `is_noise: true`:**

| Situation | Why it is noise |
|-----------|----------------|
| "The uncle in 304 plays loud music every night" | Personal dispute, no community safety angle |
| "The building lift has been slow for a week" | Maintenance complaint, not a safety threat |
| "Stray dogs near the gate again" | Recurring nuisance, not an incident |
| "Why doesn't management fix the potholes??" | Infrastructure complaint directed at management, not actionable safety alert |
| "Someone used my parking spot again" | Personal grievance |
| "Power cut for 3 hours today" | Utility issue with no safety dimension |

**The important edge case — high-confidence noise:**
If someone submits a very detailed, well-written complaint about loud music, the AI may give it a `confidence` of 0.9 because it is certain about its classification. The card is still excluded from the digest because `is_noise: true` is checked first, before confidence is ever evaluated. High certainty about something being noise does not make it safety-relevant.

---

## `confidence` — How Certain Is the AI?

`confidence` answers: **"How much does the AI trust its own classification?"**

This is where the Responsible AI layer lives. The AI is explicitly instructed in the system prompt to be honest about its uncertainty and not inflate scores.

---

### 0.9 – 1.0 → Verified
**What it means:** The report contains specific, corroborating details. The AI has very high certainty this is a real, classifiable safety event.

**What makes a report score this high:**
- Named location (specific street, building, landmark)
- Specific time or date
- Named victim or documented loss (amount, item)
- Known fraud pattern the AI recognises
- Multiple corroborating details in a single report

**Example:**
```
"Refund Scam call at 11am today. Caller said HDFC, asked for 
OTP. My mother in Block A lost ₹40,000. Same number: 9876XXXXXX"
```
Multiple anchors: time, bank name, method, victim, amount, number. Confidence: ~0.93

---

### 0.7 – 0.89 → Likely
**What it means:** The report is credible and actionable but has some ambiguity — missing a detail, second-hand, or unconfirmed.

**What keeps a report below 0.9:**
- Second-hand information ("my neighbour told me")
- Missing a key detail (no time, no specific location)
- Single data point with no corroboration
- Plausible but unverified claim

**Example:**
```
"Watch out for Refund Scam calls in Whitefield! My neighbour 
lost money yesterday. Please warn seniors."
```
Real incident, named area, but no specific amount, time, or phone number. Confidence: ~0.78

---

### 0.5 – 0.69 → Uncertain
**What it means:** The report is safety-adjacent but vague, second-hand, or emotionally driven. The AI does not have enough to be confident.

**What triggers this range:**
- No specific details at all
- Entirely second-hand ("someone told me that someone said")
- Emotionally written with few facts
- Could plausibly be misinterpreted

**Example:**
```
"Be careful out there. Heard there are scammers operating 
in our area. Stay safe everyone."
```
No details, no incident, no victim. Confidence: ~0.52

**What happens to this card:**
It passes `is_noise` (it is technically safety-adjacent) but fails the confidence threshold (0.52 < 0.6). It is stored in the database but never shown in the digest. This is exactly the behaviour you want — the system does not dismiss it entirely, but it does not alarm the community over a rumour.

---

### 0.0 – 0.49 → Speculative
**What it means:** The AI considers this report too uncertain, too vague, or too speculative to classify with any confidence. This often overlaps with noise but specifically captures cases where the AI is genuinely uncertain rather than certain it is irrelevant.

**What triggers this range:**
- Pure speculation ("I think maybe I heard something weird?")
- Self-contradicting report
- Joke or sarcastic report the AI cannot parse as serious
- Report in unclear language the AI cannot confidently interpret

**Example:**
```
"I think I heard a weird noise last night, maybe a scam or 
something? Not sure, could be wind. Be careful I guess?"
```
No incident, no location, no details, self-doubting language throughout. Confidence: ~0.35

---

## How All Three Fields Work Together

This table shows every combination and what happens:

| is_noise | confidence | Reaches Digest? | Why |
|----------|------------|-----------------|-----|
| false | 0.90 | ✅ Yes | Clear safety signal, AI is certain |
| false | 0.72 | ✅ Yes | Credible report, passes threshold |
| false | 0.60 | ✅ Yes | Exactly at boundary — included |
| false | 0.59 | ❌ No | Just below threshold — withheld |
| false | 0.35 | ❌ No | Too speculative — withheld |
| true | 0.95 | ❌ No | Noise blocked before confidence check |
| true | 0.20 | ❌ No | Noise blocked before confidence check |

The sequence always runs in this order:

```
Report submitted
      │
      ▼
is_noise == true?  ──── YES ──→  Blocked. Stored for audit only.
      │
      NO
      ▼
confidence >= 0.6? ──── NO  ──→  Withheld. Stored for audit only.
      │
      YES
      ▼
Published to community digest ✅
```

The two filters catch two completely different failure modes. `is_noise` catches things that should never be safety alerts. `confidence` catches things that might be safety alerts but where the AI does not have enough information to be sure. You need both because a low-confidence report is not the same as noise — it might be real, it just needs corroboration before it reaches residents.