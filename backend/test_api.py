"""
End-to-end API verification with FastAPI's TestClient. No Pinecone, no Groq:
the retrieval backend and the LLM are both injected fakes, so this exercises the
API layer's own behaviour — lifecycle, streaming, tenancy, deletion.
"""
import json, logging, os, re, shutil
from pathlib import Path

os.environ["AUDIT_DEV_MODE"] = "1"          # ingest dry-run: no embedding, no upsert
os.environ["AUDIT_STORAGE"] = "./_apitest"
logging.disable(logging.INFO)

shutil.rmtree("./_apitest", ignore_errors=True)

from fastapi.testclient import TestClient

import graph as G
import main
from main import app
from retriever import InMemoryTextStore, PineconeRetriever, StructureIndex
from test_loop import FakeResponse
from test_retriever import FakePineconeIndex, HashEmbedder
from ingest import (IngestionConfig, build_defined_term_index, build_xref_graph,
                    chunk_document, parse_pdf, segment_clauses, sparse_encode)

DIM = 384
_shared_index = FakePineconeIndex()


def fake_backend_factory(record):
    """Build a retriever over an in-process fake index, from real ingest output."""
    cfg = IngestionConfig()
    pdf = Path(record.pdf_path)
    doc = parse_pdf(pdf)
    clauses = segment_clauses(doc.text)
    terms = build_defined_term_index(doc.text, clauses)
    xrefs = build_xref_graph(doc.text, clauses)
    chunks = chunk_document(doc, clauses, terms, xrefs, tenant_id=record.tenant_id,
                            document_id=record.document_id, cfg=cfg)
    emb = HashEmbedder()
    vecs = emb.embed_documents([c.text for c in chunks])
    _shared_index.upsert([
        {"id": c.span_id, "values": v, "sparse_values": sparse_encode(c.text, cfg),
         "metadata": {**{k: (float(x) if isinstance(x, int) else x)
                         for k, x in c.metadata.model_dump(mode="json", exclude_none=True).items()},
                      "chunk_type": c.metadata.chunk_type.value, "text": c.text[:8000]}}
        for c, v in zip(chunks, vecs)], namespace=record.namespace)

    structure = StructureIndex.from_dict({
        "clauses": [{"clause_id": c.clause_id, "parent_id": c.parent_id, "title": c.title,
                     "children": c.children, "path": c.path} for c in clauses],
        "defined_terms": terms, "cross_references": xrefs})

    from retriever import RetrieverConfig
    return PineconeRetriever(
        index=_shared_index, tenant_id=record.tenant_id, document_id=record.document_id,
        structure=structure, text_store=InMemoryTextStore({record.namespace: doc.text}),
        embedder=emb, cfg=RetrieverConfig(enable_rerank=False))


main.set_backend_factory(fake_backend_factory)

# Script the LLM. span ids are resolved lazily on first auditor call.
# A fake Auditor/Critic that cites spans it was actually shown. The evidence
# block rendered by graph.py carries "[span_id: spn_XXXX | clause: ...]", so the
# fake parses those out — exactly as a real Auditor must, since the orchestrator
# discards any claim citing a span that was not supplied to it.
SPAN_RE = re.compile(r"\[span_id: (spn_[0-9a-f]+)")


