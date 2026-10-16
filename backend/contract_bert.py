"""
contract_bert.py — Contract-BERT Integration & Clause Classification Module.

Reference:
- Model: nlpaueb/bert-base-uncased-contracts (Chalkidis et al., AUEB NLP Group)
- Architecture:
    PDF Upload & Text Extraction
               ↓
      Contract-BERT Module
  (Generates 768-dim clause representations from contract-tuned BERT)
               ↓
    Clause Classifier Layer
  (Labels clauses into categories: payment, termination, liability, etc.)
               ↓
  Researcher → Auditor → Critic (Existing RAG & Verification Workflow)

PURPOSE:
1. Process individual contract clauses through the domain-specific Contract-BERT model.
2. Generate dense 768-dimensional contextual representations for each clause.
3. Classify and label clauses into standard legal categories (payment, termination,
   liability, confidentiality, indemnification, etc.).
4. Enrich the structural index (structure.json) so the agentic RAG loop
   (Researcher/Evaluator/Auditor) can leverage contract-domain clause classification.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("clausewise.contract_bert")

# Canonical clause taxonomy
CANONICAL_CLAUSE_CATEGORIES: dict[str, str] = {
    "payment": (
        "Fees, payment terms, compensation, invoicing schedule, late payment interest, "
        "rates, billing currency, taxes, reimbursement of expenses, payment obligations."
    ),
    "termination": (
        "Termination of agreement, termination for convenience, termination for cause, "
        "notice period for cancellation, default, breach and cure period, effect of termination, survival."
    ),
    "limitation_of_liability": (
        "Limitation of liability, aggregate liability cap, exclusion of consequential damages, "
        "indirect damages, maximum recoverable amount, disclaimer of lost profits."
    ),
    "confidentiality": (
        "Confidential information, non-disclosure obligations, trade secrets, protection of proprietary data, "
        "permitted disclosures, return or destruction of confidential materials."
    ),
    "indemnification": (
        "Indemnification, defence and hold harmless, third-party claims, indemnity obligations, "
        "defence procedures, settlement authorization, gross negligence exclusions."
    ),
    "governing_law": (
        "Governing law, choice of law, jurisdiction, venue, applicable state or national legal statutory code, "
        "submission to court jurisdiction."
    ),
    "intellectual_property": (
        "Intellectual property rights, ownership of work product, assignment of inventions, copyright, "
        "patent, trademark, proprietary technology, license grants."
    ),
    "warranties": (
        "Representations and warranties, warranty disclaimer, express warranties, implied warranty of merchantability, "
        "fitness for particular purpose, as-is condition."
    ),
    "force_majeure": (
        "Force majeure, acts of God, unexpected natural disasters, strikes, pandemic, war, government action, "
        "excused delay in contractual performance."
    ),
    "dispute_resolution": (
        "Dispute resolution, binding arbitration, mediation, executive escalation procedures, "
        "informal negotiation, American Arbitration Association (AAA) or ICC rules."
    ),
    "assignment": (
        "Assignment and transfer of agreement, subcontracting, change of control restrictions, "
        "successors and permitted assigns, prior written consent for transfer."
    ),
    "term_duration": (
        "Term of agreement, effective date, initial term, renewal periods, extension of duration, "
        "expiration date."
    ),
    "general_obligation": (
        "General contractual covenant, miscellaneous provisions, notices, severability, amendments, "
        "entire agreement clause, waivers."
    ),
}


class ContractBERTModule:
    """
    Contract-BERT representation generator and clause classifier.
    Loads nlpaueb/bert-base-uncased-contracts and generates clause representations.
    """

    def __init__(
        self,
        model_name_or_path: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.model_name_or_path = model_name_or_path or self._resolve_model_path()
        self.device = device or self._detect_device()
        self._tokenizer = None
        self._model = None
        self._category_embeddings: dict[str, list[float]] = {}
        self._is_loaded = False
        self._load_failed = False

    def _resolve_model_path(self) -> Optional[str]:
        # Check if local model weights are present in backend/models/contract_bert
        local_dir = Path(__file__).parent / "models" / "contract_bert"
        if (local_dir / "pytorch_model.bin").exists() and (local_dir / "config.json").exists():
            return str(local_dir)
        return None

    def _detect_device(self) -> str:
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _ensure_loaded(self) -> bool:
        if self._is_loaded:
            return True
        if self._load_failed:
            return False

        # Only attempt to load if model weights are present locally to avoid blocking HTTP requests
        model_path = self.model_name_or_path or self._resolve_model_path()
        if not model_path:
            return False

        try:
            from transformers import AutoModel, AutoTokenizer
            import torch

            logger.info("Loading Contract-BERT from %s on %s...", self.model_name_or_path, self.device)
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name_or_path)
            self._model = AutoModel.from_pretrained(
                self.model_name_or_path,
                use_safetensors=False,
            )
            self._model.to(self.device)
            self._model.eval()

            # Pre-compute representations for category anchors
            self._precompute_category_embeddings()

            self._is_loaded = True
            logger.info("Contract-BERT module initialized successfully.")
            return True
        except Exception as exc:
            logger.warning(
                "Contract-BERT loading failed (%s). Will use heuristic fallback for clause tagging.",
                exc,
            )
            self._load_failed = True
            return False

    def _precompute_category_embeddings(self) -> None:
        for cat, desc in CANONICAL_CLAUSE_CATEGORIES.items():
            rep = self._encode_text_raw(desc)
            if rep:
                self._category_embeddings[cat] = rep

    def _encode_text_raw(self, text: str) -> Optional[list[float]]:
        if not self._model or not self._tokenizer:
            return None
        import torch

        try:
            inputs = self._tokenizer(
                text,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                last_hidden = outputs.last_hidden_state  # [1, seq_len, 768]
                attention_mask = inputs["attention_mask"].unsqueeze(-1)  # [1, seq_len, 1]

                # Mean pooling over non-padded tokens
                sum_embeddings = torch.sum(last_hidden * attention_mask, dim=1)
                sum_mask = torch.clamp(attention_mask.sum(dim=1), min=1e-9)
                mean_pooled = sum_embeddings / sum_mask

                # L2 normalize
                normed = torch.nn.functional.normalize(mean_pooled, p=2, dim=1)
                vector = normed[0].cpu().tolist()
                return vector
        except Exception as exc:
            logger.debug("Raw encoding error: %s", exc)
            return None

    def generate_clause_representation(self, text: str) -> Optional[list[float]]:
        """
        Generates a 768-dimensional contextual vector representation
        of a contract clause using Contract-BERT.
        """
        if not text or not text.strip():
            return None
        if not self._ensure_loaded():
            return None
        return self._encode_text_raw(text)

    def classify_clause(self, clause_text: str, title: str = "") -> dict[str, Any]:
        """
        Classifies a contract clause into a canonical category using Contract-BERT.
        Returns category label, confidence, and similarity distribution.
        """
        combined = f"{title}. {clause_text}".strip() if title else clause_text.strip()
        if not combined:
            return {"category": "general_obligation", "confidence": 0.0, "method": "default"}

        # Attempt Contract-BERT neural classification
        if self._ensure_loaded() and self._category_embeddings:
            rep = self.generate_clause_representation(combined[:1200])
            if rep:
                scores: dict[str, float] = {}
                for cat, cat_rep in self._category_embeddings.items():
                    # Cosine similarity between L2-normalized vectors is dot product
                    sim = sum(a * b for a, b in zip(rep, cat_rep))
                    scores[cat] = sim

                sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                top_cat, top_score = sorted_scores[0]
                
                # Rescale cosine score (-1 to 1) into a confidence metric (0.0 to 1.0)
                confidence = max(0.0, min(1.0, (top_score + 1.0) / 2.0))
                
                return {
                    "category": top_cat,
                    "confidence": round(confidence, 3),
                    "method": "contract_bert_neural",
                    "top_candidates": [
                        {"category": cat, "score": round(score, 3)}
                        for cat, score in sorted_scores[:3]
                    ],
                }

        # Fast heuristic fallback if neural model is not loaded
        return self._heuristic_classify(combined)

    def _heuristic_classify(self, text: str) -> dict[str, Any]:
        """Keyword heuristic fallback when PyTorch model is initializing or unavailable."""
        lower = text.lower()
        keyword_map = {
            "payment": ["fee", "payment", "invoice", "compensation", "billing", "reimbursement", "price", "rates"],
            "termination": ["terminat", "cancel", "cure period", "material breach", "convenience", "expire"],
            "limitation_of_liability": ["liability", "indirect damages", "consequential damages", "aggregate cap", "in no event"],
            "confidentiality": ["confidential", "proprietary", "non-disclosure", "trade secret", "disclose"],
            "indemnification": ["indemnif", "hold harmless", "defend", "third-party claim"],
            "governing_law": ["governing law", "jurisdiction", "venue", "courts of", "state of"],
            "intellectual_property": ["intellectual property", "work product", "patent", "copyright", "trademark", "ownership"],
            "warranties": ["warrant", "as is", "merchantability", "disclaimer", "fitness for"],
            "force_majeure": ["force majeure", "act of god", "natural disaster", "epidemic", "pandemic", "strike"],
            "dispute_resolution": ["arbitrat", "mediat", "dispute", "conciliation"],
            "assignment": ["assign", "transfer", "change of control", "subcontract"],
            "term_duration": ["term of", "effective date", "initial term", "renewal", "duration"],
        }

        best_cat = "general_obligation"
        best_count = 0
        for cat, keywords in keyword_map.items():
            count = sum(1 for kw in keywords if kw in lower)
            if count > best_count:
                best_count = count
                best_cat = cat

        conf = min(0.9, 0.4 + best_count * 0.15) if best_count > 0 else 0.3
        return {
            "category": best_cat,
            "confidence": round(conf, 3),
            "method": "heuristic_fallback",
        }


# Global singleton instance for efficient in-process reuse
_contract_bert_instance: Optional[ContractBERTModule] = None


def get_contract_bert() -> ContractBERTModule:
    global _contract_bert_instance
    if _contract_bert_instance is None:
        _contract_bert_instance = ContractBERTModule()
    return _contract_bert_instance


def enrich_clauses_with_contract_bert(
    canonical_text: str,
    clauses: list[Any],
) -> list[dict[str, Any]]:
    """
    Enriches a list of segmented clauses with Contract-BERT classifications
    and representations.
    """
    bert = get_contract_bert()
    enriched = []

    for c in clauses:
        # Extract clause text from canonical text
        start = getattr(c, "char_start", 0)
        end = getattr(c, "char_end", len(canonical_text))
        clause_text = canonical_text[start:end] if 0 <= start < end <= len(canonical_text) else ""
        title = getattr(c, "title", "")

        classification = bert.classify_clause(clause_text, title=title)

        c_dict = {
            "clause_id": getattr(c, "clause_id", ""),
            "parent_id": getattr(c, "parent_id", None),
            "title": title,
            "children": getattr(c, "children", []),
            "path": getattr(c, "path", ""),
            "char_start": start,
            "char_end": end,
            "clause_type": classification["category"],
            "classification_confidence": classification["confidence"],
            "classification_method": classification["method"],
        }
        enriched.append(c_dict)

    return enriched
