import os
import json
import logging
from groq import Groq
from models import SafetyCard

logger = logging.getLogger(__name__)

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = """
You are a Community Safety AI. Filter noise from genuine safety signals.

Return STRICT JSON only — no markdown, no extra text:
{
  "category": "Scam/Fraud | Theft | Infrastructure | Health | Suspicious Activity | Noise/Nuisance",
  "severity": "Critical | High | Medium | Low",
  "summary": "one sentence",
  "action_steps": ["2-4 concrete steps"],
  "target_audience": ["e.g. Seniors", "All Residents"],
  "reasoning": "1-2 sentences",
  "is_noise": true/false,
  "confidence": 0.0-1.0
}

Confidence rules (be honest — do not inflate):
  0.9-1.0  Specific, verifiable, actionable threat
  0.7-0.89 Credible but some ambiguity
  0.5-0.69 Vague or second-hand; needs corroboration
  0.0-0.49 Speculative, rumour, or unverifiable

is_noise = true for personal rants, off-topic complaints, or zero actionable value.
"""


def process_with_ai(text: str, location: str = "Unknown") -> SafetyCard:
    """
    Calls the LLM, validates the response, and returns a SafetyCard.
    Falls back to a rule-based card on any failure so the pipeline never
    hard-crashes on a bad API response.
    """
    prompt = f"Location: {location}\nReport: {text}\n\nReturn JSON only."
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.2,
            max_tokens=500,
        )
        raw = completion.choices[0].message.content.strip()

        # Strip accidental markdown fences some models add
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()

        data = json.loads(raw)
        data["source_text"] = text[:500]
        return SafetyCard(**data)

    except json.JSONDecodeError as exc:
        logger.warning("AI returned invalid JSON: %s", exc)
        return _fallback_card(text, reason=f"JSON parse error: {exc}")
    except Exception as exc:
        logger.error("AI engine error: %s", exc)
        return _fallback_card(text, reason=str(exc))


def _fallback_card(text: str, reason: str) -> SafetyCard:
    """
    Deterministic keyword-based fallback.
    Confidence is set to 0.65 — above the 0.6 digest threshold so the card
    still surfaces to residents, but below 0.7 to signal lower certainty.
    """
    t = text.lower()
    if any(k in t for k in ("scam", "fraud", "phishing", "otp", "refund")):
        category, severity = "Scam/Fraud", "High"
    elif any(k in t for k in ("theft", "stolen", "robbery", "break-in")):
        category, severity = "Theft", "High"
    elif any(k in t for k in ("fire", "flood", "accident", "injury")):
        category, severity = "Infrastructure", "Critical"
    else:
        category, severity = "Suspicious Activity", "Medium"

    return SafetyCard(
        category=category,
        severity=severity,
        summary="Alert captured by backup safety filter — AI temporarily offline.",
        action_steps=[
            "Verify via local news or neighbourhood group before sharing.",
            "Contact local authorities if you witness anything directly.",
        ],
        target_audience=["All Residents"],
        reasoning=f"AI offline — deterministic fallback triggered. Reason: {reason}",
        is_noise=False,
        confidence=0.65,
        source_text=text[:500],
    )
