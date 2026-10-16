"""
database.py — MongoDB Atlas connection & data persistence layer for Clausewise AI.

Manages:
1. User profiles (Google OAuth sign-in & session management)
2. Audit report history & metadata (PDF details, risk scores, findings)
3. Audit history query & aggregation statistics
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from bson import ObjectId
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
import gridfs

logger = logging.getLogger("database")

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb+srv://akashghosh2507_db_user:sLvHis735ZrKPVKy@cluster0.cdl6p1p.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
)
DB_NAME = os.getenv("MONGODB_DB_NAME", "clausewise")

_client: Optional[MongoClient] = None
_db: Optional[Database] = None
_fs: Optional[gridfs.GridFS] = None

# In-memory fallbacks if MongoDB is momentarily unreachable
_mem_users: Dict[str, Dict[str, Any]] = {}
_mem_audits: Dict[str, Dict[str, Any]] = {}
_mem_pdfs: Dict[str, tuple[bytes, str]] = {}


def get_db() -> Optional[Database]:
    """Returns singleton MongoDB database instance, or None if connection fails."""
    global _client, _db
    if _db is not None:
        return _db
    if not MONGODB_URI:
        logger.warning("MONGODB_URI not configured. Using in-memory fallback.")
        return None
    try:
        _client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=4000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
        )
        # Test connection
        _client.admin.command("ping")
        _db = _client[DB_NAME]
        
        # Ensure indexes
        try:
            _db.users.create_index("email", unique=True)
            _db.users.create_index("google_id")
            _db.audits.create_index([("user_id", 1), ("created_at", -1)])
            _db.audits.create_index("document_id")
        except Exception as idx_err:
            logger.debug(f"Index creation note: {idx_err}")
            
        logger.info(f"Connected to MongoDB Atlas database: {DB_NAME}")
        return _db
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB Atlas: {e}. Falling back to in-memory mode.")
        _db = None
        return None


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to convert MongoDB ObjectId to string and format dates."""
    if not doc:
        return {}
    res = dict(doc)
    if "_id" in res:
        res["id"] = str(res.pop("_id"))
    for k, v in list(res.items()):
        if isinstance(v, ObjectId):
            res[k] = str(v)
        elif isinstance(v, datetime):
            res[k] = v.isoformat()
    return res


# -----------------------------------------------------------------------------
# User Operations
# -----------------------------------------------------------------------------

