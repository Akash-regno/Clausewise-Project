"""
ingest.py — Module 1: Data Ingestion and Embedding.

Design reference: Chapter 3, Section 3.3.1 (M1.1-M1.6), Section 3.3.2 (M2.1-M2.4).

PURPOSE
-------
Transform an uploaded PDF into a set of semantically coherent, structurally
annotated, retrievable spans "without destroying the internal referential
structure on which legal interpretation depends" (Section 3.3.1).

THE TWO THINGS THIS MODULE MUST NOT GET WRONG
---------------------------------------------
1. CHARACTER OFFSETS. Every span carries `page`, `char_start`, `char_end`
   against a canonical text. These are not diagnostics — they are the operands
   of the V2 citation check (Section 3.1.3.2), which is the system's only
   *deterministic* verification predicate, and of the evidence highlighting in
   the frontend (M4.3). If offsets drift, V2 silently degrades from a proof to
   a formality. The canonical text is therefore written to disk beside the
   index (`--text-out`) so V2 can re-derive span text and compare, rather than
   trusting the copy stored in vector metadata.

2. THE STRUCTURAL INDICES. The defined-term index and cross-reference graph
   built in `M1.3` are what make Level-2 corrective retrieval possible.
   Section 3.3.1: "without them, definition resolution and cross-reference
   following are not implementable." They are built here, at ingest time, once
   — not rediscovered by an agent at query time.

Section 3.6.1 rates clause segmentation as the project's "principal novel
engineering effort" with formatting variance as the main threat (risk R7). The
mitigation specified there — "graceful fallback to semantic chunking with
parent-child structure retained" — is implemented in `segment_clauses`, which
degrades to a single synthetic root clause rather than raising.

USAGE
-----
    export PINECONE_API_KEY=...
    python ingest.py --pdf contract.pdf \
                     --tenant-id tnt_221 \
                     --document-id doc_7f3a \
                     --contract-type MSA \
                     --index contract-audit

    # Parse and inspect without touching Pinecone or downloading a model:
    python ingest.py --pdf contract.pdf --tenant-id t --document-id d --dry-run

DEPENDENCIES
    pip install pypdf pydantic langchain-huggingface sentence-transformers pinecone

Heavy dependencies (pypdf, sentence-transformers, pinecone) are imported lazily
inside the functions that need them, so the parsing and segmentation layer can
be imported and unit-tested with no model download and no network access.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from schemas import ChunkType, ContractType, SpanMetadata

logger = logging.getLogger("ingest")


# =============================================================================
# SECTION 0 — CONFIGURATION
# =============================================================================


@dataclass
class IngestionConfig:
    """
    All tunables in one place.

    Chunk sizes are expressed in characters rather than tokens deliberately:
    offsets are the unit of traceability, so the pipeline reasons in the same
    unit end to end. all-MiniLM-L6-v2 truncates at 256 word-pieces (~1000-1200
    characters of English legal prose), so `child_target_chars` is set just
    below that ceiling — a child chunk larger than the encoder window is a chunk
    whose tail is silently unindexed.
    """

    # --- M1.1 upload validation ---
    max_file_bytes: int = 25 * 1024 * 1024
    max_pages: int = 300
    min_chars_per_page: int = 100  # text-layer detection threshold

    # --- M1.4 chunking ---
    child_target_chars: int = 900
    child_max_chars: int = 1400
    child_overlap_sentences: int = 1
    min_chunk_chars: int = 60  # below this, merge forward rather than index noise

    # --- M1.6 embedding and indexing ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embed_batch_size: int = 64
    upsert_batch_size: int = 100
    metadata_text_limit: int = 8000  # Pinecone metadata ceiling is 40KB/vector

    # --- M2.1 index topology ---
    index_name: str = "contract-audit"
    index_metric: str = "dotproduct"
    cloud: str = "aws"
    region: str = "us-east-1"

    # Hybrid dense-sparse support (ladder Level 3, Section 3.1.2).
    # Pinecone requires metric="dotproduct" for sparse-dense vectors, which is
    # why that is the default above: for L2-normalised vectors dot product and
    # cosine are identical, so this preserves the Level-3 option at zero cost.
    enable_sparse: bool = True
    sparse_dim: int = 2**20


# =============================================================================
# SECTION 1 — M1.1 UPLOAD VALIDATION
# =============================================================================


class IngestionError(RuntimeError):
    """Raised for conditions the user must be told about explicitly."""


def validate_upload(pdf_path: Path, cfg: IngestionConfig) -> None:
    """
    M1.1 — MIME/size/page-count checks and text-layer detection.

    Section 3.3.1: "Documents lacking an extractable text layer are rejected
    with an explanatory message, consistent with the OCR delimitation declared
    in Section 1.4.3." Rejecting loudly at the boundary is the correct
    behaviour — a scanned PDF that slips through produces an audit over empty
    evidence, which is precisely the silent failure this architecture exists to
    prevent.
    """
    from pypdf import PdfReader

    if not pdf_path.exists():
        raise IngestionError(f"File not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise IngestionError(f"Expected a .pdf file, got: {pdf_path.suffix!r}")

    size = pdf_path.stat().st_size
    if size == 0:
        raise IngestionError("File is empty.")
    if size > cfg.max_file_bytes:
        raise IngestionError(
            f"File is {size / 1e6:.1f} MB; the ceiling is "
            f"{cfg.max_file_bytes / 1e6:.0f} MB."
        )

    # Magic-number check. Trusting the extension is how a renamed file gets in.
    with pdf_path.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise IngestionError("File does not carry a PDF header; it may be renamed.")

    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the user
        raise IngestionError(f"PDF could not be opened: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        raise IngestionError("PDF is encrypted. Remove the password and retry.")

    n_pages = len(reader.pages)
    if n_pages == 0:
        raise IngestionError("PDF contains no pages.")
    if n_pages > cfg.max_pages:
        raise IngestionError(f"PDF has {n_pages} pages; the ceiling is {cfg.max_pages}.")

    # Text-layer detection: sample rather than extract everything twice.
    sample_idx = sorted({0, n_pages // 2, n_pages - 1})
    sampled_chars = 0
    for i in sample_idx:
        try:
            sampled_chars += len(reader.pages[i].extract_text() or "")
        except Exception:  # noqa: BLE001 - a bad page is a signal, not a crash
            continue
    if sampled_chars < cfg.min_chars_per_page * len(sample_idx):
        raise IngestionError(
            "No extractable text layer was found. This document appears to be a "
            "scan or image. OCR is outside the current scope — please supply a "
            "text-based PDF."
        )

    logger.info("Validation passed: %d pages, %.1f KB", n_pages, size / 1024)


# =============================================================================
# SECTION 2 — M1.2 PARSING WITH OFFSET PRESERVATION
# =============================================================================


@dataclass
class PageSpan:
    """Where one PDF page begins and ends in the canonical text."""

    page: int  # 1-based, as a human reads it
    char_start: int
    char_end: int


@dataclass
class ParsedDocument:
    """
    The canonical text plus the page map that makes any offset locatable.

    `text` is THE reference string for the whole system. Every char_start /
    char_end in every span, every citation the Critic checks, and every
    highlight the frontend draws is an index into this exact string. It is
    persisted alongside the index for that reason.
    """

    text: str
    pages: list[PageSpan]
    content_hash: str

    def page_for_offset(self, offset: int) -> int:
        """Binary search the page map. O(log n) per span, called once per chunk."""
        starts = [p.char_start for p in self.pages]
        idx = bisect.bisect_right(starts, offset) - 1
        idx = max(0, min(idx, len(self.pages) - 1))
        return self.pages[idx].page


def _normalise(raw: str) -> str:
    """
    Normalise extracted text WITHOUT changing its length.

    This constraint is the whole point. Any transformation that inserts or
    deletes characters invalidates every offset computed downstream, so
    normalisation is restricted to same-width substitutions: NFKC composition
    is skipped, ligatures are left alone, and only single-character
    replacements are applied. Whitespace is *not* collapsed here — collapsing
    runs of spaces would shift every subsequent offset.
    """
    # Same-width replacements only: each mapping is 1 char -> 1 char.
    table = {
        0x00A0: " ",  # non-breaking space
        0x2018: "'", 0x2019: "'",  # smart single quotes
        0x201C: '"', 0x201D: '"',  # smart double quotes
        0x2013: "-", 0x2014: "-",  # en/em dash
        0x00AD: " ",  # soft hyphen
        0x200B: " ",  # zero-width space
    }
    out = raw.translate(table)
    # Strip any remaining control characters by replacing with a space (1:1).
    out = "".join(
        ch if (ch in "\n\t" or unicodedata.category(ch)[0] != "C") else " " for ch in out
    )
    assert len(out) == len(raw), "normalisation must preserve length"
    return out


def parse_pdf(pdf_path: Path) -> ParsedDocument:
    """
    M1.2 — extract the text layer while preserving page indices and offsets.

    Section 3.3.1: "Offset preservation is not incidental: it is the mechanism
    by which a finding in the final report is later mapped back to a
    highlightable region of the original document."

    Pages are joined with a fixed two-character separator so the mapping from
    offset to page is exact rather than approximate.
    """
    import io
    from pypdf import PdfReader

    if isinstance(pdf_path, bytes):
        reader = PdfReader(io.BytesIO(pdf_path))
    elif hasattr(pdf_path, "read"):
        reader = PdfReader(pdf_path)
    else:
        reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    pages: list[PageSpan] = []
    cursor = 0
    separator = "\n\n"

    for i, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Page %d failed extraction (%s); treated as empty.", i, exc)
            page_text = ""
        page_text = _normalise(page_text)
        start = cursor
        parts.append(page_text)
        cursor += len(page_text)
        pages.append(PageSpan(page=i, char_start=start, char_end=cursor))
        if i < len(reader.pages):
            parts.append(separator)
            cursor += len(separator)

    text = "".join(parts)
    raw_bytes = pdf_path if isinstance(pdf_path, bytes) else Path(pdf_path).read_bytes()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    logger.info("Parsed %d pages, %d characters.", len(pages), len(text))
    return ParsedDocument(text=text, pages=pages, content_hash=content_hash)


# =============================================================================
# SECTION 3 — M1.3 STRUCTURAL SEGMENTATION
#
# "This stage encodes the domain specificity of the module." (Section 3.3.1)
# =============================================================================


@dataclass
class ClauseNode:
    """One node of the clause tree. Character spans are absolute into canonical text."""

    clause_id: str
    number: str                      # "9.2" or "9.2(a)"
    title: str
    level: int
    parent_id: Optional[str]
    char_start: int
    char_end: int
    path: str                        # "9 > 9.2"
    children: list[str] = field(default_factory=list)
    numeric_key: tuple[int, ...] = ()
    # Node kind. Needed because enumerated sub-clauses ((a), (b), (c)) are
    # SIBLINGS of one another but nest under the enclosing decimal clause; the
    # level of an enum node must be computed from its nearest non-enum ancestor,
    # not from whatever happens to be on top of the stack.
    is_heading: bool = False
    is_enum: bool = False
    enum_kind: str = ""              # "alpha" | "roman" | ""


# Heading conventions: ARTICLE / SECTION / SCHEDULE / ANNEXURE (Section 3.3.1).
HEADING_RE = re.compile(
    r"^\s{0,8}(ARTICLE|SECTION|SCHEDULE|ANNEXURE|ANNEX|EXHIBIT|APPENDIX|PART)\s+"
    r"([IVXLCDM]{1,7}|\d{1,3}|[A-Z])\b[.:\)]?\s*(.{0,120})$",
    re.IGNORECASE,
)

# Decimal numbering: 9.  9.2  9.2.1
DECIMAL_RE = re.compile(r"^\s{0,10}(\d{1,3}(?:\.\d{1,3}){0,4})[.)]?\s+(?=\S)(.{0,200})$")

# Alphabetic and roman sub-enumeration: (a) (iv)
ENUM_RE = re.compile(r"^\s{0,16}\(([a-zA-Z]{1,7}|[ivxlcdmIVXLCDM]{1,7})\)\s+(?=\S)")

_ROMAN = set("ivxlcdm")


# Single-character markers that are legal in BOTH sequences. `(i)` is the
# canonical ambiguity: it is the ninth letter and the first roman numeral.
_AMBIGUOUS_ENUM = {"i": "h", "v": "u", "x": "w"}


def _classify_enum(token: str, preceding_alpha: Optional[str]) -> str:
    """
    Decide whether an enumeration marker is alphabetic or roman.

    Multi-character tokens composed of roman characters are unambiguous. Single
    characters are not: `(i)` continues an alphabetic list only if `(h)` opened
    immediately before it under the same parent; otherwise it OPENS a roman
    list, since a roman list starts at `(i)` while an alphabetic list starts at
    `(a)`.

    Getting this wrong is not cosmetic. Misreading `(i)` as alphabetic makes the
    following `(ii)` a roman child OF it, so `(i)`, `(ii)`, `(iii)` — which are
    siblings enumerating three exceptions — become a nested chain. A retriever
    fetching the parent of `(iii)` would then return `(i)` rather than the
    operative clause, and the Critic's V3 MISSING_CONDITION check would be
    verifying against the wrong carve-out.
    """
    low = token.lower()
    if len(low) > 1:
        return "roman" if all(ch in _ROMAN for ch in low) else "alpha"
    if low in _AMBIGUOUS_ENUM:
        return "alpha" if preceding_alpha == _AMBIGUOUS_ENUM[low] else "roman"
    return "alpha"


def _numeric_key(number: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in number.split("."))
    except ValueError:
        return ()


def _clause_id(number: str) -> str:
    """
    'cls_09_2' from '9.2' — zero-padded per the metadata example in M1.5.

    Padding makes identifiers sort lexicographically in document order, which
    matters because `clause_path` prefix filtering (M2.3) is a string operation.
    """
    parts = []
    for seg in re.split(r"[.\(\)]", number):
        seg = seg.strip()
        if not seg:
            continue
        parts.append(f"{int(seg):02d}" if seg.isdigit() else seg.lower())
    return "cls_" + "_".join(parts)


def _plausible_successor(number: str, last_child: dict[tuple[int, ...], int]) -> bool:
    """
    Reject numeric false positives by requiring the numbering to be sequential.

    Without this guard a wrapped line such as "10.5 per cent of the fees shall
    be payable..." is indistinguishable from clause 10.5 by regex alone. Stray
    decimals in prose do not form a sequence, so sequence membership is the
    discriminator.

    THE TRADE-OFF, stated explicitly because it is the tunable that governs
    risk R7. Strict succession (`last == seen + 1`) maximises precision but
    rejects legitimate gaps, which occur at top level when sections are deleted
    from a drafting template (clause 4 followed by clause 9). The rule adopted
    is therefore asymmetric:

      - depth 1  : any forward jump is accepted (template gaps are common);
      - depth >1 : strict succession only (sub-clause gaps are rare, and this
                   is the depth at which prose false positives appear).

    Loosening the depth->1 rule trades precision for recall. Segmentation
    accuracy is measured on the benchmark (Section 3.6.1), so this constant is
    the thing to tune against that measurement rather than by intuition.
    """
    key = _numeric_key(number)
    if not key:
        return False
    parent, last = key[:-1], key[-1]
    if parent and parent not in last_child:
        return False  # references a parent clause that was never opened
    seen = last_child.get(parent)
    if seen is None:
        return last == 1  # first child of a parent with no children yet
    if last == 1:
        return True  # numbering restart, e.g. clause 1 inside a Schedule
    if len(key) == 1:
        return last > seen  # top level: tolerate template gaps
    return last == seen + 1  # deeper: strict succession


def segment_clauses(text: str) -> list[ClauseNode]:
    """
    M1.3 — build the clause tree.

    Walks the document line by line, maintaining a stack of open clauses. A
    clause closes when a sibling or shallower clause opens, or at end of text,
    so `char_end` of a parent covers all of its descendants — which is what
    makes parent-document retrieval (Level 2) return complete legal units.

    GRACEFUL DEGRADATION (risk R7). If the document uses no recognisable
    enumeration, the function returns a single synthetic root clause covering
    the whole text. The parent-child chunking downstream still applies, so the
    pipeline degrades to semantic chunking with structure retained rather than
    failing — the mitigation specified in Section 3.6.1.
    """
    nodes: dict[str, ClauseNode] = {}
    order: list[str] = []
    stack: list[ClauseNode] = []
    last_child: dict[tuple[int, ...], int] = {}
    last_alpha: dict[str, str] = {}   # base clause_id -> last alphabetic marker
    enum_counter = 0

    def close_to(level: int, end: int) -> None:
        while stack and stack[-1].level >= level:
            stack.pop().char_end = end

    def open_node(
        number: str,
        title: str,
        level: int,
        start: int,
        key: tuple[int, ...] = (),
        *,
        is_heading: bool = False,
        is_enum: bool = False,
        enum_kind: str = "",
    ) -> None:
        nonlocal enum_counter
        close_to(level, start)
        parent = stack[-1] if stack else None
        cid = _clause_id(number)
        if cid in nodes:  # numbering restart, e.g. Schedule 1 clause 1
            enum_counter += 1
            cid = f"{cid}_r{enum_counter}"
        node = ClauseNode(
            clause_id=cid,
            number=number,
            title=title.strip(" .:-")[:120],
            level=level,
            parent_id=parent.clause_id if parent else None,
            char_start=start,
            char_end=len(text),
            path=(f"{parent.path} > {number}" if parent else number),
            numeric_key=key,
            is_heading=is_heading,
            is_enum=is_enum,
            enum_kind=enum_kind,
        )
        if parent:
            parent.children.append(cid)
        nodes[cid] = node
        order.append(cid)
        stack.append(node)

    def enum_placement(token: str) -> tuple[int, str, str]:
        """
        Level, parent number and kind for an enumerated sub-clause.

        Levels are computed from the nearest NON-enum ancestor so that (a), (b),
        (c) come out as siblings. Taking the level from `stack[-1]` instead
        makes each marker a child of the previous one, producing a spurious
        chain 9.2(a) > 9.2(a)(b) > 9.2(a)(b)(c) — which then propagates into
        `clause_path` and breaks the prefix filtering of M2.3.

        Roman markers nest one level below any open alpha marker, since
        `(a) ... (i) ...` is the conventional ordering in legal drafting.
        """
        base = next((n for n in reversed(stack) if not n.is_enum), None)
        base_level = base.level if base else 0
        base_number = base.number if base else ""
        base_key = base.clause_id if base else "_root"

        kind = _classify_enum(token, last_alpha.get(base_key))
        if kind == "alpha":
            last_alpha[base_key] = token.lower()
            return base_level + 1, base_number, kind

        alpha = next(
            (n for n in reversed(stack) if n.is_enum and n.enum_kind == "alpha"), None
        )
        if alpha is not None:
            return alpha.level + 1, alpha.number, kind
        return base_level + 1, base_number, kind

    # Line offsets are tracked explicitly; str.splitlines() discards them.
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            offset += len(line)
            continue

        heading = HEADING_RE.match(line)
        decimal = DECIMAL_RE.match(line)
        enum = ENUM_RE.match(line)

        if heading:
            kw, num, title = heading.group(1).upper(), heading.group(2), heading.group(3)
            open_node(f"{kw[:3]}{num}", title, level=1, start=offset, is_heading=True)
            # NOTE: the decimal sequence is deliberately NOT reset here. Clause
            # numbering in commercial agreements runs continuously across
            # ARTICLE headings far more often than it restarts, and the
            # `last == 1` escape hatch in _plausible_successor already handles
            # the restart case (typical of SCHEDULE blocks).
        elif decimal and _plausible_successor(decimal.group(1), last_child):
            number, title = decimal.group(1), decimal.group(2)
            key = _numeric_key(number)
            last_child[key[:-1]] = key[-1]
            # Register this clause as an addressable parent, so that its own
            # children (9 -> 9.1) pass the plausibility guard. Without this the
            # guard rejects every sub-clause in the document.
            last_child.setdefault(key, 0)
            # A decimal clause sits one level below any enclosing heading.
            base = 1 if any(n.is_heading for n in stack) else 0
            open_node(number, title, level=base + len(key), start=offset, key=key)
        elif enum and stack:
            token = enum.group(1)
            level, parent_number, kind = enum_placement(token)
            open_node(
                f"{parent_number}({token})",
                title="",
                level=level,
                start=offset,
                is_enum=True,
                enum_kind=kind,
            )

        offset += len(line)

    close_to(0, len(text))

    if not nodes:
        logger.warning(
            "No clause structure detected; falling back to a single root clause "
            "(risk R7 degradation path)."
        )
        return [
            ClauseNode(
                clause_id="cls_00",
                number="0",
                title="DOCUMENT",
                level=0,
                parent_id=None,
                char_start=0,
                char_end=len(text),
                path="0",
            )
        ]

    result = [nodes[c] for c in order]

    # Preamble: text preceding the first numbered clause is legally meaningful
    # — party identification, recitals, effective date — and is frequently
    # where the governing-law and jurisdiction position is first stated. It
    # would otherwise be silently dropped, taking with it the very content the
    # jurisdiction check of Section 3.7.7 depends on.
    first_start = result[0].char_start
    if first_start >= 100:
        result.insert(
            0,
            ClauseNode(
                clause_id="cls_00",
                number="0",
                title="PREAMBLE AND RECITALS",
                level=0,
                parent_id=None,
                char_start=0,
                char_end=first_start,
                path="0",
            ),
        )

    logger.info("Segmented %d clauses.", len(result))
    return result


# --- Defined-term index ------------------------------------------------------

DEFINITION_PATTERNS = [
    # "Confidential Information" means / shall mean / refers to
    re.compile(
        r"[\"'\u201c\u2018]([A-Z][A-Za-z0-9 ,'\-]{2,60})[\"'\u201d\u2019]\s*"
        r"(?:\([^)]{0,40}\)\s*)?(?:shall\s+mean|means|shall\s+have\s+the\s+meaning|"
        r"refers\s+to|is\s+defined\s+as)\b"
    ),
    # Unquoted: Service Provider means ...
    re.compile(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\s+"
        r"(?:shall\s+mean|means|refers\s+to)\b"
    ),
]


def build_defined_term_index(text: str, clauses: Sequence[ClauseNode]) -> dict[str, str]:
    """
    M1.3 — map each defined term to the clause containing its definition.

    Consumed by Level-2 corrective retrieval: when a candidate span contains a
    capitalised defined term, the Researcher resolves the definition and
    includes it. Section 3.3.3.3 makes this mandatory — "a liability provision
    returned without its exceptions is an incomplete result."
    """
    index: dict[str, str] = {}
    starts = [c.char_start for c in clauses]

    for pattern in DEFINITION_PATTERNS:
        for match in pattern.finditer(text):
            term = match.group(1).strip()
            if len(term) < 3 or term.lower() in {"this", "the", "that"}:
                continue
            i = max(0, bisect.bisect_right(starts, match.start()) - 1)
            index.setdefault(term, clauses[i].clause_id)

    logger.info("Indexed %d defined terms.", len(index))
    return index


def _compile_term_matcher(terms: Iterable[str]) -> Optional[re.Pattern[str]]:
    """One alternation is far cheaper than N substring scans per chunk."""
    escaped = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    if not escaped:
        return None
    return re.compile(r"\b(" + "|".join(escaped) + r")\b")


# --- Cross-reference graph ---------------------------------------------------

XREF_RE = re.compile(
    r"\b(?:Clause|Section|Article|Paragraph|Sub-?clause|Schedule|Annexure|Exhibit)s?\s+"
    r"(\d{1,3}(?:\.\d{1,3}){0,4})",
    re.IGNORECASE,
)


def build_xref_graph(
    text: str, clauses: Sequence[ClauseNode]
) -> dict[str, list[str]]:
    """
    M1.3 — an edge from clause i to clause j wherever i explicitly references j.

    Section 3.3.2/M2.2 notes why this matters: cross-reference following is a
    "deterministic graph traversal ... not a probabilistic similarity search,
    and therefore exact." A clause that says "subject to Clause 9.3" has its
    meaning materially altered by 9.3; a retriever that returns one without the
    other has returned a misleading result, and the Critic's V3 predicate is
    designed to catch exactly that (MISSING_CONDITION).
    """
    # First occurrence wins. Clause numbering restarts inside SCHEDULE blocks,
    # so "1" can denote two different clauses; a plain dict comprehension would
    # silently bind every reference to the LAST such clause, pointing readers of
    # "Clause 1" at a schedule provision. Preferring document order at least
    # binds to the operative body of the agreement.
    by_number: dict[str, str] = {}
    for c in clauses:
        by_number.setdefault(c.number, c.clause_id)
    starts = [c.char_start for c in clauses]
    graph: dict[str, list[str]] = {}

    for match in XREF_RE.finditer(text):
        # Suppress self-matches on heading lines. "ARTICLE 1 DEFINITIONS" and
        # "SCHEDULE 1 SERVICE LEVELS" satisfy the reference pattern exactly,
        # so without this guard every heading in the document manufactures a
        # spurious edge to whichever clause happens to be numbered 1. A genuine
        # reference ("subject to Clause 9.3") always has text before it on the
        # line; a heading does not.
        line_start = text.rfind("\n", 0, match.start()) + 1
        if match.start() - line_start < 2:
            continue

        target_num = match.group(1)
        target_id = by_number.get(target_num)
        if not target_id:
            continue
        i = max(0, bisect.bisect_right(starts, match.start()) - 1)
        source_id = clauses[i].clause_id
        if source_id == target_id:
            continue
        graph.setdefault(source_id, [])
        if target_id not in graph[source_id]:
            graph[source_id].append(target_id)

    logger.info("Built %d cross-reference edges.", sum(len(v) for v in graph.values()))
    return graph


# =============================================================================
# SECTION 4 — M1.4 CLAUSE-AWARE PARENT-CHILD CHUNKING
# =============================================================================


@dataclass
class Chunk:
    """A unit destined for the index, carrying its full M1.5 metadata."""

    span_id: str
    text: str
    metadata: SpanMetadata


SENTENCE_END_RE = re.compile(r"(?<=[.;:!?])\s+(?=[\"'(\u201c]?[A-Z0-9(])")


def _split_sentences(text: str, base_offset: int) -> list[tuple[str, int, int]]:
    """Sentence split that returns absolute offsets, not just strings."""
    out: list[tuple[str, int, int]] = []
    cursor = 0
    for match in SENTENCE_END_RE.finditer(text):
        end = match.start()
        piece = text[cursor:end]
        if piece.strip():
            out.append((piece, base_offset + cursor, base_offset + end))
        cursor = match.end()
    tail = text[cursor:]
    if tail.strip():
        out.append((tail, base_offset + cursor, base_offset + len(text)))
    return out


def _own_text_span(node: ClauseNode, clauses_by_id: dict[str, ClauseNode]) -> tuple[int, int]:
    """
    The clause's own body — its span up to the start of its first child.

    Chunking a container clause's full span would duplicate all descendant text
    in the index, inflating cost and skewing similarity scores toward whichever
    clause happens to have the most sub-clauses.
    """
    if not node.children:
        return node.char_start, node.char_end
    first_child = min(
        (clauses_by_id[c] for c in node.children if c in clauses_by_id),
        key=lambda n: n.char_start,
        default=None,
    )
    if first_child is None:
        return node.char_start, node.char_end
    return node.char_start, max(node.char_start, first_child.char_start)


def chunk_document(
    doc: ParsedDocument,
    clauses: Sequence[ClauseNode],
    defined_terms: dict[str, str],
    xrefs: dict[str, list[str]],
    *,
    tenant_id: str,
    document_id: str,
    cfg: IngestionConfig,
) -> list[Chunk]:
    """
    M1.4 — parent-child chunking, with chunk boundaries that never cross clauses.

    "Retrieval matches on children and returns parents, obtaining the precision
    of fine-grained matching with the semantic completeness of clause-level
    context." (Section 3.3.1)

    Both units are indexed. Children carry `chunk_type=CLAUSE_BODY` and are what
    similarity search should filter to; parents carry `CLAUSE_PARENT` and exist
    so that Level-2 structural fetch by `parent_span_id` is a direct lookup
    rather than a second search.
    """
    clauses_by_id = {c.clause_id: c for c in clauses}
    matcher = _compile_term_matcher(defined_terms.keys())
    chunks: list[Chunk] = []
    counter = 0

    def next_span_id() -> str:
        nonlocal counter
        counter += 1
        return f"spn_{counter:04d}"

    def make_metadata(
        node: ClauseNode, start: int, end: int, chunk_type: ChunkType, parent: Optional[str]
    ) -> SpanMetadata:
        body = doc.text[start:end]
        terms = sorted({m.group(1) for m in matcher.finditer(body)}) if matcher else []
        return SpanMetadata(
            span_id="spn_0000",  # replaced by the caller; keeps construction in one place
            document_id=document_id,
            tenant_id=tenant_id,
            clause_id=node.clause_id,
            clause_path=node.path,
            clause_title=node.title,
            parent_span_id=parent,
            page=doc.page_for_offset(start),
            char_start=start,
            char_end=end,
            defined_terms=terms,
            cross_refs=xrefs.get(node.clause_id, []),
            chunk_type=chunk_type,
        )

    for node in clauses:
        if node.char_end <= node.char_start:
            continue

        # --- Parent record: the complete clause, the unit of legal meaning ---
        parent_span_id = next_span_id()
        parent_meta = make_metadata(
            node, node.char_start, node.char_end, ChunkType.CLAUSE_PARENT, None
        )
        parent_meta = parent_meta.model_copy(update={"span_id": parent_span_id})
        chunks.append(
            Chunk(
                span_id=parent_span_id,
                text=doc.text[node.char_start : node.char_end],
                metadata=parent_meta,
            )
        )

        # --- Child records: sentence-bounded windows over the clause's own body ---
        own_start, own_end = _own_text_span(node, clauses_by_id)
        own = doc.text[own_start:own_end]
        if len(own.strip()) < cfg.min_chunk_chars:
            continue

        sentences = _split_sentences(own, own_start)
        if not sentences:
            continue

        window: list[tuple[str, int, int]] = []
        window_len = 0

        def flush() -> None:
            nonlocal window, window_len
            if not window:
                return
            start, end = window[0][1], window[-1][2]
            if end - start >= cfg.min_chunk_chars:
                sid = next_span_id()
                meta = make_metadata(node, start, end, ChunkType.CLAUSE_BODY, parent_span_id)
                meta = meta.model_copy(update={"span_id": sid})
                chunks.append(Chunk(span_id=sid, text=doc.text[start:end], metadata=meta))
            overlap = window[-cfg.child_overlap_sentences :] if cfg.child_overlap_sentences else []
            window = list(overlap)
            window_len = sum(len(s[0]) for s in window)

        for sentence in sentences:
            s_len = len(sentence[0])
            # A single sentence longer than the encoder window is split on
            # character boundaries as a last resort; losing its tail silently
            # would be worse than an imperfect boundary.
            if s_len > cfg.child_max_chars:
                flush()
                text_, s_start, _ = sentence
                for off in range(0, s_len, cfg.child_target_chars):
                    piece_start = s_start + off
                    piece_end = min(s_start + off + cfg.child_target_chars, s_start + s_len)
                    sid = next_span_id()
                    meta = make_metadata(
                        node, piece_start, piece_end, ChunkType.CLAUSE_BODY, parent_span_id
                    )
                    meta = meta.model_copy(update={"span_id": sid})
                    chunks.append(
                        Chunk(span_id=sid, text=doc.text[piece_start:piece_end], metadata=meta)
                    )
                continue

            if window_len + s_len > cfg.child_target_chars and window:
                flush()
            window.append(sentence)
            window_len += s_len

        flush()

    logger.info(
        "Produced %d chunks (%d parents, %d children).",
        len(chunks),
        sum(1 for c in chunks if c.metadata.chunk_type == ChunkType.CLAUSE_PARENT),
        sum(1 for c in chunks if c.metadata.chunk_type == ChunkType.CLAUSE_BODY),
    )
    return chunks


def verify_offsets(chunks: Sequence[Chunk], doc: ParsedDocument) -> None:
    """
    Assert that every chunk's stored offsets reproduce its text exactly.

    This is the ingest-time rehearsal of the V2 citation check. If it fails
    here, every downstream citation is unverifiable, so it is worth the linear
    scan: a corrupted offset caught at ingest is a bug, the same offset caught
    in production is a false finding presented to a non-expert user.
    """
    for chunk in chunks:
        expected = doc.text[chunk.metadata.char_start : chunk.metadata.char_end]
        if expected != chunk.text:
            raise IngestionError(
                f"Offset integrity failure at {chunk.span_id}: stored offsets "
                f"[{chunk.metadata.char_start}:{chunk.metadata.char_end}] do not "
                f"reproduce the chunk text."
            )
    logger.info("Offset integrity verified for %d chunks.", len(chunks))


# =============================================================================
# SECTION 5 — M1.6 EMBEDDING AND INDEXING
# =============================================================================


def get_embedder(cfg: IngestionConfig):
    """
    HuggingFace local embeddings, L2-normalised (M1.6).

    Normalisation is set at the encoder rather than applied afterwards so that
    it cannot be forgotten at query time: with unit vectors, dot product equals
    cosine, which is what allows the index to use `dotproduct` — required for
    sparse-dense hybrid retrieval at ladder Level 3 — without changing the
    semantics of dense search.
    """
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:  # pragma: no cover - older stacks
        from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore

    return HuggingFaceEmbeddings(
        model_name=cfg.embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True, "batch_size": cfg.embed_batch_size},
    )


_TOKEN_RE = re.compile(r"[a-z][a-z0-9\-']{2,}")


def sparse_encode(text: str, cfg: IngestionConfig) -> dict[str, list]:
    """
    A dependency-free sparse term-frequency vector for hybrid retrieval.

    M1.6 requires that chunks be upserted "together with sparse term-frequency
    vectors supporting hybrid retrieval". Terms are hashed into a fixed space
    and weighted with sublinear tf, then L2-normalised so sparse and dense
    scores combine on a comparable scale. This is deliberately not full BM25:
    corpus statistics are unavailable at single-document ingest time, and a
    per-document IDF would be meaningless. Upgrading to BM25 with corpus
    statistics is a Level-3 refinement, not a Module-1 requirement.
    """
    from collections import Counter
    from math import log, sqrt

    counts = Counter(_TOKEN_RE.findall(text.lower()))
    if not counts:
        return {"indices": [], "values": []}
    weights = {
        (int(hashlib.md5(t.encode()).hexdigest()[:8], 16) % cfg.sparse_dim): 1.0 + log(c)
        for t, c in counts.items()
    }
    norm = sqrt(sum(v * v for v in weights.values())) or 1.0
    items = sorted(weights.items())
    return {"indices": [i for i, _ in items], "values": [v / norm for _, v in items]}


class PineconeIndexer:
    """
    M2.1/M2.4 — namespaced upsert with server-side namespace derivation.

    Section 3.3.2/M2.4: "The namespace parameter is derived server-side from the
    authenticated session and the job record. No code path permits a
    client-supplied namespace to reach the retrieval client." The namespace is
    therefore computed in `__init__` from tenant and document identifiers and is
    never accepted as an argument to `upsert`.
    """

    def __init__(self, cfg: IngestionConfig, tenant_id: str, document_id: str) -> None:
        from pinecone import Pinecone, ServerlessSpec

        api_key = os.environ.get("PINECONE_API_KEY")
        if not api_key:
            raise IngestionError("PINECONE_API_KEY is not set in the environment.")

        self.cfg = cfg
        self.namespace = f"{tenant_id}::{document_id}"  # derived, never supplied
        self._pc = Pinecone(api_key=api_key)

        existing = {ix["name"] for ix in self._pc.list_indexes()}
        if cfg.index_name not in existing:
            logger.info("Creating index %r (dim=%d, metric=%s).",
                        cfg.index_name, cfg.embedding_dim, cfg.index_metric)
            self._pc.create_index(
                name=cfg.index_name,
                dimension=cfg.embedding_dim,
                metric=cfg.index_metric,
                spec=ServerlessSpec(cloud=cfg.cloud, region=cfg.region),
            )
        self.index = self._pc.Index(cfg.index_name)

    # --- M1.6 idempotency ---------------------------------------------------

    def _sentinel_id(self, content_hash: str) -> str:
        return f"manifest_{content_hash[:16]}"

    def already_ingested(self, content_hash: str) -> bool:
        """
        "Ingestion is idempotent by content hash to prevent duplicate indexing
        on retry." (M1.6) A sentinel vector records completion, so a retry after
        a partial failure re-runs rather than leaving a half-populated
        namespace — the sentinel is written last, on purpose.
        """
        try:
            result = self.index.fetch(
                ids=[self._sentinel_id(content_hash)], namespace=self.namespace
            )
            vectors = getattr(result, "vectors", None) or {}
            return bool(vectors)
        except Exception as exc:  # noqa: BLE001 - absence is the normal path
            logger.debug("Idempotency probe returned %s; treating as not ingested.", exc)
            return False

    def _write_sentinel(self, content_hash: str, chunk_count: int) -> None:
        marker = [1.0] + [0.0] * (self.cfg.embedding_dim - 1)
        self.index.upsert(
            vectors=[{
                "id": self._sentinel_id(content_hash),
                "values": marker,
                "metadata": {
                    "record_type": "manifest",
                    "content_hash": content_hash,
                    "chunk_count": chunk_count,
                },
            }],
            namespace=self.namespace,
        )

    # --- Upsert -------------------------------------------------------------

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]],
               content_hash: str) -> int:
        if len(chunks) != len(vectors):
            raise IngestionError("Chunk and vector counts differ; refusing to upsert.")

        payload: list[dict[str, Any]] = []
        for chunk, vector in zip(chunks, vectors):
            meta = chunk.metadata.model_dump(mode="json", exclude_none=True)
            # Pinecone metadata accepts str / number / bool / list[str] only.
            meta["chunk_type"] = chunk.metadata.chunk_type.value
            meta["text"] = chunk.text[: self.cfg.metadata_text_limit]
            record: dict[str, Any] = {
                "id": chunk.span_id,
                "values": list(vector),
                "metadata": meta,
            }
            if self.cfg.enable_sparse:
                sparse = sparse_encode(chunk.text, self.cfg)
                if sparse["indices"]:
                    record["sparse_values"] = sparse
            payload.append(record)

        written = 0
        for i in range(0, len(payload), self.cfg.upsert_batch_size):
            batch = payload[i : i + self.cfg.upsert_batch_size]
            self.index.upsert(vectors=batch, namespace=self.namespace)
            written += len(batch)
            logger.info("Upserted %d/%d vectors.", written, len(payload))

        self._write_sentinel(content_hash, len(payload))
        return written

    def delete_namespace(self) -> None:
        """Retention support (Section 3.2.7): drop the whole document namespace."""
        self.index.delete(delete_all=True, namespace=self.namespace)


# =============================================================================
# SECTION 6 — ORCHESTRATION
# =============================================================================


def ingest_document(
    pdf_path: Path,
    *,
    tenant_id: str,
    document_id: str,
    contract_type: ContractType,
    cfg: Optional[IngestionConfig] = None,
    dry_run: bool = False,
    text_out: Optional[Path] = None,
    sidecar_out: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Run the full M1.1 - M1.6 pipeline and return an ingestion manifest.

    `dry_run` executes every deterministic stage — validation, parsing,
    segmentation, index construction, chunking, offset verification — and stops
    before embedding and upsert. Since those deterministic stages are where the
    domain-specific risk lives (R7), being able to inspect them without a model
    download or a network call is what makes the segmenter tunable.
    """
    cfg = cfg or IngestionConfig()

    validate_upload(pdf_path, cfg)                                   # M1.1
    doc = parse_pdf(pdf_path)                                        # M1.2
    clauses = segment_clauses(doc.text)                              # M1.3
    defined_terms = build_defined_term_index(doc.text, clauses)      # M1.3
    xrefs = build_xref_graph(doc.text, clauses)                      # M1.3
    chunks = chunk_document(                                         # M1.4 + M1.5
        doc, clauses, defined_terms, xrefs,
        tenant_id=tenant_id, document_id=document_id, cfg=cfg,
    )
    verify_offsets(chunks, doc)

    # Persist the canonical text. V2 citation checking resolves span offsets
    # against THIS file, not against metadata copies, so it must be durable.
    if text_out:
        text_out.write_text(doc.text, encoding="utf-8")
        logger.info("Canonical text written to %s", text_out)

    # Persist the structural indices. They are query-time inputs to Level-2
    # corrective retrieval and are expensive to rebuild.
    sidecar = {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "contract_type": contract_type.value,
        "content_hash": doc.content_hash,
        "namespace": f"{tenant_id}::{document_id}",
        "n_pages": len(doc.pages),
        "n_chars": len(doc.text),
        "clauses": [
            {
                "clause_id": c.clause_id, "number": c.number, "title": c.title,
                "level": c.level, "parent_id": c.parent_id, "path": c.path,
                "char_start": c.char_start, "char_end": c.char_end,
                "children": c.children,
            }
            for c in clauses
        ],
        "defined_terms": defined_terms,
        "cross_references": xrefs,
        "n_chunks": len(chunks),
    }
    if sidecar_out:
        sidecar_out.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        logger.info("Structural indices written to %s", sidecar_out)

    if dry_run:
        logger.info("Dry run complete; embedding and upsert skipped.")
        return {**sidecar, "upserted": 0, "dry_run": True}

    indexer = PineconeIndexer(cfg, tenant_id, document_id)
    if indexer.already_ingested(doc.content_hash):
        logger.info("Content hash already present in namespace; skipping (idempotent).")
        return {**sidecar, "upserted": 0, "skipped_duplicate": True}

    embedder = get_embedder(cfg)                                     # M1.6
    logger.info("Embedding %d chunks with %s ...", len(chunks), cfg.embedding_model)
    vectors = embedder.embed_documents([c.text for c in chunks])

    written = indexer.upsert(chunks, vectors, doc.content_hash)
    logger.info("Ingestion complete: %d vectors in namespace %r.", written, indexer.namespace)
    return {**sidecar, "upserted": written, "dry_run": False}


