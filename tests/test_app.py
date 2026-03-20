"""
Tests for Community Safety AI
Run: pytest tests/test_app.py -v
"""
import sys, os, json, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ══════════════════════════════════════════════════════════════════════════════
# 1. UNIT — SafetyCard model validation
# ══════════════════════════════════════════════════════════════════════════════

class TestSafetyCardModel:

    def _make_card(self, **overrides):
        from models import SafetyCard
        defaults = dict(
            category="Scam/Fraud", severity="High",
            summary="Test alert", action_steps=["Do X"],
            target_audience=["All Residents"], reasoning="Reason",
            is_noise=False, confidence=0.8,
        )
        return SafetyCard(**{**defaults, **overrides})

    def test_valid_card_is_created(self):
        card = self._make_card()
        assert card.category == "Scam/Fraud"
        assert card.id is not None          # auto-generated

    def test_confidence_exactly_zero_is_valid(self):
        card = self._make_card(confidence=0.0)
        assert card.confidence == 0.0

    def test_confidence_exactly_one_is_valid(self):
        card = self._make_card(confidence=1.0)
        assert card.confidence == 1.0

    def test_confidence_below_zero_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_card(confidence=-0.01)

    def test_confidence_above_one_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_card(confidence=1.01)

    def test_report_text_too_short_raises(self):
        from pydantic import ValidationError
        from models import ReportInput
        with pytest.raises(ValidationError):
            ReportInput(text="hi")          # < 10 chars

    def test_report_text_too_long_raises(self):
        from pydantic import ValidationError
        from models import ReportInput
        with pytest.raises(ValidationError):
            ReportInput(text="x" * 2001)    # > 2000 chars


# ══════════════════════════════════════════════════════════════════════════════
# 2. UNIT — Digest filter logic (the core Responsible-AI behaviour)
# ══════════════════════════════════════════════════════════════════════════════

THRESHOLD = 0.6


def passes_digest(is_noise: bool, confidence: float, threshold: float = THRESHOLD) -> bool:
    """Mirror of the filter expression in main.py — kept in sync manually."""
    return not is_noise and confidence >= threshold


class TestDigestFilter:

    # ── Happy-path ────────────────────────────────────────────────────────────

    def test_high_confidence_non_noise_passes(self):
        assert passes_digest(is_noise=False, confidence=0.9)

    def test_confidence_at_exact_threshold_passes(self):
        assert passes_digest(is_noise=False, confidence=0.6)

    # ── Exclusion cases ───────────────────────────────────────────────────────

    def test_low_confidence_is_excluded(self):
        """Core requirement: hallucinated / speculative alerts must not reach residents."""
        assert not passes_digest(is_noise=False, confidence=0.3)

    def test_confidence_just_below_threshold_is_excluded(self):
        assert not passes_digest(is_noise=False, confidence=0.59)

    def test_noise_is_excluded_regardless_of_confidence(self):
        """A high-confidence personal rant is still noise."""
        assert not passes_digest(is_noise=True, confidence=0.95)

    def test_noise_with_low_confidence_is_excluded(self):
        assert not passes_digest(is_noise=True, confidence=0.2)

    # ── Threshold tunability ──────────────────────────────────────────────────

    def test_stricter_threshold_excludes_more(self):
        assert not passes_digest(is_noise=False, confidence=0.6, threshold=0.7)

    def test_looser_threshold_allows_more(self):
        assert passes_digest(is_noise=False, confidence=0.55, threshold=0.5)

    # ── Demo scenarios (match the video walkthrough exactly) ─────────────────

    def test_demo_ambiguous_report_is_filtered(self):
        """
        Demo Step 2: 'I heard a weird noise, maybe a scam?' → AI gives 0.4
        Expected: digest is empty even though is_noise=False.
        """
        assert not passes_digest(is_noise=False, confidence=0.4), (
            "Ambiguous/speculative reports must not alert the community."
        )

    def test_demo_clear_scam_alert_is_shown(self):
        """
        Demo Step 4: 'Watch out for Refund scam in Whitefield' → AI gives 0.88
        Expected: card appears in digest.
        """
        assert passes_digest(is_noise=False, confidence=0.88), (
            "Specific, actionable alerts must reach residents."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. UNIT — AI Engine fallback behaviour
# ══════════════════════════════════════════════════════════════════════════════

class TestAIEngineFallback:

    def _call_fallback(self, text):
        from ai_engine import _fallback_card
        return _fallback_card(text, reason="test")

    def test_fallback_scam_keywords(self):
        card = self._call_fallback("Watch out for otp scam calls")
        assert card.category == "Scam/Fraud"
        assert card.severity == "High"

    def test_fallback_theft_keywords(self):
        card = self._call_fallback("There was a robbery near the park")
        assert card.category == "Theft"

    def test_fallback_fire_keywords(self):
        card = self._call_fallback("There is a fire in building 3")
        assert card.category == "Infrastructure"
        assert card.severity == "Critical"

    def test_fallback_unknown_is_suspicious_activity(self):
        card = self._call_fallback("Something strange is happening")
        assert card.category == "Suspicious Activity"

    def test_fallback_confidence_passes_digest_threshold(self):
        """Fallback must surface to residents even without the LLM."""
        card = self._call_fallback("Possible scam")
        assert card.confidence >= THRESHOLD

    def test_fallback_is_not_noise(self):
        card = self._call_fallback("Possible scam")
        assert card.is_noise is False

    def test_fallback_on_json_parse_error(self):
        """Bad JSON from the LLM must not crash the pipeline."""
        with patch("ai_engine.client") as mock_client:
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="not valid json {{"))]
            )
            from ai_engine import process_with_ai
            card = process_with_ai("Scam near bus stop", "Whitefield")
            # Should return a valid card, not raise
            assert card.confidence >= 0
            assert card.is_noise is False

    def test_fallback_on_api_exception(self):
        """Network/auth errors must not crash the pipeline."""
        with patch("ai_engine.client") as mock_client:
            mock_client.chat.completions.create.side_effect = Exception("API timeout")
            from ai_engine import process_with_ai
            card = process_with_ai("Theft on main road", "HSR Layout")
            assert card is not None


