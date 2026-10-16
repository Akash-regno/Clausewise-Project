"""
schemas.py — Inter-agent data contracts for the self-correcting contract audit system.

Design reference: Chapter 3, Sections 3.1.3 (claim schema), 3.2.4 (orchestration
state), 3.3.1/M1.5 (span metadata), 3.3.3.2 (agent I/O contracts).

WHY THIS FILE EXISTS AS A SEPARATE MODULE
-----------------------------------------
Section 3.2.7 specifies that "agent outputs are schema-validated before being
written to state, so that instructions embedded in an adversarially drafted
document cannot alter orchestration control flow." That is only enforceable if
validation is *mechanical* and happens at a single choke point. Every model
output in this system is parsed through a model defined here before it is
allowed to touch `AuditState`. A malformed claim is rejected by Pydantic, not by
a downstream agent noticing something is wrong.

Two schema properties are load-bearing and are enforced with validators rather
than left to prompt compliance:

  1. A `Claim` cannot exist without at least one `evidence_span_id`
     (Section 3.3.3.4: "A claim you cannot bind to supplied evidence must not be
     emitted"). This is enforced at the type level — an unbound claim is
     unrepresentable.
  2. A `Verdict` PASSes if and only if V1=ENTAILED AND V2=VALID AND V3=CORRECT
     (Section 3.1.3.2). The aggregation is computed, never supplied by the
     model, so the Critic cannot declare its own verdict by fiat.

Requires: pydantic>=2.0
"""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

# =============================================================================
# SECTION 0 — CONTROLLED VOCABULARIES
#
# These are Enums rather than bare strings because they are the operands of
# routing predicates. A typo in a routing string is a silent control-flow bug;
# a typo in an Enum member is an ImportError at startup.
# =============================================================================


class ContractType(str, Enum):
    """Contract taxonomy. Selects the clause-obligation checklist (Section 3.1.4)."""

    NDA = "NDA"
    MSA = "MSA"
    SOW = "SOW"
    EMPLOYMENT = "EMPLOYMENT"
    LEASE = "LEASE"
    VENDOR = "VENDOR"


