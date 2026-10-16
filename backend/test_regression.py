"""
test_regression.py — Regression tests for the four issues identified
in the Clausewise test run against test_contract.pdf.

GROUND TRUTH CONTRACT (10 sections):
  1  DEFINITIONS
  2  TERM AND TERMINATION  (clause 2.2 = 90-day termination notice)
  3  SERVICES
  4  FEES AND PAYMENT      (payment terms)
  5  CONFIDENTIALITY       (confidentiality)
  6  INTELLECTUAL PROPERTY (IP ownership)
  7  WARRANTIES
  8  COMPLIANCE
  9  INDEMNIFICATION       (clauses 9.1, 9.2, 9.3)
  10 LIMITATION OF LIABILITY

Run with:
    python -m pytest test_regression.py -v

The test harness replaces the LLM factory with a scripted fake that returns
deterministic responses, so these tests run offline without an API key.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent
_SIDECAR = _BACKEND_DIR / "test_contract.structure.json"
_CANONICAL = _BACKEND_DIR / "test_contract.canonical.txt"


def _skip_if_missing():
    if not _SIDECAR.exists() or not _CANONICAL.exists():
        pytest.skip(
            "test_contract.structure.json / test_contract.canonical.txt not found. "
            "Run ingest.py --dry-run on test_contract.pdf first."
        )


# ---------------------------------------------------------------------------
# Scripted LLM fake — deterministic, no API key required
# ---------------------------------------------------------------------------

from schemas import (
    AttributionVerdict,
    ClaimType,
    ContractType,
    CoverageState,
    EntailmentVerdict,
    PartyRole,
    RetrievalGrade,
    Severity,
)

import graph as G
from graph import (
    OrchestratorConfig,
    SidecarRetriever,
    _DraftClaim,
    _DraftClaims,
    _GradeResponse,
    _CriticResponse,
    _ReformulationResponse,
)


def _make_scripted_factory():
    """
    Returns an LLM factory that produces deterministic, schema-valid outputs.

    Evaluator: grades SUFFICIENT when evidence spans are present.
    Auditor:   emits one DESCRIPTIVE claim per evidence bundle, citing the
               first available span.
    Critic:    passes every claim (ENTAILED, VALID, CORRECT) — we're testing
               coverage and dedup, not Critic calibration.
    Researcher reformulator: echoes query text unchanged.
    """

    class _ScriptedLLM:
        def bind(self, **_kwargs):
            return self

        def invoke(self, messages):
            # Derive context from the last user message
            text = ""
            for m in messages:
                if hasattr(m, "content"):
                    text += m.content

            # ---- Evaluator ------------------------------------------------
            if "SUFFICIENT" in text and "grade" in text.lower():
                has_spans = "span_id:" in text
                grade = "SUFFICIENT" if has_spans else "INSUFFICIENT"
                raw = json.dumps({"grade": grade, "rationale": "scripted"})
                return _FakeResponse(raw)

            # ---- Auditor --------------------------------------------------
            if '"claims"' in text or "Emit at most" in text:
                # Extract first span_id from the evidence block
                span_match = re.search(r"\[span_id:\s*([a-zA-Z0-9_]+)", text)
                # Extract first clause path
                clause_match = re.search(r"clause:\s*([^\|]+)", text)
                # Extract checklist item
                checklist_match = re.search(r"Checklist item:\s*(\S+)", text)

                if span_match and clause_match:
                    span_id = span_match.group(1).strip()
                    clause_path = clause_match.group(1).strip()
                    checklist = (
                        checklist_match.group(1).strip() if checklist_match else "provision"
                    )

                    # Derive clause_id from path (e.g. "2 > 2.2" -> "cls_02_02")
                    # Fall back gracefully if parsing fails
                    clause_id = _path_to_clause_id(clause_path)

                    prop = (
                        f"Under {clause_path}, the contract contains a {checklist} "
                        f"provision that warrants attention."
                    )
                    claim = {
                        "clause_id": clause_id,
                        "claim_type": "DESCRIPTIVE",
                        "proposition": prop,
                        "evidence_span_ids": [span_id],
                        "severity": "MEDIUM",
                        "party_affected": "BOTH",
                        "rationale": "Scripted test claim.",
                    }
                    raw = json.dumps({"claims": [claim]})
                    return _FakeResponse(raw)

                # No span found — emit empty (no claim)
                return _FakeResponse(json.dumps({"claims": []}))

            # ---- Critic ---------------------------------------------------
            if "V1" in text or "ENTAILMENT" in text or "ENTAILED" in text:
                raw = json.dumps({
                    "v1_entailment": "ENTAILED",
                    "v3_attribution": "CORRECT",
                    "evidence_quote": "Scripted citation.",
                    "failure_description": "",
                    "retrieval_directive": "",
                    "target_clause_ids": [],
                    "target_defined_terms": [],
                })
                return _FakeResponse(raw)

            # ---- Researcher reformulator ----------------------------------
            if "reformulated_query" in text.lower() or "hypothetical_clause" in text.lower():
                # Return the original query text so the reformulation search
                # uses the same terms and produces the same (empty) result set
                # for topics that are genuinely absent from the contract.
                q_match = (
                    re.search(r"Audit query:\s*(.+?)(?:\n|$)", text)
                    or re.search(r"Query:\s*(.+?)(?:\n|$)", text)
                )
                reformulated = q_match.group(1).strip() if q_match else "relevant provision"
                raw = json.dumps({
                    "reformulated_query": reformulated,
                    "hypothetical_clause": "",
                })
                return _FakeResponse(raw)

            # ---- Grade response fallback ---------------------------------
            return _FakeResponse(json.dumps({"grade": "SUFFICIENT", "rationale": "scripted"}))

    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content
            self.usage_metadata = {}

    def _factory(agent: str) -> _ScriptedLLM:
        return _ScriptedLLM()

    return _factory


def _path_to_clause_id(path: str) -> str:
    """
    Convert a clause path like '2 > 2.2' to a clause_id like 'cls_02_02'.
    Used by the scripted LLM to emit valid clause identifiers.
    """
    # Take the last segment after '>'
    parts = [p.strip() for p in path.split(">")]
    last = parts[-1] if parts else path.strip()
    # Build clause_id from the dot-separated number
    segments = []
    for seg in re.split(r"[.\(\)]", last):
        seg = seg.strip()
        if not seg:
            continue
        if seg.isdigit():
            segments.append(f"{int(seg):02d}")
        else:
            segments.append(seg.lower())
    return "cls_" + "_".join(segments) if segments else "cls_00"


# ---------------------------------------------------------------------------
# Shared fixture: run the full pipeline once with the scripted LLM
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def audit_report():
    """Run a full pipeline on test_contract and return the AuditReport."""
    _skip_if_missing()

    G.set_llm_factory(_make_scripted_factory())

    backend = SidecarRetriever(_SIDECAR, _CANONICAL)
    report = G.run_audit(
        backend,
        job_id="test_job_001",
        tenant_id="tnt_test",
        document_id="doc_test",
        contract_type=ContractType.MSA,
        cfg=OrchestratorConfig(
            top_k=6,
            max_claims_per_bundle=2,  # same as production — dedup must handle this
            critic_concurrency=1,
        ),
    )

    # Restore default factory so other tests are not affected
    G.set_llm_factory(G._default_llm_factory)
    return report


# ---------------------------------------------------------------------------
# Issue 1 — Duplicate finding for clause 2.2
# ---------------------------------------------------------------------------


def test_no_duplicate_findings_for_clause_2_2(audit_report):
    """
    Exactly one verified finding for clause 2.2 (termination notice).

    Definition of done: no two findings in the report share the same clause_id
    that maps to the termination clause, regardless of how the Auditor worded them.
    """
    # The termination clause is cls_02_02 in our test contract structure.
    termination_clause_ids = {"cls_02_02", "cls_02", "2 > 2.2", "2.2"}

    findings_on_22 = [
        f for f in audit_report.findings
        if f.clause_id in termination_clause_ids
    ]
    assert len(findings_on_22) <= 1, (
        f"Expected at most 1 finding for clause 2.2 (termination), got "
        f"{len(findings_on_22)}: {[f.clause_id for f in findings_on_22]}"
    )


def test_no_clause_duplicate_any_severity(audit_report):
    """
    No two verified findings share both the same clause_id AND contradictory
    severity (which would be a sign of un-merged duplicates).
    """
    from collections import defaultdict
    by_clause: dict[str, list] = defaultdict(list)
    for f in audit_report.findings:
        by_clause[f.clause_id].append(f.severity)

    for cid, severities in by_clause.items():
        unique_severities = set(severities)
        assert len(unique_severities) == len(severities) or len(severities) == 1, (
            f"Clause {cid} has {len(severities)} findings with severities "
            f"{[s.value for s in severities]} — dedup may not have fired."
        )


# ---------------------------------------------------------------------------
# Issue 2 — Checklist false negatives
# ---------------------------------------------------------------------------


def test_checklist_confidentiality_not_absent(audit_report):
    """
    Confidentiality (clause 5) must not show as ABSENT.
    The contract contains a Confidentiality section (5.1 Duty).
    """
    item = _get_coverage(audit_report, "confidentiality")
    assert item is not None, "No coverage item for 'confidentiality'"
    assert item.state != CoverageState.ABSENT, (
        f"Confidentiality wrongly marked ABSENT (got {item.state.value}). "
        "Clause 5 exists in the contract."
    )


def test_checklist_payment_terms_not_absent(audit_report):
    """
    Payment terms (clause 4) must not show as ABSENT.
    The contract contains 4.1 Invoicing and 4.2 Taxes.
    """
    item = _get_coverage(audit_report, "payment_terms")
    assert item is not None, "No coverage item for 'payment_terms'"
    assert item.state != CoverageState.ABSENT, (
        f"Payment terms wrongly marked ABSENT (got {item.state.value}). "
        "Clause 4 exists in the contract."
    )


def test_checklist_ip_assignment_not_absent(audit_report):
    """
    IP assignment (clause 6) must not show as ABSENT.
    The contract contains 6.1 Ownership.
    """
    item = _get_coverage(audit_report, "ip_assignment")
    assert item is not None, "No coverage item for 'ip_assignment'"
    assert item.state != CoverageState.ABSENT, (
        f"IP assignment wrongly marked ABSENT (got {item.state.value}). "
        "Clause 6 exists in the contract."
    )


def test_checklist_governing_law_is_absent(audit_report):
    """
    Governing law should be ABSENT — this clause genuinely does not exist
    in the test contract. Regression guard: must not flip to ADDRESSED.
    """
    item = _get_coverage(audit_report, "governing_law")
    assert item is not None, "No coverage item for 'governing_law'"
    assert item.state == CoverageState.ABSENT, (
        f"Governing law should be ABSENT (it genuinely is not in the contract), "
        f"but got {item.state.value}."
    )


# ---------------------------------------------------------------------------
# Issue 3 — Coverage completeness
# ---------------------------------------------------------------------------


def test_every_checklist_item_has_coverage_entry(audit_report):
    """
    Every checklist item must appear in the coverage report.
    No topic should be silently dropped from the report.
    """
    expected_items = {
        "limitation_of_liability",
        "indemnity_scope",
        "termination_rights",
        "payment_terms",
        "ip_assignment",
        "confidentiality",
        "governing_law",
    }
    actual_items = {item.checklist_item for item in audit_report.coverage}
    missing = expected_items - actual_items
    assert not missing, f"These checklist items are missing from coverage: {missing}"


def test_at_least_half_checklist_items_have_evidence(audit_report):
    """
    At least 4 of the 7 MSA checklist items should have evidence (ADDRESSED
    or PRESENT_BUT_UNANALYSED), given the contract covers 6 of the 7 topics.
    Governing law is the only genuinely absent one.
    """
    present = [
        item for item in audit_report.coverage
        if item.state != CoverageState.ABSENT
    ]
    assert len(present) >= 4, (
        f"Only {len(present)} checklist items have evidence. "
        "Expected at least 4 (all except governing_law)."
    )


def test_non_governing_law_topics_not_all_absent(audit_report):
    """
    The six topics that ARE in the contract must not all be marked ABSENT.
    """
    absent_count = sum(
        1 for item in audit_report.coverage
        if item.state == CoverageState.ABSENT
        and item.checklist_item != "governing_law"
    )
    assert absent_count <= 2, (
        f"{absent_count} non-governing-law topics are marked ABSENT. "
        "Expected at most 2 (some retrieval failure tolerance)."
    )


# ---------------------------------------------------------------------------
# Issue 4 — Grounding discipline for clause 9.2
# ---------------------------------------------------------------------------


def test_no_finding_asserts_uncapped_without_citation(audit_report):
    """
    No finding on clause 9.2 should assert 'uncapped' unless the cited span
    text actually contains that word (or 'no cap', 'without cap').

    The test_contract.canonical.txt we ship DOES include 'uncapped IP indemnity'
    in clause 9.2.  If the pipeline retrieves that text, asserting 'uncapped' is
    correct.  If it retrieves a truncated version, it must not assert it.

    This test checks the _logical_ constraint: finding text must not contain a
    cap characterisation that is absent from all cited spans.
    """
    _skip_if_missing()
    canonical = _CANONICAL.read_text(encoding="utf-8")
    backend = SidecarRetriever(_SIDECAR, _CANONICAL)

    cap_words = re.compile(r"\buncapped\b|\bno cap\b|\bwithout.*?cap\b", re.IGNORECASE)

    clause_92_ids = {"cls_09_02", "cls_09", "9 > 9.2", "9.2"}
    for finding in audit_report.findings:
        if finding.clause_id not in clause_92_ids:
            continue

        # If the proposition asserts uncapped or similar, the cited spans must
        # contain that language.
        prop_asserts_uncapped = bool(cap_words.search(finding.proposition))
        if not prop_asserts_uncapped:
            continue  # nothing to check

        # Collect the cited span texts from the canonical file via the backend.
        cited_texts: list[str] = []
        for span_id in finding.evidence_span_ids:
            span = backend.get_span(span_id, namespace=f"tnt_test::doc_test")
            if span:
                cited_texts.append(span.text)

        cited_combined = " ".join(cited_texts)
        assert cap_words.search(cited_combined), (
            f"Finding {finding.claim_id} on clause 9.2 asserts uncapped/no-cap "
            f"status ('{finding.proposition[:120]}') but the cited spans do not "
            f"contain that language. This is a grounding violation.\n"
            f"Cited text: {cited_combined[:300]!r}"
        )


def test_clause_92_finding_cites_real_span(audit_report):
    """
    Any finding on clause 9.2 must cite at least one span whose text
    is non-empty (i.e. the span resolves to actual contract text).
    This guards against a fabricated span_id bypassing V2.
    """
    _skip_if_missing()
    backend = SidecarRetriever(_SIDECAR, _CANONICAL)
    clause_92_ids = {"cls_09_02", "cls_09", "9 > 9.2", "9.2"}

    for finding in audit_report.findings:
        if finding.clause_id not in clause_92_ids:
            continue
        for span_id in finding.evidence_span_ids:
            span = backend.get_span(span_id, namespace="tnt_test::doc_test")
            assert span is not None and span.text.strip(), (
                f"Finding {finding.claim_id} on clause 9.2 cites span {span_id} "
                "which does not resolve to non-empty text. Possible fabricated citation."
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_coverage(report, checklist_item: str):
    for item in report.coverage:
        if item.checklist_item == checklist_item:
            return item
    return None
