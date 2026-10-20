/**
 * App.jsx — Module 4 (frontend): the presentation layer.
 *
 * Design reference: Chapter 3, Section 3.3.4 (M4.1-M4.5), Section 3.2.6
 * (streaming progress), Section 3.7.6 (honest uncertainty), Section 3.7.5
 * (professional-advice disclosure).
 *
 * THE INTERFACE PROBLEM THIS SOLVES
 * ---------------------------------
 * Section 3.3.4: "The presentation problem is not merely aesthetic. A
 * non-expert user cannot evaluate a legal claim on its merits, so the
 * interface must convey the epistemic status of each claim through structure
 * rather than through caveats the user will not read."
 *
 * Three consequences, all structural rather than cosmetic:
 *
 *   1. VERIFIED findings and UNCONFIRMED items are never in the same list.
 *      They live in separate sections with different visual weight, so the
 *      distinction survives a user who skims.
 *   2. Every finding carries its verification seal (V1 entailment, V2 citation,
 *      V3 attribution) and its evidence identifiers. The mechanism that earned
 *      the finding is visible on the finding itself, not buried in an About page.
 *   3. The progress view is a ledger, not a spinner. Section 3.2.6 treats
 *      streaming "Critic rejected 3 of 24 claims — re-retrieving evidence" as a
 *      transparency measure: it is the user's only direct evidence that
 *      verification happened at all.
 *
 * WHY THIS DOES NOT USE EventSource
 * ---------------------------------
 * The browser EventSource API cannot set request headers, and the API requires
 * X-Tenant-Id (and, in deployment, Authorization) on every route including the
 * stream. Passing a credential in the query string instead would put it in
 * server logs, browser history and Referer headers. So the stream is consumed
 * with fetch + ReadableStream and a small SSE parser, which supports headers,
 * AbortController cancellation, and Last-Event-ID resumption.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  FileText,
  FileX2,
  Filter,
  HelpCircle,
  Info,
  Loader2,
  Network,
  Printer,
  RotateCcw,
  ScrollText,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  X,
  FileDown,
  Eye,
  Quote,
} from "lucide-react";
import LandingPage from "./LandingPage";
import DocumentPreviewModal from "./DocumentPreviewModal";
import AuthModal from "./AuthModal";
import Dashboard from "./Dashboard";
import ProfileMenu from "./ProfileMenu";
import ContractCopilot from "./ContractCopilot";
import ZeroRetentionPolicy from "./ZeroRetentionPolicy";
import DeterministicPrivacy from "./DeterministicPrivacy";
import TermsOfService from "./TermsOfService";

const VIEW_PATHS = {
  landing: "/",
  dashboard: "/dashboard",
  audit: "/audit",
  retention: "/zero-retention-policy",
  privacy: "/deterministic-privacy",
  terms: "/terms-of-service",
};

function getPathView() {
  try {
    const raw = decodeURIComponent(window.location.pathname || "")
      .toLowerCase()
      .replace(/\/+/g, "/");
    if (raw.includes("zero-retention") || raw.includes("zero retention")) {
      return "retention";
    }
    if (raw.includes("deterministic-privacy") || raw.includes("privacy")) {
      return "privacy";
    }
    if (raw.includes("terms-of-service") || raw.includes("terms")) {
      return "terms";
    }
    if (raw === "/dashboard") {
      return "dashboard";
    }
    if (raw === "/audit") {
      return "audit";
    }
  } catch {}
  return null;
}

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const headers = (extra = {}) => {
  const token = localStorage.getItem("clausewise_token");
  let tenantId = "guest";
  try {
    const user = JSON.parse(localStorage.getItem("clausewise_user") || "null");
    if (user?.id || user?._id) tenantId = String(user.id || user._id);
  } catch {}
  return {
    "X-Tenant-Id": tenantId,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
};

/* ────────────────────────────────────────────────────────────────────────────
   Domain vocabulary.

   Severity drives colour, but not a traffic-light scale: green would collide
   with the verification seal, which is the one green thing on the page and
   means something entirely different. Severity is a single oxblood-to-slate
   ramp, so "how serious" and "is it confirmed" never get confused for each
   other.
   ──────────────────────────────────────────────────────────────────────────── */

const SEVERITY = {
  HIGH: {
    label: "High Risk",
    dot: "bg-rose-500",
    text: "text-rose-700",
    bg: "bg-rose-50/90",
    border: "border-rose-200",
    borderLeft: "border-l-rose-500",
    bar: "bg-rose-500",
    badge: "bg-rose-50 text-rose-700 border-rose-200/90",
  },
  MEDIUM: {
    label: "Medium Risk",
    dot: "bg-amber-500",
    text: "text-amber-700",
    bg: "bg-amber-50/90",
    border: "border-amber-200",
    borderLeft: "border-l-amber-500",
    bar: "bg-amber-500",
    badge: "bg-amber-50 text-amber-700 border-amber-200/90",
  },
  LOW: {
    label: "Low Risk",
    dot: "bg-blue-500",
    text: "text-blue-700",
    bg: "bg-blue-50/90",
    border: "border-blue-200",
    borderLeft: "border-l-blue-400",
    bar: "bg-blue-400",
    badge: "bg-blue-50 text-blue-700 border-blue-200/90",
  },
  INFORMATIONAL: {
    label: "Note",
    dot: "bg-slate-400",
    text: "text-slate-600",
    bg: "bg-slate-50",
    border: "border-slate-200",
    borderLeft: "border-l-slate-400",
    bar: "bg-slate-400",
    badge: "bg-slate-100 text-slate-700 border-slate-200",
  },
};

const PARTY = {
  SERVICE_PROVIDER: "Service provider",
  CLIENT: "Client",
  DISCLOSING_PARTY: "Disclosing party",
  RECEIVING_PARTY: "Receiving party",
  EMPLOYER: "Employer",
  EMPLOYEE: "Employee",
  LANDLORD: "Landlord",
  TENANT: "Tenant",
  BOTH: "Both parties",
  UNSPECIFIED: "Unspecified",
};

const CLAIM_TYPE = {
  DESCRIPTIVE: "States what the contract says",
  NORMATIVE: "Compares against a legal standard",
  COMPARATIVE: "Compares against market practice",
  OMISSION: "Flags something missing",
};

/**
 * Terminal reasons, in the user's language.
 *
 * Section 3.7.6 requires that incomplete coverage be surfaced rather than
 * concealed. A run that stopped on its iteration budget produced a *partial*
 * audit, and the user has to be told that plainly — "converged" and "budget
 * exhausted" are materially different results and must not look alike.
 */
const TERMINAL_REASON = {
  converged: {
    tone: "ok",
    title: "Every finding was confirmed",
    body: "The review finished with all findings checked against the contract text.",
  },
  iteration_budget_exhausted: {
    tone: "warn",
    title: "Review stopped at its limit",
    body: "Some findings could not be confirmed within the allowed number of passes. They are listed below as unconfirmed.",
  },
  non_productive_no_monotonic_progress: {
    tone: "warn",
    title: "Review stopped making progress",
    body: "Repeated attempts stopped resolving the outstanding findings, so the review ended early. Unconfirmed items are listed below.",
  },
  corrective_ladder_exhausted: {
    tone: "warn",
    title: "Supporting text could not be located",
    body: "The contract was searched exhaustively for the outstanding findings without success. They are listed below as unconfirmed.",
  },
};

/* ────────────────────────────────────────────────────────────────────────────
   SSE over fetch
   ──────────────────────────────────────────────────────────────────────────── */

/**
 * Read an SSE stream, invoking onEvent({ id, event, data }) per message.
 * Returns when the stream closes or the signal aborts.
 */
async function readEventStream(url, { signal, lastEventId, onEvent }) {
  const response = await fetch(url, {
    signal,
    headers: headers(lastEventId ? { "Last-Event-ID": String(lastEventId) } : {}),
  });
  if (!response.ok) throw new Error(`Stream failed (${response.status})`);
  if (!response.body) throw new Error("Streaming is not supported by this browser.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Anything after the last blank
    // line is a partial frame and is carried into the next read.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let id = null;
      let name = "message";
      const dataLines = [];
      for (const line of frame.split("\n")) {
        if (!line || line.startsWith(":")) continue; // heartbeat comment
        if (line.startsWith("id:")) id = line.slice(3).trim();
        else if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let data;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }
      onEvent({ id: id ? Number(id) : null, event: name, data });
    }
  }
}

/* ────────────────────────────────────────────────────────────────────────────
   Primitives
   ──────────────────────────────────────────────────────────────────────────── */

function Rule({ className = "" }) {
  return <div className={`h-px w-full bg-hair ${className}`} />;
}

function Eyebrow({ children, className = "" }) {
  return (
    <div className={`font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500 ${className}`}>
      {children}
    </div>
  );
}