class ClaimType(str, Enum):
    """
    Section 3.1.3.1. The taxonomy exists because each class requires a
    different verification predicate, not for reporting convenience:

      DESCRIPTIVE — verified purely against the source document.
      NORMATIVE   — verified against the compliance corpus.
      COMPARATIVE — requires verification of BOTH contract- and standard-side.
      OMISSION    — verified by negative search (Section 3.1.4).
    """

    DESCRIPTIVE = "DESCRIPTIVE"
    NORMATIVE = "NORMATIVE"
    COMPARATIVE = "COMPARATIVE"
    OMISSION = "OMISSION"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"

    @property
    def rank(self) -> int:
        """Sort key for severity-ordered report composition (Table 3.3, stage 14)."""
        return {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFORMATIONAL": 3}[self.value]


class PartyRole(str, Enum):
    """
    Which party bears the consequence of the claim.

    This is a first-class field rather than free text because V3 (attribution
    correctness) verifies obligation *direction*, and Section 3.3.3.5 states
    that "an inverted obligation direction is a failure even where every other
    element is correct." Direction cannot be checked mechanically if it is
    buried in prose.
    """

    SERVICE_PROVIDER = "SERVICE_PROVIDER"
    CLIENT = "CLIENT"
    DISCLOSING_PARTY = "DISCLOSING_PARTY"
    RECEIVING_PARTY = "RECEIVING_PARTY"
    EMPLOYER = "EMPLOYER"
    EMPLOYEE = "EMPLOYEE"
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"
    BOTH = "BOTH"
    UNSPECIFIED = "UNSPECIFIED"


class RetrievalGrade(str, Enum):
    """Table 3.1. Drives the inner-loop routing predicate."""

    SUFFICIENT = "SUFFICIENT"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT = "INSUFFICIENT"


class ChunkType(str, Enum):
    """
    Parent-child chunking (Section 3.3.1/M1.4). Retrieval matches on
    CLAUSE_BODY (children) and returns CLAUSE_PARENT (whole clauses).
    """

    CLAUSE_BODY = "CLAUSE_BODY"
    CLAUSE_PARENT = "CLAUSE_PARENT"
    DEFINITION = "DEFINITION"
    PREAMBLE = "PREAMBLE"
    SCHEDULE = "SCHEDULE"


# --- Verification predicate outcomes (Section 3.1.3.2) -----------------------


class EntailmentVerdict(str, Enum):
    """V1 — groundedness. NEUTRAL is the *default on uncertainty*, not a soft pass."""

    ENTAILED = "ENTAILED"
    NEUTRAL = "NEUTRAL"
    CONTRADICTED = "CONTRADICTED"


class CitationVerdict(str, Enum):
    """V2 — citation validity. Deterministic; produced by code, never by a model."""

    VALID = "VALID"
    INVALID_SPAN_ID = "INVALID_SPAN_ID"      # span_id does not resolve
    OFFSET_MISMATCH = "OFFSET_MISMATCH"      # stored offsets do not match text
    TEXT_MISMATCH = "TEXT_MISMATCH"          # retrieved text != span identifier's text


class AttributionVerdict(str, Enum):
    """V3 — attribution correctness. Legally the most consequential predicate."""

    CORRECT = "CORRECT"
    WRONG_PARTY = "WRONG_PARTY"              # inverted obligation direction
    WRONG_MODALITY = "WRONG_MODALITY"        # must / may / must not confusion
    WRONG_QUANTITY = "WRONG_QUANTITY"        # caps, periods, percentages misstated
    MISSING_CONDITION = "MISSING_CONDITION"  # exception / proviso / carve-out ignored


class TerminalClaimState(str, Enum):
    """Table 3.2. Governs report disposition."""

    VERIFIED = "VERIFIED"
    UNVERIFIABLE = "UNVERIFIABLE"
    REJECTED = "REJECTED"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"


class CoverageState(str, Enum):
    """Section 3.1.4 — completeness verification states."""

    ADDRESSED = "ADDRESSED"
    PRESENT_BUT_UNANALYSED = "PRESENT_BUT_UNANALYSED"
    ABSENT = "ABSENT"


# =============================================================================
# SECTION 1 — RETRIEVAL LAYER CONTRACTS
# =============================================================================


class _Strict(BaseModel):
    """
    Base class: reject unknown fields.

    This matters more than it looks. `extra="forbid"` means a model that
    hallucinates an extra key — or a prompt-injected document that persuades an
    agent to emit an unexpected field — fails validation instead of silently
    writing unvalidated data into orchestration state (Section 3.2.7).
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False, validate_assignment=True)


class SpanMetadata(_Strict):
    """
    Metadata carried by every indexed vector (Section 3.3.1/M1.5).

    Section 3.3.1 is explicit that this metadata is not decorative:
      - `clause_path`, `defined_terms`, `cross_refs` are the operands of
        Level-2 corrective retrieval (structural scope expansion).
      - `page`, `char_start`, `char_end` are the operands of both evidence
        traceability (M4.3) and the deterministic V2 citation check.

    Every field here is therefore a functional dependency of a later module.
    """

    span_id: str = Field(pattern=r"^spn_[0-9a-f]{4,}$")
    document_id: str
    tenant_id: str
    clause_id: str
    clause_path: str = Field(description="Human-readable hierarchy, e.g. '9 > 9.2'")
    clause_title: str = ""
    parent_span_id: Optional[str] = None
    page: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    defined_terms: list[str] = Field(default_factory=list)
    cross_refs: list[str] = Field(default_factory=list)
    chunk_type: ChunkType = ChunkType.CLAUSE_BODY

    @field_validator("char_end")
    @classmethod
    def _end_after_start(cls, v: int, info: ValidationInfo) -> int:
        start = info.data.get("char_start")
        if start is not None and v <= start:
            raise ValueError(f"char_end ({v}) must exceed char_start ({start})")
        return v


class Span(_Strict):
    """A retrieved span: its text plus the metadata that makes it citable."""

    span_id: str
    text: str
    metadata: SpanMetadata
    score: Optional[float] = Field(default=None, description="Retrieval relevance score")


class AuditQuery(_Strict):
    """
    A checklist-derived audit query (Table 3.3, stage 8).

    `retrieval_level` is carried on the query itself rather than only in the
    state dict so that a query object is self-describing when logged — the
    ladder rung is the single most diagnostic field in a retrieval trace.
    """

    query_id: str
    checklist_item: str = Field(description="e.g. 'limitation_of_liability'")
    query_text: str
    contract_type: ContractType
    retrieval_level: int = Field(default=1, ge=1, le=4)
    reformulations: list[str] = Field(
        default_factory=list,
        description="Level-1 ladder history: synonym expansions and HyDE drafts.",
    )


class EvidenceBundle(_Strict):
    """
    Researcher output (Table 3.5).

    An empty `spans` list with grade INSUFFICIENT is a *valid and valuable*
    result, per Section 3.3.3.3: "An empty result is a correct and valuable
    outcome." The schema must not make honest emptiness harder to express than
    fabricated adequacy.
    """

    query_id: str
    spans: list[Span] = Field(default_factory=list)
    grade: RetrievalGrade = RetrievalGrade.INSUFFICIENT
    grade_rationale: str = ""
    retrieval_level_used: int = Field(default=1, ge=1, le=4)
    evidence_unavailable: bool = False
    reformulations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _empty_bundle_cannot_be_sufficient(self) -> "EvidenceBundle":
        """Guard against a grader approving a bundle containing nothing."""
        if self.grade == RetrievalGrade.SUFFICIENT and not self.spans:
            raise ValueError("A bundle with no spans cannot be graded SUFFICIENT")
        if self.evidence_unavailable and self.grade != RetrievalGrade.INSUFFICIENT:
            raise ValueError("evidence_unavailable requires grade INSUFFICIENT")
        return self

    @property
    def span_ids(self) -> set[str]:
        return {s.span_id for s in self.spans}


# =============================================================================
# SECTION 2 — THE CLAIM (Section 3.1.3.1)
# =============================================================================


class Claim(_Strict):
    """
    An atomic, independently verifiable, evidence-bound proposition.

    This is the central object of the system. The Auditor emits an array of
    these and *does not emit prose* (Section 3.1.3.1). Atomicity is what makes
    per-claim verification possible, and per-claim verification is what bounds
    correction cost to O(|failing claims|) via freezing (Section 3.1.3.4).
    """

    claim_id: str = Field(pattern=r"^clm_\d{3,}$", examples=["clm_014"])
    clause_id: str = Field(examples=["cls_09_2"])
    claim_type: ClaimType
    proposition: str = Field(
        min_length=10,
        description="Exactly one verifiable assertion. Multi-part findings are "
        "a contract violation, not a style preference.",
    )
    evidence_span_ids: list[str] = Field(min_length=1)
    reference_ids: list[str] = Field(
        default_factory=list,
        description="Compliance corpus identifiers. Required for NORMATIVE and "
        "COMPARATIVE claims — see validator below.",
    )
    severity: Severity
    party_affected: PartyRole
    rationale: str = ""

    # --- Loop bookkeeping. Not model-supplied; set by the orchestrator. ------
    iteration_created: int = Field(default=0, ge=0)
    terminal_state: Optional[TerminalClaimState] = None
    source_query_id: Optional[str] = None
    regeneration_count: int = Field(default=0, ge=0)

    @field_validator("evidence_span_ids")
    @classmethod
    def _spans_must_be_unique_and_wellformed(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("evidence_span_ids contains duplicates")
        for sid in v:
            if not sid.startswith("spn_"):
                raise ValueError(f"malformed span identifier: {sid!r}")
        return v

    @model_validator(mode="after")
    def _normative_claims_need_references(self) -> "Claim":
        """
        Section 3.3.3.4 prohibits the Auditor from citing statute absent from the
        supplied compliance references. A NORMATIVE or COMPARATIVE claim with no
        `reference_ids` is, by construction, drawing on parametric memory — the
        exact failure mode the prohibition targets. Reject it mechanically here
        rather than relying on the Critic to catch it downstream.
        """
        if self.claim_type in (ClaimType.NORMATIVE, ClaimType.COMPARATIVE):
            if not self.reference_ids:
                raise ValueError(
                    f"{self.claim_type.value} claim requires at least one "
                    "reference_id from the supplied compliance corpus"
                )
        return self

    def frozen_copy(self) -> "Claim":
        """Mark VERIFIED. Frozen claims exit the loop permanently (Alg. line 29)."""
        return self.model_copy(update={"terminal_state": TerminalClaimState.VERIFIED})


# =============================================================================
# SECTION 3 — VERIFICATION CONTRACTS (Sections 3.1.3.2, 3.3.3.5)
# =============================================================================


class Verdict(_Strict):
    """
    The outcome of applying V1/V2/V3 to a single claim.

    `passed` is a computed property, not a field. The Critic reports three
    independent predicate outcomes; the conjunction is evaluated in code. This
    prevents a model from returning `{"v1": "NEUTRAL", "passed": true}` — an
    inconsistency that would otherwise have to be caught by review.
    """

    claim_id: str
    v1_entailment: EntailmentVerdict
    v2_citation: CitationVerdict
    v3_attribution: AttributionVerdict
    v1_evidence_quote: str = Field(
        default="",
        description="The span text the Critic relied on. Kept for audit trail "
        "and for measuring the Critic itself (Section 3.3.3.5, Instrumentation).",
    )
    critic_latency_ms: float = 0.0
    iteration: int = Field(default=0, ge=0)

    @property
    def passed(self) -> bool:
        """PASS iff V1 = ENTAILED AND V2 = VALID AND V3 = CORRECT."""
        return (
            self.v1_entailment == EntailmentVerdict.ENTAILED
            and self.v2_citation == CitationVerdict.VALID
            and self.v3_attribution == AttributionVerdict.CORRECT
        )

    @property
    def is_contradicted(self) -> bool:
        """
        V1 = CONTRADICTED routes to REJECTED, not to re-retrieval (Table 3.2).
        Re-retrieving evidence for a proposition the document contradicts is
        wasted budget — the claim is wrong, not under-evidenced.
        """
        return self.v1_entailment == EntailmentVerdict.CONTRADICTED

    @property
    def failing_predicates(self) -> list[str]:
        out = []
        if self.v1_entailment != EntailmentVerdict.ENTAILED:
            out.append("V1")
        if self.v2_citation != CitationVerdict.VALID:
            out.append("V2")
        if self.v3_attribution != AttributionVerdict.CORRECT:
            out.append("V3")
        return out


class Critique(_Strict):
    """
    The structured, actionable directive accompanying a FAIL.

    Section 3.3.3.5, Design notes: "The requirement that the critique specify a
    *retrieval directive* rather than merely a verdict is what makes the
    corrective loop convergent rather than merely repetitive — the Researcher
    receives an instruction, not a complaint."

    `retrieval_directive` is therefore mandatory and non-empty. A critique
    without one is not a critique; it is a rejection with no actuator attached,
    and it would cause the loop to repeat identical retrieval.
    """

    claim_id: str
    failing_predicates: list[str] = Field(min_length=1)
    failure_description: str = Field(min_length=5)
    retrieval_directive: str = Field(
        min_length=10,
        description="Concrete next retrieval action, e.g. 'retrieve the clause "
        "referenced at the end of span spn_0912 — the exception was not fetched'.",
    )
    suggested_ladder_level: int = Field(ge=1, le=4)
    target_clause_ids: list[str] = Field(default_factory=list)
    target_defined_terms: list[str] = Field(default_factory=list)

    @field_validator("failure_description", mode="before")
    @classmethod
    def _sanitize_failure_description(cls, v: Any) -> str:
        s = str(v or "").strip()
        if not s or s.lower() in ("none", "null") or len(s) < 5:
            return "Verification check failed for this claim."
        return s

    @field_validator("retrieval_directive", mode="before")
    @classmethod
    def _sanitize_retrieval_directive(cls, v: Any) -> str:
        s = str(v or "").strip()
        if not s or s.lower() in ("none", "null") or len(s) < 10:
            return "Re-retrieve the clause and any cross-referenced provisions to resolve verification."
        return s


# =============================================================================
# SECTION 4 — COMPLETENESS AND REPORTING (Sections 3.1.4, 3.3.4)
# =============================================================================


class CoverageItem(_Strict):
    """One row of the clause-obligation checklist reconciliation."""

    checklist_item: str
    state: CoverageState
    supporting_claim_ids: list[str] = Field(default_factory=list)
    located_clause_ids: list[str] = Field(default_factory=list)
    note: str = ""


class TraceEvent(_Strict):
    """
    One entry in the audit trail.

    Objective 5 requires reporting convergence distributions and the
    cost-reliability trade-off. That is only possible if every node transition
    emits a structured event at the time it happens.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    node: str
    event: str
    iteration: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0


class AuditReport(_Strict):
    """
    Final composed output (Table 3.3, stage 14).

    The four claim collections are kept structurally separate rather than
    merged with a status flag. Section 3.3.4/M4.4 requires that verified
    findings, unverifiable items, and coverage gaps "are never interleaved in a
    single undifferentiated list" — enforcing that in the schema means the
    frontend cannot accidentally violate it.
    """

    job_id: str
    document_id: str
    tenant_id: str
    contract_type: ContractType
    findings: list[Claim] = Field(
        default_factory=list, description="VERIFIED only. The invariant of Section 3.1.5."
    )
    requires_human_review: list[Claim] = Field(
        default_factory=list, description="UNVERIFIABLE — surfaced as unconfirmed."
    )
    omissions: list[Claim] = Field(default_factory=list)
    coverage: list[CoverageItem] = Field(default_factory=list)
    uncovered_queries: list[str] = Field(default_factory=list)
    terminal_reason: str = ""
    iterations_used: int = 0
    token_usage: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _enforce_grounding_invariant(self) -> "AuditReport":
        """
        THE system invariant (Section 3.1.5): "no claim in state other than
        VERIFIED is ever presented to the user as a finding."

        This is checked here, at the last boundary before serialisation, because
        it is the one guarantee whose violation is invisible to the user and
        catastrophic to the project's central claim. If this raises in
        production, the correct response is to fail the job, not to degrade.
        """
        for c in self.findings:
            if c.terminal_state != TerminalClaimState.VERIFIED:
                raise ValueError(
                    f"INVARIANT VIOLATION: claim {c.claim_id} in state "
                    f"{c.terminal_state} present in findings"
                )
        return self

    def sorted_findings(self) -> list[Claim]:
        """Severity-ordered, stable within severity by claim_id."""
        return sorted(self.findings, key=lambda c: (c.severity.rank, c.claim_id))


# =============================================================================
# SECTION 5 — ORCHESTRATION STATE (Section 3.2.4)
# =============================================================================
#
# LangGraph merges the dict a node returns into the running state. For a plain
# key, the returned value REPLACES the current one. For a key annotated with a
# reducer, the returned value is COMBINED with the current one.
#
# Choosing per key is a correctness decision, not a style one:
#
#   REPLACE — pending_claims, draft_claims, evidence, verdicts, critiques,
#             iteration. These are recomputed wholesale each pass. Using an
#             additive reducer here would make `pending_claims` grow
#             monotonically and the loop would never terminate.
#
#   APPEND  — verified_claims, unverifiable_claims, rejected_claims,
#             audit_trail, failed_count_history. These accumulate and are never
#             revised. `verified_claims` in particular is the freezing
#             mechanism (Section 3.1.3.4): once a claim lands here it is never
#             re-verified or regenerated, which is what makes correction cost
#             O(|failing|) rather than O(|draft|).
#
# CONTRACT FOR NODE AUTHORS: a node returning an APPEND key must return only the
# DELTA, never the full list. Returning the full list double-counts. This is the
# single most common LangGraph bug and the reason it is documented here.
# =============================================================================


def merge_counters(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    """Reducer for token accounting: sum per-agent counts across nodes."""
    merged = dict(left)
    for key, value in right.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def merge_latest(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Reducer for keyed maps where the newest write for a key wins."""
    merged = dict(left)
    merged.update(right)
    return merged


class AuditState(TypedDict, total=False):
    """
    The single explicitly typed state object of the orchestration graph.

    Section 3.2.4: "Explicit typing is a deliberate reliability measure: it
    renders every inter-agent hand-off inspectable, serialisable, and
    independently testable, and it is the mechanism by which failure is
    attributable to a specific stage."

    `total=False` so that nodes may return partial updates, which is the normal
    LangGraph idiom.
    """

    # --- Immutable context ---------------------------------------------------
    job_id: str
    tenant_id: str
    document_id: str
    contract_type: ContractType
    namespace: str  # "{tenant_id}::{document_id}" — derived server-side (M2.4)

    # --- Retrieval state -----------------------------------------------------
    query_queue: list[AuditQuery]
    evidence: Annotated[dict[str, EvidenceBundle], merge_latest]  # query_id -> bundle
    retrieval_level: Annotated[dict[str, int], merge_latest]      # query_id -> rung 1..4
    uncovered_queries: Annotated[list[str], operator.add]

    # --- Generation state ----------------------------------------------------
    draft_claims: list[Claim]
    verified_claims: Annotated[list[Claim], operator.add]      # FROZEN. Append only.
    pending_claims: list[Claim]                                # The failing subset.
    unverifiable_claims: Annotated[list[Claim], operator.add]
    rejected_claims: Annotated[list[Claim], operator.add]

    # --- Verification state --------------------------------------------------
    verdicts: Annotated[dict[str, Verdict], merge_latest]
    critiques: Annotated[dict[str, Critique], merge_latest]

    # --- Completeness --------------------------------------------------------
    coverage: list[CoverageItem]

    # --- Loop control (Section 3.1.5) ---------------------------------------
    iteration: int
    failed_count_history: Annotated[list[int], operator.add]
    terminal_reason: Optional[str]

    # --- Observability (Objective 5) ----------------------------------------
    token_usage: Annotated[dict[str, int], merge_counters]
    stage_latencies: Annotated[dict[str, float], merge_latest]
    audit_trail: Annotated[list[TraceEvent], operator.add]


# --- Loop configuration ------------------------------------------------------

N_MAX: int = 2
"""
Hard iteration bound (Section 3.1.5, guarantee 1). Section 3.1.5 states this is
"a configuration parameter to be tuned empirically against the convergence
distribution measured under Objective 5" — so it is a module constant with a
single definition site, not a literal scattered through the routing code.
"""


def new_audit_state(
    *,
    job_id: str,
    tenant_id: str,
    document_id: str,
    contract_type: ContractType,
) -> AuditState:
    """
    Construct a fully initialised state.

    Every collection is initialised, so no node ever needs `state.get(k, [])`.
    Defensive `.get()` calls hide missing-key bugs; explicit initialisation
    surfaces them as KeyError at the point of the mistake.

    The namespace is derived here, server-side, from the tenant and document
    identifiers — never from client input (Sections 3.2.7 and 3.3.2/M2.4).
    """
    return AuditState(
        job_id=job_id,
        tenant_id=tenant_id,
        document_id=document_id,
        contract_type=contract_type,
        namespace=f"{tenant_id}::{document_id}",
        query_queue=[],
        evidence={},
        retrieval_level={},
        uncovered_queries=[],
        draft_claims=[],
        verified_claims=[],
        pending_claims=[],
        unverifiable_claims=[],
        rejected_claims=[],
        verdicts={},
        critiques={},
        coverage=[],
        iteration=0,
        failed_count_history=[],
        terminal_reason=None,
        token_usage={},
        stage_latencies={},
        audit_trail=[],
    )


# =============================================================================
# SECTION 6 — ROUTING PREDICATE (Section 3.2.5)
#
# Placed here, beside the state it reads, so that the termination argument can
# be checked against the state definition without opening another file.
# =============================================================================


def exhausted_ladder(claim: Claim, critiques: dict[str, Critique]) -> bool:
    """A claim whose corrective ladder has reached Level 4 has no action left."""
    critique = critiques.get(claim.claim_id)
    return critique is None or critique.suggested_ladder_level >= 4


def route_after_critic(state: AuditState) -> Literal["researcher", "composer"]:
    """
    The outer-loop routing predicate (Section 3.2.5).

    TERMINATION ARGUMENT. Every path reaches "composer" in bounded time:
      (a) `pending_claims` empty              -> converged;
      (b) `iteration >= N_MAX`                -> hard bound, guarantee 1;
      (c) failing count did not decrease      -> monotonic-progress, guarantee 2;
      (d) every failing claim at Level 4      -> evidence exhaustion, guarantee 3.
    Only when all four are false does the loop continue, and each continuation
    increments `iteration`, so (b) is reached in at most N_MAX passes.

    There is no input for which this function fails to reach "composer".
    """
    failed = state["pending_claims"]

    if not failed:
        return "composer"  # converged

    if state["iteration"] >= N_MAX:
        return "composer"  # budget exhausted

    history = state["failed_count_history"]
    if len(history) >= 2 and history[-1] >= history[-2]:
        return "composer"  # non-productive: failing set is not shrinking

    if all(exhausted_ladder(c, state["critiques"]) for c in failed):
        return "composer"  # no corrective action available

    return "researcher"  # corrective iteration


def route_after_evaluator(state: AuditState) -> Literal["researcher", "auditor", "composer"]:
    """
    The inner-loop routing predicate (Table 3.4).

    Escalate while any query is below SUFFICIENT and has ladder headroom;
    proceed to the Auditor once at least one bundle is SUFFICIENT (or AMBIGUOUS
    at level 4, meaning the ladder was fully tried); go straight to the
    composer only when every query has exhausted the ladder AND no usable
    evidence exists at all — the all-queries-uncovered case.

    The AMBIGUOUS-at-level-4 extension (Issue 3 fix) ensures that bundles
    populated by the title-sweep fallback are passed to the Auditor rather than
    silently discarded.  The Auditor gate in graph.py already requires
    retrieval_level >= 2 before processing AMBIGUOUS bundles, so this routing
    change does not loosen grounding — it only ensures control flow reaches the
    Auditor when useful evidence is available.
    """
    bundles = state["evidence"].values()
    if not bundles:
        return "composer"

    escalatable = [
        b for b in bundles
        if b.grade != RetrievalGrade.SUFFICIENT and b.retrieval_level_used < 4
    ]
    if escalatable:
        return "researcher"

    # All bundles are either SUFFICIENT or at level 4 (ladder exhausted).
    # Route to the Auditor if ANY bundle has usable evidence (SUFFICIENT or
    # AMBIGUOUS-with-spans — the Auditor gate in graph.py handles the rest).
    reachable = [
        b for b in bundles
        if b.grade == RetrievalGrade.SUFFICIENT
        or (b.grade == RetrievalGrade.AMBIGUOUS and b.spans and not b.evidence_unavailable)
    ]
    if reachable:
        return "auditor"

    return "composer"  # ladder exhausted for every query, no usable evidence



__all__ = [
    "ContractType", "ClaimType", "Severity", "PartyRole", "RetrievalGrade",
    "ChunkType", "EntailmentVerdict", "CitationVerdict", "AttributionVerdict",
    "TerminalClaimState", "CoverageState",
    "SpanMetadata", "Span", "AuditQuery", "EvidenceBundle",
    "Claim", "Verdict", "Critique", "CoverageItem", "TraceEvent", "AuditReport",
    "AuditState", "new_audit_state", "N_MAX",
    "route_after_critic", "route_after_evaluator", "exhausted_ladder",
    "merge_counters", "merge_latest",
]
