import React, { useEffect } from "react";
import { ArrowLeft } from "lucide-react";

export default function DeterministicPrivacy({
  user,
  onBack,
  onNavigateRetention,
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
            <span className="font-mono text-xs text-zinc-400">Deterministic Privacy</span>
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
            Deterministic Privacy
          </h1>
          <p className="text-xs font-mono text-zinc-500">
            Last Updated: October 2026 · Verifiable Mathematical Citation Standard
          </p>
        </div>

        {/* Narrative Flow */}
        <div className="space-y-10 text-sm sm:text-base leading-relaxed text-zinc-400">
          <div>
            <p className="text-zinc-300 text-base sm:text-lg leading-relaxed">
              Generative AI systems frequently speculate, paraphrase, or hallucinate findings that do not exist in the underlying legal text. ClauseWise was engineered to solve this through deterministic verification: every risk finding is mathematically tied to verbatim citations.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              1. Mathematical Grounding (V1·V2·V3 Triple-Verification)
            </h2>
            <p>
              Before any finding reaches your report, it must pass a triple-verification pipeline: V1 natural language entailment (verifying the factual truth of the proposition), V2 verbatim quotation boundaries (matching exact character strings in the original file), and V3 party attribution (verifying which party bears the obligation). Any finding that cannot be proven against verbatim text is discarded by our critic engine.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              2. Transport &amp; Storage Encryption
            </h2>
            <p>
              All traffic between your browser and the ClauseWise audit engine is encrypted using modern TLS 1.3 with forward secrecy. Transient document storage uses AES-256 encryption at rest. Decryption keys are managed via isolated hardware security environments.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              3. Zero Commercial Telemetry &amp; Ad Trackers
            </h2>
            <p>
              We collect only the bare minimum Google OAuth identity attributes (name, email address, profile avatar) required to authenticate your tenant workspace. We do not inject advertising pixels, marketing trackers, or third-party behavioral analytics into any contract review pages.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              4. Cryptographic Tenant Segregation
            </h2>
            <p>
              Every API call and audit run carries an authenticated cryptographic tenant identifier. Audit histories, ledgers, and contract binaries belonging to one account are mathematically inaccessible to any other user or organization.
            </p>
          </div>
        </div>

        {/* Footer Navigation Links */}
        <div className="mt-16 pt-8 border-t border-zinc-900 flex flex-wrap items-center justify-between gap-4 text-xs">
          <span className="text-zinc-600 font-mono">Other Policies:</span>
          <div className="flex items-center gap-5">
            <a
              href="/zero-retention-policy"
              onClick={(e) => {
                e.preventDefault();
                onNavigateRetention();
              }}
              className="text-zinc-400 hover:text-white transition cursor-pointer"
            >
              Zero-Retention Policy →
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
          <div className="font-mono text-[11px] text-zinc-600">Deterministic Privacy Standard</div>
        </div>
      </footer>
    </div>
  );
}
