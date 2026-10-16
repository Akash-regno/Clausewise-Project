"""
Deterministic loop test: a scripted fake model exercises freezing, corrective
regeneration, and every termination guarantee, with no API in the loop.
"""
import json, logging, re, sys
from pathlib import Path

import graph as G
from schemas import ContractType, N_MAX

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s  %(message)s")


class FakeResponse:
    def __init__(self, payload):
        self.content = json.dumps(payload)
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 40}


SPAN_RE = re.compile(r"\[span_id: (spn_[0-9a-f]+)")


class FakeLLM:
    """Scripted model. `script` controls how the critic behaves per pass."""

    def __init__(self, agent, script):
        self.agent, self.script = agent, script

    def bind(self, **kw):
        return self

    def invoke(self, messages):
        text = "\n".join(getattr(m, "content", "") for m in messages)
        spans = SPAN_RE.findall(text)

        if self.agent == "researcher":
            return FakeResponse({"reformulated_query": "indemnify hold harmless uncapped",
                                 "hypothetical_clause": "The Provider shall indemnify..."})

        if self.agent == "evaluator":
            return FakeResponse({"grade": "SUFFICIENT", "rationale": "covers the requirement"})

        if self.agent == "auditor":
            self.script["auditor_calls"] += 1
            if "failed independent verification" in text:
                # Corrective regeneration: emit a corrected single claim.
                span = spans[0] if spans else self.script["span_a"]
                return FakeResponse({"claims": [{
                    "clause_id": "cls_09_02", "claim_type": "DESCRIPTIVE",
                    "proposition": "The Service Provider bears an uncapped indemnity for third-party IP claims, subject to the carve-outs in clause 9.3.",
                    "evidence_span_ids": [span],
                    "severity": "HIGH", "party_affected": "SERVICE_PROVIDER",
                    "rationale": "corrected direction", "reference_ids": []}]})
            # Initial draft: three claims, only for the first bundle.
            if self.script["drafted"]:
                return FakeResponse({"claims": []})
            if not spans:
                return FakeResponse({"claims": []})
            self.script["drafted"] = True
            span_a = spans[0]
            span_b = spans[1] if len(spans) > 1 else self.script.get("span_b", span_a)
            span_c = spans[2] if len(spans) > 2 else self.script.get("span_c", span_a)
            return FakeResponse({"claims": [
                {"clause_id": "cls_09_02", "claim_type": "DESCRIPTIVE",
                 "proposition": "The Client bears an uncapped indemnity for third-party IP claims.",
                 "evidence_span_ids": [span_a], "severity": "HIGH",
                 "party_affected": "CLIENT", "rationale": "x", "reference_ids": []},
                {"clause_id": "cls_10_02", "claim_type": "DESCRIPTIVE",
                 "proposition": "Liability of the Client is capped at fees paid in the preceding twelve months.",
                 "evidence_span_ids": [span_b], "severity": "MEDIUM",
                 "party_affected": "CLIENT", "rationale": "x", "reference_ids": []},
                {"clause_id": "cls_02_02", "claim_type": "DESCRIPTIVE",
                 "proposition": "Either party may terminate on ninety days written notice.",
                 "evidence_span_ids": [span_c], "severity": "LOW",
                 "party_affected": "BOTH", "rationale": "x", "reference_ids": []},
                {"clause_id": "cls_99", "claim_type": "DESCRIPTIVE",
                 "proposition": "This claim cites a span that was never supplied to the Auditor.",
                 "evidence_span_ids": ["spn_deadbeef"], "severity": "LOW",
                 "party_affected": "CLIENT", "rationale": "x", "reference_ids": []},
            ]})

        if self.agent == "critic":
            self.script["critic_calls"] += 1
            # The inverted-indemnity claim fails V3 on the first pass only.
            if "The Client bears an uncapped indemnity" in text:
                return FakeResponse({
                    "v1_entailment": "ENTAILED", "v3_attribution": "WRONG_PARTY",
                    "evidence_quote": "The Service Provider shall indemnify",
                    "failure_description": "Obligation direction inverted: the Service Provider indemnifies the Client, not the reverse.",
                    "retrieval_directive": "Retrieve clause 9.3, which states the carve-outs the indemnity is subject to.",
                    "target_clause_ids": ["cls_09_03"], "target_defined_terms": ["Losses"]})
            if self.script["mode"] == "never_converge":
                return FakeResponse({
                    "v1_entailment": "NEUTRAL", "v3_attribution": "CORRECT",
                    "evidence_quote": "", "failure_description": "Not established by the cited text.",
                    "retrieval_directive": "Retrieve additional supporting provisions and re-verify.",
                    "target_clause_ids": [], "target_defined_terms": []})
            return FakeResponse({"v1_entailment": "ENTAILED", "v3_attribution": "CORRECT",
                                 "evidence_quote": "cited text", "failure_description": "",
                                 "retrieval_directive": "", "target_clause_ids": [],
                                 "target_defined_terms": []})

        raise AssertionError(f"unexpected agent {self.agent}")


