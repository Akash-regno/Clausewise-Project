import React, { useState } from "react";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { X, AlertCircle } from "lucide-react";

const GOOGLE_CLIENT_ID =
  import.meta.env.VITE_GOOGLE_CLIENT_ID ||
  "1050607714350-uno5makl8dkkqhbtnbcu198maujcbvtu.apps.googleusercontent.com";

export default function AuthModal({
  isOpen,
  onClose,
  onAuthSuccess,
  api,
  onOpenLegal,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleGoogleSuccess = async (credentialResponse) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${api}/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: credentialResponse.credential }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Authentication could not be completed.");
      onAuthSuccess(data);
      onClose();
    } catch (err) {
      setError(err.message || "Sign-in failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-md animate-fade-in"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-[420px] bg-white rounded-3xl shadow-2xl border border-slate-200/90 overflow-hidden transform transition-all"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="flex items-center justify-between px-7 pt-7 pb-2">
          <div className="flex items-center gap-2">
            <img src="/logo.png" alt="Clausewise" className="h-[14px] w-auto object-contain" />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition cursor-pointer"
            aria-label="Close modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="px-7 py-5">
          <h2 className="font-display text-2xl font-bold text-slate-900 tracking-tight mb-2">
            Sign in to ClauseWise
          </h2>
          <p className="text-xs sm:text-[13px] text-slate-500 leading-relaxed mb-7">
            Access your secure contract risk intelligence ledger, triple-verified findings, and legal audit history.
          </p>

          {error && (
            <div className="mb-5 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-start gap-2.5">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Official Google OAuth Sign In */}
          <div className="space-y-4">
            <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
              <div className="w-full flex justify-center py-1">
                <GoogleLogin
                  onSuccess={handleGoogleSuccess}
                  onError={() => setError("Google authentication encountered an error. Check account permissions.")}
                  useOneTap
                  shape="pill"
                  theme="outline"
                  size="large"
                  text="continue_with"
                  width="100%"
                />
              </div>
            </GoogleOAuthProvider>

            {loading && (
              <div className="text-center py-2 text-xs text-slate-500 animate-pulse font-mono">
                Verifying secure session...
              </div>
            )}
          </div>

          <div className="mt-6 pt-5 border-t border-slate-100 text-center">
            <p className="text-[11px] text-slate-400 leading-relaxed">
              By continuing, you agree to ClauseWise’s{" "}
              <button
                type="button"
                onClick={() => {
                  onClose();
                  if (onOpenLegal) onOpenLegal("terms");
                }}
                className="underline hover:text-slate-700 cursor-pointer font-medium"
              >
                Terms of Service
              </button>{" "}
              and{" "}
              <button
                type="button"
                onClick={() => {
                  onClose();
                  if (onOpenLegal) onOpenLegal("privacy");
                }}
                className="underline hover:text-slate-700 cursor-pointer font-medium"
              >
                Privacy Policy
              </button>
              . Encrypted tenant-isolated processing.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
