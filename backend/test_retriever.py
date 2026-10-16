"""
Module 2 verification against a fake Pinecone index populated from real
ingest.py output. Proves Protocol conformance, parent lifting, structural
expansion, tenant isolation, and — most importantly — that V2 is not circular.
"""
import hashlib, logging, math, re, sys
from pathlib import Path

logging.disable(logging.INFO)

from ingest import (IngestionConfig, build_defined_term_index, build_xref_graph,
                    chunk_document, parse_pdf, segment_clauses, sparse_encode)
from retriever import (InMemoryTextStore, PineconeRetriever, RetrievalError,
                       RetrievalMode, RetrieverConfig, StructureIndex)
from schemas import ChunkType
import graph as G

DIM = 384


class HashEmbedder:
    """Deterministic offline stand-in for all-MiniLM-L6-v2. Same interface."""

    def _vec(self, text):
        v = [0.0] * DIM
        for tok in re.findall(r"[a-z]{3,}", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
            v[h % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_query(self, text): return self._vec(text)
    def embed_documents(self, texts): return [self._vec(t) for t in texts]


class FakePineconeIndex:
    """Mimics the subset of the Pinecone SDK the retriever uses."""

    def __init__(self): self.store = {}

    def upsert(self, vectors, namespace):
        ns = self.store.setdefault(namespace, {})
        for v in vectors: ns[v["id"]] = v

    @staticmethod
    def _match(meta, flt):
        for key, cond in (flt or {}).items():
            val = meta.get(key)
            if "$eq" in cond and val != cond["$eq"]: return False
            if "$in" in cond and val not in cond["$in"]: return False
        return True

    def query(self, vector, top_k, namespace, include_metadata=True,
              filter=None, sparse_vector=None):
        out = []
        for vid, rec in self.store.get(namespace, {}).items():
            meta = rec.get("metadata", {})
            if not self._match(meta, filter): continue
            score = sum(a * b for a, b in zip(vector, rec["values"]))
            if sparse_vector and rec.get("sparse_values"):
                qs = dict(zip(sparse_vector["indices"], sparse_vector["values"]))
                ds = dict(zip(rec["sparse_values"]["indices"], rec["sparse_values"]["values"]))
                score += sum(qs[i] * ds[i] for i in set(qs) & set(ds))
            out.append({"id": vid, "score": score, "metadata": meta})
        out.sort(key=lambda m: m["score"], reverse=True)
        return {"matches": out[:top_k]}

    def fetch(self, ids, namespace):
        ns = self.store.get(namespace, {})
        return {"vectors": {i: ns[i] for i in ids if i in ns}}

    def delete(self, delete_all=False, namespace=None):
        if delete_all: self.store.pop(namespace, None)


# ---------------------------------------------------------------- build the index
cfg_i = IngestionConfig()
doc = parse_pdf(Path("test_contract.pdf"))
clauses = segment_clauses(doc.text)
terms = build_defined_term_index(doc.text, clauses)
xrefs = build_xref_graph(doc.text, clauses)
chunks = chunk_document(doc, clauses, terms, xrefs, tenant_id="tnt_221",
                        document_id="doc_7f3a", cfg=cfg_i)

emb = HashEmbedder()
index = FakePineconeIndex()
NS = "tnt_221::doc_7f3a"
vectors = emb.embed_documents([c.text for c in chunks])
index.upsert([
    {"id": c.span_id, "values": v,
     "sparse_values": sparse_encode(c.text, cfg_i),
     # Pinecone returns every number as a float64 — replicate that faithfully.
     "metadata": {**{k: (float(x) if isinstance(x, int) else x)
                     for k, x in c.metadata.model_dump(mode="json", exclude_none=True).items()},
                  "chunk_type": c.metadata.chunk_type.value,
                  "text": c.text[:8000]}}
    for c, v in zip(chunks, vectors)], namespace=NS)
# The idempotency sentinel ingest.py writes must never surface as evidence.
index.upsert([{"id": "manifest_abc123", "values": [1.0] + [0.0] * (DIM - 1),
               "metadata": {"record_type": "manifest", "content_hash": "abc123"}}],
             namespace=NS)

structure = StructureIndex.from_dict({
    "clauses": [{"clause_id": c.clause_id, "parent_id": c.parent_id, "title": c.title,
                 "children": c.children, "path": c.path} for c in clauses],
    "defined_terms": terms, "cross_references": xrefs})

backend = PineconeRetriever(
    index=index, tenant_id="tnt_221", document_id="doc_7f3a", structure=structure,
    text_store=InMemoryTextStore({NS: doc.text}), embedder=emb,
    cfg=RetrieverConfig(enable_rerank=False))

print("=" * 72)
print("1. PROTOCOL CONFORMANCE")
print("=" * 72)
for m in ("search", "get_span", "text_at", "expand_structural"):
    assert callable(getattr(backend, m)), m
print("   RetrievalBackend methods present: search, get_span, text_at, expand_structural")
print("   Researcher tools (Table 3.5): fetch_clauses, resolve_definitions, "
      "follow_xref, fetch_compliance")

print("\n" + "=" * 72)
print("2. HYBRID SEARCH + PARENT LIFTING (M1.4 / M2.2)")
print("=" * 72)
hits = backend.search("indemnify hold harmless third party intellectual property",
                      namespace=NS, top_k=4, mode=RetrievalMode.HYBRID)
for h in hits:
    print(f"   {h.span_id}  {h.metadata.chunk_type.value:<14} {h.metadata.clause_path:<22} "
          f"score={h.score:.3f}  {len(h.text)}ch")
assert all(h.metadata.chunk_type == ChunkType.CLAUSE_PARENT for h in hits), \
    "matched children were not lifted to parents"
assert not any(h.span_id.startswith("manifest") for h in hits)
print("   PASS: matched on children, returned whole clauses; sentinel excluded.")

print("\n" + "=" * 72)
print("3. FLOAT->INT COERCION AT THE METADATA BOUNDARY")
print("=" * 72)
h = hits[0]
print(f"   stored as float64, read back as: char_start={h.metadata.char_start!r} "
      f"({type(h.metadata.char_start).__name__}), page={h.metadata.page!r}")
assert isinstance(h.metadata.char_start, int) and isinstance(h.metadata.page, int)
print("   PASS: offsets are ints, so string slicing in V2 will not raise.")

print("\n" + "=" * 72)
print("4. STRUCTURAL EXPANSION — LADDER LEVEL 2 (deterministic traversal)")
print("=" * 72)
target = next(h for h in hits if h.metadata.clause_id.startswith("cls_09_02"))
print(f"   seed: {target.metadata.clause_id}  ({target.metadata.clause_path})")
exp = backend.expand_structural([target], namespace=NS)
for s in exp:
    print(f"     +-> {s.metadata.clause_id:<18} {s.metadata.clause_path}")
ids = {s.metadata.clause_id for s in exp}
assert "cls_09_03" in ids or any(i.startswith("cls_09_02_") for i in ids), ids
print("   PASS: provisos and/or the cross-referenced carve-out clause retrieved.")

print("\n" + "=" * 72)
print("5. V2 IS NOT CIRCULAR — the decisive test")
print("=" * 72)
from graph import citation_check
from schemas import Claim, ClaimType, Severity, PartyRole

good = Claim(claim_id="clm_001", clause_id=target.metadata.clause_id,
             claim_type=ClaimType.DESCRIPTIVE,
             proposition="The Service Provider gives an uncapped IP indemnity.",
             evidence_span_ids=[target.span_id], severity=Severity.HIGH,
             party_affected=PartyRole.SERVICE_PROVIDER)
print(f"   honest citation      -> {citation_check(good, backend, NS).value}")
assert citation_check(good, backend, NS).value == "VALID"

fake = good.model_copy(update={"claim_id": "clm_002", "evidence_span_ids": ["spn_ffff"]})
print(f"   fabricated span_id   -> {citation_check(fake, backend, NS).value}")
assert citation_check(fake, backend, NS).value == "INVALID_SPAN_ID"

# Tamper with the metadata copy of the text, leaving offsets untouched. This is
# the case a circular check cannot catch: metadata says one thing, the canonical
# document says another.
victim = index.store[NS][target.span_id]
original = victim["metadata"]["text"]
victim["metadata"]["text"] = original.replace("Service Provider", "Client", 1)
backend._span_cache.clear(); backend._clause_span_cache.clear()
verdict = citation_check(good, backend, NS).value
print(f"   tampered metadata    -> {verdict}")
assert verdict == "TEXT_MISMATCH", f"CIRCULAR CHECK: got {verdict}"
victim["metadata"]["text"] = original
backend._span_cache.clear(); backend._clause_span_cache.clear()
print("   PASS: V2 compares metadata against canonical text, not against itself.")

print("\n" + "=" * 72)
print("6. TENANT ISOLATION (M2.4)")
print("=" * 72)
try:
    backend.search("indemnity", namespace="tnt_999::doc_evil", top_k=3)
    print("   FAIL: foreign namespace accepted"); sys.exit(1)
except RetrievalError as e:
    print(f"   rejected: {str(e)[:88]}...")
print("   PASS: a namespace not derived from the job record cannot reach the client.")

print("\n" + "=" * 72)
print("7. END-TO-END — graph.py drives the Pinecone backend unchanged")
print("=" * 72)
from test_loop import FakeLLM
from schemas import ContractType

probe = backend.search("indemnify liability termination", namespace=NS, top_k=6)
script = {"mode": "converge", "drafted": False, "auditor_calls": 0, "critic_calls": 0,
          "span_a": probe[0].span_id, "span_b": probe[1].span_id, "span_c": probe[2].span_id}
G.set_llm_factory(lambda a: FakeLLM(a, script))
report = G.run_audit(backend, job_id="job_m2", tenant_id="tnt_221",
                     document_id="doc_7f3a", contract_type=ContractType.MSA)
print(f"   terminal_reason : {report.terminal_reason}")
print(f"   findings        : {len(report.findings)}")
print(f"   regenerated     : {sum(1 for c in report.findings if c.regeneration_count)}")
print(f"   auditor/critic  : {script['auditor_calls']}/{script['critic_calls']} calls")
assert report.terminal_reason == "converged"
assert all(c.terminal_state.value == "VERIFIED" for c in report.findings)
print("   PASS: SidecarRetriever -> PineconeRetriever swap required no node changes.")
print()
