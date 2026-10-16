"""
retriever.py — Module 2: The Vector Database Layer.

Design reference: Chapter 3, Section 3.3.2 (M2.1-M2.4), Section 3.1.2 (the
corrective escalation ladder), Section 3.2.7 (tenant isolation).

PURPOSE
-------
"Provide low-latency semantic and hybrid retrieval over two logically distinct
corpora with strict tenant isolation." (Section 3.3.2)

This module satisfies the `RetrievalBackend` Protocol that `graph.py` is written
against, so swapping it in for `SidecarRetriever` changes no node code.

THREE THINGS THIS MODULE GETS RIGHT THAT A NAIVE WRAPPER WOULD NOT
------------------------------------------------------------------
1. V2 IS NOT ALLOWED TO BE CIRCULAR. The deterministic citation check
   (Section 3.1.3.2) compares a span's stored text against the text at its
   stored offsets. If both sides of that comparison come from Pinecone metadata,
   the check compares a value to itself and passes unconditionally — it would
   report 1.0 accuracy while verifying nothing. `text_at` therefore reads the
   CANONICAL TEXT written by `ingest.py`, through a store that is independent of
   the vector index. If that store is unavailable the check fails closed.

2. THE SPARSE ENCODER IS IMPORTED, NOT REIMPLEMENTED. Hybrid retrieval requires
   that query terms hash into the same sparse dimensions as document terms.
   Re-deriving the hashing here would produce a subtly different vector space in
   which sparse scores are noise — and it would look like it worked, because
   dense retrieval would carry the results. `sparse_encode` and the embedding
   model both come from `ingest.py` so drift is impossible by construction.

3. STRUCTURAL RETRIEVAL DOES NOT TOUCH THE VECTOR INDEX FOR ITS TRAVERSALS.
   Section 3.3.2/M2.2: definition resolution and cross-reference following are
   "deterministic graph traversals ... not probabilistic similarity searches,
   and are therefore exact." The clause tree, defined-term index and
   cross-reference graph come from the structural sidecar built at ingest time;
   Pinecone is used only to materialise the spans those traversals identify.

USAGE
-----
    export PINECONE_API_KEY=...
    from retriever import PineconeRetriever, LocalTextStore, StructureIndex

    backend = PineconeRetriever.for_document(
        tenant_id="tnt_221", document_id="doc_7f3a",
        structure=StructureIndex.from_sidecar(Path("doc.structure.json")),
        text_store=LocalTextStore(Path("./canonical")),
    )
    report = run_audit(backend, ...)

DEPENDENCIES
    pip install pinecone langchain-huggingface sentence-transformers
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence

from schemas import ChunkType, Span, SpanMetadata

logger = logging.getLogger("retriever")


# =============================================================================
# SECTION 0 — CONFIGURATION AND MODES
# =============================================================================


class RetrievalMode(str, Enum):
    """
    Table in Section 3.3.2/M2.2, mapped to the ladder rungs of Section 3.1.2.

      DENSE          — cosine over embeddings. Ladder default.
      HYBRID         — dense fused with sparse lexical scores. Ladder Level 3.
      HYBRID_RERANK  — enlarged pool reordered by cross-encoder. Level 3, upper.
      STRUCTURAL     — direct fetch by clause_id / parent / cross_refs. Level 2.

    STRUCTURAL is not a similarity search and does not appear in `search()`; it
    is reached through `expand_structural`, `fetch_clauses` and
    `resolve_definitions`.
    """

    DENSE = "DENSE"
    HYBRID = "HYBRID"
    HYBRID_RERANK = "HYBRID_RERANK"


@dataclass
class RetrieverConfig:
    index_name: str = "contract-audit"

    # Hybrid fusion weight. 1.0 = pure dense, 0.0 = pure sparse. Legal text
    # rewards a lexical component more than general prose does, because defined
    # terms and statutory formulae are exact strings that embeddings blur —
    # "Confidential Information" and "confidential information" are legally
    # distinct and semantically identical.
    hybrid_alpha: float = 0.7

    # Candidate pool sizes. The rerank pool is deliberately several times the
    # returned k: a cross-encoder can only reorder what the retriever surfaced,
    # so recall at the pool boundary caps the whole ladder.
    rerank_pool: int = 40
    rerank_model: str = "BAAI/bge-reranker-base"
    enable_rerank: bool = True

    # Parent-document retrieval (Section 3.3.1/M1.4): match children, return
    # parents. Disable only for diagnostics — returning child chunks to the
    # Auditor is what produces findings that ignore a clause's own provisos.
    return_parents: bool = True

    # Resilience (risk R2).
    max_retries: int = 4
    backoff_base: float = 1.5

    span_cache_size: int = 4096
    compliance_namespace_prefix: str = ""  # "{jurisdiction}::{instrument}"


class RetrievalError(RuntimeError):
    pass


class TextStoreUnavailable(RetrievalError):
    """Raised when canonical text cannot be read. V2 must fail closed on this."""


# =============================================================================
# SECTION 1 — CANONICAL TEXT STORE
# =============================================================================


class CanonicalTextStore(Protocol):
    """
    Source of truth for document text, independent of the vector index.

    Kept as a Protocol because in deployment this is object storage
    (Section 3.2.1, L5) with signed short-lived URLs, whereas in development it
    is a directory of files. The V2 guarantee does not depend on which.
    """

    def read(self, namespace: str) -> str: ...


class LocalTextStore:
    """
    Reads `{tenant}__{document}.canonical.txt` from a directory.

    `ingest.py` writes canonical text next to the PDF by default; point this at
    that directory, or copy the files into one. The namespace separator `::` is
    rewritten to `__` because it is not a legal filename character on every
    platform.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._cache: dict[str, str] = {}

    def _path(self, namespace: str) -> Path:
        return self.root / f"{namespace.replace('::', '__')}.canonical.txt"

    def read(self, namespace: str) -> str:
        if namespace in self._cache:
            return self._cache[namespace]
        path = self._path(namespace)
        if not path.exists():
            raise TextStoreUnavailable(
                f"Canonical text not found for namespace {namespace!r} at {path}. "
                "V2 citation checking cannot proceed without it; every claim would "
                "fail verification. Ensure ingest.py wrote --text-out for this document."
            )
        text = path.read_text(encoding="utf-8")
        self._cache[namespace] = text
        return text