# =============================================================================
# SECTION 7 — CLI
# =============================================================================


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Module 1 — ingest a contract PDF into the vector index."
    )
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument(
        "--contract-type",
        default="MSA",
        choices=[t.value for t in ContractType],
    )
    parser.add_argument("--index", default=IngestionConfig.index_name)
    parser.add_argument("--text-out", type=Path, help="Where to write canonical text.")
    parser.add_argument("--sidecar-out", type=Path, help="Where to write structural indices.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and segment only; no model download, no network.")
    parser.add_argument("--no-sparse", action="store_true",
                        help="Disable sparse vectors (dense-only index).")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    )

    cfg = IngestionConfig(index_name=args.index, enable_sparse=not args.no_sparse)
    stem = args.pdf.stem
    text_out = args.text_out or args.pdf.with_name(f"{stem}.canonical.txt")
    sidecar_out = args.sidecar_out or args.pdf.with_name(f"{stem}.structure.json")

    try:
        manifest = ingest_document(
            args.pdf,
            tenant_id=args.tenant_id,
            document_id=args.document_id,
            contract_type=ContractType(args.contract_type),
            cfg=cfg,
            dry_run=args.dry_run,
            text_out=text_out,
            sidecar_out=sidecar_out,
        )
    except IngestionError as exc:
        # M1.1 rejections are user-facing messages, not stack traces.
        print(f"\nIngestion rejected: {exc}\n", file=sys.stderr)
        return 2

    print(
        f"\n  document   {manifest['document_id']}"
        f"\n  namespace  {manifest['namespace']}"
        f"\n  pages      {manifest['n_pages']}"
        f"\n  clauses    {len(manifest['clauses'])}"
        f"\n  terms      {len(manifest['defined_terms'])}"
        f"\n  xrefs      {sum(len(v) for v in manifest['cross_references'].values())}"
        f"\n  chunks     {manifest['n_chunks']}"
        f"\n  upserted   {manifest['upserted']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