class ApiFakeLLM:
    def __init__(self, agent, state):
        self.agent, self.state = agent, state

    def bind(self, **kw):
        return self

    def invoke(self, messages):
        text = "\n".join(getattr(m, "content", "") for m in messages)
        spans = SPAN_RE.findall(text)

        if self.agent == "researcher":
            return FakeResponse({"reformulated_query": "indemnify hold harmless",
                                 "hypothetical_clause": "The Provider shall indemnify."})
        if self.agent == "evaluator":
            return FakeResponse({"grade": "SUFFICIENT", "rationale": "covers the requirement"})

        if self.agent == "auditor":
            if not spans:
                return FakeResponse({"claims": []})
            if "failed independent verification" in text:
                # Corrective regeneration: correct the obligation direction.
                return FakeResponse({"claims": [{
                    "clause_id": "cls_09_02", "claim_type": "DESCRIPTIVE",
                    "proposition": "The Service Provider gives an uncapped IP indemnity, subject to the carve-outs in clause 9.3.",
                    "evidence_span_ids": [spans[0]], "severity": "HIGH",
                    "party_affected": "SERVICE_PROVIDER", "rationale": "corrected",
                    "reference_ids": []}]})
            if self.state["drafted"]:
                return FakeResponse({"claims": []})
            self.state["drafted"] = True
            out = [{"clause_id": "cls_09_02", "claim_type": "DESCRIPTIVE",
                    "proposition": "The Client bears an uncapped indemnity for third-party IP claims.",
                    "evidence_span_ids": [spans[0]], "severity": "HIGH",
                    "party_affected": "CLIENT", "rationale": "x", "reference_ids": []}]
            if len(spans) > 1:
                out.append({"clause_id": "cls_10_02", "claim_type": "DESCRIPTIVE",
                            "proposition": "Liability is capped at the fees paid in the preceding twelve months.",
                            "evidence_span_ids": [spans[1]], "severity": "MEDIUM",
                            "party_affected": "CLIENT", "rationale": "x", "reference_ids": []})
            # A fabricated citation the orchestrator must discard before verification.
            out.append({"clause_id": "cls_99", "claim_type": "DESCRIPTIVE",
                        "proposition": "This claim cites a span never supplied to the Auditor.",
                        "evidence_span_ids": ["spn_deadbeef"], "severity": "LOW",
                        "party_affected": "CLIENT", "rationale": "x", "reference_ids": []})
            return FakeResponse({"claims": out})

        if self.agent == "critic":
            if "The Client bears an uncapped indemnity" in text:
                return FakeResponse({
                    "v1_entailment": "ENTAILED", "v3_attribution": "WRONG_PARTY",
                    "evidence_quote": "The Service Provider shall indemnify",
                    "failure_description": "Obligation direction inverted.",
                    "retrieval_directive": "Retrieve clause 9.3, which states the carve-outs.",
                    "target_clause_ids": ["cls_09_03"], "target_defined_terms": []})
            return FakeResponse({"v1_entailment": "ENTAILED", "v3_attribution": "CORRECT",
                                 "evidence_quote": "cited text", "failure_description": "",
                                 "retrieval_directive": "", "target_clause_ids": [],
                                 "target_defined_terms": []})
        raise AssertionError(self.agent)


LLM_STATE = {"drafted": False}
G.set_llm_factory(lambda agent: ApiFakeLLM(agent, LLM_STATE))

H = {"X-Tenant-Id": "tnt_alpha"}

client = TestClient(app)
client.__enter__()   # run lifespan: binds the event loop to the EventBus

print("=" * 72)
print("1. HEALTH + MANDATORY DISCLOSURE (M4.5 / Section 3.7.5)")
print("=" * 72)
r = client.get("/health")
assert r.status_code == 200
print(f"   disclosure carried by the API: {r.json()['disclosure'][:64]}...")

print("\n" + "=" * 72)
print("2. UPLOAD -> INGEST (Table 3.3 stages 1-7)")
print("=" * 72)
with open("test_contract.pdf", "rb") as fh:
    r = client.post("/upload", files={"file": ("msa.pdf", fh, "application/pdf")},
                    data={"contract_type": "MSA"}, headers=H)
assert r.status_code == 201, r.text
up = r.json()
DOC = up["document_id"]
print(f"   document_id={DOC}  status={up['status']}")
print(f"   pages={up['n_pages']} clauses={up['n_clauses']} chunks={up['n_chunks']}")
assert up["n_clauses"] > 10 and up["n_chunks"] > 10

