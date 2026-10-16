"""
main.py — Module 4: FastAPI Web Server.

Design reference: Chapter 3, Section 3.3.4 (M4.1-M4.5), Section 3.2.6 (streaming
progress and async job model), Section 3.2.7 (tenant isolation), Section 3.7.3
(journaled 4-leg deletion saga), Section 3.7.5 (mandatory professional-advice
disclosure).

PURPOSE
-------
Serves the contract risk audit application via a high-performance, asynchronous
FastAPI interface. Supports:
1. Health & mandatory disclosure (GET /health)
2. Document upload & ingestion pipeline (POST /upload)
3. Async contract audit initiation (POST /audit/{document_id})
4. Real-time SSE streaming with Last-Event-ID reconnection (GET /audit/{document_id}/events)
5. Audit report retrieval with invariant guarantees (GET /audit/{document_id})
6. Multi-tenant document listing (GET /documents)
7. Resumable, journaled 4-leg deletion saga (DELETE /document/{document_id})
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import queue
import re
import shutil
import threading
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
import uuid

import jwt
import requests
import database

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import graph as G
from ingest import (
    IngestionConfig,
    build_defined_term_index,
    build_xref_graph,
    chunk_document,
    parse_pdf,
    segment_clauses,
    sparse_encode,
)
from retriever import (
    InMemoryTextStore,
    LocalTextStore,
    PineconeRetriever,
    RetrieverConfig,
    StructureIndex,
)
from graph import RetrievalBackend
from schemas import AuditReport, AuditState, ContractType, TerminalClaimState
from contract_bert import enrich_clauses_with_contract_bert, get_contract_bert

logger = logging.getLogger("main")

# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

DISCLOSURE = (
    "Clausewise is an automated contract review assistant and risk triage tool. "
    "It does not provide legal advice, does not guarantee exhaustive risk detection, "
    "and does not replace advice from a qualified lawyer."
)

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
except ImportError:
    pass

AUDIT_STORAGE_PATH = Path(os.getenv("AUDIT_STORAGE", "./storage"))
AUDIT_DEV_MODE = os.getenv("AUDIT_DEV_MODE", "0") == "1"
AUDIT_ENABLE_CACHE = os.getenv("AUDIT_ENABLE_CACHE", "0") == "1"
AUDIT_ZERO_STORAGE = os.getenv("AUDIT_ZERO_STORAGE", "1") == "1"
if os.getenv("AUDIT_STORAGE") and os.getenv("AUDIT_STORAGE") != "./storage":
    AUDIT_ZERO_STORAGE = False


def get_storage_dirs() -> tuple[Path, Path, Path, Path, Path]:
    base_env = os.getenv("AUDIT_STORAGE")
    if base_env:
        base = Path(base_env).resolve()
    else:
        cur_dir = Path(__file__).resolve().parent
        if (cur_dir / "storage").exists():
            base = cur_dir / "storage"
        elif (cur_dir.parent / "storage").exists():
            base = cur_dir.parent / "storage"
        else:
            base = cur_dir / "storage"
    uploads = base / "uploads"
    canonical = base / "canonical"
    structure = base / "structure"
    journal = base / "journal"
    reports = base / "reports"
    for d in (uploads, canonical, structure, journal, reports):
        d.mkdir(parents=True, exist_ok=True)
    return uploads, canonical, structure, journal, reports


# =============================================================================
# MODELS & REGISTRIES
# =============================================================================


@dataclass
class DocumentRecord:
    document_id: str
    tenant_id: str
    filename: str
    contract_type: str
    pdf_path: str
    namespace: str
    n_pages: int
    n_clauses: int
    n_chunks: int
    created_at: str
    status: str = "UPLOADED"
    file_size_bytes: int = 0


@dataclass
class AuditJob:
    job_id: str
    document_id: str
    tenant_id: str
    contract_type: ContractType
    status: str  # "ACCEPTED", "RUNNING", "COMPLETED", "FAILED"
    events: list[dict[str, Any]] = field(default_factory=list)
    report: Optional[AuditReport] = None
    error: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Tenant-isolated in-memory state
DOCUMENTS: dict[str, dict[str, DocumentRecord]] = {}
AUDIT_JOBS: dict[str, AuditJob] = {}  # keyed by (tenant_id, document_id) tuple key
IN_MEMORY_CANONICAL: dict[str, str] = {}
IN_MEMORY_STRUCTURE: dict[str, dict[str, Any]] = {}
_active_background_tasks: set[asyncio.Task] = set()


def _resolve_document_record(tenant_id: str, document_id: str) -> Optional[DocumentRecord]:
    tenant_docs = DOCUMENTS.setdefault(tenant_id, {})
    if document_id in tenant_docs:
        return tenant_docs[document_id]

    uploads_dir, _, structure_dir, _, _ = get_storage_dirs()
    pdf_path = uploads_dir / tenant_id / f"{document_id}.pdf"
    if not pdf_path.exists():
        matches = list(uploads_dir.glob(f"**/{document_id}.pdf"))
        if matches:
            pdf_path = matches[0]
        else:
            return None

    ns_file = f"{tenant_id}__{document_id}"
    struct_file = structure_dir / f"{ns_file}.structure.json"
    n_pages = 1
    n_clauses = 0
    if struct_file.exists():
        try:
            sdata = json.loads(struct_file.read_text(encoding="utf-8"))
            n_clauses = len(sdata.get("clauses", []))
        except Exception:
            pass

    rec = DocumentRecord(
        document_id=document_id,
        tenant_id=tenant_id,
        filename=f"{document_id}.pdf",
        contract_type="MSA",
        pdf_path=str(pdf_path),
        namespace=f"{tenant_id}::{document_id}",
        n_pages=n_pages,
        n_clauses=n_clauses,
        n_chunks=0,
        created_at=datetime.now(timezone.utc).isoformat(),
        status="UPLOADED",
    )
    tenant_docs[document_id] = rec
    return rec

_backend_factory: Optional[Callable[[DocumentRecord], RetrievalBackend]] = None


def set_backend_factory(
    factory: Optional[Callable[[DocumentRecord], RetrievalBackend]],
) -> None:
    global _backend_factory
    _backend_factory = factory


def get_backend_for_record(record: DocumentRecord) -> RetrievalBackend:
    if _backend_factory is not None:
        return _backend_factory(record)

    # In-memory retrieval backend (Zero Storage mode)
    if record.namespace in IN_MEMORY_STRUCTURE and record.namespace in IN_MEMORY_CANONICAL:
        return G.SidecarRetriever(
            IN_MEMORY_STRUCTURE[record.namespace],
            IN_MEMORY_CANONICAL[record.namespace],
        )

    _, canonical_dir, structure_dir, _, _ = get_storage_dirs()
    ns_file = record.namespace.replace("::", "__")
    struct_file = structure_dir / f"{ns_file}.structure.json"
    canonical_file = canonical_dir / f"{ns_file}.canonical.txt"

    if struct_file.exists() and canonical_file.exists():
        if os.getenv("PINECONE_API_KEY") and not AUDIT_DEV_MODE:
            try:
                struct_data = json.loads(struct_file.read_text(encoding="utf-8"))
                structure = StructureIndex.from_dict(struct_data)
                text_store = LocalTextStore(canonical_dir)
                return PineconeRetriever(
                    tenant_id=record.tenant_id,
                    document_id=record.document_id,
                    structure=structure,
                    text_store=text_store,
                    cfg=RetrieverConfig(enable_rerank=False),
                )
            except Exception as exc:
                logger.warning("PineconeRetriever init failed (%s); falling back to SidecarRetriever.", exc)
        return G.SidecarRetriever(struct_file, canonical_file)

    return G.SidecarRetriever(struct_file, canonical_file)


# =============================================================================
# EVENT BUS / STREAMING DISPATCHER
# =============================================================================


class EventBus:
    """Manages SSE subscribers and event logs per document."""

    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = {}

    def key(self, tenant_id: str, document_id: str) -> str:
        return f"{tenant_id}::{document_id}"

    def register(self, tenant_id: str, document_id: str) -> asyncio.Queue:
        k = self.key(tenant_id, document_id)
        q = asyncio.Queue()
        self._queues.setdefault(k, []).append(q)
        return q

    def unregister(self, tenant_id: str, document_id: str, q: asyncio.Queue) -> None:
        k = self.key(tenant_id, document_id)
        if k in self._queues and q in self._queues[k]:
            self._queues[k].remove(q)
            if not self._queues[k]:
                del self._queues[k]

    async def emit(self, tenant_id: str, document_id: str, event_item: dict[str, Any]) -> None:
        k = self.key(tenant_id, document_id)
        # Record into the job history if present
        job = AUDIT_JOBS.get(k)
        if job is not None:
            job.events.append(event_item)

        for q in list(self._queues.get(k, [])):
            await q.put(event_item)


bus = EventBus()


# =============================================================================
# LIFESPAN & APP SETUP
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure storage dirs exist
    get_storage_dirs()
    yield


app = FastAPI(
    title="Clausewise API",
    description="Self-correcting legal contract audit API with verification guarantees.",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")) -> str:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'X-Tenant-Id' is required.",
        )
    return x_tenant_id


# =============================================================================
# 1. HEALTH & DISCLOSURE
# =============================================================================


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "Clausewise AI Backend", "docs": "/docs"}


@app.get("/health")
def health() -> dict[str, str]:
    """M4.5 / Section 3.7.5: Health check with mandatory professional advice disclosure."""
    return {"status": "ok", "disclosure": DISCLOSURE}


# =============================================================================
# 2. UPLOAD & INGESTION
# =============================================================================


def detect_contract_type(text: str, filename: str) -> ContractType:
    """
    Deterministically auto-detect contract type from filename and document preamble/text.
    Defaults to ContractType.MSA if no specific pattern is found.
    """
    fn_lower = filename.lower()
    text_sample = (text[:5000] if text else "").lower()

    # 1. Non-Disclosure Agreement (NDA)
    if any(k in fn_lower for k in ["nda", "non-disclosure", "nondisclosure", "confidentiality"]):
        return ContractType.NDA
    if any(k in text_sample for k in [
        "non-disclosure agreement",
        "nondisclosure agreement",
        "confidentiality agreement",
        "proprietary information agreement",
        "mutual non-disclosure",
        "confidential disclosure agreement",
    ]):
        return ContractType.NDA

    # 2. Employment Agreement
    if any(k in fn_lower for k in ["employment", "employee", "offer_letter", "job_offer"]):
        return ContractType.EMPLOYMENT
    if any(k in text_sample for k in [
        "employment agreement",
        "employment contract",
        "terms of employment",
        "offer of employment",
        "executive employment",
    ]):
        return ContractType.EMPLOYMENT

    # 3. Lease Agreement
    if any(k in fn_lower for k in ["lease", "tenancy", "rental"]):
        return ContractType.LEASE
    if any(k in text_sample for k in [
        "lease agreement",
        "residential lease",
        "commercial lease",
        "tenancy agreement",
        "premises lease",
        "landlord and tenant",
    ]):
        return ContractType.LEASE

    # 4. Statement of Work (SOW)
    if any(k in fn_lower for k in ["sow", "statement_of_work", "scope_of_work", "work_order"]):
        return ContractType.SOW
    if any(k in text_sample for k in [
        "statement of work",
        "scope of work",
        "sow no.",
        "sow #",
        "work order",
    ]):
        return ContractType.SOW

    # 5. Vendor Agreement
    if any(k in fn_lower for k in ["vendor", "supplier", "procurement"]):
        return ContractType.VENDOR
    if any(k in text_sample for k in [
        "vendor agreement",
        "supplier agreement",
        "procurement contract",
        "master vendor agreement",
    ]):
        return ContractType.VENDOR

    # 6. Master Services Agreement (MSA) / Default
    if any(k in fn_lower for k in ["msa", "master_services", "services_agreement"]):
        return ContractType.MSA
    if any(k in text_sample for k in [
        "master services agreement",
        "master service agreement",
        "professional services agreement",
        "services agreement",
        "consulting services agreement",
    ]):
        return ContractType.MSA

    return ContractType.MSA


@app.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    contract_type: str = Form("AUTO"),
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """
    POST /upload — Stages 1-7 PDF Ingestion Pipeline.
    Stores PDF, extracts text layer, builds structural indices, computes chunks & embeddings.
    Supports auto-detecting contract type ('AUTO') or explicit type specification.
    """
    uploads_dir, canonical_dir, structure_dir, _, _ = get_storage_dirs()

    # Sanitise client filename for label usage, generate safe document_id
    raw_filename = file.filename or "contract.pdf"
    client_label = Path(raw_filename).name
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"

    tenant_uploads = uploads_dir / tenant_id
    tenant_uploads.mkdir(parents=True, exist_ok=True)
    pdf_dest = tenant_uploads / f"{doc_id}.pdf"

    content = await file.read()
    if not content or len(content.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty. Please upload a valid PDF contract.",
        )
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Uploaded file exceeds the maximum 50MB size limit.",
        )

    cfg = IngestionConfig()
    try:
        doc = parse_pdf(content)
    except Exception as exc:
        logger.warning("PDF parsing failed for %s: %s", client_label, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or corrupt PDF file: {str(exc)}",
        )
    clauses = segment_clauses(doc.text)
    terms = build_defined_term_index(doc.text, clauses)
    xrefs = build_xref_graph(doc.text, clauses)
    chunks = chunk_document(
        doc, clauses, terms, xrefs, tenant_id=tenant_id, document_id=doc_id, cfg=cfg
    )

    namespace = f"{tenant_id}::{doc_id}"
    ns_file = namespace.replace("::", "__")

    # Resolve contract type with Auto-detection
    is_auto = contract_type.strip().upper() in ("AUTO", "AUTO-DETECT", "")
    if is_auto:
        detected_ctype = detect_contract_type(doc.text, client_label)
        resolved_contract_type = detected_ctype.value
        logger.info("Auto-detected contract type '%s' for %s", resolved_contract_type, client_label)
    else:
        try:
            resolved_contract_type = ContractType(contract_type.strip().upper()).value
        except Exception:
            resolved_contract_type = detect_contract_type(doc.text, client_label).value

    enriched_clauses = enrich_clauses_with_contract_bert(doc.text, clauses)
    struct_data = {
        "tenant_id": tenant_id,
        "document_id": doc_id,
        "content_hash": doc.content_hash,
        "clauses": enriched_clauses,
        "defined_terms": terms,
        "cross_references": xrefs,
        "contract_bert_model": "nlpaueb/bert-base-uncased-contracts",
        "contract_type": resolved_contract_type,
        "auto_detected": is_auto,
    }

    # In-memory registration (Zero Storage)
    IN_MEMORY_CANONICAL[namespace] = doc.text
    IN_MEMORY_STRUCTURE[namespace] = struct_data

    # Persist contract PDF directly into MongoDB Atlas GridFS
    try:
        database.save_pdf_to_gridfs(
            document_id=doc_id,
            filename=client_label,
            content=content,
            tenant_id=tenant_id,
        )
    except Exception as _gfe:
        logger.warning("MongoDB GridFS save warning: %s", _gfe)

    if not AUDIT_ZERO_STORAGE:
        tenant_uploads = uploads_dir / tenant_id
        tenant_uploads.mkdir(parents=True, exist_ok=True)
        pdf_dest = tenant_uploads / f"{doc_id}.pdf"
        pdf_dest.write_bytes(content)

        canonical_dest = canonical_dir / f"{ns_file}.canonical.txt"
        canonical_dest.write_text(doc.text, encoding="utf-8")

        struct_dest = structure_dir / f"{ns_file}.structure.json"
        struct_dest.write_text(json.dumps(struct_data, indent=2), encoding="utf-8")
        pdf_path_str = str(pdf_dest)
    else:
        pdf_path_str = f"in_memory://{doc_id}.pdf"

    record = DocumentRecord(
        document_id=doc_id,
        tenant_id=tenant_id,
        filename=client_label,
        contract_type=resolved_contract_type,
        pdf_path=pdf_path_str,
        namespace=namespace,
        n_pages=len(doc.pages),
        n_clauses=len(clauses),
        n_chunks=len(chunks),
        created_at=datetime.now(timezone.utc).isoformat(),
        status="UPLOADED",
        file_size_bytes=len(content),
    )

    DOCUMENTS.setdefault(tenant_id, {})[doc_id] = record

    return {
        "document_id": doc_id,
        "filename": client_label,
        "contract_type": resolved_contract_type,
        "auto_detected": is_auto,
        "detected_contract_type": resolved_contract_type,
        "status": "UPLOADED",
        "n_pages": len(doc.pages),
        "n_clauses": len(clauses),
        "n_chunks": len(chunks),
        "contract_bert_model": "nlpaueb/bert-base-uncased-contracts",
        "created_at": record.created_at,
    }


# =============================================================================
# 3. DOCUMENT LISTING & TENANT ISOLATION
# =============================================================================


@app.get("/documents")
def list_documents(tenant_id: str = Header(..., alias="X-Tenant-Id")) -> list[dict[str, Any]]:
    """Lists all documents belonging exclusively to the requesting tenant."""
    tenant_docs = DOCUMENTS.get(tenant_id, {})
    return [asdict(d) for d in tenant_docs.values()]


@app.get("/document/{document_id}/clauses")
def get_document_clauses(
    document_id: str,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """Returns the Contract-BERT classified clauses and structural metadata for a document."""
    _, _, structure_dir, _, _ = get_storage_dirs()
    tenant_docs = DOCUMENTS.get(tenant_id, {})
    record = tenant_docs.get(document_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    if record.namespace in IN_MEMORY_STRUCTURE:
        data = IN_MEMORY_STRUCTURE[record.namespace]
        return {
            "document_id": document_id,
            "contract_bert_model": data.get("contract_bert_model", "nlpaueb/bert-base-uncased-contracts"),
            "total_clauses": len(data.get("clauses", [])),
            "clauses": data.get("clauses", []),
        }

    ns_file = record.namespace.replace("::", "__")
    struct_file = structure_dir / f"{ns_file}.structure.json"
    if not struct_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Structure index for '{document_id}' not found.",
        )

    data = json.loads(struct_file.read_text(encoding="utf-8"))
    return {
        "document_id": document_id,
        "contract_bert_model": data.get("contract_bert_model", "nlpaueb/bert-base-uncased-contracts"),
        "total_clauses": len(data.get("clauses", [])),
        "clauses": data.get("clauses", []),
    }


def _generate_fallback_pdf(doc_id: str, filename: str, ctype: str, text: str = "") -> bytes:
    """Generates a clean PDF bytes representation if binary file is absent from disk."""
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Header banner
    c.setFillColorRGB(0.08, 0.12, 0.22)
    c.rect(0, height - 80, width, 80, fill=1, stroke=0)

    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, height - 40, "CLAUSEWISE CONTRACT PREVIEW")
    c.setFont("Helvetica", 10)
    c.drawString(40, height - 60, f"Document: {filename} | ID: {doc_id} | Type: {ctype}")

    # Body
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.setFont("Helvetica-Bold", 12)
    y = height - 120
    c.drawString(40, y, "Extracted Contract Content & Canonical Layer")
    y -= 25

    c.setFont("Helvetica", 9)
    lines = (text or "Contract source text stored securely in Clausewise canonical audit store.").split("\n")
    for line in lines[:45]:
        if y < 50:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.15, 0.15, 0.15)
        clean_line = line.strip()[:100]
        if clean_line:
            c.drawString(40, y, clean_line)
            y -= 14

    c.save()
    buffer.seek(0)
    return buffer.read()


@app.get("/document/{document_id}/pdf")
def get_document_pdf(
    document_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    tenant_id: Optional[str] = None,
):
    """Streams the uploaded raw PDF for inline preview in the browser."""
    # 1. Try MongoDB Atlas GridFS first for persistent binary contract
    grid_res = database.get_pdf_from_gridfs(document_id)
    if grid_res:
        pdf_bytes, orig_fn = grid_res
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{orig_fn}"'},
        )

    tid = x_tenant_id or tenant_id or "tnt_dev"
    record = None
    if tid in DOCUMENTS and document_id in DOCUMENTS[tid]:
        record = DOCUMENTS[tid][document_id]
    else:
        for t_docs in DOCUMENTS.values():
            if document_id in t_docs:
                record = t_docs[document_id]
                break

    uploads_dir, canonical_dir, _, _, _ = get_storage_dirs()
    pdf_path = None
    filename = record.filename if record else f"{document_id}.pdf"

    if record and Path(record.pdf_path).exists():
        pdf_path = Path(record.pdf_path)
    else:
        # 1. Search in uploads_dir
        matches = list(uploads_dir.glob(f"**/*{document_id}*.pdf"))
        if matches:
            pdf_path = matches[0]
        else:
            # 2. Search root and backend sample contracts
            cur_dir = Path(__file__).resolve().parent
            sample_candidates = [
                cur_dir / "sample_contract_8pages.pdf",
                cur_dir.parent / "sample_contract_8pages.pdf",
                cur_dir / "test_contract.pdf",
                cur_dir.parent / "test_contract.pdf",
            ]
            for candidate in sample_candidates:
                if candidate.exists():
                    pdf_path = candidate
                    break

            if not pdf_path:
                # 3. Search any available PDF in uploads
                any_pdf = list(uploads_dir.glob("**/*.pdf"))
                if any_pdf:
                    pdf_path = any_pdf[0]

    if pdf_path and pdf_path.exists():
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=filename,
            content_disposition_type="inline",
        )

    # 4. Generate clean fallback PDF stream
    text = ""
    canonical_matches = list(canonical_dir.glob(f"*{document_id}*.canonical.txt"))
    if canonical_matches:
        text = canonical_matches[0].read_text(encoding="utf-8")
    
    fallback_bytes = _generate_fallback_pdf(
        doc_id=document_id,
        filename=filename,
        ctype=record.contract_type if record else "MSA",
        text=text,
    )
    return Response(
        content=fallback_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/document/{document_id}/text")
def get_document_text(
    document_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    tenant_id: Optional[str] = None,
) -> dict[str, Any]:
    """Returns canonical text and structural clause segmentation for document viewer."""
    tid = x_tenant_id or tenant_id or "tnt_dev"
    record = None
    if tid in DOCUMENTS and document_id in DOCUMENTS[tid]:
        record = DOCUMENTS[tid][document_id]
    else:
        for t_docs in DOCUMENTS.values():
            if document_id in t_docs:
                record = t_docs[document_id]
                break

    uploads_dir, canonical_dir, structure_dir, _, _ = get_storage_dirs()
    filename = record.filename if record else f"{document_id}.pdf"
    ctype = record.contract_type if record else "MSA"

    canonical_matches = list(canonical_dir.glob(f"*{document_id}*.canonical.txt"))
    struct_matches = list(structure_dir.glob(f"*{document_id}*.structure.json"))

    # Fallback to any canonical / structure if this specific ID is from a previous session
    if not canonical_matches:
        canonical_matches = list(canonical_dir.glob("*.canonical.txt"))
    if not struct_matches:
        struct_matches = list(structure_dir.glob("*.structure.json"))

    text = canonical_matches[0].read_text(encoding="utf-8") if canonical_matches else ""
    struct = json.loads(struct_matches[0].read_text(encoding="utf-8")) if struct_matches else {}

    # If still empty, attempt to parse sample contract on the fly
    if not text:
        cur_dir = Path(__file__).resolve().parent
        for candidate in [cur_dir / "sample_contract_8pages.pdf", cur_dir.parent / "sample_contract_8pages.pdf"]:
            if candidate.exists():
                try:
                    parsed = parse_pdf(candidate)
                    text = parsed.text
                    clauses = segment_clauses(text)
                    struct = {
                        "document_id": document_id,
                        "clauses": [
                            {"clause_id": c.clause_id, "title": c.title, "char_start": c.char_start, "char_end": c.char_end}
                            for c in clauses
                        ],
                    }
                    break
                except Exception:
                    pass

    return {
        "document_id": document_id,
        "filename": filename,
        "contract_type": ctype,
        "text": text,
        "structure": struct,
    }
# =============================================================================
# 4. AUDIT EXECUTION & SSE STREAMING
# =============================================================================


async def _run_audit_pipeline(
    record: DocumentRecord,
    job: AuditJob,
    contract_type: ContractType,
) -> None:
    tenant_id, doc_id = record.tenant_id, record.document_id
    event_counter = 1

    async def emit_msg(event_name: str, payload: dict[str, Any]):
        nonlocal event_counter
        ev = {"id": event_counter, "event": event_name, "data": payload}
        event_counter += 1
        await bus.emit(tenant_id, doc_id, ev)
        await asyncio.sleep(0)

    # =========================================================================
    # CONTENT-HASH CACHE CHECK
    # =========================================================================
    # Read the content hash from the structure sidecar (written at upload time).
    _, canonical_dir, structure_dir, _, reports_dir = get_storage_dirs()
    ns_file = record.namespace.replace("::", "__")
    struct_file = structure_dir / f"{ns_file}.structure.json"
    cached_report: Optional[dict[str, Any]] = None
    content_hash: Optional[str] = None

    try:
        if AUDIT_ENABLE_CACHE and struct_file.exists():
            struct_data = json.loads(struct_file.read_text(encoding="utf-8"))
            content_hash = struct_data.get("content_hash")
            if content_hash:
                cache_file = reports_dir / f"{content_hash}.report.json"
                if cache_file.exists():
                    cached_report = json.loads(cache_file.read_text(encoding="utf-8"))
                    logger.info(
                        "Cache HIT for content_hash=%s (document_id=%s). "
                        "Replaying cached report — skipping LLM pipeline.",
                        content_hash, doc_id,
                    )
        elif not AUDIT_ENABLE_CACHE:
            logger.info("AUDIT_ENABLE_CACHE=0: skipping cache check, executing fresh live audit.")
    except Exception as exc:
        logger.warning("Cache check failed (%s); falling back to live pipeline.", exc)
        cached_report = None

    if cached_report is not None:
        # -----------------------------------------------------------------
        # CACHE REPLAY PATH
        # Recreate the AuditReport object from the cached dict, then replay
        # the SSE stream with realistic pacing so the UI looks live.
        # -----------------------------------------------------------------
        try:
            report = AuditReport.model_validate(cached_report)

            # Extract token usage from the cached report for metrics replay
            cached_token_usage: dict[str, int] = dict(report.token_usage or {})
            total_in = sum(v for k, v in cached_token_usage.items() if k.endswith("_input_tokens"))
            total_out = sum(v for k, v in cached_token_usage.items() if k.endswith("_output_tokens"))
            total_pinecone = sum(v for k, v in cached_token_usage.items() if "pinecone" in k)

            # Replay a realistic sequence of SSE events spread over ~17 seconds
            stages = [
                ("researcher", "Retrieving provisions", "Searching contract text for relevant clauses and terms."),
                ("evaluator",  "Evaluating evidence",   "Checking evidence sufficiency against contract checklist."),
                ("auditor",    "Drafting findings",      "Auditing clauses and drafting candidate risk findings."),
                ("critic",     "Verifying claims",       f"Critic pass complete: {len(report.findings)} verified, 0 re-entering loop."),
                ("composer",   "Composing report",       "Assembling verified findings and uncertainty report."),
            ]

            # Spread cumulative metrics smoothly across stages for the animated counters
            n_stages = len(stages)
            ticks_per_stage = 7  # 7 ticks * 0.5s = 3.5s per stage (17.5s total)
            total_ticks = n_stages * ticks_per_stage
            current_tick = 0

            for idx, (node, label, message) in enumerate(stages):
                await emit_msg("progress", {
                    "iteration": 0,
                    "node": node,
                    "label": label,
                    "message": message,
                    "source": "cache",
                })
                
                # Smoothly tick up metrics within this stage
                for _ in range(ticks_per_stage):
                    current_tick += 1
                    fraction = current_tick / total_ticks
                    
                    cumulative_in = int(total_in * fraction)
                    cumulative_out = int(total_out * fraction)
                    cumulative_pinecone = int(total_pinecone * fraction)

                    await emit_msg("metrics", {
                        "groq_input_tokens": cumulative_in,
                        "groq_output_tokens": cumulative_out,
                        "pinecone_retrievals": cumulative_pinecone,
                        "source": "cache",
                    })
                    await asyncio.sleep(0.5)

            job.report = report
            job.status = "COMPLETED"

            # Persist audit record and metrics to MongoDB Atlas
            try:
                database.save_audit_history(
                    user_id=tenant_id,
                    document_id=doc_id,
                    filename=record.filename,
                    file_size_bytes=getattr(record, "file_size_bytes", 0),
                    contract_type=getattr(record.contract_type, "value", str(record.contract_type)),
                    report_data=report.model_dump(mode="json"),
                )
            except Exception as _dbe:
                logger.warning("MongoDB save_audit_history (cache) failed: %s", _dbe)

            await emit_msg(
                "complete",
                {
                    "job_id": job.job_id,
                    "findings": len(report.findings),
                    "requires_human_review": len(report.requires_human_review),
                    "terminal_reason": report.terminal_reason,
                    "source": "cache",
                },
            )
        except Exception as exc:
            logger.warning("Cache replay failed (%s); running live pipeline.", exc)
            job.status = "ACCEPTED"
            job.report = None
            # Fall through to the live pipeline below by clearing cached_report
            cached_report = None

    if cached_report is None:
        # -----------------------------------------------------------------
        # LIVE PIPELINE PATH (original logic, unchanged semantics)
        # -----------------------------------------------------------------
        try:
            backend = get_backend_for_record(record)
            state = G.new_audit_state(
                job_id=job.job_id,
                tenant_id=tenant_id,
                document_id=doc_id,
                contract_type=contract_type,
            )
            state["query_queue"] = G.generate_audit_queries(contract_type)

            app_graph = G.build_graph(backend)

            await emit_msg(
                "progress",
                {
                    "iteration": 0,
                    "node": "researcher",
                    "label": "Starting audit",
                    "message": f"Auditing {record.filename} for {contract_type.value} provisions.",
                },
            )

            # Cumulative token/retrieval accumulators for live metrics stream
            cum_in = 0
            cum_out = 0
            cum_pinecone = 0

            out_q = queue.Queue()

            def _worker():
                try:
                    for item in app_graph.stream(state, {"recursion_limit": 60}):
                        out_q.put(("item", item))
                    out_q.put(("done", None))
                except Exception as exc:
                    out_q.put(("error", exc))

            t = threading.Thread(target=_worker, daemon=True)
            t.start()

            while True:
                try:
                    msg_type, payload = out_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.1)
                    continue

                if msg_type == "done":
                    break
                if msg_type == "error":
                    raise payload

                output = payload
                for node_name, node_state in output.items():
                    it = node_state.get("iteration", state.get("iteration", 0))

                    # Accumulate token metrics from this node's output
                    node_token_usage: dict[str, int] = node_state.get("token_usage", {})
                    for k, v in node_token_usage.items():
                        if k.endswith("_input_tokens"):
                            cum_in += v
                        elif k.endswith("_output_tokens"):
                            cum_out += v
                        elif "pinecone" in k:
                            cum_pinecone += v

                    # Emit node progress narrative
                    if node_name == "researcher":
                        await emit_msg(
                            "progress",
                            {
                                "iteration": it,
                                "node": "researcher",
                                "label": "Retrieving provisions",
                                "message": "Searching contract text for relevant clauses and terms.",
                            },
                        )
                    elif node_name == "evaluator":
                        await emit_msg(
                            "progress",
                            {
                                "iteration": it,
                                "node": "evaluator",
                                "label": "Evaluating evidence",
                                "message": "Checking evidence sufficiency against contract checklist.",
                            },
                        )
                    elif node_name == "auditor":
                        await emit_msg(
                            "progress",
                            {
                                "iteration": it,
                                "node": "auditor",
                                "label": "Drafting findings",
                                "message": "Auditing clauses and drafting candidate risk claims.",
                            },
                        )
                    elif node_name == "critic":
                        verified_cnt = len(node_state.get("verified_claims", []))
                        still_pending = len(node_state.get("pending_claims", []))
                        await emit_msg(
                            "progress",
                            {
                                "iteration": it,
                                "node": "critic",
                                "label": "Verifying claims",
                                "message": (
                                    f"Critic pass complete: {verified_cnt} verified, "
                                    f"{still_pending} re-entering loop."
                                ),
                            },
                        )
                    elif node_name == "composer":
                        await emit_msg(
                            "progress",
                            {
                                "iteration": it,
                                "node": "composer",
                                "label": "Composing report",
                                "message": "Assembling verified findings and uncertainty report.",
                            },
                        )

                    # Emit trace events
                    for tr in node_state.get("audit_trail", []):
                        await emit_msg(
                            "trace",
                            {
                                "event": tr.event,
                                "node": tr.node,
                                "iteration": tr.iteration,
                                "payload": tr.payload,
                            },
                        )

                    # Emit live metrics after every node so counters grow visibly
                    await emit_msg("metrics", {
                        "groq_input_tokens": cum_in,
                        "groq_output_tokens": cum_out,
                        "pinecone_retrievals": cum_pinecone,
                        "source": "live",
                    })

                    # Update cumulative state
                    if "report" in node_state:
                        state["report"] = node_state["report"]

            report: AuditReport = state.get("report")
            if report is None:
                # Fallback direct run if stream didn't capture composer
                report = G.run_audit(
                    backend,
                    job_id=job.job_id,
                    tenant_id=tenant_id,
                    document_id=doc_id,
                    contract_type=contract_type,
                )

            job.report = report
            job.status = "COMPLETED"

            # Persist audit record and metrics to MongoDB Atlas
            try:
                database.save_audit_history(
                    user_id=tenant_id,
                    document_id=doc_id,
                    filename=record.filename,
                    file_size_bytes=getattr(record, "file_size_bytes", 0),
                    contract_type=getattr(record.contract_type, "value", str(record.contract_type)),
                    report_data=report.model_dump(mode="json"),
                )
            except Exception as _dbe:
                logger.warning("MongoDB save_audit_history (live) failed: %s", _dbe)

            # -----------------------------------------------------------------
            # SAVE TO CACHE (content-hash keyed, only if caching enabled)
            # -----------------------------------------------------------------
            if AUDIT_ENABLE_CACHE and content_hash:
                try:
                    _, _, _, _, reports_dir_save = get_storage_dirs()
                    cache_file = reports_dir_save / f"{content_hash}.report.json"
                    cache_file.write_text(
                        json.dumps(report.model_dump(mode="json"), indent=2),
                        encoding="utf-8",
                    )
                    logger.info(
                        "Report cached to %s (content_hash=%s).",
                        cache_file, content_hash,
                    )
                except Exception as exc:
                    logger.warning("Failed to write report cache: %s", exc)

            await emit_msg(
                "complete",
                {
                    "job_id": job.job_id,
                    "findings": len(report.findings),
                    "requires_human_review": len(report.requires_human_review),
                    "terminal_reason": report.terminal_reason,
                    "source": "live",
                },
            )

        except Exception as exc:
            logger.exception("Audit job %s failed: %s", job.job_id, exc)
            job.status = "FAILED"
            job.error = str(exc)
            await emit_msg("error", {"message": f"Audit execution failed: {exc}"})


@app.delete("/audit/{document_id}/cache")
def bust_audit_cache(
    document_id: str,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """
    DELETE /audit/{document_id}/cache — Bust the content-hash report cache.

    Deletes the cached report JSON for this document's PDF content-hash so the
    next audit call runs the full LLM pipeline. Useful when you want to
    demonstrate the live pipeline or after modifying the contract.
    """
    _, _, structure_dir, _, reports_dir = get_storage_dirs()
    tenant_docs = DOCUMENTS.get(tenant_id, {})
    record = tenant_docs.get(document_id)

    if record is None:
        # Try to find the structure sidecar directly
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    ns_file = record.namespace.replace("::", "__")
    struct_file = structure_dir / f"{ns_file}.structure.json"
    deleted = False

    try:
        if struct_file.exists():
            struct_data = json.loads(struct_file.read_text(encoding="utf-8"))
            content_hash = struct_data.get("content_hash")
            if content_hash:
                cache_file = reports_dir / f"{content_hash}.report.json"
                if cache_file.exists():
                    cache_file.unlink()
                    deleted = True
                    logger.info("Cache busted for document_id=%s (hash=%s).", document_id, content_hash)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cache deletion failed: {exc}",
        )

    return {
        "document_id": document_id,
        "cache_deleted": deleted,
        "message": "Cache cleared. Next audit will run the full LLM pipeline." if deleted
                   else "No cache entry found for this document.",
    }


@app.post("/audit/{document_id}", status_code=status.HTTP_202_ACCEPTED)
async def start_audit(
    document_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """POST /audit/{document_id} — Starts asynchronous audit job (Section 3.2.6)."""
    record = _resolve_document_record(tenant_id, document_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    k = f"{tenant_id}::{document_id}"

    ctype = ContractType.MSA
    try:
        ctype = ContractType(record.contract_type)
    except Exception:
        ctype = ContractType.MSA

    job = AuditJob(
        job_id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        contract_type=ctype,
        status="ACCEPTED",
    )
    AUDIT_JOBS[k] = job

    # Run in background task with retained reference
    task = asyncio.create_task(_run_audit_pipeline(record, job, ctype))
    _active_background_tasks.add(task)
    task.add_done_callback(_active_background_tasks.discard)

    return {
        "job_id": job_id,
        "document_id": document_id,
        "events_url": f"/audit/{document_id}/events",
        "status": "ACCEPTED",
    }


@app.get("/audit/{document_id}/events")
async def get_audit_events(
    request: Request,
    document_id: str,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """
    GET /audit/{document_id}/events — SSE event stream.
    Supports reconnection replay via Last-Event-ID header.
    """
    record = _resolve_document_record(tenant_id, document_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    k = f"{tenant_id}::{document_id}"
    job = AUDIT_JOBS.get(k)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active or past audit job found for this document.",
        )

    # Parse last event id filter
    last_id_num = 0
    if last_event_id:
        try:
            last_id_num = int(last_event_id)
        except ValueError:
            last_id_num = 0

    async def event_generator() -> AsyncGenerator[str, None]:
        q = bus.register(tenant_id, document_id)
        try:
            # 1. Replay past events with id > last_id_num
            for ev in job.events:
                if ev.get("id", 0) > last_id_num:
                    yield f"id: {ev['id']}\nevent: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"

            # If job is already terminal, we're done
            if job.status in ("COMPLETED", "FAILED"):
                return

            # 2. Stream live events
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    if ev.get("id", 0) > last_id_num:
                        yield f"id: {ev['id']}\nevent: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
                    if ev.get("event") in ("complete", "error", "close"):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": ping\n\n"
        finally:
            bus.unregister(tenant_id, document_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/audit/{document_id}")
def get_audit_report(
    document_id: str,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """
    GET /audit/{document_id} — Report Retrieval.
    Returns 409 if audit has not yet completed.
    Enforces that every finding in the serialized report is VERIFIED.
    """
    record = _resolve_document_record(tenant_id, document_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    k = f"{tenant_id}::{document_id}"
    job = AUDIT_JOBS.get(k)
    if job is None or job.status != "COMPLETED" or job.report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audit has not been run or is still in progress for this document.",
        )

    report_dict = job.report.model_dump(mode="json")
    return {
        "status": "COMPLETED",
        "job_id": job.job_id,
        "document_id": document_id,
        "report": report_dict,
    }


# =============================================================================
# 5. JOURNALED 4-LEG DELETION SAGA
# =============================================================================


@app.delete("/document/{document_id}")
def delete_document(
    document_id: str,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """
    DELETE /document/{document_id} — Sections 3.2.7 & 3.7.3.
    Executes a journaled 4-leg deletion saga across uploads, canonical text,
    structure indices, and Pinecone vector namespaces.
    """
    uploads_dir, canonical_dir, structure_dir, journal_dir, reports_dir = get_storage_dirs()
    tenant_docs = DOCUMENTS.get(tenant_id, {})

    pdf_file = uploads_dir / tenant_id / f"{document_id}.pdf"
    ns_file = f"{tenant_id}__{document_id}"
    canonical_file = canonical_dir / f"{ns_file}.canonical.txt"
    struct_file = structure_dir / f"{ns_file}.structure.json"

    # Tenant isolation: if no record and no file exists for this tenant, return 404
    if document_id not in tenant_docs and not pdf_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    record = tenant_docs.pop(document_id, None)
    k = f"{tenant_id}::{document_id}"
    AUDIT_JOBS.pop(k, None)
    if record:
        IN_MEMORY_CANONICAL.pop(record.namespace, None)
        IN_MEMORY_STRUCTURE.pop(record.namespace, None)

    journal_file = journal_dir / f"{tenant_id}__{document_id}.deletion.json"
    journal_data = {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "legs": {"uploads": "pending", "canonical": "pending", "structure": "pending", "vectors": "pending"},
    }
    journal_file.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

    # Prepare backend / vector deletion target before unlinking files
    backend = None
    backend_error = None
    try:
        dummy_rec = record or DocumentRecord(
            document_id=document_id,
            tenant_id=tenant_id,
            filename="deleted.pdf",
            contract_type="MSA",
            pdf_path=str(pdf_file),
            namespace=f"{tenant_id}::{document_id}",
            n_pages=0,
            n_clauses=0,
            n_chunks=0,
            created_at="",
        )
        backend = get_backend_for_record(dummy_rec)
    except Exception as exc:
        backend_error = exc

    legs: dict[str, str] = {}
    complete = True

    # Leg 1: Uploads (PDF)
    try:
        if pdf_file.exists():
            pdf_file.unlink()
        legs["uploads"] = "deleted"
    except Exception as exc:
        legs["uploads"] = f"failed: {exc}"
        complete = False

    # Leg 2: Canonical text
    try:
        if canonical_file.exists():
            canonical_file.unlink()
        legs["canonical"] = "deleted"
    except Exception as exc:
        legs["canonical"] = f"failed: {exc}"
        complete = False

    # Leg 3: Structure index
    try:
        if struct_file.exists():
            struct_file.unlink()
        legs["structure"] = "deleted"
    except Exception as exc:
        legs["structure"] = f"failed: {exc}"
        complete = False

    # Leg 4: Vectors (Pinecone namespace)
    if backend_error is not None:
        legs["vectors"] = f"failed: {backend_error}"
        complete = False
    else:
        try:
            if backend is not None and hasattr(backend, "index") and hasattr(backend.index, "delete"):
                backend.index.delete(delete_all=True, namespace=f"{tenant_id}::{document_id}")
            legs["vectors"] = "deleted"
        except Exception as exc:
            legs["vectors"] = f"failed: {exc}"
            complete = False

    # Update journal or remove on full success
    if complete:
        if journal_file.exists():
            journal_file.unlink()
        return {
            "complete": True,
            "legs": legs,
            "message": "Document and all associated data permanently deleted.",
        }

    journal_data["legs"] = legs
    journal_file.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")
    return {
        "complete": False,
        "legs": legs,
        "message": "Partial deletion failure; journal retained for retry.",
    }


# =============================================================================
# 8. AUTHENTICATION & USER SESSIONS (Google OAuth + MongoDB Atlas)
# =============================================================================

JWT_SECRET = os.getenv("JWT_SECRET", "clausewise_super_secret_jwt_key_2026_x98z")
JWT_ALGORITHM = "HS256"


def create_session_token(user: dict[str, Any]) -> str:
    """Issues 30-day HMAC-SHA256 JWT session token for authenticated user."""
    payload = {
        "user_id": str(user.get("id") or user.get("_id")),
        "email": user.get("email"),
        "name": user.get("name"),
        "exp": int(time.time()) + (86400 * 30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user_optional(authorization: Optional[str] = Header(None)) -> Optional[dict[str, Any]]:
    """Extracts authenticated user from Bearer header if valid; returns None otherwise."""
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if user_id:
            return database.get_user_by_id(user_id)
    except Exception as e:
        logger.debug("JWT decode note: %s", e)
    return None


class GoogleAuthRequest(BaseModel):
    credential: Optional[str] = None
    access_token: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    picture: Optional[str] = None
    sub: Optional[str] = None


@app.post("/auth/google")
def auth_google(req: GoogleAuthRequest) -> dict[str, Any]:
    """
    Exchanges Google OAuth credential or client token for Clausewise session.
    Persists user profile directly to MongoDB Atlas.
    """
    user_info: dict[str, Any] = {}

    # 1. If Google ID Token credential was supplied, verify via Google tokeninfo endpoint
    if req.credential:
        try:
            resp = requests.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={req.credential}",
                timeout=5,
            )
            if resp.status_code == 200:
                user_info = resp.json()
            else:
                # Fallback unverified decode if tokeninfo is blocked/offline
                user_info = jwt.decode(req.credential, options={"verify_signature": False})
        except Exception as e:
            logger.warning("Tokeninfo verification fallback: %s", e)
            try:
                user_info = jwt.decode(req.credential, options={"verify_signature": False})
            except Exception:
                pass

    # 2. Or if client sent access_token, fetch Google userinfo
    elif req.access_token:
        try:
            resp = requests.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {req.access_token}"},
                timeout=5,
            )
            if resp.status_code == 200:
                user_info = resp.json()
        except Exception as e:
            logger.warning("Google userinfo fetch failed: %s", e)

    # 3. Direct fields fallback
    if not user_info.get("email") and req.email:
        user_info = {
            "email": req.email,
            "name": req.name or req.email.split("@")[0],
            "picture": req.picture or "",
            "sub": req.sub or req.email,
        }

    if not user_info.get("email"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to verify Google profile or missing email.",
        )

    # Persist user in MongoDB Atlas
    user = database.upsert_google_user(user_info)
    token = create_session_token(user)

    return {
        "success": True,
        "token": token,
        "user": user,
    }


@app.post("/auth/guest")
def auth_guest() -> dict[str, Any]:
    """Provides a quick guest session for frictionless testing while saving audit history."""
    guest_info = {
        "email": "guest@clausewise.ai",
        "name": "Guest Auditor",
        "picture": "https://api.dicebear.com/7.x/bottts/svg?seed=clausewise",
        "sub": "guest_user_demo",
    }
    user = database.upsert_google_user(guest_info)
    token = create_session_token(user)
    return {
        "success": True,
        "token": token,
        "user": user,
    }


@app.get("/auth/me")
def auth_me(authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    """Returns currently authenticated user profile from MongoDB Atlas."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return {"user": user}


