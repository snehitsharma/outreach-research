# ============================================================
# schemas.py
# ============================================================

from pydantic import BaseModel, Field
from enum import Enum
import uuid




# ---------- Enums (instead of scattered Literals — reused everywhere, one source of truth) ----------



class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class VerifierStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FLAGGED = "flagged"

class RejectionReason(str, Enum):
    UNSUPPORTED = "unsupported"
    MISSING_EXPECTED = "missing_expected"
    LOW_RELEVANCE = "low_relevance"
    CONTRADICTED = "contradicted"

class ResolverDecision(str, Enum):
    KEEP = "keep"
    DISCARD = "discard"
    REPRIORITIZE = "reprioritize"

class Goal(str, Enum):
    SALES = "sales"
    JOB_SEARCH = "job_search"
    GENERAL = "general"


# ---------- Shared base — every sourced claim has these three things ----------

class SourcedItem(BaseModel):
    """Common shape for anything traced back to a scraped source."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    researcher_id: str
    src_link: str
    snippet: str
    confidence: Confidence


# ---------- Domain objects (inherit shared fields, add their own) ----------

class Finding(SourcedItem):
    claim: str
    verifier_status: VerifierStatus = VerifierStatus.PENDING

class Contact(SourcedItem):
    name: str
    role: str | None = None
    email: str | None = None
    phone: str | None = None

class Penalty(BaseModel):
    id: str                          # references a Finding.id or Contact.id
    claim: str
    src_link: str
    snippet: str
    rejection_reason: RejectionReason
    resolver_decision: ResolverDecision | None = None

class Report(BaseModel):
    summary: str
    findings_by_theme: dict[str, list[str]]
    contacts: list[Contact] = Field(default_factory=list)
    citations: list[Finding] = Field(default_factory=list)
    recommended_contact: Contact | None = None
    recommended_contact_reason: str | None = None


class DraftItem(BaseModel):
    kind: str  # "outreach" or "follow_up"
    subject: str | None = None
    body: str | None = None
    draft_text: str | None = None
    to_email: str | None = None
    gmail_draft_id: str | None = None
    gmail_message_id: str | None = None
    gmail_thread_id: str | None = None
    approved: bool | None = None
    sent: bool = False
    scheduled_for: str | None = None



# ---------- Input / config ----------

class JobInput(BaseModel):
    raw_query: str
    goal: Goal | None = None
    pitch_context: str | None = None   # what's being sold / applied for, etc.