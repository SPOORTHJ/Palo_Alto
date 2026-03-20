from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime, timezone
import uuid


class SafetyCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    category: str
    severity: str
    summary: str
    action_steps: List[str]
    target_audience: List[str]
    reasoning: str
    is_noise: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_text: Optional[str] = None

    @field_validator("target_audience", "action_steps", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        """LLMs sometimes return a plain string instead of a list.
        Wrap it automatically so Pydantic validation never fails on this."""
        if isinstance(v, str):
            return [v]
        return v



class ReportInput(BaseModel):
    text: str = Field(..., min_length=10, max_length=2000)
    location: Optional[str] = "Unknown"