def upsert_google_user(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates or updates a user profile from Google OAuth payload.
    Expected keys: email, name, picture, sub (google_id).
    """
    db = get_db()
    email = user_info.get("email", "").lower().strip()
    google_id = user_info.get("sub", "")
    name = user_info.get("name", email.split("@")[0] if email else "User")
    picture = user_info.get("picture", "")

    now = datetime.now(timezone.utc)
    user_data = {
        "email": email,
        "name": name,
        "picture": picture,
        "google_id": google_id,
        "last_login": now,
    }

    if db is not None:
        try:
            existing = db.users.find_one({"email": email})
            if existing:
                db.users.update_one(
                    {"_id": existing["_id"]},
                    {"$set": user_data},
                )
                existing.update(user_data)
                return serialize_doc(existing)
            else:
                user_data["created_at"] = now
                insert_res = db.users.insert_one(user_data)
                user_data["_id"] = insert_res.inserted_id
                return serialize_doc(user_data)
        except Exception as e:
            logger.error(f"MongoDB upsert_google_user error: {e}")

    # Fallback in-memory
    if email not in _mem_users:
        user_data["created_at"] = now
        user_data["_id"] = str(ObjectId())
        _mem_users[email] = user_data
    else:
        _mem_users[email].update(user_data)
    return serialize_doc(_mem_users[email])


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves user by ID."""
    db = get_db()
    if db is not None:
        try:
            if ObjectId.is_valid(user_id):
                doc = db.users.find_one({"_id": ObjectId(user_id)})
            else:
                doc = db.users.find_one({"$or": [{"id": user_id}, {"email": user_id}]})
            if doc:
                return serialize_doc(doc)
        except Exception as e:
            logger.error(f"MongoDB get_user_by_id error: {e}")

    for u in _mem_users.values():
        if str(u.get("_id")) == str(user_id) or str(u.get("id")) == str(user_id) or u.get("email") == user_id:
            return serialize_doc(u)
    return None


def update_user_profile(user_id: str, name: Optional[str] = None, picture: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Updates user display name and/or avatar picture in MongoDB Atlas."""
    db = get_db()
    updates: Dict[str, Any] = {}
    if name is not None and name.strip():
        updates["name"] = name.strip()
    if picture is not None:
        updates["picture"] = picture
    if not updates:
        return get_user_by_id(user_id)

    updates["updated_at"] = datetime.now(timezone.utc)
    if db is not None:
        try:
            if ObjectId.is_valid(user_id):
                db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
            else:
                db.users.update_one({"$or": [{"id": user_id}, {"email": user_id}]}, {"$set": updates})
            return get_user_by_id(user_id)
        except Exception as e:
            logger.error(f"MongoDB update_user_profile error: {e}")

    user = get_user_by_id(user_id)
    if user:
        user.update(updates)
        return user
    return None


def delete_user_account(user_id: str) -> bool:
    """Permanently deletes user account, audits, and all stored GridFS PDFs from MongoDB Atlas."""
    db = get_db()
    if db is not None:
        try:
            # 1. Fetch user's audits to clean up GridFS PDFs
            audits = list(db.audits.find({"$or": [{"user_id": user_id}, {"tenant_id": user_id}]}))
            for aud in audits:
                doc_id = aud.get("document_id")
                if doc_id:
                    delete_pdf_from_gridfs(doc_id)

            # 2. Delete any GridFS files tagged with tenant_id == user_id
            fs = get_gridfs()
            if fs is not None:
                try:
                    for grid_out in fs.find({"tenant_id": user_id}):
                        fs.delete(grid_out._id)
                except Exception as _e:
                    logger.warning(f"GridFS tenant file cleanup: {_e}")

            # 3. Delete all audit documents from collection
            db.audits.delete_many({"$or": [{"user_id": user_id}, {"tenant_id": user_id}]})

            # 4. Delete user record
            if ObjectId.is_valid(user_id):
                del_res = db.users.delete_one({"_id": ObjectId(user_id)})
            else:
                del_res = db.users.delete_one({"$or": [{"id": user_id}, {"email": user_id}]})
            return del_res.deleted_count > 0
        except Exception as e:
            logger.error(f"MongoDB delete_user_account error: {e}")
            return False

    # Fallback in-memory cleanup
    for k, v in list(_mem_users.items()):
        if str(v.get("_id")) == user_id or str(v.get("id")) == user_id or v.get("email") == user_id:
            del _mem_users[k]
            break
    for k, v in list(_mem_audits.items()):
        if v.get("user_id") == user_id or v.get("tenant_id") == user_id:
            del _mem_audits[k]
    return True


# -----------------------------------------------------------------------------
# GridFS PDF Storage & Retrieval Operations
# -----------------------------------------------------------------------------

def get_gridfs() -> Optional[gridfs.GridFS]:
    """Returns singleton GridFS instance for contract PDF binaries in MongoDB Atlas."""
    global _fs
    db = get_db()
    if db is not None:
        if _fs is None:
            _fs = gridfs.GridFS(db, collection="contract_pdfs")
        return _fs
    return None


def save_pdf_to_gridfs(document_id: str, filename: str, content: bytes, tenant_id: str) -> Optional[str]:
    """Saves raw PDF binary bytes to MongoDB Atlas GridFS."""
    fs = get_gridfs()
    if fs is not None and content:
        try:
            # Purge any previous file versions for this document_id
            for f in fs.find({"document_id": document_id}):
                try:
                    fs.delete(f._id)
                except Exception:
                    pass
            fid = fs.put(
                content,
                filename=filename,
                document_id=document_id,
                tenant_id=str(tenant_id),
                content_type="application/pdf",
                uploadDate=datetime.now(timezone.utc),
            )
            return str(fid)
        except Exception as e:
            logger.error(f"Failed to save PDF to MongoDB GridFS: {e}")
    # In-memory fallback
    _mem_pdfs[document_id] = (content, filename)
    return f"mem_{document_id}"


def get_pdf_from_gridfs(document_id: str) -> Optional[tuple[bytes, str]]:
    """Retrieves raw PDF binary bytes and original filename from MongoDB Atlas GridFS."""
    fs = get_gridfs()
    if fs is not None:
        try:
            grid_out = fs.find_one({"document_id": document_id})
            if grid_out:
                return grid_out.read(), getattr(grid_out, "filename", f"{document_id}.pdf")
        except Exception as e:
            logger.error(f"Failed to retrieve PDF from MongoDB GridFS: {e}")
    if document_id in _mem_pdfs:
        return _mem_pdfs[document_id]
    return None


def delete_pdf_from_gridfs(document_id: str) -> bool:
    """Removes PDF binary from MongoDB Atlas GridFS."""
    fs = get_gridfs()
    deleted = False
    if fs is not None:
        try:
            for f in fs.find({"document_id": document_id}):
                fs.delete(f._id)
                deleted = True
        except Exception as e:
            logger.error(f"Failed to delete PDF from MongoDB GridFS: {e}")
    if document_id in _mem_pdfs:
        del _mem_pdfs[document_id]
        deleted = True
    return deleted


# -----------------------------------------------------------------------------
# Audit History Operations
# -----------------------------------------------------------------------------

def save_audit_history(
    user_id: Optional[str],
    document_id: str,
    filename: str,
    file_size_bytes: int,
    contract_type: str,
    report_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Saves an audit run, its metadata, calculated risk summary, and full report.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    # Calculate high-level summary metrics
    overall_score = report_data.get("overall_risk_score", 0.0)
    risk_level = report_data.get("risk_level", "LOW")
    findings = report_data.get("findings", [])
    
    crit_count = sum(1 for f in findings if f.get("severity") in ("CRITICAL", "HIGH") or f.get("risk_level") == "HIGH")
    med_count = sum(1 for f in findings if f.get("severity") == "MEDIUM" or f.get("risk_level") == "MEDIUM")
    low_count = sum(1 for f in findings if f.get("severity") == "LOW" or f.get("risk_level") == "LOW")
    total_clauses = len(report_data.get("clause_analyses", []))

    audit_record = {
        "user_id": str(user_id) if user_id else "anonymous",
        "document_id": document_id,
        "filename": filename or f"Contract_{document_id[:8]}.pdf",
        "file_size_bytes": file_size_bytes or 0,
        "contract_type": contract_type or "General Agreement",
        "overall_risk_score": round(float(overall_score), 1),
        "risk_level": risk_level,
        "critical_count": crit_count,
        "medium_count": med_count,
        "low_count": low_count,
        "total_findings": len(findings),
        "total_clauses": total_clauses,
        "created_at": now,
        "report_data": report_data,
    }

    if db is not None:
        try:
            # Upsert by document_id so re-runs or updates don't create duplicate entries
            db.audits.update_one(
                {"document_id": document_id},
                {"$set": audit_record},
                upsert=True,
            )
            saved = db.audits.find_one({"document_id": document_id})
            return serialize_doc(saved)
        except Exception as e:
            logger.error(f"MongoDB save_audit_history error: {e}")

    # Fallback in-memory
    audit_record["_id"] = str(ObjectId())
    _mem_audits[document_id] = audit_record
    return serialize_doc(audit_record)


def list_user_audits(user_id: Optional[str], limit: int = 50) -> List[Dict[str, Any]]:
    """
    Returns list of past audits for a user (without full giant report payload for speed).
    Enforces strict user and tenant isolation. Never returns audits if user_id is missing or anonymous.
    """
    if not user_id or str(user_id) in ("anonymous", "null", "undefined", "", "tnt_dev"):
        return []

    uid = str(user_id)
    query = {"$or": [{"user_id": uid}, {"tenant_id": uid}]}
    db = get_db()
    if db is not None:
        try:
            cursor = (
                db.audits.find(
                    query,
                    {
                        "_id": 1,
                        "user_id": 1,
                        "document_id": 1,
                        "filename": 1,
                        "file_size_bytes": 1,
                        "contract_type": 1,
                        "overall_risk_score": 1,
                        "risk_level": 1,
                        "critical_count": 1,
                        "medium_count": 1,
                        "low_count": 1,
                        "total_findings": 1,
                        "total_clauses": 1,
                        "created_at": 1,
                    },
                )
                .sort("created_at", pymongo.DESCENDING)
                .limit(limit)
            )
            return [serialize_doc(d) for d in cursor]
        except Exception as e:
            logger.error(f"MongoDB list_user_audits error: {e}")

    # Fallback in-memory
    items = [i for i in _mem_audits.values() if str(i.get("user_id")) == uid or str(i.get("tenant_id")) == uid]
    items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    res = []
    for it in items[:limit]:
        c = dict(it)
        c.pop("report_data", None)
        res.append(serialize_doc(c))
    return res


def get_audit_by_id(audit_id_or_doc_id: str) -> Optional[Dict[str, Any]]:
    """Returns complete audit record including full report_data."""
    db = get_db()
    if db is not None:
        try:
            # Try ObjectId first, then document_id
            doc = None
            if ObjectId.is_valid(audit_id_or_doc_id):
                doc = db.audits.find_one({"_id": ObjectId(audit_id_or_doc_id)})
            if not doc:
                doc = db.audits.find_one({"document_id": audit_id_or_doc_id})
            if doc:
                return serialize_doc(doc)
        except Exception as e:
            logger.error(f"MongoDB get_audit_by_id error: {e}")

    # Fallback in-memory
    for it in _mem_audits.values():
        if (
            str(it.get("_id")) == audit_id_or_doc_id
            or str(it.get("id")) == audit_id_or_doc_id
            or it.get("document_id") == audit_id_or_doc_id
        ):
            return serialize_doc(it)
    return None


def delete_audit_by_id(audit_id_or_doc_id: str) -> bool:
    """Deletes an audit record."""
    db = get_db()
    if db is not None:
        try:
            if ObjectId.is_valid(audit_id_or_doc_id):
                res = db.audits.delete_one({"_id": ObjectId(audit_id_or_doc_id)})
                if res.deleted_count > 0:
                    delete_pdf_from_gridfs(audit_id_or_doc_id)
                    return True
            res = db.audits.delete_one({"document_id": audit_id_or_doc_id})
            delete_pdf_from_gridfs(audit_id_or_doc_id)
            return res.deleted_count > 0
        except Exception as e:
            logger.error(f"MongoDB delete_audit_by_id error: {e}")

    # Fallback in-memory
    for k, v in list(_mem_audits.items()):
        if (
            k == audit_id_or_doc_id
            or str(v.get("_id")) == audit_id_or_doc_id
            or str(v.get("id")) == audit_id_or_doc_id
        ):
            del _mem_audits[k]
            return True
    return False


def get_user_dashboard_stats(user_id: Optional[str]) -> Dict[str, Any]:
    """Computes aggregated dashboard metrics for user."""
    audits = list_user_audits(user_id, limit=200)
    total_audits = len(audits)
    if total_audits == 0:
        return {
            "total_audits": 0,
            "average_risk_score": 0.0,
            "critical_risks_detected": 0,
            "medium_risks_detected": 0,
            "low_risks_detected": 0,
            "compliance_health_score": 100,
        }

    total_score = sum(a.get("overall_risk_score", 0.0) for a in audits)
    crit = sum(a.get("critical_count", 0) for a in audits)
    med = sum(a.get("medium_count", 0) for a in audits)
    low = sum(a.get("low_count", 0) for a in audits)
    avg_score = round(total_score / total_audits, 1)

    # Compliance score = 100 - avg_risk_score (scaled)
    compliance = max(10, min(100, int(100 - (avg_score * 0.9))))

    return {
        "total_audits": total_audits,
        "average_risk_score": avg_score,
        "critical_risks_detected": crit,
        "medium_risks_detected": med,
        "low_risks_detected": low,
        "compliance_health_score": compliance,
    }