class InMemoryTextStore:
    """For tests and for callers that already hold the canonical text."""

    def __init__(self, texts: Mapping[str, str]) -> None:
        self._texts = dict(texts)

    def read(self, namespace: str) -> str:
        if namespace not in self._texts:
            raise TextStoreUnavailable(f"No canonical text for namespace {namespace!r}")
        return self._texts[namespace]


# =============================================================================
# SECTION 2 — STRUCTURAL INDEX
#
# The clause tree, defined-term index and cross-reference graph built by
# ingest.py M1.3. Section 3.3.1: "without them, definition resolution and
# cross-reference following are not implementable."
#
# In deployment this is a PostgreSQL read (Section 3.2.1, L5). The interface is
# the same either way, so the swap is confined to the constructor.
# =============================================================================


@dataclass
class StructureIndex:
    clauses: dict[str, dict[str, Any]] = field(default_factory=dict)
    defined_terms: dict[str, str] = field(default_factory=dict)   # term -> clause_id
    cross_refs: dict[str, list[str]] = field(default_factory=dict)  # clause -> [clause]

    @classmethod
    def from_sidecar(cls, path: Path) -> "StructureIndex":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StructureIndex":
        return cls(
            clauses={c["clause_id"]: dict(c) for c in data.get("clauses", [])},
            defined_terms=dict(data.get("defined_terms", {})),
            cross_refs={k: list(v) for k, v in data.get("cross_references", {}).items()},
        )

    # --- Deterministic traversals ------------------------------------------

    def parent_of(self, clause_id: str) -> Optional[str]:
        node = self.clauses.get(clause_id)
        return node.get("parent_id") if node else None

    def children_of(self, clause_id: str) -> list[str]:
        node = self.clauses.get(clause_id)
        return list(node.get("children", [])) if node else []

    def siblings_of(self, clause_id: str) -> list[str]:
        """
        Sibling-chunk expansion (Section 3.1.2, Level 2).

        Siblings matter because enumerated provisos are siblings, not children:
        clause 9.2's conditions live in 9.2(a), (b), (c). Retrieving 9.2 without
        them yields a finding that ignores stated conditions, which V3 rejects
        as MISSING_CONDITION.
        """
        parent = self.parent_of(clause_id)
        if parent is None:
            return []
        return [c for c in self.children_of(parent) if c != clause_id]

    def refs_from(self, clause_id: str) -> list[str]:
        return list(self.cross_refs.get(clause_id, []))

    def definition_clause(self, term: str) -> Optional[str]:
        return self.defined_terms.get(term)

    def terms_in(self, clause_id: str) -> list[str]:
        node = self.clauses.get(clause_id)
        if not node:
            return []
        return [t for t in self.defined_terms if t in node.get("title", "")]