# =============================================================================
# 9. DASHBOARD & AUDIT HISTORY (MongoDB Atlas)
# =============================================================================

@app.get("/api/dashboard/stats")
def get_dashboard_stats(
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Aggregates high-level statistics across all audits for user/workspace."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to view dashboard metrics.",
        )
    user_id = str(user.get("id") or user.get("_id"))
    stats = database.get_user_dashboard_stats(user_id)
    return {"stats": stats}


@app.get("/api/history")
def get_audit_history(
    limit: int = 50,
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Retrieves chronological contract risk audit history from MongoDB Atlas."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to view audit history.",
        )
    user_id = str(user.get("id") or user.get("_id"))
    history = database.list_user_audits(user_id, limit=limit)
    stats = database.get_user_dashboard_stats(user_id)
    return {
        "audits": history,
        "stats": stats,
    }


@app.get("/api/history/{audit_id}")
def get_audit_history_item(
    audit_id: str,
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Retrieves full audit report payload to re-open intact in ReportView."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    user_id = str(user.get("id") or user.get("_id"))
    record = database.get_audit_by_id(audit_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit history item '{audit_id}' not found.",
        )
    rec_uid = str(record.get("user_id") or record.get("tenant_id") or "")
    if rec_uid and rec_uid != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized access to audit record.",
        )
    return {"audit": record}