ns = f"tnt_alpha::{DOC}"
canonical = Path(f"./_apitest/canonical/{ns.replace('::','__')}.canonical.txt")
print(f"   canonical text on disk: {canonical.exists()} "
      f"({canonical.stat().st_size if canonical.exists() else 0} bytes)")
assert canonical.exists(), "LocalTextStore path convention broken -> V2 would fail closed"

print("\n" + "=" * 72)
print("3. GET BEFORE POST -> 409, NOT AN ACCIDENTAL AUDIT")
print("=" * 72)
r = client.get(f"/audit/{DOC}", headers=H)
print(f"   status={r.status_code}  detail={r.json()['detail'][:70]}...")
assert r.status_code == 409

print("\n" + "=" * 72)
print("4. FILENAME SANITISATION (path traversal)")
print("=" * 72)
with open("test_contract.pdf", "rb") as fh:
    r = client.post("/upload",
                    files={"file": ("../../../etc/cron.d/evil.pdf", fh, "application/pdf")},
                    data={"contract_type": "MSA"}, headers=H)
evil = r.json()
evil_path = Path(f"./_apitest/uploads/tnt_alpha/{evil['document_id']}.pdf")
print(f"   client filename kept only as a label: {evil['filename']!r}")
print(f"   stored at: {evil_path}")
assert evil_path.exists() and not Path("/etc/cron.d/evil.pdf").exists()
client.delete(f"/document/{evil['document_id']}", headers=H)

print("\n" + "=" * 72)
print("5. POST /audit -> 202 + SSE STREAM (Section 3.2.6)")
print("=" * 72)
LLM_STATE["drafted"] = False
r = client.post(f"/audit/{DOC}", headers=H)
assert r.status_code == 202, r.text
start = r.json()
print(f"   202 Accepted  job_id={start['job_id']}  events={start['events_url']}")

events = []
with client.stream("GET", f"/audit/{DOC}/events", headers=H) as stream:
    cur = {}
    for line in stream.iter_lines():
        if line.startswith("event: "):
            cur["event"] = line[7:]
        elif line.startswith("data: "):
            cur["data"] = json.loads(line[6:])
        elif line == "" and cur.get("event"):
            events.append(cur); 
            if cur["event"] in ("complete", "error", "close"):
                break
            cur = {}

kinds = {}
for e in events:
    kinds[e["event"]] = kinds.get(e["event"], 0) + 1
print(f"   event types received: {kinds}")

print("\n   --- progress narrative the user sees ---")
for e in events:
    if e["event"] == "progress":
        d = e["data"]
        print(f"     it={d.get('iteration',0)}  {d.get('label','')[:38]:<38} {d.get('message','')[:52]}")

trace_events = [e["data"]["event"] for e in events if e["event"] == "trace"]
print(f"\n   trace events (Objective 5 instrumentation): {sorted(set(trace_events))}")
assert "progress" in kinds and "complete" in kinds
assert "verification_pass" in trace_events, "freezing not observable in the stream"
assert any("corrective" in t for t in trace_events), "corrective loop not observable"

final = [e for e in events if e["event"] == "complete"][0]["data"]
print(f"\n   complete: findings={final['findings']} "
      f"review={final['requires_human_review']} reason={final['terminal_reason']}")

print("\n" + "=" * 72)
print("6. SSE REPLAY VIA Last-Event-ID (reconnection)")
print("=" * 72)
r = client.get(f"/audit/{DOC}/events", headers={**H, "Last-Event-ID": "3"})
replayed = r.text.count("event: ")
print(f"   reconnect from id=3 replayed {replayed} events (total was {len(events)})")
assert 0 < replayed < len(events)

print("\n" + "=" * 72)
print("7. REPORT RETRIEVAL")
print("=" * 72)
r = client.get(f"/audit/{DOC}", headers=H)
rep = r.json()
print(f"   status={rep['status']}  findings={len(rep['report']['findings'])}")
for f in rep["report"]["findings"]:
    print(f"     [{f['severity']:<6}] {f['party_affected']:<16} {f['proposition'][:56]}")
    assert f["terminal_state"] == "VERIFIED", "INVARIANT BREACH via the API"