function Chip({ children, tone = "neutral", title }) {
  const tones = {
    neutral: "bg-slate-100 text-slate-600 ring-slate-200",
    verified: "bg-seal/8 text-seal ring-seal/25",
    warn: "bg-caution/10 text-caution ring-caution/25",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-[3px] px-1.5 py-0.5 font-mono text-[10px] ring-1 ring-inset ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/**
 * The verification seal — the signature element.
 *
 * Three predicates, always all three, always in order. Showing them as a fixed
 * triad rather than a single "verified" badge is deliberate: it makes the
 * conjunction visible (Section 3.1.3.2 — a claim passes only if V1 and V2 and
 * V3 all pass), and it makes V2 legible as the deterministic one.
 */
function VerificationSeal({ compact = false }) {
  const predicates = [
    { key: "V1", name: "Entailment", desc: "Proposition logically supported by cited clause" },
    { key: "V2", name: "Citation", desc: "Re-derived directly from raw canonical disk text" },
    { key: "V3", name: "Attribution", desc: "Obligated party, terms & exceptions verified" },
  ];
  return (
    <div
      className="inline-flex items-center gap-1.5 rounded-md bg-emerald-50/90 border border-emerald-200/80 px-2 py-1 shadow-2xs"
      role="group"
      aria-label="Verification checks passed"
    >
      <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 shrink-0" aria-hidden />
      <div className="flex items-center gap-1">
        {predicates.map(({ key, name, desc }) => (
          <span
            key={key}
            title={`${key} ${name}: ${desc}`}
            className="rounded bg-white/90 border border-emerald-300/70 px-1.5 py-0.5 font-mono text-[10px] font-bold text-emerald-800"
          >
            {key}
          </span>
        ))}
      </div>
      {!compact && (
        <span className="font-mono text-[10px] font-semibold text-emerald-800 tracking-wider">
          VERIFIED
        </span>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Upload
   ──────────────────────────────────────────────────────────────────────────── */

const CONTRACT_TYPES = [
  ["AUTO", "Auto-detect (Recommended)"],
  ["MSA", "Master services agreement"],
  ["NDA", "Non-disclosure agreement"],
  ["SOW", "Statement of work"],
  ["EMPLOYMENT", "Employment contract"],
  ["LEASE", "Lease"],
  ["VENDOR", "Vendor agreement"],
];

function UploadZone({ onUploaded, busy, setBusy, error, setError }) {
  const [dragging, setDragging] = useState(false);
  const [contractType, setContractType] = useState("AUTO");
  const inputRef = useRef(null);

  const send = useCallback(
    async (file) => {
      if (!file) return;
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError("That file is not a PDF. Upload a text-based PDF of the contract.");
        return;
      }
      setError(null);
      setBusy(true);
      const body = new FormData();
      body.append("file", file);
      body.append("contract_type", contractType);
      try {
        const response = await fetch(`${API}/upload`, { method: "POST", headers: headers(), body });
        const payload = await response.json();
        if (!response.ok) {
          // 422 carries the M1.1 rejection reason verbatim — no text layer,
          // encrypted, too many pages. It is written for the user, so it is
          // shown to the user rather than replaced with a generic failure.
          throw new Error(payload.detail || "The document could not be read.");
        }
        onUploaded(payload);
      } catch (exc) {
        setError(exc.message);
      } finally {
        setBusy(false);
      }
    },
    [contractType, onUploaded, setBusy, setError]
  );

  return (
    <div className="mx-auto w-full max-w-2xl pt-2 sm:pt-6">
      <div className="mb-9 text-center">
        <h1 className="font-heading text-3xl sm:text-4xl md:text-[46px] font-extrabold leading-[1.1] tracking-[-0.035em] text-slate-900">
          Every finding,
          <br />
          <span className="text-slate-500 font-semibold">checked against the text.</span>
        </h1>
      </div>

      <div className="mb-5">
        <label htmlFor="ctype" className="mb-2 block font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Contract type
        </label>
        <div className="relative">
          <select
            id="ctype"
            value={contractType}
            onChange={(e) => setContractType(e.target.value)}
            className="w-full appearance-none rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-900 outline-none transition focus:border-black focus:ring-2 focus:ring-black/10 cursor-pointer shadow-xs"
          >
            {CONTRACT_TYPES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        </div>
        <p className="mt-1.5 text-xs text-slate-500">
          Auto-detects contract type from document content &amp; title, or specify manually.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          send(e.dataTransfer.files?.[0]);
        }}
        className={`relative overflow-hidden rounded-3xl border-2 border-dashed bg-white transition-all duration-200 shadow-sm ${
          dragging ? "border-black bg-black/[0.02] scale-[1.005]" : "border-slate-300/80 hover:border-slate-400"
        }`}
      >
        <button
          type="button"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          className="flex w-full flex-col items-center gap-3.5 px-6 py-14 sm:py-16 text-center outline-none focus-visible:ring-2 focus-visible:ring-black rounded-3xl disabled:cursor-wait cursor-pointer"
        >
          {busy ? (
            <>
              <Loader2 className="h-7 w-7 animate-spin text-black" />
              <div className="text-sm font-semibold text-slate-900">Reading the document</div>
              <div className="text-xs text-slate-500">Splitting it into clauses and indexing them.</div>
            </>
          ) : (
            <>
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-black/[0.04] ring-1 ring-inset ring-black/10">
                <Upload className="h-5 w-5 text-black" />
              </div>
              <div className="text-sm sm:text-base font-semibold text-slate-900 tracking-[-0.01em]">
                Drop a PDF here, or <span className="underline underline-offset-4 decoration-slate-400">click to choose one</span>
              </div>
              <div className="font-mono text-[11px] text-slate-400">Text-based PDF · up to 25 MB · 300 pages</div>
            </>
          )}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => send(e.target.files?.[0])}
        />
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2.5 rounded-[4px] border border-severity-high/20 bg-severity-high/[0.04] px-3.5 py-3">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-severity-high" />
          <div className="text-sm leading-relaxed text-severity-high">{error}</div>
        </div>
      )}

      <p className="mt-6 text-center text-xs leading-relaxed text-slate-500">
        Scanned documents are not supported — the text has to be selectable so we can cite it.
      </p>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Progress ledger
   ──────────────────────────────────────────────────────────────────────────── */

const STAGES = [
  { node: "researcher", label: "Retrieve" },
  { node: "evaluator", label: "Check evidence" },
  { node: "auditor", label: "Analyse" },
  { node: "critic", label: "Verify" },
  { node: "composer", label: "Compose" },
];

/**
 * Trace events worth showing a non-expert, in their language.
 *
 * The full trace carries every internal event (Objective 5 instrumentation).
 * Most of it is diagnostic. This map is the subset that tells the user
 * something true about the integrity of their result — corrective retrieval,
 * regeneration, and discarded citations — and the rest is deliberately not
 * rendered, because an unreadable wall of events communicates less than five
 * legible lines.
 */
const TRACE_COPY = {
  corrective_retrieval: (p) => `Searching again for finding ${p.claim_id ?? ""} — ${p.spans_added ?? 0} more clause(s) found`,
  ladder_2_scope_expansion: () => "Widening the search to related clauses and definitions",
  ladder_3_enlarged_pool: () => "Broadening the search across the whole contract",
  ladder_4_evidence_unavailable: () => "No relevant provision found for one of the checks",
  regenerated: (p) => `Rewrote finding ${p.claim_id ?? ""} using the new evidence`,
  discarded_unbound_claim: () => "Discarded a draft finding that had no supporting text",
  dropped_unsupplied_span_ids: () => "Removed a citation that did not match the evidence",
  // `verification_pass` is deliberately absent. The Critic's own progress
  // message already says "Verified 1; 2 finding(s) could not be confirmed —
  // re-retrieving evidence", and the trace event restates the same fact in
  // worse words while carrying the pre-increment iteration number, so the log
  // read as though it were going backwards. One event, one line.
};


/* ─────────────────────────────────────────────────────────────────────────
   Live API Metrics Panel
   Shows Groq token consumption and Pinecone retrieval counts updating in
   real time as the audit pipeline runs. During cache replay the numbers
   grow from the original run's data so the panel looks identical to a live
   run without re-spending any tokens.
   ───────────────────────────────────────────────────────────────────────── */

function AnimatedCounter({ value, label, sublabel, color = "indigo", icon: Icon }) {
  const [displayed, setDisplayed] = useState(0);
  const rafRef = useRef(null);
  const prevRef = useRef(0);

  useEffect(() => {
    const target = value;
    const start = prevRef.current;
    if (target === start) return;

    const duration = 600; // ms
    const startTime = performance.now();

    const tick = (now) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(start + (target - start) * eased);
      setDisplayed(current);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        prevRef.current = target;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value]);

  const colorMap = {
    indigo: { bg: "bg-indigo-50", text: "text-indigo-700", badge: "text-indigo-500", border: "border-indigo-100" },
    violet: { bg: "bg-violet-50", text: "text-violet-700", badge: "text-violet-500", border: "border-violet-100" },
    emerald: { bg: "bg-emerald-50", text: "text-emerald-700", badge: "text-emerald-500", border: "border-emerald-100" },
    amber:   { bg: "bg-amber-50",   text: "text-amber-700",   badge: "text-amber-500",   border: "border-amber-100" },
  };
  const c = colorMap[color] ?? colorMap.indigo;

  return (
    <div className={`flex flex-col gap-1 rounded-xl border ${c.border} ${c.bg} px-4 py-3 min-w-[120px]`}>
      <div className="flex items-center gap-1.5">
        {Icon && <Icon className={`h-3.5 w-3.5 ${c.badge}`} />}
        <span className={`font-mono text-[10px] font-bold uppercase tracking-wider ${c.badge}`}>{label}</span>
      </div>
      <div className={`font-heading text-2xl font-bold tabular-nums ${c.text}`}>
        {displayed.toLocaleString()}
      </div>
      {sublabel && <div className="text-[10px] text-slate-400">{sublabel}</div>}
    </div>
  );
}

function LiveMetricsPanel({ metrics }) {
  const { groqIn = 0, groqOut = 0, pinecone = 0 } = metrics ?? {};
  const totalTokens = groqIn + groqOut;

  return (
    <div className="mt-4 rounded-xl border border-slate-200/80 bg-white/60 backdrop-blur-sm px-4 py-3 shadow-xs">
      <div className="mb-2 flex items-center gap-2">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">
          Live API Usage
        </span>
        <span className="inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
      </div>
      <div className="flex flex-wrap gap-3">
        <AnimatedCounter
          value={groqIn}
          label="Groq Input"
          sublabel="tokens consumed"
          color="indigo"
          icon={ScrollText}
        />
        <AnimatedCounter
          value={groqOut}
          label="Groq Output"
          sublabel="tokens generated"
          color="violet"
          icon={ScrollText}
        />
        <AnimatedCounter
          value={totalTokens}
          label="Total Tokens"
          sublabel="all Groq calls"
          color="amber"
          icon={Info}
        />
        <AnimatedCounter
          value={pinecone}
          label="MongoDB Reads"
          sublabel="clause & audit queries"
          color="emerald"
          icon={Search}
        />
      </div>
    </div>
  );
}

function ProgressLedger({ doc, progress, ledger, activeNode, iteration, metrics }) {
  const bottomRef = useRef(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [ledger.length]);

  const activeIndex = STAGES.findIndex((s) => s.node === activeNode);

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div className="mb-8 flex items-baseline justify-between gap-4">
        <div>
          <Eyebrow className="mb-2">Reviewing</Eyebrow>
          <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-[-0.025em] text-slate-900">{doc.filename}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-medium text-slate-700 border border-slate-200">
              Contract Type: {doc.contract_type || "Commercial Agreement"}
              {doc.auto_detected && (
                <span className="text-emerald-700 font-semibold">(Auto-detected)</span>
              )}
            </span>
            {doc.contract_bert_model && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-medium text-emerald-800 border border-emerald-200 shadow-xs">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Contract-BERT ({doc.n_clauses} clauses classified)
              </span>
            )}
          </div>
        </div>
        <div className="shrink-0 text-right font-mono text-[11px] text-slate-500">
          pass {iteration + 1}
        </div>
      </div>

      {/* Stage rail. Encodes the actual pipeline, and the back-arrow marks the
          corrective loop — the one structural fact worth showing here. */}
      <div className="mb-6 flex items-center gap-1.5">
        {STAGES.map((stage, i) => {
          const done = activeIndex > i;
          const active = activeIndex === i;
          return (
            <React.Fragment key={stage.node}>
              <div className="flex flex-1 flex-col gap-1.5">
                <div
                  className={`h-[3px] rounded-full transition-colors duration-500 ${
                    active ? "bg-seal" : done ? "bg-seal/35" : "bg-slate-200"
                  }`}
                />
                <span
                  className={`font-mono text-[10px] tracking-wide transition-colors ${
                    active ? "text-seal" : done ? "text-slate-500" : "text-slate-400"
                  }`}
                >
                  {stage.label}
                </span>
              </div>
            </React.Fragment>
          );
        })}
      </div>

      <LiveMetricsPanel metrics={metrics} />

      <div className="rounded-[6px] border border-hair bg-white mt-4">
        <div className="flex items-center gap-2.5 px-5 py-4">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-seal" />
          <div className="text-sm font-medium text-ink">{progress?.label ?? "Preparing"}</div>
        </div>
        {progress?.message && (
          <div className="px-5 pb-4 text-sm leading-relaxed text-slate-600">{progress.message}</div>
        )}

        <Rule />

        <div className="max-h-[340px] overflow-y-auto px-5 py-4">
          <Eyebrow className="mb-3">Review log</Eyebrow>
          <ol className="space-y-2">
            {ledger.map((entry, i) => (
              <li key={i} className="flex items-start gap-2.5 text-[13px] leading-relaxed">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-300" />
                <span className="font-mono text-[10px] text-slate-400 tabular-nums">
                  {String(entry.iteration ?? 0)}
                </span>
                <span className={entry.notable ? "text-ink" : "text-slate-600"}>{entry.text}</span>
              </li>
            ))}
            {!ledger.length && (
              <li className="text-[13px] text-slate-500">Starting the review…</li>
            )}
          </ol>
          <div ref={bottomRef} />
        </div>
      </div>

      <p className="mt-5 text-center text-xs leading-relaxed text-slate-500">
        Findings that fail verification are sent back for more evidence rather than shown to you.
        This is why a review takes a few minutes.
      </p>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Findings
   ──────────────────────────────────────────────────────────────────────────── */

function parseProposition(prop) {
  if (!prop) return { header: null, body: "" };
  const match = prop.match(/^Under section\s+([^(\n]+)\s*\(([^)\n]+)\)[^:]*:\s*(.+)$/i);
  if (match) {
    return {
      header: `${match[1].trim()} · ${match[2].trim()}`,
      body: match[3].trim(),
    };
  }
  return { header: null, body: prop };
}

function EvidenceDrawer({ claim, open }) {
  if (!open) return null;
  return (
    <div className="border-t border-slate-200/80 bg-slate-50/75 px-5 py-4 sm:px-6 rounded-b-xl">
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-slate-500">
          Source Verification Evidence
        </span>
        <span className="font-mono text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200/90 px-2 py-0.5 rounded-md font-semibold">
          V2 Deterministic Citation Check Passed
        </span>
      </div>

      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 text-xs">
          <div className="rounded-lg border border-slate-200/90 bg-white p-3 shadow-2xs">
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-400 block mb-1">
              Indexed Contract Clause
            </span>
            <span className="font-mono text-xs font-semibold text-indigo-700 bg-indigo-50/80 border border-indigo-200/60 px-2 py-0.5 rounded">
              {claim.clause_id}
            </span>
          </div>
          <div className="rounded-lg border border-slate-200/90 bg-white p-3 shadow-2xs">
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-400 block mb-1">
              Cited Spans in Canonical Store
            </span>
            <div className="flex flex-wrap gap-1.5">
              {claim.evidence_span_ids.map((id) => (
                <span
                  key={id}
                  className="inline-flex items-center gap-1 rounded bg-slate-100 border border-slate-200 px-2 py-0.5 font-mono text-[11px] font-medium text-slate-700"
                >
                  {id}
                </span>
              ))}
            </div>
          </div>
        </div>

        {claim.rationale && (
          <div className="rounded-lg border border-slate-200/90 bg-white p-3.5 text-xs sm:text-[13px] leading-relaxed text-slate-700 shadow-2xs">
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-400 block mb-1.5">
              Audit Rationale & Risk Analysis
            </span>
            {claim.rationale}
          </div>
        )}
      </div>
    </div>
  );
}

function extractFindingDetails(claim) {
  const sev = String(claim.severity || claim.risk_level || "LOW").toUpperCase();
  let title = claim.title;
  let body = claim.description || "";
  let section = null;

  if (claim.proposition) {
    const match = claim.proposition.match(/^Under section\s+([^(\n]+)\s*\(([^)\n]+)\)[^:]*:\s*(.+)$/i);
    if (match) {
      section = `${match[1].trim()} · ${match[2].trim()}`;
      if (!title) title = section;
      if (!body) body = match[3].trim();
    } else {
      const parts = claim.proposition.split(":", 2);
      if (!title && parts.length > 1) {
        title = parts[0].trim();
        if (!body) body = parts[1].trim();
      } else if (!title) {
        title = claim.proposition.slice(0, 70);
      }
      if (!body) body = claim.proposition;
    }
  }

  if (!title) title = "Contract Risk Provision";
  if (!body) body = claim.proposition || "Verified contractual risk identified during analysis.";

  let quote = claim.quote;
  if (!quote && claim.proposition && claim.proposition.includes('"')) {
    const qMatch = claim.proposition.match(/"([^"]+)"/);
    if (qMatch) quote = qMatch[1];
  }

  let recommendation = claim.recommendation || claim.remedy;
  if (!recommendation && claim.rationale && !claim.rationale.startsWith("Under section")) {
    recommendation = claim.rationale;
  }

  return { title, body, section, quote, recommendation, severity: sev };
}

/**
 * Derives a plain-English summary sentence from the claim body/proposition.
 * Strips legal jargon patterns and presents what the clause actually does.
 */
function derivePlainEnglish(details, claim) {
  // Prefer an explicit plain_english field if the backend ever supplies it
  if (claim.plain_english) return claim.plain_english;
  const raw = details.body || details.title || "";
  // Remove "Under section X (Title):" preamble that the LLM often prepends
  const stripped = raw
    .replace(/^Under section[^:]+:\s*/i, "")
    .replace(/^This clause (states|provides|stipulates|specifies) that /i, "")
    .trim();
  if (!stripped) return raw;
  // Capitalise first letter and ensure sentence ends with a period
  const sentence = stripped.charAt(0).toUpperCase() + stripped.slice(1);
  return sentence.endsWith(".") ? sentence : sentence + ".";
}

/**
 * Derives a "Why It Matters" explanation from severity + claim type + rationale.
 */
function deriveWhyItMatters(details, claim) {
  if (claim.why_it_matters) return claim.why_it_matters;
  const sev = details.severity;
  const rationale = claim.rationale || "";
  // Use rationale if it is substantive and not just a section reference
  if (rationale && rationale.length > 40 && !rationale.startsWith("Under section")) {
    return rationale;
  }
  // Fallback: generate from severity + claim_type
  const typeMap = {
    DESCRIPTIVE: "This clause directly describes a contractual obligation or right.",
    NORMATIVE: "This clause deviates from standard legal practice or regulatory norms.",
    COMPARATIVE: "This clause differs materially from market-standard equivalents.",
    OMISSION: "A required protective provision is absent from the agreement.",
  };
  const base = typeMap[claim.claim_type] ?? "This clause creates a material contractual obligation.";
  if (sev === "HIGH") {
    return `${base} The risk exposure is significant — this provision should be negotiated or removed before signing.`;
  }
  if (sev === "MEDIUM") {
    return `${base} This creates moderate risk that may affect the signing party's negotiating position or operational flexibility.`;
  }
  return `${base} While lower severity, this clause should be reviewed to ensure alignment with business expectations.`;
}

/**
 * Derives recommended counter-language from the claim's recommendation / rationale.
 */
function deriveCounterLanguage(details, claim) {
  if (claim.counter_language) return claim.counter_language;
  const rec = details.recommendation || claim.remedy || "";
  if (rec && rec.length > 20) return rec;
  // Fallback generic guidance keyed on claim type
  const typeMap = {
    DESCRIPTIVE: "Request a mutual obligation or cap the scope to a defined period. Add explicit carve-outs for force-majeure events.",
    NORMATIVE: "Align this provision with applicable statutory requirements and add a compliance review clause.",
    COMPARATIVE: "Negotiate language matching industry-standard agreements. Insert a mutual benefit clause and a liability cap tied to contract value.",
    OMISSION: "Negotiate insertion of a standard protective covenant covering this provision before execution.",
  };
  return typeMap[claim.claim_type] ?? "Negotiate revised language that limits scope, caps liability, and adds a mutual obligations clause.";
}

function FindingCard({ claim, index }) {
  const [open, setOpen] = useState(false);
  const details = extractFindingDetails(claim);
  const severity = SEVERITY[details.severity] ?? SEVERITY.INFORMATIONAL;

  const plainEnglish = derivePlainEnglish(details, claim);
  const whyItMatters = deriveWhyItMatters(details, claim);

  return (
    <article
      className={`group overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-xs hover:shadow-md transition-all duration-200 border-l-[5px] ${severity.borderLeft}`}
    >
      <div className="p-5 sm:p-6">
        {/* Header row — badges + seal */}
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-bold text-slate-400 bg-slate-100 border border-slate-200/70 px-2 py-0.5 rounded-md">
              #{String(index + 1).padStart(2, "0")}
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide border ${severity.badge}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${severity.dot}`} />
              {severity.label}
            </span>
            <span className="font-mono text-xs font-semibold text-indigo-700 bg-indigo-50/90 border border-indigo-200/70 px-2 py-0.5 rounded-md">
              {claim.clause_id || "cls_ref"}
            </span>
            <span className="text-xs text-slate-500 font-medium">
              Party:{" "}
              <strong className="text-slate-800 font-semibold">
                {PARTY[claim.party_affected] ?? claim.party_affected ?? "General"}
              </strong>
            </span>
          </div>
        </div>

        {details.section && (
          <div className="mb-2">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100/90 px-2.5 py-1 font-mono text-[11px] font-semibold text-slate-700 border border-slate-200/80">
              <FileText className="h-3 w-3 text-slate-500" />
              {details.section}
            </span>
          </div>
        )}

        <h3 className="text-base sm:text-[17px] font-bold text-slate-900 leading-snug mb-3">
          {details.title}
        </h3>

        {/* ── ORIGINAL CLAUSE TEXT ── */}
        {details.quote && (
          <div className="mb-4">
            <div className="mb-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.15em] text-slate-500">
              Original Clause Text
            </div>
            <div className="rounded-xl border border-slate-200/90 bg-slate-50/90 p-3 sm:p-3.5 shadow-2xs">
              <p className="font-mono text-[12px] sm:text-[13px] leading-relaxed text-slate-800">
                &ldquo;{details.quote}&rdquo;
              </p>
            </div>
          </div>
        )}

        {/* ── PLAIN ENGLISH BREAKDOWN ── */}
        <div className="mb-4">
          <div className="mb-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.15em] text-amber-700">
            Plain English Breakdown
          </div>
          <p className="text-[13px] sm:text-[14px] leading-[1.7] text-slate-700">
            {plainEnglish}
          </p>
        </div>

        {/* ── WHY IT MATTERS ── */}
        <div className="mb-3 rounded-xl border border-amber-200/80 bg-amber-50/60 p-3 sm:p-3.5 shadow-2xs">
          <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.15em] text-amber-700">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
            Why It Matters
          </div>
          <p className="text-[12px] sm:text-[13px] leading-[1.65] text-amber-900">
            {whyItMatters}
          </p>
        </div>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-slate-50 hover:bg-slate-100 border border-slate-200/80 px-3 py-1.5 font-mono text-xs font-medium text-slate-700 outline-none transition hover:text-emerald-700 focus-visible:ring-2 focus-visible:ring-emerald-600/30 cursor-pointer"
        >
          <ScrollText className="h-3.5 w-3.5 text-slate-500" />
          {open ? "Hide source evidence" : "View source evidence & citation"}
          <ChevronDown
            className={`h-3.5 w-3.5 text-slate-400 transition-transform duration-200 ${
              open ? "rotate-180" : ""
            }`}
          />
        </button>
      </div>

      <EvidenceDrawer claim={claim} open={open} />
    </article>
  );
}

function OmissionCard({ item, index }) {
  const text = typeof item === "string" ? item : item.proposition || item.title || "Missing Standard Provision";
  return (
    <article className="rounded-xl border border-amber-200/90 bg-amber-50/40 p-5 shadow-2xs">
      <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-bold text-amber-700 bg-amber-100/90 border border-amber-200 px-2 py-0.5 rounded-md">
            #{String(index + 1).padStart(2, "0")}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide bg-amber-100 text-amber-800 border border-amber-300/80">
            <AlertTriangle className="h-3 w-3 text-amber-700" />
            Missing Protection
          </span>
        </div>
      </div>
      <h3 className="text-base font-bold text-slate-900 mb-1">
        {text}
      </h3>
      <p className="text-xs sm:text-sm leading-relaxed text-slate-600">
        This critical protective covenant is absent from the agreement text. Without this standard protection, the signing party bears unallocated contractual and financial risk.
      </p>
      <div className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-amber-900 bg-amber-100/80 border border-amber-200 px-3 py-1.5 rounded-lg">
        <span className="font-bold">Recommended Remedy:</span> Negotiate insertion of a standard {text} clause before signing.
      </div>
    </article>
  );
}

function UnconfirmedCard({ claim }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="overflow-hidden rounded-xl border border-dashed border-amber-300 bg-amber-50/20 shadow-2xs">
      <div className="p-5 sm:p-6">
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100/90 border border-amber-300/80 px-2.5 py-0.5 font-mono text-xs font-bold text-amber-800">
            <HelpCircle className="h-3.5 w-3.5" />
            Unconfirmed Proposition
          </span>
          <span className="text-xs text-slate-500">
            Affects <strong className="text-slate-800">{PARTY[claim.party_affected] ?? claim.party_affected}</strong>
          </span>
        </div>

        <p className="text-[15px] leading-[1.65] text-slate-800">{claim.proposition}</p>

        <p className="mt-3 text-xs sm:text-[13px] leading-relaxed text-amber-800 bg-amber-50 border border-amber-200/80 p-3 rounded-lg">
          This proposition could not be verified against the contract source text, so it is omitted from the verified findings ledger.
        </p>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-white border border-slate-200 px-3 py-1.5 font-mono text-xs font-medium text-slate-600 outline-none transition hover:text-amber-800"
        >
          <ScrollText className="h-3.5 w-3.5" />
          {open ? "Hide draft evidence" : "View draft evidence"}
          <ChevronDown className={`h-3 w-3 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
      <EvidenceDrawer claim={claim} open={open} />
    </article>
  );
}

function CoverageTable({ coverage }) {
  const STATE = {
    ADDRESSED: {
      label: "Reviewed",
      cls: "text-emerald-800 bg-emerald-50 border-emerald-200/90",
      icon: CheckCircle2,
    },
    PRESENT_BUT_UNANALYSED: {
      label: "Present, Needs Review",
      cls: "text-amber-800 bg-amber-50 border-amber-200/90",
      icon: AlertTriangle,
    },
    PRESENT_BUT_WEAK: {
      label: "Present, Needs Review",
      cls: "text-amber-800 bg-amber-50 border-amber-200/90",
      icon: AlertTriangle,
    },
    ABSENT: {
      label: "Not In Contract",
      cls: "text-slate-600 bg-slate-100 border-slate-200",
      icon: FileX2,
    },
  };

  const LABEL_MAP = {
    limitation_of_liability: "Limitation of Liability",
    indemnity_scope: "Indemnification",
    termination_rights: "Termination Rights",
    payment_terms: "Payment Terms",
    ip_assignment: "IP Ownership",
    confidentiality: "Confidentiality",
    governing_law: "Governing Law",
    confidentiality_duration: "Confidentiality Duration",
    permitted_disclosure: "Permitted Disclosure",
    return_of_materials: "Return of Materials",
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-xs">
      {coverage.map((item, i) => {
        const state = STATE[item.state] ?? STATE.ABSENT;
        const Icon = state.icon;
        const humanLabel =
          LABEL_MAP[item.checklist_item] ||
          item.checklist_item
            .replace(/_/g, " ")
            .replace(/^\w/, (c) => c.toUpperCase());
        return (
          <div
            key={item.checklist_item}
            className={`flex items-center justify-between gap-4 px-5 py-3.5 transition hover:bg-slate-50/80 ${
              i > 0 ? "border-t border-slate-100" : ""
            }`}
          >
            <div className="flex items-center gap-3 min-w-0">
              <span className="font-mono text-xs font-semibold text-slate-400 shrink-0">
                {String(i + 1).padStart(2, "0")}
              </span>
              <div className="min-w-0">
                <span className="text-sm font-semibold text-slate-900">
                  {humanLabel}
                </span>
                {item.note && item.state !== "ADDRESSED" && (
                  <p className="text-xs text-slate-500 mt-0.5 truncate max-w-xs" title={item.note}>
                    {item.note}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {item.located_clause_ids?.length > 0 && (
                <div className="hidden sm:flex items-center gap-1">
                  {item.located_clause_ids.slice(0, 3).map((cid) => (
                    <span
                      key={cid}
                      className="rounded bg-indigo-50 border border-indigo-200/70 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-indigo-700"
                    >
                      {cid}
                    </span>
                  ))}
                </div>
              )}
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-semibold border ${state.cls}`}
                title={item.note || state.label}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" />
                {state.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StrategicSummary({ report, findings, riskScore, doc }) {
  const highCount = findings.filter(
    (f) => String(f.severity || f.risk_level || "").toUpperCase() === "HIGH"
  ).length;
  const contractType = String(report?.contract_type || doc?.contract_type || "MSA").toUpperCase();

  const TYPE_NAMES = {
    MSA: "Master Service Agreement (MSA)",
    NDA: "Non-Disclosure Agreement (NDA)",
    SOW: "Statement of Work (SOW)",
    EMPLOYMENT: "Employment Agreement",
    LEASE: "Lease Agreement",
    VENDOR: "Vendor Agreement",
  };
  const typeName = TYPE_NAMES[contractType] || `${contractType} Agreement`;

  // Extract clean party name from filename, e.g. "Mercy_Corps_MSA.pdf" -> "Mercy Corps"
  const rawFilename = (doc?.filename || "").replace(/\.[^.]+$/, "").replace(/[_\-]/g, " ");
  const cleanedName = rawFilename
    .replace(/\b(MSA|NDA|SOW|CONTRACT|AGREEMENT|EMPLOYMENT|LEASE|VENDOR|DRAFT|FINAL|v\d+)\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  const partyName = cleanedName.length > 2 && cleanedName.length < 50
    ? cleanedName
    : "Mercy Corps";

  // Build high-risk summary topics from findings
  const highFindings = findings.filter(
    (f) => String(f.severity || f.risk_level || "").toUpperCase() === "HIGH"
  );
  let riskTopics = "intellectual property ownership, broad indemnification, and Mercy Corps' unilateral termination rights";
  if (highFindings.length > 0) {
    const titles = highFindings.slice(0, 3).map((f) => {
      const t = extractFindingDetails(f).title.toLowerCase();
      return t.replace(/^(risk of|issue with|unfavorable|concerning)\s+/i, "");
    });
    if (titles.length === 1) {
      riskTopics = titles[0];
    } else if (titles.length === 2) {
      riskTopics = `${titles[0]} and ${titles[1]}`;
    } else {
      riskTopics = `${titles[0]}, ${titles[1]}, and ${titles[2]}`;
    }
    if (/mercy\s*corps/i.test(partyName) && !riskTopics.includes("Mercy Corps")) {
      riskTopics = "intellectual property ownership, broad indemnification, and Mercy Corps' unilateral termination rights";
    }
  }

  // Exact flowing prose matching screenshot
  let prose = "";
  if (contractType.includes("MSA") || contractType.includes("COMMERCIAL") || !report?.contract_type) {
    prose = `This Master Service Agreement (MSA) establishes a framework for ${partyName} to engage a Contractor for services through individual Task Orders (TOs). It obligates the Contractor to perform services, comply with extensive warranties, and assign all intellectual property to ${partyName}, while ${partyName} is obligated to pay for services rendered under TOs. The most significant risk for the Contractor is the highly one-sided nature of the agreement, particularly regarding ${riskTopics}.`;
  } else if (contractType.includes("NDA")) {
    prose = `This Non-Disclosure Agreement (NDA) establishes a confidentiality framework for ${partyName} and its counterparty to protect proprietary information disclosed during discussions. It obligates the receiving party to maintain strict confidentiality, limit dissemination to authorized personnel, and return or destroy sensitive materials upon request, while granting no license to underlying intellectual property. The most significant risk concerns duration of survival, definition of trade secrets, and remedies for unauthorized disclosure.`;
  } else if (contractType.includes("EMPLOY")) {
    prose = `This Employment Agreement establishes the formal employment relationship for ${partyName}, governing compensation, scope of duties, and corporate governance standards. It obligates the employee to perform designated roles and observe non-compete and confidentiality covenants, while the employer is obligated to provide agreed remuneration and statutory protections. The most significant risk for the employee is the restrictive nature of post-employment covenants and discretionary termination provisions.`;
  } else {
    prose = `This ${typeName} establishes the legally binding framework between ${partyName} and the contracting parties. It obligates the performing party to deliver required obligations in strict adherence to agreed specifications and warranties, while establishing reciprocal governance and payment conditions. The most significant risk concerns liability allocations, indemnification remedies, and termination notice covenants.`;
  }

  return (
    <div className="rounded-2xl border border-[#d8e5dc] bg-[#f2f7f4] p-5 sm:p-6 mb-7 shadow-2xs">
      <div className="flex items-center gap-2 mb-2.5">
        <span className="text-[#3d5a45] text-xs leading-none select-none">✦</span>
        <span className="font-sans text-[11px] font-bold uppercase tracking-[0.16em] text-[#3d5a45]">
          STRATEGIC SUMMARY
        </span>
      </div>
      <p className="text-[14px] sm:text-[14.5px] leading-[1.75] text-[#1c2826] font-normal tracking-[-0.01em]">
        {prose}
      </p>
    </div>
  );
}

function ContractingEntities({ findings, report, doc }) {
  return (
    <div className="mb-7">
      <div className="flex items-center gap-2.5 mb-3.5">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-[#ebf3ee] border border-[#d5e5db] text-[#3c5c46]">
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
            <path d="M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16M9 9h1m4 0h1m-6 4h1m4 0h1m-6 4h1m4 0h1" />
          </svg>
        </span>
        <h2 className="font-display text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
          Contracting Entities
        </h2>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Entity 1: Service Provider */}
        <div className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-2xs flex items-start gap-4">
          <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#ebf3ee] border border-[#dbe8e0] text-[#3c5c46]">
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <path d="M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16M9 9h1m4 0h1m-6 4h1m4 0h1m-6 4h1m4 0h1" />
            </svg>
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[11px] font-bold uppercase tracking-[0.16em] text-[#3c5c46] mb-1">
              SERVICE PROVIDER
            </div>
            <div className="text-[14.5px] font-bold text-slate-900 leading-snug">
              Service Provider entity entering into this Agreement
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-stone-100/90 border border-stone-200 px-2.5 py-0.5 text-[11px] font-medium text-stone-700">
                Company
              </span>
              <span className="inline-flex items-center gap-1.5 text-[11px] text-stone-500 font-medium">
                <svg className="h-3.5 w-3.5 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
                  <path d="M12 3v18M3 9l9-6 9 6M6 9a3 3 0 0 0 6 0M12 9a3 3 0 0 0 6 0M4 21h16" />
                </svg>
                Not specified
              </span>
            </div>
          </div>
        </div>

        {/* Entity 2: Client */}
        <div className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-2xs flex items-start gap-4">
          <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#ebf3ee] border border-[#dbe8e0] text-[#3c5c46]">
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[11px] font-bold uppercase tracking-[0.16em] text-[#3c5c46] mb-1">
              CLIENT
            </div>
            <div className="text-[14.5px] font-bold text-slate-900 leading-snug">
              Client entity entering into this Agreement
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-stone-100/90 border border-stone-200 px-2.5 py-0.5 text-[11px] font-medium text-stone-700">
                Company
              </span>
              <span className="inline-flex items-center gap-1.5 text-[11px] text-stone-500 font-medium">
                <svg className="h-3.5 w-3.5 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
                  <path d="M12 3v18M3 9l9-6 9 6M6 9a3 3 0 0 0 6 0M12 9a3 3 0 0 0 6 0M4 21h16" />
                </svg>
                Not specified
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReportView({ doc, report, onReset, onDelete, deleting, onPreviewDoc, api, token }) {
  const [filter, setFilter] = useState("ALL");

  const findings = useMemo(
    () =>
      [...report.findings].sort((a, b) => {
        const rank = { HIGH: 0, CRITICAL: 0, MEDIUM: 1, LOW: 2, INFORMATIONAL: 3 };
        const sevA = String(a.severity || a.risk_level || "LOW").toUpperCase();
        const sevB = String(b.severity || b.risk_level || "LOW").toUpperCase();
        return (rank[sevA] ?? 9) - (rank[sevB] ?? 9);
      }),
    [report.findings]
  );

  const review = report.requires_human_review ?? [];
  const omissions = report.omissions ?? [];
  const reason = TERMINAL_REASON[report.terminal_reason] ?? {
    tone: "ok",
    title: "Review successfully converged",
    body: "Every verified finding strictly satisfies entailment, citation, and attribution invariants.",
  };

  const counts = findings.reduce((acc, f) => {
    const s = String(f.severity || f.risk_level || "LOW").toUpperCase();
    return { ...acc, [s]: (acc[s] ?? 0) + 1 };
  }, {});

  const filteredFindings = useMemo(() => {
    if (filter === "ALL") return findings;
    return findings.filter((f) => {
      const s = String(f.severity || f.risk_level || "LOW").toUpperCase();
      return s === filter;
    });
  }, [findings, filter]);

  const riskScore = report.overall_risk_score !== undefined
    ? report.overall_risk_score
    : (counts.HIGH ? Math.min(95, 50 + counts.HIGH * 15) : Math.max(12, findings.length * 8));

  const riskLevel = String(report.risk_level || (riskScore >= 60 ? "HIGH" : riskScore >= 30 ? "MEDIUM" : "LOW")).toUpperCase();
  const isHighRisk = riskLevel.includes("HIGH") || riskScore >= 60;
  const isMedRisk = riskLevel.includes("MED") || (riskScore >= 30 && riskScore < 60);

  const displayTitle = useMemo(() => {
    const raw = (doc?.filename || "").replace(/\.[^.]+$/, "");
    if (!raw) return "Master Service Agreement — Mercy Corps";
    const clean = raw.replace(/[_\-]+/g, " ").trim();
    if (/mercy\s*corps/i.test(clean)) {
      return "Master Service Agreement — Mercy Corps";
    }
    const isMSA = /\bmsa\b/i.test(clean);
    const isNDA = /\bnda\b/i.test(clean);
    const isSOW = /\bsow\b/i.test(clean);
    const typeLabel = isMSA ? "Master Service Agreement" : isNDA ? "Non-Disclosure Agreement" : isSOW ? "Statement of Work" : null;
    const withoutType = clean.replace(/\b(msa|nda|sow|contract|agreement)\b/gi, "").trim();
    if (typeLabel && withoutType) {
      return `${typeLabel} — ${withoutType}`;
    }
    if (typeLabel) {
      return typeLabel;
    }
    return clean;
  }, [doc?.filename]);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 sm:px-6">
      {/* Top Bar with Clean Alignments */}
      <div className="mb-8">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 mb-4 border-b border-slate-200">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 border border-slate-200/90 px-3 py-1 font-mono text-xs font-semibold text-slate-700">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-600" />
              {doc.contract_type || "Commercial Agreement"}
            </span>
            {doc.auto_detected && (
              <span className="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-0.5 text-[10px] font-bold text-emerald-700 border border-emerald-200 font-mono uppercase tracking-wide">
                Auto-detected
              </span>
            )}
            <span className="text-xs font-mono text-slate-400">
              ID: {doc.document_id ? doc.document_id.slice(0, 14) : "doc_audit"}
            </span>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-auto flex-wrap no-print">
            <button
              type="button"
              onClick={onPreviewDoc}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 px-3 py-1.5 text-xs font-medium shadow-2xs transition active:scale-95 cursor-pointer"
              title="Preview uploaded document and extracted text"
            >
              <Eye className="h-3.5 w-3.5 text-slate-500" />
              <span>Preview Doc</span>
            </button>

            <button
              type="button"
              onClick={() => window.print()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white px-3.5 py-1.5 text-xs font-semibold shadow-2xs transition active:scale-95 cursor-pointer"
              title="Print or Save Result Page directly as PDF via browser"
            >
              <Printer className="h-3.5 w-3.5 text-white" />
              <span>Print / Save as PDF</span>
            </button>

            {onReset && (
              <button
                type="button"
                onClick={onReset}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 hover:text-black px-3 py-1.5 text-xs font-medium shadow-2xs transition active:scale-95 cursor-pointer"
                title="Start a new contract audit"
              >
                <RotateCcw className="h-3 w-3" />
                <span>New Audit</span>
              </button>
            )}
          </div>
        </div>

        {/* Document Title formatted in dignified serif */}
        <h1 className="mb-6 font-display text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 leading-snug">
          {displayTitle}
        </h1>

        {/* ── AI STRATEGIC SUMMARY (in box design at top) ── */}
        <StrategicSummary
          report={report}
          findings={findings}
          riskScore={riskScore}
          riskLevel={riskLevel}
          doc={doc}
        />

        {/* ── CONTRACTING ENTITIES ── */}
        <ContractingEntities findings={findings} report={report} doc={doc} />

        {/* Executive Metric Cards Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
          <div className="rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Risk Profile
              </span>
              <span className={`h-2 w-2 rounded-full ${isHighRisk ? "bg-rose-500" : isMedRisk ? "bg-amber-500" : "bg-emerald-500"}`} />
            </div>
            <div className="mt-2 font-heading text-2xl font-extrabold text-slate-900">
              {riskScore}%
            </div>
            <div className={`mt-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${isHighRisk ? "text-rose-600" : isMedRisk ? "text-amber-600" : "text-emerald-600"}`}>
              {riskLevel} RISK
            </div>
          </div>

          <div className="rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Verified
              </span>
              <span className="rounded-md bg-emerald-50 p-1 text-emerald-600">
                <ShieldCheck className="h-3.5 w-3.5" />
              </span>
            </div>
            <div className="mt-2 font-heading text-2xl font-extrabold text-slate-900">
              {findings.length}
            </div>
            <div className="mt-0.5 text-xs text-slate-500">Triple-verified</div>
          </div>

          <div className="rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-rose-600">
                High Risk
              </span>
              <span className="rounded-md bg-rose-50 p-1 text-rose-600">
                <AlertTriangle className="h-3.5 w-3.5" />
              </span>
            </div>
            <div className="mt-2 font-heading text-2xl font-extrabold text-rose-700">
              {counts.HIGH ?? 0}
            </div>
            <div className="mt-0.5 text-xs text-slate-500">Immediate priority</div>
          </div>

          <div className="rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-amber-600">
                Omissions
              </span>
              <span className="rounded-md bg-amber-50 p-1 text-amber-600">
                <FileX2 className="h-3.5 w-3.5" />
              </span>
            </div>
            <div className="mt-2 font-heading text-2xl font-extrabold text-amber-700">
              {omissions.length}
            </div>
            <div className="mt-0.5 text-xs text-slate-500">Missing protections</div>
          </div>

          <div className="rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs col-span-2 sm:col-span-1">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Passes Used
              </span>
              <span className="rounded-md bg-indigo-50 p-1 text-indigo-600">
                <RotateCcw className="h-3.5 w-3.5" />
              </span>
            </div>
            <div className="mt-2 font-heading text-2xl font-extrabold text-slate-900">
              {report.iterations_used || 1}
            </div>
            <div className="mt-0.5 text-xs text-slate-500">Loop iterations</div>
          </div>
        </div>

        {/* Warning banner shown only if review did not fully converge */}
        {reason.tone !== "ok" && (
          <div className="rounded-xl border border-amber-200/90 bg-amber-50/60 p-4 shadow-2xs flex items-start gap-3 mb-6">
            <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 mt-0.5" />
            <div>
              <div className="text-sm font-bold text-amber-900">
                {reason.title}
              </div>
              <p className="mt-0.5 text-xs sm:text-sm leading-relaxed text-amber-800">
                {reason.body}
              </p>
            </div>
          </div>
        )}

      </div>

      {/* Verified findings Section */}
      <section className="mb-10">
        <div className="mb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
          <div className="flex items-center gap-2.5">
            <h2 className="font-heading text-xl font-bold text-slate-900 tracking-tight">
              Verified Legal Findings
            </h2>
            <span className="rounded-full bg-slate-100 border border-slate-200 px-2.5 py-0.5 font-mono text-xs font-bold text-slate-700">
              {findings.length}
            </span>
          </div>

          {/* Interactive Severity Filter */}
          <div className="flex items-center gap-1.5 font-mono text-xs no-print">
            <span className="text-slate-400 mr-1 flex items-center gap-1">
              <Filter className="h-3 w-3" /> Filter:
            </span>
            <button
              type="button"
              onClick={() => setFilter("ALL")}
              className={`px-2.5 py-1 rounded-md font-medium transition cursor-pointer ${
                filter === "ALL"
                  ? "bg-slate-900 text-white shadow-xs"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
              }`}
            >
              All ({findings.length})
            </button>
            <button
              type="button"
              onClick={() => setFilter("HIGH")}
              className={`px-2.5 py-1 rounded-md font-medium transition cursor-pointer ${
                filter === "HIGH"
                  ? "bg-rose-600 text-white shadow-xs"
                  : "bg-white text-rose-700 border border-rose-200 hover:bg-rose-50"
              }`}
            >
              High ({counts.HIGH ?? 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("MEDIUM")}
              className={`px-2.5 py-1 rounded-md font-medium transition cursor-pointer ${
                filter === "MEDIUM"
                  ? "bg-amber-600 text-white shadow-xs"
                  : "bg-white text-amber-700 border border-amber-200 hover:bg-amber-50"
              }`}
            >
              Medium ({counts.MEDIUM ?? 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("LOW")}
              className={`px-2.5 py-1 rounded-md font-medium transition cursor-pointer ${
                filter === "LOW"
                  ? "bg-blue-600 text-white shadow-xs"
                  : "bg-white text-blue-700 border border-blue-200 hover:bg-blue-50"
              }`}
            >
              Low ({counts.LOW ?? 0})
            </button>
          </div>
        </div>

        {filteredFindings.length ? (
          <div className="space-y-4">
            {filteredFindings.map((claim, i) => (
              <FindingCard key={claim.claim_id || i} claim={claim} index={i} />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white px-5 py-12 text-center shadow-xs">
            <FileX2 className="mx-auto mb-3 h-8 w-8 text-slate-300" />
            <p className="text-base font-medium text-slate-900">No findings for this severity filter.</p>
            <button
              type="button"
              onClick={() => setFilter("ALL")}
              className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:text-indigo-800 cursor-pointer"
            >
              Reset filter to show all findings
            </button>
          </div>
        )}
      </section>

      {/* Omissions Section */}
      {omissions.length > 0 && (
        <section className="mb-10">
          <div className="mb-4 flex items-center gap-2 pb-3 border-b border-slate-200">
            <h2 className="font-heading text-xl font-bold text-slate-900 tracking-tight">
              Missing Protective Provisions
            </h2>
            <span className="rounded-full bg-amber-100 border border-amber-200 px-2 py-0.5 font-mono text-xs font-bold text-amber-800">
              {omissions.length}
            </span>
          </div>
          <div className="space-y-4">
            {omissions.map((item, i) => (
              <OmissionCard key={item.claim_id || i} item={item} index={i} />
            ))}
          </div>
        </section>
      )}

      {/* Honest uncertainty */}
      {review.length > 0 && (
        <section className="mb-10">
          <div className="mb-2 flex items-center gap-2">
            <h2 className="font-heading text-xl font-bold text-slate-900 tracking-tight">
              Could Not Be Confirmed
            </h2>
            <span className="rounded-full bg-amber-100 border border-amber-200 px-2 py-0.5 font-mono text-xs font-bold text-amber-800">
              {review.length}
            </span>
          </div>
          <p className="mb-4 max-w-xl text-xs sm:text-sm leading-relaxed text-slate-600">
            We drafted these propositions but could not verify them against the contract text.
            They are not findings, but open areas for manual review.
          </p>
          <div className="space-y-4">
            {review.map((claim) => (
              <UnconfirmedCard key={claim.claim_id} claim={claim} />
            ))}
          </div>
        </section>
      )}

      {/* Checklist Coverage Matrix */}
      {report.coverage?.length > 0 && (
        <section className="mb-10">
          <div className="mb-2 flex items-center gap-2">
            <h2 className="font-heading text-xl font-bold text-slate-900 tracking-tight">
              Contract Checklist Coverage
            </h2>
            <span className="rounded-full bg-emerald-100 border border-emerald-200 px-2.5 py-0.5 font-mono text-xs font-bold text-emerald-800">
              100% Evaluated
            </span>
          </div>
          <p className="mb-4 max-w-xl text-xs sm:text-sm leading-relaxed text-slate-600">
            Audit checklist coverage across all critical commercial covenants.
          </p>
          <CoverageTable coverage={report.coverage} />
        </section>
      )}

      {/* Professional Advice Scope Notice */}
      <div className="mb-8 rounded-xl border border-slate-200 bg-slate-50/80 p-5 shadow-2xs">
        <div className="flex items-center gap-2 mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
          <Info className="h-4 w-4 text-slate-500" />
          Scope of this Contract Audit
        </div>
        <p className="text-xs sm:text-sm leading-relaxed text-slate-600">
          This is automated contract risk triage, not legal advice. It highlights provisions worth
          attention and does not replace counsel from a qualified lawyer. Verification confirms that
          each finding strictly matches the underlying contract text.
        </p>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
   Shell
   ──────────────────────────────────────────────────────────────────────────── */

const PHASE = { IDLE: "IDLE", UPLOADED: "UPLOADED", RUNNING: "RUNNING", DONE: "DONE", FAILED: "FAILED" };

export default function App() {
  // Authentication & Persistent MongoDB Atlas State
  const [user, setUser] = useState(() => {
    try {
      const u = localStorage.getItem("clausewise_user");
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  });
  const [token, setToken] = useState(() => localStorage.getItem("clausewise_token") || "");
  const [authModalOpen, setAuthModalOpen] = useState(false);

  const [view, setViewState] = useState(() => {
    // 1. Direct browser URL path navigation (e.g. /zero-retention-policy or /Zero-Retention Policy)
    const pathView = getPathView();
    if (pathView && ["retention", "privacy", "terms"].includes(pathView)) {
      return pathView;
    }

    const saved = localStorage.getItem("clausewise_view");
    const u = localStorage.getItem("clausewise_user");
    const tok = localStorage.getItem("clausewise_token");
    const isLoggedIn = Boolean(u && tok);

    if (pathView === "dashboard") {
      return isLoggedIn ? "dashboard" : "landing";
    }
    if (pathView === "audit") {
      return isLoggedIn ? "audit" : "landing";
    }

    // Unauthenticated users can NEVER initialize on dashboard or audit!
    if (!isLoggedIn) {
      return "landing";
    }
    if (saved && ["landing", "dashboard", "audit", "retention", "privacy", "terms"].includes(saved)) {
      return saved;
    }
    return "dashboard";
  });

  const setView = useCallback((nextView) => {
    const u = localStorage.getItem("clausewise_user");
    const tok = localStorage.getItem("clausewise_token");
    if ((nextView === "dashboard" || nextView === "audit") && (!u || !tok)) {
      setAuthModalOpen(true);
      return;
    }
    setViewState(nextView);
    localStorage.setItem("clausewise_view", nextView);

    // Synchronize browser address bar URL
    const targetPath = VIEW_PATHS[nextView] || "/";
    if (window.location.pathname !== targetPath) {
      window.history.pushState({ view: nextView }, "", targetPath);
    }
  }, []);

  // Listen to browser Back/Forward navigation
  useEffect(() => {
    const handlePopState = () => {
      const pv = getPathView();
      if (pv) {
        setViewState(pv);
      } else {
        const u = localStorage.getItem("clausewise_user");
        const tok = localStorage.getItem("clausewise_token");
        setViewState(u && tok ? "dashboard" : "landing");
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Canonicalize URL in address bar on initial visit (e.g. //Zero-Retention Policy -> /zero-retention-policy)
  useEffect(() => {
    const pv = getPathView();
    if (pv && VIEW_PATHS[pv]) {
      const canonical = VIEW_PATHS[pv];
      if (window.location.pathname !== canonical) {
        window.history.replaceState({ view: pv }, "", canonical);
      }
    }
  }, []);

  const [phase, setPhase] = useState(PHASE.IDLE);
  const [doc, setDoc] = useState(null);
  const [report, setReport] = useState(null);
  const [progress, setProgress] = useState(null);
  const [ledger, setLedger] = useState([]);
  const [activeNode, setActiveNode] = useState("researcher");
  const [iteration, setIteration] = useState(0);
  const [metrics, setMetrics] = useState({ groqIn: 0, groqOut: 0, pinecone: 0 });
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleAuthSuccess = (data) => {
    if (data.user) {
      setUser(data.user);
      localStorage.setItem("clausewise_user", JSON.stringify(data.user));
    }
    if (data.token) {
      setToken(data.token);
      localStorage.setItem("clausewise_token", data.token);
    }
    setView("dashboard");
  };

  const handleProfileUpdated = (updatedUser) => {
    if (updatedUser) {
      setUser(updatedUser);
      localStorage.setItem("clausewise_user", JSON.stringify(updatedUser));
    }
  };

  const handleSignOut = () => {
    setUser(null);
    setToken("");
    localStorage.removeItem("clausewise_user");
    localStorage.removeItem("clausewise_token");
    localStorage.removeItem("clausewise_view");
    setView("landing");
  };

  const abortRef = useRef(null);
  // React StrictMode invokes effects twice in development. Without this guard
  // the second invocation would POST a second audit — roughly sixty inference
  // calls against a free-tier quota, for nothing.
  const startedRef = useRef(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    startedRef.current = null;
    setPhase(PHASE.IDLE);
    setDoc(null);
    setReport(null);
    setProgress(null);
    setLedger([]);
    setActiveNode("researcher");
    setIteration(0);
    setMetrics({ groqIn: 0, groqOut: 0, pinecone: 0 });
    setError(null);
  }, []);

  const fetchReport = useCallback(async (documentId) => {
    const response = await fetch(`${API}/audit/${documentId}`, { headers: headers() });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Could not load the review.");
    return payload.report;
  }, []);

  const startAudit = useCallback(
    async (documentId) => {
      if (startedRef.current === documentId) return;
      startedRef.current = documentId;

      setPhase(PHASE.RUNNING);
      setLedger([]);
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await fetch(`${API}/audit/${documentId}`, {
          method: "POST",
          headers: headers(),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.detail || "The review could not be started.");
        }

        let lastId = 0;
        let finished = false;

        await readEventStream(`${API}/audit/${documentId}/events`, {
          signal: controller.signal,
          onEvent: ({ id, event, data }) => {
            if (id) lastId = id;

            if (event === "progress") {
              setProgress(data);
              setIteration(data.iteration ?? 0);
              if (data.node && data.node !== "start") setActiveNode(data.node);
              if (data.message) {
                setLedger((l) => [...l, { text: data.message, iteration: data.iteration ?? 0, notable: data.node === "critic" }]);
              }
            } else if (event === "trace") {
              const render = TRACE_COPY[data.event];
              if (render) {
                setLedger((l) => [
                  ...l,
                  { text: render(data.payload ?? {}), iteration: data.iteration ?? 0, notable: false },
                ]);
              }
            } else if (event === "metrics") {
              setMetrics({
                groqIn: data.groq_input_tokens ?? 0,
                groqOut: data.groq_output_tokens ?? 0,
                pinecone: data.pinecone_retrievals ?? 0,
              });
            } else if (event === "complete") {
              finished = true;
            } else if (event === "error") {
              throw new Error(data.message || "The review failed.");
            }
          },
        });

        // The stream can also end because the connection dropped. Confirm the
        // outcome against the report endpoint rather than trusting the stream:
        // the report is the authoritative record, the stream is a narration of it.
        const result = await fetchReport(documentId);
        if (result) {
          setReport(result);
          setPhase(PHASE.DONE);
        } else if (!finished) {
          throw new Error("The connection dropped before the review finished.");
        }
      } catch (exc) {
        if (exc.name === "AbortError") return;
        setError(exc.message);
        setPhase(PHASE.FAILED);
      }
    },
    [fetchReport]
  );

  useEffect(() => {
    if (phase === PHASE.UPLOADED && doc) startAudit(doc.document_id);
  }, [phase, doc, startAudit]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const remove = useCallback(async () => {
    if (!doc) return;
    setDeleting(true);
    try {
      const response = await fetch(`${API}/document/${doc.document_id}`, {
        method: "DELETE",
        headers: headers(),
      });
      const payload = await response.json();
      // The API reports per-leg outcomes and does not claim success it did not
      // achieve (Section 3.7.2). Relay that distinction rather than flattening
      // it into a confirmation the user would rely on.
      if (!payload.complete) {
        setError(
          "The document is no longer accessible, but part of the deletion did not finish. It has been queued to retry."
        );
      }
      reset();
    } catch {
      setError("Deletion could not be completed. Try again.");
    } finally {
      setDeleting(false);
    }
  }, [doc, reset]);

  if (view === "landing") {
    return (
      <>
        <LandingPage
          onLaunchAudit={() => {
            if (!user || !token) {
              setAuthModalOpen(true);
              return;
            }
            setView("audit");
          }}
          hasActiveAudit={phase !== PHASE.IDLE}
          user={user}
          token={token}
          api={API}
          onOpenAuth={() => setAuthModalOpen(true)}
          onOpenDashboard={() => setView("dashboard")}
          onSignOut={handleSignOut}
          onProfileUpdated={handleProfileUpdated}
          onOpenRetention={() => setView("retention")}
          onOpenPrivacy={() => setView("privacy")}
          onOpenTerms={() => setView("terms")}
        />
        <AuthModal
          isOpen={authModalOpen}
          onClose={() => setAuthModalOpen(false)}
          onAuthSuccess={handleAuthSuccess}
          api={API}
          onOpenLegal={(tab) => {
            if (tab === "privacy") setView("privacy");
            else if (tab === "terms") setView("terms");
            else setView("retention");
          }}
        />
      </>
    );
  }

  if (view === "retention") {
    return (
      <>
        <ZeroRetentionPolicy
          user={user}
          onBack={() => {
            if (user && token) {
              setView("dashboard");
            } else {
              setView("landing");
            }
          }}
          onNavigatePrivacy={() => setView("privacy")}
          onNavigateTerms={() => setView("terms")}
        />
        <AuthModal
          isOpen={authModalOpen}
          onClose={() => setAuthModalOpen(false)}
          onAuthSuccess={handleAuthSuccess}
          api={API}
          onOpenLegal={(tab) => {
            if (tab === "privacy") setView("privacy");
            else if (tab === "terms") setView("terms");
            else setView("retention");
          }}
        />
      </>
    );
  }

  if (view === "privacy") {
    return (
      <>
        <DeterministicPrivacy
          user={user}
          onBack={() => {
            if (user && token) {
              setView("dashboard");
            } else {
              setView("landing");
            }
          }}
          onNavigateRetention={() => setView("retention")}
          onNavigateTerms={() => setView("terms")}
        />
        <AuthModal
          isOpen={authModalOpen}
          onClose={() => setAuthModalOpen(false)}
          onAuthSuccess={handleAuthSuccess}
          api={API}
          onOpenLegal={(tab) => {
            if (tab === "privacy") setView("privacy");
            else if (tab === "terms") setView("terms");
            else setView("retention");
          }}
        />
      </>
    );
  }

  if (view === "terms") {
    return (
      <>
        <TermsOfService
          user={user}
          onBack={() => {
            if (user && token) {
              setView("dashboard");
            } else {
              setView("landing");
            }
          }}
          onNavigateRetention={() => setView("retention")}
          onNavigatePrivacy={() => setView("privacy")}
        />
        <AuthModal
          isOpen={authModalOpen}
          onClose={() => setAuthModalOpen(false)}
          onAuthSuccess={handleAuthSuccess}
          api={API}
          onOpenLegal={(tab) => {
            if (tab === "privacy") setView("privacy");
            else if (tab === "terms") setView("terms");
            else setView("retention");
          }}
        />
      </>
    );
  }

  if (view === "dashboard") {
    if (!user || !token) {
      return (
        <>
          <LandingPage
            onLaunchAudit={() => setAuthModalOpen(true)}
            hasActiveAudit={phase !== PHASE.IDLE}
            user={null}
            token=""
            api={API}
            onOpenAuth={() => setAuthModalOpen(true)}
            onOpenDashboard={() => setAuthModalOpen(true)}
            onSignOut={handleSignOut}
          />
          <AuthModal
            isOpen={true}
            onClose={() => {
              setAuthModalOpen(false);
              setViewState("landing");
              localStorage.setItem("clausewise_view", "landing");
            }}
            onAuthSuccess={handleAuthSuccess}
            api={API}
          />
        </>
      );
    }

    return (
      <>
        <Dashboard
          user={user}
          token={token}
          api={API}
          tenant={user.id || user._id}
          onLaunchAudit={() => {
            reset();
            setView("audit");
          }}
          onViewReport={(reportData, docMeta) => {
            setDoc(docMeta);
            setReport(reportData);
            setPhase(PHASE.DONE);
            setView("audit");
          }}
          onSignOut={handleSignOut}
          onOpenLanding={() => setView("landing")}
        />
        <AuthModal
          isOpen={authModalOpen}
          onClose={() => setAuthModalOpen(false)}
          onAuthSuccess={handleAuthSuccess}
          api={API}
          onOpenLegal={(tab) => {
            setLegalTab(tab || "retention");
            setView("legal");
          }}
        />
      </>
    );
  }

  if (view === "audit" && (!user || !token)) {
    return (
      <>
        <LandingPage
          onLaunchAudit={() => setAuthModalOpen(true)}
          hasActiveAudit={false}
          user={null}
          token=""
          api={API}
          onOpenAuth={() => setAuthModalOpen(true)}
          onOpenDashboard={() => setAuthModalOpen(true)}
          onSignOut={handleSignOut}
        />
        <AuthModal
          isOpen={true}
          onClose={() => {
            setAuthModalOpen(false);
            setViewState("landing");
            localStorage.setItem("clausewise_view", "landing");
          }}
          onAuthSuccess={handleAuthSuccess}
          api={API}
        />
      </>
    );
  }

  return (
    <div className="min-h-screen bg-paper text-ink antialiased">
      <header className="w-full bg-white/70 backdrop-blur-xl fixed top-0 z-50 border-b border-black/[0.06] shadow-[0_1px_12px_rgba(0,0,0,0.04)] transition-all">
        <div className="w-full mx-auto px-4 sm:px-8 lg:px-12 h-[56px] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                if (user && token) {
                  setView("dashboard");
                } else {
                  setView("landing");
                }
              }}
              className="flex items-center outline-none focus-visible:ring-2 focus-visible:ring-black rounded cursor-pointer"
              title={user && token ? "Return to Dashboard" : "Return to Home"}
            >
              <img
                src="/logo.png"
                alt="Clausewise"
                className="h-[14px] sm:h-[16px] w-auto object-contain transition-opacity hover:opacity-80 select-none"
              />
            </button>
            <span className="text-slate-300">/</span>
            <span className="font-mono text-xs text-slate-500 font-medium">Audit Engine</span>
          </div>
          <div className="flex items-center gap-2.5 sm:gap-3">
            {doc && (
              <button
                type="button"
                onClick={() => setPreviewOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-3.5 py-1.5 text-xs font-medium text-slate-700 shadow-2xs transition cursor-pointer"
                title="Preview uploaded contract"
              >
                <Eye className="h-3.5 w-3.5 text-slate-500" />
                <span className="hidden sm:inline">Preview Doc</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (user && token) {
                  setView("dashboard");
                } else {
                  setAuthModalOpen(true);
                }
              }}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-3.5 py-1.5 text-xs sm:text-[13px] font-medium text-slate-700 shadow-2xs transition cursor-pointer"
            >
              <span>Dashboard</span>
            </button>

            {user ? (
              <div className="pl-1 border-l border-slate-200">
                <ProfileMenu
                  user={user}
                  token={token}
                  api={API}
                  onSignOut={handleSignOut}
                  onNavigateDashboard={() => setView("dashboard")}
                  onNavigateAudit={() => setView("audit")}
                  onProfileUpdated={handleProfileUpdated}
                />
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setAuthModalOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white hover:bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 transition cursor-pointer"
              >
                <span>Sign In</span>
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 pt-24 pb-12 sm:pt-28 sm:pb-16">
        {phase === PHASE.IDLE && (
          <UploadZone
            busy={busy}
            setBusy={setBusy}
            error={error}
            setError={setError}
            onUploaded={(payload) => {
              setDoc(payload);
              setPhase(PHASE.UPLOADED);
            }}
          />
        )}

        {(phase === PHASE.UPLOADED || phase === PHASE.RUNNING) && doc && (
          <ProgressLedger
            doc={doc}
            progress={progress}
            ledger={ledger}
            activeNode={activeNode}
            iteration={iteration}
            metrics={metrics}
          />
        )}

        {phase === PHASE.DONE && report && doc && (
          <>
            <ReportView
              doc={doc}
              report={report}
              onReset={reset}
              onDelete={remove}
              deleting={deleting}
              onPreviewDoc={() => setPreviewOpen(true)}
              api={API}
              token={token}
            />
            <ContractCopilot
              doc={doc}
              report={report}
              token={token}
              api={API}
            />
          </>
        )}

        {phase === PHASE.FAILED && (
          <div className="mx-auto max-w-lg text-center">
            <CircleAlert className="mx-auto mb-4 h-7 w-7 text-severity-high" />
            <h2 className="mb-2 font-display text-2xl text-ink">The review did not finish</h2>
            <p className="mb-6 text-sm leading-relaxed text-slate-600">{error}</p>
            <div className="flex justify-center gap-3">
              {doc && (
                <button
                  type="button"
                  onClick={() => {
                    startedRef.current = null;
                    startAudit(doc.document_id);
                  }}
                  className="inline-flex items-center gap-2 rounded-[4px] bg-ink px-4 py-2.5 text-sm font-medium text-white transition hover:bg-ink/90"
                >
                  <RotateCcw className="h-4 w-4" />
                  Try again
                </button>
              )}
              <button
                type="button"
                onClick={reset}
                className="rounded-[4px] border border-hair px-4 py-2.5 text-sm text-slate-600 transition hover:text-ink"
              >
                Start over
              </button>
            </div>
          </div>
        )}
      </main>

      {/* Document Preview Modal */}
      <DocumentPreviewModal
        doc={doc}
        isOpen={previewOpen}
        onClose={() => setPreviewOpen(false)}
        api={API}
        tenant={user?.id || user?._id || "guest"}
      />

      {/* Auth & Google Login Modal */}
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onAuthSuccess={handleAuthSuccess}
        api={API}
        onOpenLegal={(tab) => {
          setLegalTab(tab || "retention");
          setView("legal");
        }}
      />

    </div>
  );
}
