import React, { useState, useRef } from "react";
import { createPortal } from "react-dom";
import { X, Camera, User, Mail, Check, AlertCircle, Loader2 } from "lucide-react";

export default function ProfileModal({ isOpen, onClose, user, token, api, onProfileUpdated }) {
  const [name, setName] = useState(user?.name || "");
  const [previewAvatar, setPreviewAvatar] = useState(user?.picture || "");
  const [selectedFile, setSelectedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  const fileInputRef = useRef(null);

  if (!isOpen || !user) return null;

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith("image/")) {
      setError("Please select an image file (PNG, JPG, WebP).");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError("Avatar image size must be under 5MB.");
      return;
    }

    setError(null);
    setSelectedFile(file);
    const reader = new FileReader();
    reader.onload = () => setPreviewAvatar(reader.result);
    reader.readAsDataURL(file);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(false);

    try {
      let updatedUser = { ...user, name: name.trim() };

      // 1. If file was selected, upload avatar
      if (selectedFile) {
        const formData = new FormData();
        formData.append("file", selectedFile);
        const res = await fetch(`${api}/api/user/avatar`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to upload avatar image.");
        updatedUser = data.user;
      }

      // 2. If name changed, update profile details
      if (name.trim() !== user.name) {
        const res = await fetch(`${api}/api/user/profile`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ name: name.trim() }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to update profile details.");
        updatedUser = data.user;
      }

      setSuccess(true);
      onProfileUpdated(updatedUser);
      setTimeout(() => {
        onClose();
        setSuccess(false);
      }, 700);
    } catch (err) {
      setError(err.message || "Failed to save profile changes.");
    } finally {
      setLoading(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-md bg-white rounded-3xl shadow-2xl border border-slate-200 overflow-hidden transform transition-all animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-2">
          <h2 className="font-display text-xl font-bold text-slate-900 tracking-tight">
            Account Profile
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition cursor-pointer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSave} className="px-6 py-4">
          {error && (
            <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-start gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div className="mb-4 p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs flex items-center gap-2">
              <Check className="h-4 w-4 shrink-0" />
              <span>Profile updated successfully!</span>
            </div>
          )}

          {/* Avatar Upload Preview */}
          <div className="flex flex-col items-center justify-center mb-6">
            <div className="relative group cursor-pointer" onClick={() => fileInputRef.current?.click()}>
              <img
                src={
                  previewAvatar ||
                  `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(user.name || "User")}`
                }
                alt={user.name}
                className="h-24 w-24 rounded-full border-2 border-slate-200 object-cover shadow-sm group-hover:opacity-85 transition"
              />
              <div className="absolute inset-0 rounded-full bg-black/35 opacity-0 group-hover:opacity-100 transition flex items-center justify-center text-white">
                <Camera className="h-6 w-6" />
              </div>
            </div>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="mt-2.5 text-xs text-slate-600 hover:text-black font-medium transition cursor-pointer"
            >
              Change Photo
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>

          {/* Inputs */}
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                Display Name
              </label>
              <div className="relative">
                <User className="h-4 w-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  placeholder="Your full name"
                  className="w-full pl-9 pr-3.5 py-2 text-xs sm:text-sm bg-slate-50 border border-slate-200 rounded-xl outline-none focus:bg-white focus:border-black transition"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                Email Address
              </label>
              <div className="relative">
                <Mail className="h-4 w-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="email"
                  value={user.email || ""}
                  disabled
                  className="w-full pl-9 pr-3.5 py-2 text-xs sm:text-sm bg-slate-100/80 border border-slate-200 rounded-xl text-slate-500 cursor-not-allowed font-mono"
                />
              </div>
              <p className="text-[10px] text-slate-400 mt-1">Verified with Google Identity Services</p>
            </div>
          </div>

          {/* Buttons */}
          <div className="flex items-center gap-3 mt-6 pt-4 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="flex-1 px-4 py-2.5 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-full transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2.5 text-xs font-semibold text-white bg-black hover:bg-slate-800 rounded-full transition cursor-pointer shadow-xs flex items-center justify-center gap-1.5"
            >
              {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              <span>Save Changes</span>
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}