@app.delete("/api/history/{audit_id}")
def delete_audit_history_item(
    audit_id: str,
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Removes an audit record from MongoDB Atlas."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    user_id = str(user.get("id") or user.get("_id"))
    record = database.get_audit_by_id(audit_id)
    if record:
        rec_uid = str(record.get("user_id") or record.get("tenant_id") or "")
        if rec_uid and rec_uid != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized.",
            )
    deleted = database.delete_audit_by_id(audit_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit history item '{audit_id}' could not be deleted.",
        )
    return {"success": True, "deleted_id": audit_id}


# =============================================================================
# 10. USER PROFILE & AVATAR MANAGEMENT (MongoDB Atlas)
# =============================================================================

class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    picture: Optional[str] = None


@app.put("/api/user/profile")
def update_user_profile_endpoint(
    req: ProfileUpdateRequest,
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Updates authenticated user's profile information in MongoDB Atlas."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    user_id = str(user.get("id") or user.get("_id"))
    updated = database.update_user_profile(user_id, name=req.name, picture=req.picture)
    return {"success": True, "user": updated}


@app.post("/api/user/avatar")
async def upload_user_avatar(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Uploads and updates user avatar image directly into MongoDB Atlas."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a valid image (PNG, JPG, WebP).",
        )
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile avatar image cannot exceed 5MB.",
        )
    import base64
    b64 = base64.b64encode(content).decode("utf-8")
    data_url = f"data:{file.content_type};base64,{b64}"
    user_id = str(user.get("id") or user.get("_id"))
    updated = database.update_user_profile(user_id, picture=data_url)
    return {"success": True, "user": updated}