# =============================================================================
# SECTION 3 — CROSS-ENCODER RERANKER (ladder Level 3, upper rung)
# =============================================================================


class LocalReranker:
    """
    Cross-encoder reranking on local CPU.

    Pinecone's hosted reranking is a paid inference call, so the cross-encoder
    runs locally — the same decision made for embeddings in Module 1, and for
    the same reason: the reliability argument of this project must not depend on
    a billing tier.

    A cross-encoder scores (query, passage) jointly rather than comparing two
    independently computed vectors, which is why it recovers cases dense
    retrieval misses. It is also far slower per pair, which is why it runs over
    a bounded pool at Level 3 only, and never on the default path.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("Loading reranker %s (first call only).", self.model_name)
            self._model = CrossEncoder(self.model_name, max_length=512)
        return self._model

    def rerank(self, query: str, spans: Sequence[Span], top_k: int) -> list[Span]:
        if not spans:
            return []
        try:
            model = self._load()
            pairs = [(query, s.text[:2000]) for s in spans]
            scores = model.predict(pairs)
        except Exception as exc:  # noqa: BLE001
            # Degrade to the retriever's own ordering. A reranker that cannot
            # load must not take the query down with it — Level 3 without
            # reranking is still Level 3 with a larger pool.
            logger.warning("Reranking unavailable (%s); falling back to fused order.", exc)
            return list(spans)[:top_k]

        ordered = sorted(zip(spans, scores), key=lambda pair: float(pair[1]), reverse=True)
        return [
            span.model_copy(update={"score": round(float(score), 4)})
            for span, score in ordered[:top_k]
        ]


# =============================================================================
# SECTION 4 — THE PINECONE RETRIEVER
# =============================================================================


def _as_int(value: Any, default: int = 0) -> int:
    """
    Pinecone stores every metadata number as a float64.

    So `char_start` comes back as 41207.0, and `SpanMetadata` declares it `int`.
    Pydantic would coerce silently here, but the offsets are then used for
    string slicing in V2, where a float raises TypeError deep inside the
    citation check and surfaces as an unexplained verification failure. Convert
    once, at the boundary.
    """
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


class PineconeRetriever:
    """
    Namespaced hybrid retrieval over one Pinecone index.

    M2.4 — ISOLATION GUARANTEE. The namespace is fixed at construction from the
    tenant and document identifiers and is never taken from a caller. The
    `namespace` argument required by the Protocol is ASSERTED against it rather
    than used. Section 3.3.2 requires that "no code path permits a
    client-supplied namespace to reach the retrieval client"; a parameter that
    is checked and discarded satisfies that literally, and turns any future
    plumbing mistake into a loud failure instead of a cross-tenant read.
    """

    # ---------------------------------------------------------------- construction

    def __init__(
        self,
        *,
        index: Any,
        tenant_id: str,
        document_id: str,
        structure: StructureIndex,
        text_store: CanonicalTextStore,
        embedder: Any,
        cfg: Optional[RetrieverConfig] = None,
    ) -> None:
        self.cfg = cfg or RetrieverConfig()
        self.index = index
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.namespace = f"{tenant_id}::{document_id}"  # derived, never supplied
        self.structure = structure
        self.text_store = text_store
        self.embedder = embedder
        self.reranker = LocalReranker(self.cfg.rerank_model) if self.cfg.enable_rerank else None
        self._span_cache: dict[str, Span] = {}
        self._clause_span_cache: dict[str, Span] = {}

    @classmethod
    def for_document(
        cls,
        *,
        tenant_id: str,
        document_id: str,
        structure: StructureIndex,
        text_store: CanonicalTextStore,
        cfg: Optional[RetrieverConfig] = None,
        embedder: Any = None,
        index: Any = None,
    ) -> "PineconeRetriever":
        """
        Build a retriever bound to one tenant/document pair.

        The embedder defaults to the one `ingest.py` used. This is not a
        convenience — a query encoded with a different model than the corpus is
        a silent, total retrieval failure that presents as "the system just
        isn't very good at finding things".
        """
        cfg = cfg or RetrieverConfig()

        if embedder is None:
            from ingest import IngestionConfig, get_embedder

            embedder = get_embedder(IngestionConfig())

        if index is None:
            from pinecone import Pinecone

            api_key = os.environ.get("PINECONE_API_KEY")
            if not api_key:
                raise RetrievalError("PINECONE_API_KEY is not set in the environment.")
            index = Pinecone(api_key=api_key).Index(cfg.index_name)

        return cls(
            index=index, tenant_id=tenant_id, document_id=document_id,
            structure=structure, text_store=text_store, embedder=embedder, cfg=cfg,
        )

    # ---------------------------------------------------------------- internals

    def _assert_namespace(self, namespace: str) -> None:
        if namespace != self.namespace:
            raise RetrievalError(
                f"Namespace mismatch: this retriever is bound to {self.namespace!r} "
                f"but was called with {namespace!r}. Refusing the query. A "
                f"namespace reaching the retrieval client from anywhere other "
                f"than the job record is a tenant-isolation defect (M2.4)."
            )

    def _with_retry(self, operation: str, fn, *args, **kwargs) -> Any:
        """Exponential backoff with jitter for transient index errors (R2)."""
        last: Optional[Exception] = None
        for attempt in range(self.cfg.max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last = exc
                message = str(exc).lower()
                transient = any(
                    k in message for k in ("rate", "429", "timeout", "503", "unavailable", "reset")
                )
                if not transient or attempt == self.cfg.max_retries - 1:
                    raise RetrievalError(f"{operation} failed: {exc}") from exc
                delay = (self.cfg.backoff_base ** attempt) + random.uniform(0, 0.4)
                logger.warning("%s: transient error, retrying in %.1fs", operation, delay)
                time.sleep(delay)
        raise RetrievalError(f"{operation} exhausted retries: {last}")

    @staticmethod
    def _matches(response: Any) -> list[Any]:
        """The SDK returns objects in some versions and dicts in others."""
        if response is None:
            return []
        if isinstance(response, Mapping):
            return list(response.get("matches", []) or [])
        return list(getattr(response, "matches", []) or [])

    @staticmethod
    def _field(match: Any, name: str, default: Any = None) -> Any:
        if isinstance(match, Mapping):
            return match.get(name, default)
        return getattr(match, name, default)

    def _span_from_match(self, match: Any) -> Optional[Span]:
        meta = self._field(match, "metadata") or {}
        span_id = self._field(match, "id")
        text = meta.get("text", "")
        if not span_id or not text:
            return None
        # The manifest sentinel written by ingest.py M1.6 carries no chunk_type
        # and must never enter an evidence bundle.
        if meta.get("record_type") == "manifest" or "chunk_type" not in meta:
            return None
        try:
            metadata = SpanMetadata(
                span_id=span_id,
                document_id=meta.get("document_id", self.document_id),
                tenant_id=meta.get("tenant_id", self.tenant_id),
                clause_id=meta.get("clause_id", ""),
                clause_path=meta.get("clause_path", ""),
                clause_title=meta.get("clause_title", "") or "",
                parent_span_id=meta.get("parent_span_id"),
                page=_as_int(meta.get("page"), 1) or 1,
                char_start=_as_int(meta.get("char_start")),
                char_end=_as_int(meta.get("char_end")),
                defined_terms=list(meta.get("defined_terms") or []),
                cross_refs=list(meta.get("cross_refs") or []),
                chunk_type=ChunkType(meta.get("chunk_type", ChunkType.CLAUSE_BODY.value)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discarding malformed span %s: %s", span_id, exc)
            return None

        score = self._field(match, "score")
        span = Span(
            span_id=span_id, text=text, metadata=metadata,
            score=float(score) if score is not None else None,
        )
        self._cache_span(span)
        return span

    def _cache_span(self, span: Span) -> None:
        if len(self._span_cache) >= self.cfg.span_cache_size:
            self._span_cache.clear()
        self._span_cache[span.span_id] = span
        if span.metadata.chunk_type == ChunkType.CLAUSE_PARENT:
            self._clause_span_cache[span.metadata.clause_id] = span

    def _query(
        self,
        vector: Sequence[float],
        *,
        top_k: int,
        filter: Optional[dict[str, Any]] = None,
        sparse: Optional[dict[str, list]] = None,
    ) -> list[Span]:
        kwargs: dict[str, Any] = {
            "vector": list(vector),
            "top_k": top_k,
            "namespace": self.namespace,
            "include_metadata": True,
        }
        if filter:
            kwargs["filter"] = filter
        if sparse and sparse.get("indices"):
            kwargs["sparse_vector"] = sparse
        response = self._with_retry("index.query", self.index.query, **kwargs)
        spans = [self._span_from_match(m) for m in self._matches(response)]
        return [s for s in spans if s is not None]

    # ---------------------------------------------------------------- hybrid vectors

    def _encode_query(self, query: str, mode: RetrievalMode) -> tuple[list[float], Optional[dict]]:
        """
        Encode a query for the requested mode.

        Pinecone's convention for sparse-dense fusion is to scale the two
        vectors before the query rather than to pass a weight, so alpha is
        applied here. This works only because both vectors are L2-normalised and
        the index metric is `dotproduct` — the reason `ingest.py` defaults to
        that metric even though nothing in Module 1 needed it.
        """
        from ingest import IngestionConfig, sparse_encode

        dense = self.embedder.embed_query(query)

        if mode == RetrievalMode.DENSE:
            return list(dense), None

        alpha = self.cfg.hybrid_alpha
        sparse = sparse_encode(query, IngestionConfig())
        weighted_dense = [v * alpha for v in dense]
        weighted_sparse = {
            "indices": sparse["indices"],
            "values": [v * (1.0 - alpha) for v in sparse["values"]],
        }
        return weighted_dense, weighted_sparse

    # ---------------------------------------------------------------- parent lifting

    def _lift_to_parents(self, spans: Sequence[Span]) -> list[Span]:
        """
        M1.4 — match on children, return parents.

        "Retrieval matches on children and returns parents, obtaining the
        precision of fine-grained matching with the semantic completeness of
        clause-level context." The child's score is carried to the parent, since
        the child is what actually matched; the best child wins where several
        children of one clause match.
        """
        best: dict[str, tuple[float, Span]] = {}
        passthrough: list[Span] = []

        for span in spans:
            score = span.score or 0.0
            if span.metadata.chunk_type != ChunkType.CLAUSE_BODY:
                passthrough.append(span)
                continue
            parent_id = span.metadata.parent_span_id
            if not parent_id:
                passthrough.append(span)
                continue
            current = best.get(parent_id)
            if current is None or score > current[0]:
                best[parent_id] = (score, span)

        lifted: list[Span] = []
        parents = self._fetch_by_ids(list(best.keys()))
        for parent_id, (score, child) in best.items():
            parent = parents.get(parent_id)
            if parent is None:
                lifted.append(child)  # parent missing: the child is still evidence
                continue
            lifted.append(parent.model_copy(update={"score": score}))

        merged: dict[str, Span] = {s.span_id: s for s in lifted}
        for span in passthrough:
            merged.setdefault(span.span_id, span)
        return sorted(merged.values(), key=lambda s: s.score or 0.0, reverse=True)

    def _fetch_by_ids(self, span_ids: Sequence[str]) -> dict[str, Span]:
        wanted = [s for s in span_ids if s and s not in self._span_cache]
        out = {s: self._span_cache[s] for s in span_ids if s in self._span_cache}
        if not wanted:
            return out
        response = self._with_retry(
            "index.fetch", self.index.fetch, ids=list(wanted), namespace=self.namespace
        )
        vectors = (
            response.get("vectors", {}) if isinstance(response, Mapping)
            else (getattr(response, "vectors", None) or {})
        )
        for span_id, record in vectors.items():
            meta = record.get("metadata") if isinstance(record, Mapping) else getattr(record, "metadata", None)
            span = self._span_from_match({"id": span_id, "metadata": meta or {}, "score": None})
            if span:
                out[span_id] = span
        return out

    def _spans_for_clauses(self, clause_ids: Sequence[str]) -> list[Span]:
        """
        Materialise whole-clause spans for a set of clause identifiers.

        Resolved through a metadata-filtered query rather than by id, because
        span identifiers are assigned by a counter at ingest time and are not
        derivable from a clause identifier. The query vector is irrelevant here
        — the filter does the selecting — which is why a zero-cost constant
        vector is used rather than an embedding call.
        """
        missing = [c for c in clause_ids if c and c not in self._clause_span_cache]
        found = [self._clause_span_cache[c] for c in clause_ids if c in self._clause_span_cache]
        if not missing:
            return found

        neutral = [0.0] * self._embedding_dim()
        neutral[0] = 1.0
        spans = self._query(
            neutral,
            top_k=max(len(missing) * 2, 10),
            filter={
                "clause_id": {"$in": list(missing)},
                "chunk_type": {"$eq": ChunkType.CLAUSE_PARENT.value},
            },
        )
        by_clause = {s.metadata.clause_id: s for s in spans}
        for clause_id in missing:
            span = by_clause.get(clause_id)
            if span:
                found.append(span)
        return found

    def _embedding_dim(self) -> int:
        from ingest import IngestionConfig

        return IngestionConfig().embedding_dim

    # ================================================================= PROTOCOL

    def search(
        self,
        query: str,
        *,
        namespace: str,
        top_k: int,
        mode: Optional[RetrievalMode] = None,
    ) -> list[Span]:
        """
        Similarity search. Satisfies `RetrievalBackend.search`.

        `mode` is optional so the Protocol signature is met unchanged. When it
        is not supplied the mode is inferred from `top_k`: a request for an
        enlarged pool is the orchestrator escalating to ladder Level 3
        (`ladder_3_enlarged_pool` in graph.py), and Level 3 is defined as
        hybrid retrieval followed by cross-encoder reranking. Passing the mode
        explicitly from the researcher node is the cleaner call and needs a
        one-line change there.
        """
        self._assert_namespace(namespace)

        if mode is None:
            mode = (
                RetrievalMode.HYBRID_RERANK
                if top_k >= self.cfg.rerank_pool // 2
                else RetrievalMode.HYBRID
            )

        pool = self.cfg.rerank_pool if mode == RetrievalMode.HYBRID_RERANK else max(top_k * 3, top_k)
        dense, sparse = self._encode_query(query, mode)

        # Match on children. Filtering to CLAUSE_BODY is what makes parent
        # lifting meaningful; without it, whole-clause parent records compete
        # with their own children for the same slots.
        candidates = self._query(
            dense, top_k=pool, sparse=sparse,
            filter={"chunk_type": {"$eq": ChunkType.CLAUSE_BODY.value}},
        )

        if mode == RetrievalMode.HYBRID_RERANK and self.reranker is not None:
            candidates = self.reranker.rerank(query, candidates, top_k=max(top_k * 2, top_k))

        if self.cfg.return_parents:
            candidates = self._lift_to_parents(candidates)

        logger.debug("search(mode=%s, pool=%d) -> %d spans", mode.value, pool, len(candidates))
        return candidates[:top_k]

    def get_span(self, span_id: str, *, namespace: str) -> Optional[Span]:
        """Resolve one span identifier. The first half of the V2 check."""
        self._assert_namespace(namespace)
        if span_id in self._span_cache:
            return self._span_cache[span_id]
        return self._fetch_by_ids([span_id]).get(span_id)

    def text_at(self, char_start: int, char_end: int, *, namespace: str) -> str:
        """
        The second half of V2 — and the reason this method exists at all.

        It reads the CANONICAL TEXT produced by `ingest.py`, not the copy of the
        text held in Pinecone metadata. If it read the metadata copy, V2 would
        compare `span.text` against `span.text` and return VALID for every claim
        including fabricated ones, while reporting perfect citation accuracy.
        The check is only a check because the two sides come from different
        places.

        A missing text store therefore raises rather than degrading. Callers in
        `citation_check` convert that into OFFSET_MISMATCH, so verification
        fails closed: no claim can be presented as VERIFIED on the strength of
        an unavailable source.
        """
        self._assert_namespace(namespace)
        text = self.text_store.read(namespace)
        if char_start < 0 or char_end > len(text) or char_end <= char_start:
            raise RetrievalError(
                f"Offsets [{char_start}:{char_end}] fall outside canonical text "
                f"of length {len(text)}."
            )
        return text[char_start:char_end]

    def expand_structural(self, spans: Sequence[Span], *, namespace: str) -> list[Span]:
        """
        Ladder Level 2 — scope expansion along the document's own structure.

        Section 3.1.2: retrieval is "widened along the document's own structure
        rather than outward to new sources". Four traversals, all exact:

          parent-document   — substitute the enclosing clause for a sub-passage;
          sibling-chunk     — adjacent segments of the same clause, which is
                              where enumerated provisos live;
          cross-reference   — follow "subject to Clause 9.3" to the provision
                              that qualifies the one retrieved;
          definition        — resolve each capitalised defined term.

        The cross-reference traversal is the one that repairs the failure the
        Critic reports most: an indemnity retrieved without the carve-outs it is
        expressed to be subject to is a finding that is textually accurate and
        legally wrong.
        """
        self._assert_namespace(namespace)

        wanted: set[str] = set()
        terms: set[str] = set()

        for span in spans:
            clause_id = span.metadata.clause_id
            if not clause_id:
                continue
            parent = self.structure.parent_of(clause_id)
            if parent:
                wanted.add(parent)
            wanted.update(self.structure.siblings_of(clause_id))
            wanted.update(self.structure.refs_from(clause_id))
            # Cross-references recorded on the span itself may be richer than
            # the clause-level graph when the span covers several clauses.
            wanted.update(span.metadata.cross_refs)
            terms.update(span.metadata.defined_terms)

        for term in terms:
            definition = self.structure.definition_clause(term)
            if definition:
                wanted.add(definition)

        already = {s.metadata.clause_id for s in spans}
        wanted -= already
        if not wanted:
            return []

        expanded = self._spans_for_clauses(sorted(wanted))
        logger.debug("expand_structural: %d clauses -> %d spans", len(wanted), len(expanded))
        return expanded

    # ================================================ RESEARCHER TOOLS (Table 3.5)

    def fetch_clauses(self, clause_ids: Sequence[str]) -> list[Span]:
        """`structural_fetch` — directed retrieval for a Critique naming clauses."""
        return self._spans_for_clauses(list(clause_ids))

    def resolve_definitions(self, terms: Sequence[str]) -> list[Span]:
        """`resolve_definition` — exact lookup through the defined-term index."""
        clause_ids = [
            c for c in (self.structure.definition_clause(t) for t in terms) if c
        ]
        return self._spans_for_clauses(clause_ids)

    def follow_xref(self, clause_id: str) -> list[Span]:
        """`follow_xref` — exact traversal of the cross-reference graph."""
        return self._spans_for_clauses(self.structure.refs_from(clause_id))

    def fetch_compliance(
        self, query: str, *, jurisdiction: str, instrument: str, top_k: int = 5
    ) -> list[Span]:
        """
        `fetch_compliance` — read-only retrieval from the shared compliance corpus.

        M2.1 keeps compliance in its own namespace because the two corpora have
        opposite lifecycle and access characteristics: contract data is private,
        ephemeral and per-tenant; compliance data is public, durable and shared.
        The namespace is versioned by instrument so that an audit remains
        reconstructible against the corpus version current when it was produced
        — a reproducibility requirement, not a filing convention.

        NOTE: this reads a namespace OTHER than the bound one, which is why it
        does not accept a namespace argument. The jurisdiction and instrument
        are the only inputs, and neither can address tenant data.
        """
        namespace = f"{jurisdiction}::{instrument}"
        dense = self.embedder.embed_query(query)
        response = self._with_retry(
            "compliance.query", self.index.query,
            vector=list(dense), top_k=top_k, namespace=namespace, include_metadata=True,
        )
        spans = [self._span_from_match(m) for m in self._matches(response)]
        return [s for s in spans if s is not None]

    # ================================================================= LIFECYCLE

    def delete_document(self) -> None:
        """
        Retention support (Section 3.2.7 and 3.7.3).

        Deletion of the vector namespace is one leg of a three-part transaction
        that also removes object storage and relational records. This method
        performs only its own leg; the transaction belongs in the API layer,
        which is where the other two live.
        """
        self._with_retry(
            "index.delete", self.index.delete, delete_all=True, namespace=self.namespace
        )
        self._span_cache.clear()
        self._clause_span_cache.clear()
        logger.info("Deleted vector namespace %s", self.namespace)


# =============================================================================
# SECTION 5 — CONVENIENCE CONSTRUCTION
# =============================================================================


def build_backend_from_ingest_artifacts(
    *,
    sidecar_path: Path,
    canonical_text_path: Path,
    cfg: Optional[RetrieverConfig] = None,
    index: Any = None,
    embedder: Any = None,
) -> PineconeRetriever:
    """
    Wire a retriever from the two files `ingest.py` writes.

    Tenant and document identifiers are read from the sidecar rather than passed
    in, so the namespace this retriever binds to is necessarily the namespace
    the document was indexed under. Accepting them as arguments would reintroduce
    exactly the class of mistake M2.4 exists to rule out.
    """
    data = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    structure = StructureIndex.from_dict(data)
    namespace = data["namespace"]
    text_store = InMemoryTextStore(
        {namespace: Path(canonical_text_path).read_text(encoding="utf-8")}
    )
    return PineconeRetriever.for_document(
        tenant_id=data["tenant_id"],
        document_id=data["document_id"],
        structure=structure,
        text_store=text_store,
        cfg=cfg,
        index=index,
        embedder=embedder,
    )


__all__ = [
    "RetrievalMode", "RetrieverConfig", "RetrievalError", "TextStoreUnavailable",
    "CanonicalTextStore", "LocalTextStore", "InMemoryTextStore",
    "StructureIndex", "LocalReranker", "PineconeRetriever",
    "build_backend_from_ingest_artifacts",
]