print("   invariant holds: every finding serialised is VERIFIED.")

print("\n" + "=" * 72)
print("8. TENANT ISOLATION (Section 3.2.7)")
print("=" * 72)
for path, method in ((f"/audit/{DOC}", "get"), (f"/audit/{DOC}/events", "get"),
                     (f"/document/{DOC}", "delete")):
    resp = getattr(client, method)(path, headers={"X-Tenant-Id": "tnt_attacker"})
    print(f"   {method.upper():<6} {path:<34} -> {resp.status_code}")
    assert resp.status_code == 404, f"{path} leaked to another tenant"
r = client.get("/documents", headers={"X-Tenant-Id": "tnt_attacker"})
print(f"   GET    /documents (attacker)              -> {len(r.json())} documents")
assert r.json() == []
print("   PASS: cross-tenant access returns 404, not 403 (no existence disclosure).")

print("\n" + "=" * 72)
print("9. DELETION SAGA (Sections 3.2.7 / 3.7.3)")
print("=" * 72)
pdf_p = Path(f"./_apitest/uploads/tnt_alpha/{DOC}.pdf")
struct_p = Path(f"./_apitest/structure/{ns.replace('::','__')}.structure.json")
print(f"   before: pdf={pdf_p.exists()} text={canonical.exists()} "
      f"structure={struct_p.exists()} vectors={len(_shared_index.store.get(ns, {}))}")

r = client.delete(f"/document/{DOC}", headers=H)
res = r.json()
print(f"   complete={res['complete']}")
for leg, outcome in res["legs"].items():
    print(f"     {leg:<16} {outcome}")
print(f"   after : pdf={pdf_p.exists()} text={canonical.exists()} "
      f"structure={struct_p.exists()} vectors={len(_shared_index.store.get(ns, {}))}")
assert res["complete"]
assert not pdf_p.exists() and not canonical.exists() and not struct_p.exists()
assert ns not in _shared_index.store, "vector namespace survived deletion"
assert client.get(f"/audit/{DOC}", headers=H).status_code == 404
assert not list(Path("./_apitest/journal").glob("*.deletion.json")), \
    "journal should be cleared on a fully successful saga"
print("   PASS: all three stores cleared; journal closed; document unreachable.")

print("\n" + "=" * 72)
print("10. PARTIAL DELETION FAILURE IS REPORTED HONESTLY")
print("=" * 72)
with open("test_contract.pdf", "rb") as fh:
    d2 = client.post("/upload", files={"file": ("b.pdf", fh, "application/pdf")},
                     data={"contract_type": "NDA"}, headers=H).json()["document_id"]

def broken_factory(record):
    raise RuntimeError("Pinecone unreachable")

main.set_backend_factory(broken_factory)
res2 = client.delete(f"/document/{d2}", headers=H).json()
print(f"   complete={res2['complete']}")
for leg, outcome in res2["legs"].items():
    print(f"     {leg:<16} {outcome[:56]}")
print(f"   message: {res2['message'][:78]}")
journals = list(Path("./_apitest/journal").glob("*.deletion.json"))
print(f"   journal retained for retry: {[p.name for p in journals]}")
assert res2["complete"] is False
assert "failed" in res2["legs"]["vectors"]
assert journals, "an incomplete saga must leave a journal"
assert client.get(f"/audit/{d2}", headers=H).status_code == 404, \
    "document must be unreachable even when a leg failed"
print("   PASS: failure surfaced, document already unreachable, saga resumable.")

main.set_backend_factory(fake_backend_factory)
client.__exit__(None, None, None)
shutil.rmtree("./_apitest", ignore_errors=True)
print("\nAll API checks passed.\n")