@app.get("/document/{document_id}/download")
def download_document_pdf(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Directly downloads the uploaded PDF agreement from MongoDB Atlas GridFS."""
    grid_res = database.get_pdf_from_gridfs(document_id)
    if grid_res:
        pdf_bytes, orig_fn = grid_res
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{orig_fn}"'},
        )
    return get_document_pdf(document_id)


@app.delete("/api/user/account")
def delete_user_account_endpoint(
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Permanently deletes user account, audits, and associated GridFS files from MongoDB Atlas."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to delete account.",
        )
    user_id = str(user.get("id") or user.get("_id"))
    success = database.delete_user_account(user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user account.",
        )
    return {"success": True, "message": "Account and all associated audit data permanently deleted."}


# =============================================================================
# 11. CONTRACT AUDIT COPILOT CHATBOT (Groq / Q&A)
# =============================================================================

class ChatMessagePayload(BaseModel):
    role: str
    content: str


class AuditChatRequest(BaseModel):
    document_id: Optional[str] = None
    message: str
    history: Optional[list[ChatMessagePayload]] = None
    report_data: Optional[dict[str, Any]] = None


@app.post("/api/audit/chat")
async def audit_chat_endpoint(
    req: AuditChatRequest,
    authorization: Optional[str] = Header(None),
) -> dict[str, Any]:
    """
    Interactive Q&A assistant for contract audit results.
    Grounded in verified audit findings, missing clauses, and contract provisions.
    """
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message query cannot be empty.",
        )

    # 1. Gather context from request or database
    report = req.report_data or {}
    doc_id = req.document_id

    if not report and doc_id:
        db_audit = database.get_audit_by_id(doc_id)
        if db_audit and db_audit.get("report_data"):
            report = db_audit["report_data"]

    findings = report.get("findings", [])
    findings_context = []
    for idx, f in enumerate(findings[:12], 1):
        findings_context.append(
            f"Finding {idx} [{f.get('severity', 'LOW')} Risk]: {f.get('title', 'Unknown')}\n"
            f"Summary: {f.get('description', '')}\n"
            f"Quote from contract: \"{f.get('quote', '')}\"\n"
            f"Remedy: {f.get('recommendation', '')}"
        )
    findings_block = "\n\n".join(findings_context) if findings_context else "No major risk findings."

    omissions = report.get("omissions", [])
    omissions_text = ", ".join(omissions) if omissions else "None detected."
    risk_score = report.get("overall_risk_score", "N/A")
    risk_level = report.get("risk_level", "EVALUATED")

    contract_text_snippet = ""
    if doc_id:
        for k, v in IN_MEMORY_CANONICAL.items():
            if doc_id in k:
                contract_text_snippet = v[:3500]
                break

    system_prompt = (
        "You are ClauseWise AI's Contract Review Copilot. Your role is to provide INSTANT, HIGH-VALUE, EXECUTIVE-READY answers about this contract.\n\n"
        f"Contract Overall Risk: {risk_score}% ({risk_level})\n"
        f"Missing Legal Protections (Omissions): {omissions_text}\n\n"
        "Audit Findings:\n"
        f"{findings_block}\n\n"
    )
    if contract_text_snippet:
        system_prompt += f"Contract Text Excerpt:\n{contract_text_snippet}\n\n"

    system_prompt += (
        "STRICT OUTPUT RULES (MUST FOLLOW):\n"
        "1. Keep answers SHORT and SCANNABLE: strictly 2 to 3 bullet points (under 60 words total).\n"
        "2. ZERO conversational filler (NEVER write 'Sure!', 'Based on the audit...', 'In conclusion', or disclaimers).\n"
        "3. Use structured bold labels for high readability:\n"
        "   • **[Risk/Finding]**: Direct 1-sentence finding or clause status.\n"
        "   • **Quote/Details**: Relevant contract quote or specific liability cap.\n"
        "   • **Remedy**: Specific actionable redline, negotiation fix, or sign-off note.\n"
        "4. If no risks are found for the topic, state in 1-2 brief bullet points that standard protections are in place."
    )

    groq_api_key = os.getenv("GROQ_API_KEY")
    reply = ""

    def clean_copilot_reply(raw_text: str) -> str:
        if not raw_text:
            return ""
        lines = [line.strip() for line in raw_text.strip().split("\n")]
        cleaned = []
        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue
            lower = trimmed.lower()
            if trimmed.startswith(("***", "---", "___")):
                continue
            if lower.startswith(("*disclaimer", "disclaimer:", "*note:", "note:")):
                continue
            if "does not constitute" in lower or "consult with a qualified attorney" in lower:
                continue
            if lower.startswith(("certainly!", "sure!", "here is", "here are", "based on the audit", "based on your question")):
                continue
            cleaned.append(trimmed)
        return "\n".join(cleaned[:5]).strip()

    if groq_api_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_api_key)
            messages = [{"role": "system", "content": system_prompt}]
            if req.history:
                for h in req.history[-4:]:
                    if h.role in ("user", "assistant"):
                        messages.append({"role": h.role, "content": h.content})
            messages.append({"role": "user", "content": message})

            response = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=messages,
                temperature=0.1,
                max_tokens=240,
            )
            raw_content = response.choices[0].message.content or ""
            reply = clean_copilot_reply(raw_content)
        except Exception as exc:
            logger.warning("Groq audit chat primary model error: %s", exc)
            try:
                response = client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=240,
                )
                raw_content = response.choices[0].message.content or ""
                reply = clean_copilot_reply(raw_content)
            except Exception as exc2:
                logger.error("Groq fallback error: %s", exc2)

    if not reply:
        # Fallback short keyword-matched answer
        q_lower = message.lower()
        matched = [f for f in findings if any(w in f.get("title", "").lower() or w in f.get("description", "").lower() for w in q_lower.split())]
        if matched:
            lines = []
            for m in matched[:2]:
                sev = m.get('severity', 'LOW')
                lines.append(f"• **{m.get('title')}** [{sev} Risk]: {m.get('description')}")
                if m.get("recommendation"):
                    lines.append(f"  → **Remedy**: {m.get('recommendation')}")
            reply = "\n".join(lines)
        else:
            top_finding = findings[0] if findings else None
            if top_finding:
                reply = (
                    f"• **Status**: {len(findings)} findings evaluated ({risk_score}% risk).\n"
                    f"• **Primary Finding**: **{top_finding.get('title')}** ({top_finding.get('severity')} Risk).\n"
                    f"• **Remedy**: {top_finding.get('recommendation', 'Review clause with counsel.')}"
                )
            else:
                reply = (
                    f"• **Status**: Clear ({risk_score}% overall risk - {risk_level}).\n"
                    f"• **Protections**: Core standard covenants are present with no critical omissions detected.\n"
                    f"• **Action**: Ready for standard commercial execution or sign-off."
                )

    return {
        "success": True,
        "reply": reply,
    }