# ══════════════════════════════════════════════════════════════════════════════
# 4. INTEGRATION — API endpoints (mocked AI and DB)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _make_card(**kwargs):
    from models import SafetyCard
    defaults = dict(
        category="Scam/Fraud", severity="High",
        summary="Test", action_steps=["Step"],
        target_audience=["All"], reasoning="Reason",
        is_noise=False, confidence=0.85,
    )
    return SafetyCard(**{**defaults, **kwargs})


class TestAPIEndpoints:

    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @patch("main.process_with_ai", return_value=_make_card())
    @patch("main.db.save_card")
    def test_submit_report_returns_200(self, mock_save, mock_ai, client):
        r = client.post("/report", json={"text": "Refund scam active in Whitefield!", "location": "Whitefield"})
        assert r.status_code == 200
        assert r.json()["category"] == "Scam/Fraud"

    def test_submit_report_too_short_returns_422(self, client):
        r = client.post("/report", json={"text": "help"})
        assert r.status_code == 422

    def test_submit_report_too_long_returns_422(self, client):
        r = client.post("/report", json={"text": "x" * 2001})
        assert r.status_code == 422

    @patch("main.db.load_all")
    def test_digest_counts_are_correct(self, mock_load, client):
        mock_load.return_value = [
            _make_card(is_noise=False, confidence=0.9),   # ✅ active
            _make_card(is_noise=False, confidence=0.75),  # ✅ active
            _make_card(is_noise=False, confidence=0.3),   # ❌ low confidence
            _make_card(is_noise=True,  confidence=0.95),  # ❌ noise
            _make_card(is_noise=False, confidence=0.6),   # ✅ active (at boundary)
        ]
        r = client.get("/digest")
        assert r.status_code == 200
        body = r.json()
        assert body["active_alerts"] == 3
        assert body["filtered_noise"] == 1
        assert body["filtered_low_confidence"] == 1
        assert body["total_reports"] == 5

    @patch("main.db.load_all")
    def test_digest_respects_custom_threshold(self, mock_load, client):
        mock_load.return_value = [
            _make_card(confidence=0.65),
            _make_card(confidence=0.85),
        ]
        r = client.get("/digest?min_confidence=0.8")
        assert r.json()["active_alerts"] == 1   # only 0.85 passes

    @patch("main.db.load_all")
    def test_empty_digest_when_all_noise(self, mock_load, client):
        mock_load.return_value = [
            _make_card(is_noise=True, confidence=0.9),
            _make_card(is_noise=True, confidence=0.8),
        ]
        r = client.get("/digest")
        body = r.json()
        assert body["active_alerts"] == 0
        assert body["filtered_noise"] == 2

    @patch("main.db.load_all")
    def test_digest_sorted_critical_first(self, mock_load, client):
        mock_load.return_value = [
            _make_card(severity="Low",      confidence=0.9),
            _make_card(severity="Critical", confidence=0.75),
            _make_card(severity="High",     confidence=0.8),
        ]
        r = client.get("/digest")
        severities = [a["severity"] for a in r.json()["alerts"]]
        assert severities == ["Critical", "High", "Low"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    @patch("main.db.load_all", return_value=[])
    def test_empty_database_returns_valid_digest(self, mock_load, client):
        r = client.get("/digest")
        assert r.status_code == 200
        body = r.json()
        assert body["active_alerts"] == 0
        assert body["alerts"] == []

    @patch("main.db.load_all")
    def test_confidence_boundary_0_59_excluded(self, mock_load, client):
        mock_load.return_value = [_make_card(confidence=0.59)]
        r = client.get("/digest")
        assert r.json()["active_alerts"] == 0

    @patch("main.db.load_all")
    def test_confidence_boundary_0_60_included(self, mock_load, client):
        mock_load.return_value = [_make_card(confidence=0.60)]
        r = client.get("/digest")
        assert r.json()["active_alerts"] == 1

    def test_digest_threshold_above_1_rejected(self, client):
        r = client.get("/digest?min_confidence=1.5")
        assert r.status_code == 422

    def test_digest_threshold_below_0_rejected(self, client):
        r = client.get("/digest?min_confidence=-0.1")
        assert r.status_code == 422

    @patch("main.process_with_ai", return_value=_make_card())
    @patch("main.db.save_card")
    def test_report_location_is_optional(self, mock_save, mock_ai, client):
        """Location field should default gracefully when omitted."""
        r = client.post("/report", json={"text": "Suspicious person near park gate"})
        assert r.status_code == 200

    @patch("main.process_with_ai", return_value=_make_card())
    @patch("main.db.save_card")
    def test_report_text_at_min_boundary(self, mock_save, mock_ai, client):
        r = client.post("/report", json={"text": "x" * 10})
        assert r.status_code == 200

    @patch("main.process_with_ai", return_value=_make_card())
    @patch("main.db.save_card")
    def test_report_text_at_max_boundary(self, mock_save, mock_ai, client):
        r = client.post("/report", json={"text": "x" * 2000})
        assert r.status_code == 200
