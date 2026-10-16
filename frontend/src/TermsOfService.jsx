import React, { useEffect } from "react";
import { ArrowLeft } from "lucide-react";

export default function TermsOfService({
  user,
  onBack,
  onNavigateRetention,
  onNavigatePrivacy,
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
            <span className="font-mono text-xs text-zinc-400">Terms of Service</span>
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
            Terms of Service
          </h1>
          <p className="text-xs font-mono text-zinc-500">
            Last Updated: October 2026 · Master Terms of Use
          </p>
        </div>

        {/* Narrative Flow */}
        <div className="space-y-10 text-sm sm:text-base leading-relaxed text-zinc-400">
          <div>
            <p className="text-zinc-300 text-base sm:text-lg leading-relaxed">
              These Terms of Service govern your access to and use of ClauseWise AI. By uploading contracts or using our audit services, you agree to these terms.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              1. Risk Triage Tool · Not Formal Legal Counsel
            </h2>
            <p>
              ClauseWise is an automated contract intelligence, risk triage, and clause review tool. ClauseWise does <strong>not</strong> provide legal representation, statutory legal counsel, or attorney-client privileged advice. All findings, severity classifications, and redlines are automated decision-support outputs; users should consult licensed legal counsel before executing or amending any agreement.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              2. 100% User Ownership of Contract Materials
            </h2>
            <p>
              You retain all right, title, and intellectual property ownership in all agreements, documents, schedules, and text submitted to ClauseWise. ClauseWise asserts no ownership, copyright, or proprietary interest in your confidential materials.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              3. Authorized Submission &amp; Acceptable Use
            </h2>
            <p>
              You represent and warrant that you possess all necessary authority, legal rights, and corporate authorizations to upload documents for automated review. You agree not to upload malicious binaries, interfere with tenant sandboxes, or attempt to reverse-engineer our proprietary scoring models.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              4. Automated Redline Suggestions &amp; Disclaimers
            </h2>
            <p>
              Proposed redline drafts and risk commentary are generated algorithmically against standard commercial benchmarks. The user remains solely responsible for evaluating whether any proposed redline fits their commercial, financial, and legal requirements.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              5. Limitation of Liability
            </h2>
            <p>
              ClauseWise is provided on an "as is" and "as available" basis. To the maximum extent permitted under applicable law, ClauseWise and its contributors disclaim all warranties, express or implied, and shall not be liable for any indirect, incidental, or consequential damages resulting from contract interpretations or reliance on automated triage outputs.
            </p>
          </div>

          <div className="border-t border-zinc-900 pt-8 space-y-3">
            <h2 className="text-lg sm:text-xl font-semibold text-white">
              6. Permanent Account and Data Deletion
            </h2>
            <p>
              You may terminate your account at any time using the "Delete Account" setting in your profile. Account deletion permanently eradicates all user metadata, audit records, and GridFS document binaries from our databases with zero residual persistence.
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
              href="/deterministic-privacy"
              onClick={(e) => {
                e.preventDefault();
                onNavigatePrivacy();
              }}
              className="text-zinc-400 hover:text-white transition cursor-pointer"
            >
              Deterministic Privacy →
            </a>
          </div>
        </div>
      </main>

      {/* Minimal Footer */}
      <footer className="w-full border-t border-zinc-900 bg-black py-6 text-center text-xs text-zinc-600">
        <div className="max-w-3xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div>© 2026 ClauseWise AI</div>
          <div className="font-mono text-[11px] text-zinc-600">Terms of Service · Platform Governance</div>
        </div>
      </footer>
    </div>
  );
}