def run(mode):
    backend = G.SidecarRetriever(Path("test_contract.structure.json"),
                                 Path("test_contract.canonical.txt"))
    spans = backend.search("indemnify hold harmless liability termination notice",
                           namespace="tnt_221::doc_7f3a", top_k=6)
    span_a = backend._by_clause.get("cls_09_02", spans[0]).span_id
    span_b = backend._by_clause.get("cls_10_02", spans[1] if len(spans) > 1 else spans[0]).span_id
    span_c = backend._by_clause.get("cls_02_02", spans[2] if len(spans) > 2 else spans[0]).span_id
    script = {"mode": mode, "drafted": False, "auditor_calls": 0, "critic_calls": 0,
              "span_a": span_a, "span_b": span_b, "span_c": span_c}
    G.set_llm_factory(lambda agent: FakeLLM(agent, script))
    report = G.run_audit(backend, job_id="job_test", tenant_id="tnt_221",
                         document_id="doc_7f3a", contract_type=ContractType.MSA)
    return report, script


if __name__ == "__main__":
    print("\n" + "=" * 72)
    print("SCENARIO A — one claim fails V3, is corrected, loop converges")
    print("=" * 72)
    report, script = run("converge")
    print(f"terminal_reason        : {report.terminal_reason}")
    print(f"iterations_used        : {report.iterations_used}")
    print(f"findings (VERIFIED)    : {len(report.findings)}")
    print(f"requires_human_review  : {len(report.requires_human_review)}")
    print(f"auditor calls / critic : {script['auditor_calls']} / {script['critic_calls']}")
    for c in report.sorted_findings():
        print(f"   [{c.severity.value:<13}] {c.party_affected.value:<16} regen={c.regeneration_count}  {c.proposition[:62]}")
    assert report.terminal_reason == "converged", report.terminal_reason
    assert all(c.terminal_state.value == "VERIFIED" for c in report.findings)
    corrected = [c for c in report.findings if c.regeneration_count > 0]
    assert len(corrected) == 1 and corrected[0].party_affected.value == "SERVICE_PROVIDER"
    print("PASS: inverted indemnity was caught, corrected, and re-verified.")

    print("\n" + "=" * 72)
    print("SCENARIO B — Critic never accepts: guards must terminate the loop")
    print("=" * 72)
    report_b, script_b = run("never_converge")
    print(f"terminal_reason        : {report_b.terminal_reason}")
    print(f"iterations_used        : {report_b.iterations_used}  (N_MAX={N_MAX})")
    print(f"findings (VERIFIED)    : {len(report_b.findings)}")
    print(f"requires_human_review  : {len(report_b.requires_human_review)}")
    assert report_b.iterations_used <= N_MAX + 1, report_b.iterations_used
    assert len(report_b.findings) == 0
    assert len(report_b.requires_human_review) > 0
    print("PASS: loop terminated; nothing unverified reached findings.")

    print("\n" + "=" * 72)
    print("INVARIANT + ISOLATION CHECKS")
    print("=" * 72)
    from schemas import Claim, ClaimType, Severity, PartyRole, TerminalClaimState, AuditReport
    bad = Claim(claim_id="clm_900", clause_id="c", claim_type=ClaimType.DESCRIPTIVE,
                proposition="An unverified proposition.", evidence_span_ids=["spn_0001"],
                severity=Severity.HIGH, party_affected=PartyRole.CLIENT,
                terminal_state=TerminalClaimState.UNVERIFIABLE)
    try:
        AuditReport(job_id="j", document_id="d", tenant_id="t",
                    contract_type=ContractType.MSA, findings=[bad])
        print("FAIL: invariant not enforced"); sys.exit(1)
    except Exception:
        print("PASS: unverified claim cannot be composed into findings.")

    leaky = Claim(claim_id="clm_901", clause_id="cls_09_02", claim_type=ClaimType.DESCRIPTIVE,
                  proposition="The Provider indemnifies the Client.", evidence_span_ids=["spn_0001"],
                  severity=Severity.HIGH, party_affected=PartyRole.SERVICE_PROVIDER,
                  rationale="SECRET-AUDITOR-REASONING-TOKEN")
    view = G._isolate_for_critic(leaky, [])
    for leak in ["SECRET-AUDITOR-REASONING-TOKEN", "HIGH", "clm_901"]:
        assert leak not in view, f"LEAKED: {leak}"
    print("PASS: Critic view excludes rationale, severity and claim_id.")
    print()

