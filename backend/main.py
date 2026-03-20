import logging
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from models import ReportInput, SafetyCard
from ai_engine import process_with_ai
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Community Safety AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Tuneable constant — single source of truth ──────────────────────────────────
CONFIDENCE_THRESHOLD = 0.6


@app.get("/health")
def health():
    return {"status": "ok", "confidence_threshold": CONFIDENCE_THRESHOLD}


@app.post("/report", response_model=SafetyCard)
def submit_report(report: ReportInput):
    """
    Accepts a community report, runs it through the AI pipeline, persists the
    resulting SafetyCard, and returns it to the caller.

    The card is stored regardless of confidence — the /digest endpoint decides
    what is community-visible. This separation keeps raw data auditable.
    """
    card = process_with_ai(text=report.text, location=report.location or "Unknown")
    card.source_text = report.text[:500]
    db.save_card(card)

    logger.info(
        "card saved id=%s category=%s severity=%s confidence=%.2f is_noise=%s",
        card.id, card.category, card.severity, card.confidence, card.is_noise,
    )
    return card


@app.get("/digest")
def get_digest(
    min_confidence: float = Query(
        default=CONFIDENCE_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to include in community digest.",
    )
):
    """
    Returns only community-safe alerts.

    Two-stage filter (Responsible AI):
      1. Exclude cards where is_noise=True  → removes personal rants / off-topic
      2. Exclude cards below min_confidence → prevents hallucinated alerts from
         reaching residents (precision over recall)

    All filtered cards remain in storage for admin audit via GET /all.
    """
    all_cards = db.load_all()

    active  = [c for c in all_cards if not c.is_noise and c.confidence >= min_confidence]
    noise   = [c for c in all_cards if c.is_noise]
    low_conf = [c for c in all_cards if not c.is_noise and c.confidence < min_confidence]

    # Critical-first, then descending confidence
    active.sort(key=lambda c: (_severity_rank(c.severity), c.confidence), reverse=True)

    logger.info(
        "digest served total=%d active=%d noise=%d low_conf=%d threshold=%.2f",
        len(all_cards), len(active), len(noise), len(low_conf), min_confidence,
    )

    return {
        "threshold_used": min_confidence,
        "total_reports":  len(all_cards),
        "active_alerts":  len(active),
        "filtered_noise": len(noise),
        "filtered_low_confidence": len(low_conf),
        "alerts": active,
    }


@app.get("/all", response_model=list[SafetyCard])
def get_all():
    """Admin: every stored card, unfiltered, newest first."""
    return sorted(db.load_all(), key=lambda c: c.timestamp, reverse=True)


@app.delete("/clear")
def clear():
    """Admin: wipe the data store."""
    n = db.clear_all()
    return {"deleted": n}


def _severity_rank(severity: str) -> int:
    return {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}.get(severity, 0)
