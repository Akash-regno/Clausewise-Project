# Clausewise — Self-Correcting Legal Contract Audit System

Clausewise is an AI-powered contract risk audit platform combining multi-pass agentic verification (Researcher, Evaluator, Auditor, Critic) with deterministic citation checks (V1 Entailment, V2 Citation, V3 Attribution).

## Architecture

```
├── backend/
│   ├── schemas.py              # Strict Pydantic data models (Claim, AuditState, V1/V2/V3 predicates)
│   ├── ingest.py               # PDF ingestion, structural clause segmentation, & xref graph
│   ├── retriever.py            # Vector database client & deterministic text_at verification
│   ├── graph.py                # LangGraph state machine with per-claim freezing & Groq LLM integration
│   ├── main.py                 # FastAPI web server (SSE streaming, tenancy, 4-leg deletion saga)
│   ├── requirements.txt        # Backend dependencies
│   ├── test_loop.py            # Freezing and loop termination test suite
│   ├── test_retriever.py       # Pinecone retriever & non-circular V2 verification tests
│   ├── test_api.py             # End-to-end FastAPI integration tests
│   └── test_contract.pdf       # Sample test contract for audits and tests
│
├── frontend/
│   ├── package.json            # Frontend dependencies (React, Vite, Tailwind CSS v4, Lucide)
│   ├── vite.config.js          # Vite build and dev server configuration (port 5173)
│   ├── index.html              # HTML entry loading Instrument Serif, Inter, & JetBrains Mono
│   ├── index.css               # Tailwind CSS v4 design tokens and styling
│   └── src/
│       ├── main.jsx            # React application mount point
│       └── App.jsx             # Main audit UI (dropzone, live terminal, V1-V3 seals, uncertainty ledger)
```

## Running the Project

### 1. Backend (FastAPI)
```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
- API Base URL: `http://127.0.0.1:8000`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

### 2. Frontend (Vite + React)
```bash
cd frontend
npm run dev
```
- Web Application: `http://localhost:5173`

## Running Tests
From the `backend/` directory:
```bash
python test_loop.py
python test_retriever.py
python test_api.py
```
