import React, { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  LogOut,
  LayoutDashboard,
  AlertTriangle,
  ChevronDown,
  Trash2,
  Loader2,
} from "lucide-react";
import SlideCommit from "./SlideCommit";

export default function ProfileMenu({
  user,
  token,
  api = import.meta.env.VITE_API_URL || "http://localhost:8000",
  onSignOut,
  onNavigateDashboard,
  onNavigateAudit,
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [showSignOutWarning, setShowSignOutWarning] = useState(false);
  const [showDeleteAccountModal, setShowDeleteAccountModal] = useState(false);
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const menuRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleConfirmSignOut = () => {
    setShowSignOutWarning(false);
    setDropdownOpen(false);
    onSignOut();
  };

  const handleConfirmDeleteAccount = async () => {
    setDeletingAccount(true);
    setDeleteError("");
    try {
      const res = await fetch(`${api}/api/user/account`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to delete account.");
      }
      setShowDeleteAccountModal(false);
      setDropdownOpen(false);
      onSignOut();
    } catch (err) {
      setDeleteError(err.message || "Failed to delete account. Please try again.");
    } finally {
      setDeletingAccount(false);
    }
  };

  if (!user) return null;

  // Google profile picture with standard initials fallback if needed
  const avatarUrl =
    user.picture ||
    `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(user.name || "User")}`;

  return (
    <div className="relative inline-block text-left" ref={menuRef}>
      {/* Trigger: Google Profile Avatar + Dropdown chevron */}
      <button
        type="button"
        onClick={() => setDropdownOpen((prev) => !prev)}
        className="flex items-center gap-1.5 p-0.5 rounded-full hover:ring-2 hover:ring-black/10 transition-all cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-black"
        title="Google Account"
      >
        <img
          src={avatarUrl}
          alt={user.name || "Account"}
          referrerPolicy="no-referrer"
          className="h-8 w-8 rounded-full border border-slate-200 object-cover shadow-2xs"
        />
        <ChevronDown
          className={`h-3 w-3 text-slate-400 transition-transform duration-200 ${
            dropdownOpen ? "rotate-180 text-slate-700" : ""
          }`}
        />
      </button>

      {/* Profile Dropdown Card */}
      {dropdownOpen && (
        <div className="absolute right-0 mt-2 w-64 rounded-2xl bg-white shadow-xl border border-slate-200/90 py-2 z-50 animate-in fade-in zoom-in-95 duration-100">
          {/* User Info Header with Google Account photo & details */}
          <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-3">
            <img
              src={avatarUrl}
              alt={user.name}
              referrerPolicy="no-referrer"
              className="h-10 w-10 rounded-full border border-slate-200 object-cover"
            />
            <div className="overflow-hidden">
              <h4 className="text-xs font-semibold text-slate-900 truncate">
                {user.name || "Auditor"}
              </h4>
              <p className="text-[11px] text-slate-400 font-mono truncate">{user.email}</p>
            </div>
          </div>

          {/* Navigation Links */}
          <div className="py-1">
            {onNavigateDashboard && (
              <button
                type="button"
                onClick={() => {
                  setDropdownOpen(false);
                  onNavigateDashboard();
                }}
                className="w-full text-left px-4 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2.5 transition cursor-pointer"
              >
                <LayoutDashboard className="h-4 w-4 text-slate-400" />
                <span>Dashboard & Audits</span>
              </button>
            )}
          </div>

          <div className="border-t border-slate-100 my-1"></div>

          {/* Settings: Delete Account & Sign Out */}
          <div className="px-2 py-1 space-y-0.5">
            <button
              type="button"
              onClick={() => {
                setDropdownOpen(false);
                setDeleteError("");
                setShowDeleteAccountModal(true);
              }}
              className="w-full text-left px-3 py-2 text-xs font-medium text-slate-600 hover:text-rose-600 hover:bg-rose-50/60 rounded-xl flex items-center gap-2.5 transition cursor-pointer"
            >
              <Trash2 className="h-4 w-4 text-slate-400 group-hover:text-rose-500" />
              <span>Delete Account</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setDropdownOpen(false);
                setShowSignOutWarning(true);
              }}
              className="w-full text-left px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100 rounded-xl flex items-center gap-2.5 transition cursor-pointer"
            >
              <LogOut className="h-4 w-4 text-slate-500" />
              <span>Sign Out</span>
            </button>
          </div>
        </div>
      )}

      {/* Warning Confirmation Modal: Sign Out */}
      {showSignOutWarning &&
        createPortal(
          <div
            className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
            onClick={() => setShowSignOutWarning(false)}
          >
            <div
              className="relative w-full max-w-sm bg-white rounded-3xl shadow-2xl border border-slate-200 p-6 sm:p-7 text-center transform transition-all animate-in zoom-in-95 duration-150"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Warning Icon */}
              <div className="h-12 w-12 rounded-2xl bg-amber-50 border border-amber-200 text-amber-600 flex items-center justify-center mx-auto mb-4">
                <AlertTriangle className="h-6 w-6" />
              </div>

              <h3 className="font-display text-lg sm:text-xl font-bold text-slate-900 mb-1.5">
                Sign out of ClauseWise?
              </h3>
              <p className="text-xs sm:text-[13px] text-slate-500 leading-relaxed mb-6">
                Are you sure you want to sign out? Your contract audit records and risk analyses remain securely saved.
              </p>

              <div className="flex flex-col items-center justify-center gap-4">
                <SlideCommit
                  label="Slide to sign out"
                  doneLabel="Signed out"
                  errorLabel="Failed"
                  onConfirm={async () => {
                    await new Promise((resolve) => setTimeout(resolve, 350));
                  }}
                  onDone={() => {
                    setTimeout(() => {
                      handleConfirmSignOut();
                    }, 400);
                  }}
                  trackColor="#18181b"
                  handleColor="#ffffff"
                  successColor="#09090b"
                  dangerColor="#ef4444"
                  width={280}
                  height={54}
                  radius={27}
                  speed={55}
                  returnBounce={0.35}
                  landingDip={0.02}
                  holdMs={800}
                />
                <button
                  type="button"
                  onClick={() => setShowSignOutWarning(false)}
                  className="text-xs font-medium text-slate-400 hover:text-slate-800 transition py-1 px-4 cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}

      {/* Warning Confirmation Modal: Permanently Delete Account */}
      {showDeleteAccountModal &&
        createPortal(
          <div
            className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
            onClick={() => !deletingAccount && setShowDeleteAccountModal(false)}
          >
            <div
              className="relative w-full max-w-sm bg-white rounded-3xl shadow-2xl border border-slate-200 p-6 sm:p-7 text-center transform transition-all animate-in zoom-in-95 duration-150"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Red Trash / Warning Icon */}
              <div className="h-12 w-12 rounded-2xl bg-rose-50 border border-rose-200 text-rose-600 flex items-center justify-center mx-auto mb-4">
                <Trash2 className="h-6 w-6" />
              </div>

              <h3 className="font-display text-lg sm:text-xl font-bold text-slate-900 mb-1.5">
                Delete Account Permanently?
              </h3>
              <p className="text-xs sm:text-[13px] text-slate-500 leading-relaxed mb-5">
                This will permanently delete your user profile, all uploaded contracts, and saved audit history from MongoDB Atlas. This action cannot be undone.
              </p>

              {deleteError && (
                <div className="mb-4 p-2.5 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700 text-left">
                  {deleteError}
                </div>
              )}

              <div className="flex items-center justify-center gap-3">
                <button
                  type="button"
                  disabled={deletingAccount}
                  onClick={() => setShowDeleteAccountModal(false)}
                  className="flex-1 px-4 py-2.5 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-full transition cursor-pointer disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={deletingAccount}
                  onClick={handleConfirmDeleteAccount}
                  className="flex-1 px-4 py-2.5 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-full transition cursor-pointer shadow-xs disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {deletingAccount ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      <span>Deleting...</span>
                    </>
                  ) : (
                    "Delete Account"
                  )}
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
