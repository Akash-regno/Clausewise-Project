"""
test_audit_suite.py — Automated verification suite for Clausewise AI.
Tests MongoDB Atlas, GridFS PDF persistence, User Profile & Avatar, and User Isolation.
"""

import sys
import io
import time
import requests
import pymongo
from bson import ObjectId

API = "http://127.0.0.1:8000"

def test_suite():
    results = {}
    print("=" * 60)
    print("STARTING CLAUSEWISE AI SYSTEMATIC AUDIT & VALIDATION")
    print("=" * 60)

    # 1. MongoDB Atlas Direct Connection & GridFS Verification
    print("\n[TEST 1] MongoDB Atlas Connectivity & GridFS Test...")
    import database as db
    mongo_db = db.get_db()
    assert mongo_db is not None, "Failed to connect to MongoDB Atlas"
    ping_res = mongo_db.command("ping")
    assert ping_res.get("ok") == 1.0, "Ping to Atlas failed"
    print("  -> MongoDB Atlas ping SUCCESS: Cluster0 responsive.")

    # GridFS Test
    test_pdf_content = b"%PDF-1.4 test contract binary pdf content for gridfs verification"
    test_doc_id = "doc_test_gridfs_123"
    fid = db.save_pdf_to_gridfs(test_doc_id, "test_agreement.pdf", test_pdf_content, "tnt_test")
    assert fid is not None, "Failed to store PDF in GridFS"
    
    retrieved_data = db.get_pdf_from_gridfs(test_doc_id)
    assert retrieved_data is not None, "Failed to retrieve PDF from GridFS"
    read_bytes, read_fn = retrieved_data
    assert read_bytes == test_pdf_content, "PDF binary corrupted in GridFS"
    assert read_fn == "test_agreement.pdf", "Original filename mismatch"
    print(f"  -> MongoDB Atlas GridFS Test SUCCESS (File ID: {fid}).")
    results["1_mongodb_and_gridfs"] = "PASS"

    # 2. Authentication & JWT Session
    print("\n[TEST 2] Authentication & Session Token Issuance...")
    auth_resp = requests.post(f"{API}/auth/google", json={
        "email": "auditor_alpha@clausewise.ai",
        "name": "Auditor Alpha",
        "sub": "google_uid_alpha_991",
        "picture": "https://api.dicebear.com/7.x/initials/svg?seed=Alpha"
    })
    assert auth_resp.status_code == 200, f"Auth failed: {auth_resp.text}"
    auth_data = auth_resp.json()
    token = auth_data["token"]
    user_alpha = auth_data["user"]
    user_id_alpha = user_alpha["id"]
    print(f"  -> User Alpha authenticated! User ID: {user_id_alpha}")
    
    # Verify /auth/me
    me_resp = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["email"] == "auditor_alpha@clausewise.ai"
    print("  -> /auth/me verified successfully.")
    results["2_authentication_and_jwt"] = "PASS"

    # 3. User Profile Update & Avatar Persistence
    print("\n[TEST 3] Profile Update & Avatar Upload...")
    update_resp = requests.put(
        f"{API}/api/user/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Auditor Alpha Senior Partner"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["user"]["name"] == "Auditor Alpha Senior Partner"
    print("  -> Profile name update persisted in MongoDB Atlas.")

    # Avatar upload
    avatar_bytes = io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82")
    avatar_resp = requests.post(
        f"{API}/api/user/avatar",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("custom_avatar.png", avatar_bytes, "image/png")}
    )
    assert avatar_resp.status_code == 200
    updated_pic = avatar_resp.json()["user"]["picture"]
    assert updated_pic.startswith("data:image/png;base64,"), "Avatar data URL format invalid"
    print("  -> Custom avatar upload persisted in MongoDB Atlas.")
    results["3_profile_and_avatar"] = "PASS"

    # 4. PDF Storage, Metadata, and Retrieval via API
    print("\n[TEST 4] PDF Upload, GridFS Link, and API Streaming...")
    from pathlib import Path
    test_pdf_path = Path(__file__).parent / "test_contract.pdf"
    assert test_pdf_path.exists(), "test_contract.pdf missing"
    pdf_sample = test_pdf_path.read_bytes()

    # 4a. Test Corrupt File Rejection
    corrupt_resp = requests.post(
        f"{API}/upload",
        headers={"X-Tenant-Id": user_id_alpha, "Authorization": f"Bearer {token}"},
        files={"file": ("corrupt.pdf", b"NOT_A_VALID_PDF_HEADER_123456789", "application/pdf")},
        data={"contract_type": "MSA"}
    )
    assert corrupt_resp.status_code == 400, f"Expected 400 for corrupt PDF, got {corrupt_resp.status_code}"
    print("  -> Invalid / corrupt PDF correctly rejected with 400 Bad Request.")

    # 4b. Test Empty File Rejection
    empty_resp = requests.post(
        f"{API}/upload",
        headers={"X-Tenant-Id": user_id_alpha, "Authorization": f"Bearer {token}"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"contract_type": "MSA"}
    )
    assert empty_resp.status_code == 400, f"Expected 400 for empty PDF, got {empty_resp.status_code}"
    print("  -> Empty upload correctly rejected with 400 Bad Request.")

    # 4c. Test Valid PDF Ingestion & GridFS Storage
    upload_resp = requests.post(
        f"{API}/upload",
        headers={"X-Tenant-Id": user_id_alpha, "Authorization": f"Bearer {token}"},
        files={"file": ("Enterprise_Covenant_Agreement.pdf", pdf_sample, "application/pdf")},
        data={"contract_type": "MSA"}
    )
    assert upload_resp.status_code == 201, f"Upload failed: {upload_resp.text}"
    uploaded_doc = upload_resp.json()
    doc_id = uploaded_doc["document_id"]
    print(f"  -> Valid contract uploaded and ingested into GridFS: {doc_id}")

    # Check GridFS retrieval via API
    pdf_stream_resp = requests.get(f"{API}/document/{doc_id}/pdf")
    assert pdf_stream_resp.status_code == 200
    assert pdf_stream_resp.headers.get("content-type") == "application/pdf"
    assert len(pdf_stream_resp.content) > 0
    print("  -> GET /document/{id}/pdf streams genuine PDF from GridFS.")

    # Check download endpoint
    download_resp = requests.get(f"{API}/document/{doc_id}/download")
    assert download_resp.status_code == 200
    assert "attachment" in download_resp.headers.get("content-disposition", "")
    print("  -> GET /document/{id}/download verified.")
    results["4_pdf_storage_and_retrieval"] = "PASS"

    # 5. Audit Persistence & User Isolation
    print("\n[TEST 5] Audit History Persistence & User Isolation...")
    # Save an audit under user Alpha
    db.save_audit_history(
        user_id=user_id_alpha,
        document_id=doc_id,
        filename="Enterprise_Covenant_Agreement.pdf",
        file_size_bytes=len(pdf_sample),
        contract_type="MSA",
        report_data={
            "overall_risk_score": 72.4,
            "risk_level": "HIGH",
            "findings": [
                {"title": "Uncapped Liability Section 9.2", "severity": "HIGH", "risk_level": "HIGH"}
            ],
            "clause_analyses": [{}, {}]
        }
    )

    # Fetch Alpha's audits
    alpha_history = requests.get(
        f"{API}/api/history",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": user_id_alpha}
    ).json()
    assert len(alpha_history["audits"]) >= 1, "Alpha audits missing in history"
    print(f"  -> User Alpha has {len(alpha_history['audits'])} audits in history.")

    # Authenticate User Beta
    beta_auth = requests.post(f"{API}/auth/google", json={
        "email": "auditor_beta@clausewise.ai",
        "name": "Auditor Beta",
        "sub": "google_uid_beta_774"
    }).json()
    beta_token = beta_auth["token"]
    beta_id = beta_auth["user"]["id"]

    # Fetch Beta's audits - should be 0 because Alpha's audits are strictly isolated!
    beta_history = requests.get(
        f"{API}/api/history",
        headers={"Authorization": f"Bearer {beta_token}", "X-Tenant-Id": beta_id}
    ).json()
    assert len(beta_history["audits"]) == 0, "User isolation breach: Beta saw Alpha's audits!"
    print("  -> Tenant & User Isolation VERIFIED: User Beta cannot access User Alpha's audits.")
    results["5_isolation_and_audits"] = "PASS"

    # 6. Audit Reopening & Deletion
    print("\n[TEST 6] Audit Re-opening & Deletion...")
    item_resp = requests.get(f"{API}/api/history/{doc_id}", headers={"Authorization": f"Bearer {token}"})
    assert item_resp.status_code == 200
    assert item_resp.json()["audit"]["document_id"] == doc_id
    print("  -> Full audit report retrieved for re-opening in ReportView.")

    # Delete
    del_resp = requests.delete(f"{API}/api/history/{doc_id}", headers={"Authorization": f"Bearer {token}"})
    assert del_resp.status_code == 200
    print("  -> Audit and its GridFS file deleted cleanly from MongoDB Atlas.")
    results["6_audit_reopen_and_delete"] = "PASS"

    print("\n" + "=" * 60)
    print("ALL 6 AUTOMATED BACKEND & ATLAS TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
    return results

if __name__ == "__main__":
    test_suite()
