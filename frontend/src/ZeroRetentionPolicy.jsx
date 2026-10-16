import React, { useEffect } from "react";
import { ArrowLeft } from "lucide-react";

export default function ZeroRetentionPolicy({
  user,
  onBack,
  onNavigatePrivacy,
  onNavigateTerms,
}) {
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return (
    <div className="min-h-screen bg-black text-zinc-300 antialiased selection:bg-white/20 selection:text-white flex flex-col justify-between">
      {/* Top Header */}
      <header className="w-full bg-black/90 backdrop-blur-md fixed top-0 z-50 border-b border-zinc-900">
        <div className="w-full max-w-3xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onBack}
              className="flex items-center outline-none focus-visible:ring-1 focus-visible:ring-white rounded cursor-pointer"
              title="Return"
            >
              <img
                src="/logo.png"
                alt="Clausewise"
                className="h-3.5 sm:h-4 w-auto object-contain invert select-none opacity-90 hover:opacity-100 transition"
              />
            </button>
            <span className="text-zinc-700">/</span>
            <span className="font-mono text-xs text-zinc-400">Zero-Retention Policy</span>
          </div>

          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white transition cursor-pointer"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>{user ? "Back to Dashboard" : "Back to Home"}</span>
          </button>
        </div>
      </header>

      {/* Main Reading Flow — Clean Text, No Boxes */}
      <main className="w-full max-w-3xl mx-auto px-6 pt-28 pb-20 flex-1">
        {/* Title & Metadata */}
        <div className="mb-12">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white mb-3">
            Zero-Retention Policy
          </h1>
          <p className="text-xs font-mono text-zinc-500">
            Last Updated: October 2026 · Confidential Data Lifecycle Standard
          </p>
        </div>

        {/* Narrative Flow */}
        <div className="space-y-10 text-sm sm:text-base leading-relaxed text-zinc-400">
          <div>
            <p className="text-zinc-300 text-base sm:text-lg leading-relaxed">
              Confidentiality is the fundamental requirement of contract review. ClauseWise operates on a strict zero-retention architecture: customer contracts, deal terms, and proprietary clauses exist exclusively for the fleeting duration required to analyze and report findings.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              1. 24-Hour Ephemeral Purge
            </h2>
            <p>
              Uploaded contract files (PDF and DOCX binaries) and extracted plaintext are queued for automatic, cryptographic deletion exactly 24 hours after upload. Once purged, files and raw character offsets cannot be recovered or restored by any party.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              2. Strict Zero Model Training
            </h2>
            <p>
              Your contracts and confidential business data are never used to train, fine-tune, adapt, or evaluate artificial intelligence foundation models. Inference inputs are processed strictly ephemerally within stateless runtime environments.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              3. Isolated Tenant Execution
            </h2>
            <p>
              Every audit job executes inside a mathematically segregated tenant sandbox. Memory embeddings, contextual tokens, and parsing indices generated during an audit are isolated to that specific session and cleared from server memory upon completion.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              4. Immediate Permanent Erasure on Demand
            </h2>
            <p>
              You do not need to wait 24 hours to remove documents. Clicking "Delete Audit" or "Delete Account" immediately executes an unrecoverable cascade delete across all database records and storage blocks.
            </p>
          </div>
        </div>

        {/* Footer Navigation Links */}
        <div className="mt-16 pt-8 border-t border-zinc-900 flex flex-wrap items-center justify-between gap-4 text-xs">
          <span className="text-zinc-600 font-mono">Other Policies:</span>
          <div className="flex items-center gap-5">
            <a
              href="/deterministic-privacy"
              onClick={(e) => {
                e.preventDefault();
                onNavigatePrivacy();
              }}
              className="text-zinc-400 hover:text-white transition cursor-pointer"
            >
              Deterministic Privacy →
            </a>
            <a
              href="/terms-of-service"
              onClick={(e) => {
                e.preventDefault();
                onNavigateTerms();
              }}
              className="text-zinc-400 hover:text-white transition cursor-pointer"
            >
              Terms of Service →
            </a>
          </div>
        </div>
      </main>

      {/* Minimal Footer */}
      <footer className="w-full border-t border-zinc-900 bg-black py-6 text-center text-xs text-zinc-600">
        <div className="max-w-3xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div>© 2026 ClauseWise AI</div>
          <div className="font-mono text-[11px] text-zinc-600">Zero-Retention Architecture</div>
        </div>
      </footer>
    </div>
  );
}
