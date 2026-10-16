import React, { useState, useEffect, useRef } from "react";
import {
  FileText,
  X,
  ExternalLink,
  Eye,
  Layers,
  Search,
  Download,
  Loader2,
  Copy,
  Check,
  FileCheck2,
  AlertCircle,
  Hash,
  ShieldCheck,
} from "lucide-react";

export default function DocumentPreviewModal({ doc, isOpen, onClose, api, tenant }) {
  const [activeTab, setActiveTab] = useState("pdf"); // 'pdf' | 'text'
  const [docData, setDocData] = useState(null);
  const [loadingText, setLoadingText] = useState(false);
  const [pdfBlobUrl, setPdfBlobUrl] = useState(null);
  const [loadingPdf, setLoadingPdf] = useState(false);
  const [pdfError, setPdfError] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedClause, setSelectedClause] = useState(null);
  const [copied, setCopied] = useState(false);
  const textContainerRef = useRef(null);

  const directPdfUrl = doc?.document_id
    ? `${api}/document/${doc.document_id}/pdf?tenant_id=${tenant}`
    : null;

  useEffect(() => {
    if (!isOpen || !doc?.document_id) {
      setPdfBlobUrl(null);
      setPdfError(null);
      setDocData(null);
      setSelectedClause(null);
      return;
    }

    // Fetch canonical text & structural breakdown
    setLoadingText(true);
    fetch(`${api}/document/${doc.document_id}/text?tenant_id=${tenant}`, {
      headers: { "X-Tenant-Id": tenant },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setDocData(data);
      })
      .catch((err) => console.error("Could not fetch document text:", err))
      .finally(() => setLoadingText(false));

    // Fetch PDF as Object Blob URL
    setLoadingPdf(true);
    setPdfError(null);
    let createdUrl = null;

    fetch(directPdfUrl, {
      headers: { "X-Tenant-Id": tenant },
    })
      .then(async (res) => {
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Server returned status ${res.status}`);
        }
        return res.blob();
      })
      .then((blob) => {
        createdUrl = URL.createObjectURL(blob);
        setPdfBlobUrl(createdUrl);
        setPdfError(null);
      })
      .catch((err) => {
        console.warn("Could not load PDF blob:", err);
        setPdfError(err.message || "Failed to load PDF preview");
        setPdfBlobUrl(null);
      })
      .finally(() => setLoadingPdf(false));

    return () => {
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [isOpen, doc?.document_id, api, tenant, directPdfUrl]);

  if (!isOpen || !doc) return null;

  const clauses = docData?.structure?.clauses || [];
  const filteredClauses = searchTerm
    ? clauses.filter(
        (c) =>
          c.title?.toLowerCase().includes(searchTerm.toLowerCase()) ||
          c.clause_id?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : clauses;

  const handleCopyText = () => {
    if (!docData?.text) return;
    navigator.clipboard.writeText(docData.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const scrollToClause = (clause) => {
    setSelectedClause(clause);
    if (!textContainerRef.current || !docData?.text) return;
    
    // Find text occurrence or approximate position
    const charStart = clause.char_start || 0;
    const totalLen = docData.text.length || 1;
    const scrollPercent = charStart / totalLen;
    const container = textContainerRef.current;
    container.scrollTo({
      top: scrollPercent * container.scrollHeight,
      behavior: "smooth",
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-xs p-3 sm:p-6 animate-fadeIn no-print">
      <div className="flex h-[92vh] w-full max-w-5xl flex-col rounded-2xl bg-white shadow-2xl overflow-hidden border border-slate-200">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/90 px-6 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-white shadow-xs p-1">
              <img src="/favicon.png" alt="Clausewise" className="h-6 w-6 object-contain" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-heading text-base font-bold text-slate-900 truncate max-w-md">
                  {doc.filename || "Uploaded Contract Document"}
                </h3>
                <span className="rounded bg-indigo-100 px-2 py-0.5 font-mono text-[10px] font-bold text-indigo-800">
                  {doc.contract_type || "PDF"}
                </span>
              </div>
              <p className="text-xs text-slate-500 font-mono">
                ID: {doc.document_id} · {doc.n_pages ? `${doc.n_pages} pages` : "Original Source Document"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Tab switch */}
            <div className="flex items-center rounded-lg bg-slate-200/80 p-1 text-xs font-medium">
              <button
                type="button"
                onClick={() => setActiveTab("pdf")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition ${
                  activeTab === "pdf"
                    ? "bg-white text-slate-900 shadow-xs font-semibold"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <Eye className="h-3.5 w-3.5" />
                Original PDF
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("text")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 transition ${
                  activeTab === "text"
                    ? "bg-white text-slate-900 shadow-xs font-semibold"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <Layers className="h-3.5 w-3.5" />
                Extracted Text &amp; Clauses
                {clauses.length > 0 && (
                  <span className="ml-1 rounded-full bg-indigo-100 px-1.5 py-0.2 font-mono text-[10px] font-bold text-indigo-700">
                    {clauses.length}
                  </span>
                )}
              </button>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-2 text-slate-400 hover:bg-slate-200 hover:text-slate-700 transition"
              title="Close Preview"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-hidden bg-slate-100/40">
          {activeTab === "pdf" ? (
            <div className="h-full w-full relative flex flex-col items-center justify-center">
              {loadingPdf ? (
                <div className="text-center p-8">
                  <Loader2 className="h-8 w-8 animate-spin text-indigo-600 mx-auto mb-3" />
                  <p className="text-sm font-medium text-slate-700">Streaming document preview...</p>
                  <p className="text-xs font-mono text-slate-400 mt-1">Retrieving canonical PDF stream</p>
                </div>
              ) : pdfBlobUrl ? (
                <>
                  <iframe
                    src={`${pdfBlobUrl}#toolbar=1&navpanes=0`}
                    title="PDF Document Preview"
                    className="h-full w-full border-0 bg-white"
                  />
                  <div className="absolute bottom-4 right-4 flex items-center gap-2">
                    <a
                      href={pdfBlobUrl}
                      download={doc.filename || "contract.pdf"}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 px-3 py-1.5 text-xs font-medium shadow-sm transition"
                    >
                      <Download className="h-3.5 w-3.5 text-slate-500" />
                      Download PDF
                    </a>
                    <a
                      href={directPdfUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white px-3 py-1.5 text-xs font-medium shadow-md transition"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      Open Fullscreen
                    </a>
                  </div>
                </>
              ) : (
                <div className="mx-auto max-w-md text-center p-8 bg-white rounded-2xl border border-slate-200 shadow-sm">
                  <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
                    <FileText className="h-6 w-6" />
                  </div>
                  <h4 className="text-base font-bold text-slate-900 mb-1">
                    Canonical Text Available
                  </h4>
                  <p className="text-xs text-slate-600 mb-5 leading-relaxed">
                    The structured clause breakdown and full canonical text for{" "}
                    <span className="font-semibold text-slate-800">{doc.filename || "this contract"}</span>{" "}
                    are ready for inspection.
                  </p>
                  <button
                    type="button"
                    onClick={() => setActiveTab("text")}
                    className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 text-xs font-semibold shadow-xs transition"
                  >
                    <Layers className="h-4 w-4" />
                    Inspect Extracted Clauses ({clauses.length})
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="grid h-full grid-cols-1 md:grid-cols-12 overflow-hidden">
              {/* Sidebar Clause List */}
              <div className="md:col-span-4 border-r border-slate-200 bg-white flex flex-col h-full">
                <div className="p-3 border-b border-slate-200">
                  <div className="relative">
                    <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-400" />
                    <input
                      type="text"
                      placeholder="Search clauses or titles..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="w-full rounded-lg border border-slate-200 bg-slate-50 pl-8 pr-3 py-1.5 text-xs focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                    />
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                  {loadingText ? (
                    <div className="p-8 text-center text-xs text-slate-500">
                      <Loader2 className="mx-auto h-5 w-5 animate-spin text-indigo-600 mb-2" />
                      Loading structural index...
                    </div>
                  ) : filteredClauses.length > 0 ? (
                    filteredClauses.map((c) => {
                      const isSelected = selectedClause?.clause_id === c.clause_id;
                      return (
                        <button
                          key={c.clause_id}
                          type="button"
                          onClick={() => scrollToClause(c)}
                          className={`w-full text-left rounded-lg p-2.5 text-xs transition border ${
                            isSelected
                              ? "bg-indigo-50/80 border-indigo-200 text-indigo-950 shadow-xs"
                              : "border-transparent hover:bg-slate-50 text-slate-800"
                          }`}
                        >
                          <div className="flex items-center justify-between font-mono text-[11px] mb-0.5">
                            <span className="font-bold text-indigo-600 flex items-center gap-1">
                              <Hash className="h-3 w-3" />
                              {c.clause_id}
                            </span>
                            {c.char_start !== undefined && (
                              <span className="text-[10px] text-slate-400">
                                [{c.char_start}:{c.char_end}]
                              </span>
                            )}
                          </div>
                          <div className="font-medium truncate">{c.title || "Untitled Provision"}</div>
                        </button>
                      );
                    })
                  ) : (
                    <div className="p-6 text-center text-xs text-slate-400">
                      No matching clauses found.
                    </div>
                  )}
                </div>
              </div>

              {/* Canonical Text Body */}
              <div className="md:col-span-8 flex flex-col h-full bg-slate-50/50 overflow-hidden">
                {/* Text action bar */}
                <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2.5 text-xs">
                  <div className="flex items-center gap-2 text-slate-600 font-mono text-[11px]">
                    <ShieldCheck className="h-4 w-4 text-emerald-600" />
                    <span>Deterministic Canonical Layer (V2)</span>
                  </div>
                  <button
                    type="button"
                    onClick={handleCopyText}
                    className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 hover:bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 transition"
                  >
                    {copied ? (
                      <>
                        <Check className="h-3.5 w-3.5 text-emerald-600" />
                        Copied
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5 text-slate-500" />
                        Copy Raw Text
                      </>
                    )}
                  </button>
                </div>

                <div
                  ref={textContainerRef}
                  className="flex-1 p-6 overflow-y-auto font-mono text-xs leading-relaxed text-slate-800"
                >
                  {loadingText ? (
                    <div className="p-12 text-center text-xs text-slate-500">
                      <Loader2 className="mx-auto h-6 w-6 animate-spin text-indigo-600 mb-3" />
                      Extracting canonical text layer...
                    </div>
                  ) : (
                    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs whitespace-pre-wrap selection:bg-indigo-100 selection:text-indigo-900">
                      {docData?.text || "No text available for this document."}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
