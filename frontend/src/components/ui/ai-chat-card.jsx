"use client";

import * as React from "react";
import { motion, useInView } from "motion/react";
import {
  ArrowUp,
  MessageCircleDashed,
  Plus,
  RefreshCw,
  Sparkles,
  User,
  Bot,
  Loader2,
  X,
  ShieldAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTypewriter } from "@/components/ui/ai-chat-card-utils/use-typewriter";

function FormattedContent({ content }) {
  if (!content) return null;
  const lines = content.split("\n");
  return (
    <div className="space-y-2 text-xs leading-relaxed">
      {lines.map((rawLine, lIdx) => {
        const line = rawLine.trim();
        if (!line) return null;

        let isBullet = false;
        let isAction = false;
        let bulletMarker = "•";
        let textToParse = line;

        if (/^[•\-\*]\s+/.test(line)) {
          isBullet = true;
          bulletMarker = "•";
          textToParse = line.replace(/^[•\-\*]\s+/, "").trim();
        } else if (/^(→|->)\s*/.test(line)) {
          isBullet = true;
          isAction = true;
          bulletMarker = "→";
          textToParse = line.replace(/^(→|->)\s*/, "").trim();
        } else if (/^\d+\.\s*/.test(line)) {
          isBullet = true;
          const match = line.match(/^(\d+\.)\s*/);
          bulletMarker = match ? match[1] : "•";
          textToParse = line.replace(/^\d+\.\s*/, "").trim();
        }

        const parts = textToParse.split(/(\*\*.*?\*\*)/g);
        const formatted = parts.map((part, pIdx) => {
          if (part.startsWith("**") && part.endsWith("**")) {
            const inner = part.slice(2, -2);
            const lower = inner.toLowerCase();
            const isHighlight =
              lower.includes("remedy") ||
              lower.includes("action") ||
              lower.includes("fix") ||
              lower.includes("next step");
            return (
              <strong
                key={pIdx}
                className={cn(
                  "font-semibold",
                  isHighlight ? "text-indigo-600" : "text-slate-900"
                )}
              >
                {inner}
              </strong>
            );
          }
          return part;
        });

        if (isBullet) {
          return (
            <div
              key={lIdx}
              className={cn(
                "flex items-start gap-2 pl-0.5",
                isAction ? "text-slate-800" : "text-slate-700"
              )}
            >
              <span
                className={cn(
                  "shrink-0 select-none font-bold mt-0.5",
                  isAction
                    ? "text-indigo-600 text-xs"
                    : "text-slate-400 text-[10px]"
                )}
              >
                {bulletMarker}
              </span>
              <div className="flex-1 min-w-0">{formatted}</div>
            </div>
          );
        }

        return (
          <p key={lIdx} className="text-slate-700">
            {formatted}
          </p>
        );
      })}
    </div>
  );
}

const DEFAULT_PROMPTS = [
  "What are the highest risk findings in this agreement?",
  "Is there an uncapped liability or consequential damages clause?",
  "Summarize the termination rights and notice periods",
  "Are intellectual property ownership rights mutual?",
];

export function AIChatCard({
  title = "Contract Copilot",
  subtitle = "Grounded in verified audit findings",
  greeting = "Contract Review Copilot",
  prompt = "Ask anything about liabilities, risk provisions, or termination clauses",
  prompts = DEFAULT_PROMPTS,
  autoType = true,
  placeholder = "Ask about this contract…",
  icon,
  messages = [],
  loading = false,
  onSend,
  onReset,
  onAttach,
  onClose,
  className,
}) {
  const rootRef = React.useRef(null);
  const textareaRef = React.useRef(null);
  const messagesEndRef = React.useRef(null);
  const inView = useInView(rootRef, { margin: "-10% 0px" });

  const [userActive, setUserActive] = React.useState(false);
  const [userMessage, setUserMessage] = React.useState("");
  const [spins, setSpins] = React.useState(0);
  const [showQuickMenu, setShowQuickMenu] = React.useState(false);

  const hasMessages = messages && messages.length > 0;

  const { text: typedMessage, phase } = useTypewriter(prompts, {
    typeMs: 42,
    deleteMs: 14,
    holdMs: 3200,
    gapMs: 800,
    enabled: autoType && inView && !userActive && !hasMessages,
  });

  const message = userActive || !autoType || hasMessages ? userMessage : typedMessage;

  const takeOver = () => {
    if (userActive || !autoType) return;
    setUserMessage(typedMessage);
    setUserActive(true);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const handleSend = (text) => {
    const textToSend = (text || userMessage || (!userActive ? typedMessage : "")).trim();
    if (!textToSend || loading) return;
    onSend?.(textToSend);
    setUserMessage("");
    setUserActive(true);
    setShowQuickMenu(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  React.useEffect(() => {
    if (hasMessages) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, loading, hasMessages]);

  return (
    <div
      ref={rootRef}
      className={cn(
        "flex w-full flex-col rounded-[24px] bg-white border border-slate-200/90",
        "shadow-[0_16px_50px_rgba(0,0,0,0.12),0_0_16.4px_1px_rgba(10,10,10,0.05)]",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 bg-white/95 rounded-t-[24px] shrink-0">
        <div className="overflow-hidden">
          <h3 className="text-xs font-semibold leading-4 text-slate-900 truncate">
            {title}
          </h3>
          <p className="text-[10px] leading-3 text-slate-400 font-mono truncate">
            {subtitle}
          </p>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <motion.button
            type="button"
            onClick={() => {
              setSpins((count) => count + 1);
              setUserActive(false);
              setUserMessage("");
              setShowQuickMenu(false);
              onReset?.();
            }}
            whileTap={{ scale: 0.9 }}
            aria-label="Reset conversation"
            className="flex h-[28px] w-[28px] shrink-0 items-center justify-center rounded-[14px] border border-slate-200 bg-white text-slate-400 transition-colors hover:text-slate-800 hover:border-slate-300 cursor-pointer shadow-2xs"
            title="Reset conversation"
          >
            <motion.span
              animate={{ rotate: spins * 360 }}
              transition={{ type: "spring", bounce: 0.2, duration: 0.7 }}
              className="flex"
            >
              <RefreshCw className="h-3 w-3" />
            </motion.span>
          </motion.button>

          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="flex h-[28px] w-[28px] shrink-0 items-center justify-center rounded-[14px] border border-slate-200 bg-white text-slate-400 transition-colors hover:text-slate-800 hover:border-slate-300 cursor-pointer shadow-2xs"
              title="Minimize chat"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area: Messages Stream or Empty State */}
      {hasMessages ? (
        <div className="flex-1 overflow-y-auto p-3.5 space-y-3 min-h-[220px] max-h-[380px] text-xs bg-slate-50/40">
          {messages.map((msg, idx) => {
            const isUser = msg.role === "user";
            return (
              <div
                key={idx}
                className={cn(
                  "flex gap-2 items-start",
                  isUser ? "flex-row-reverse" : "flex-row"
                )}
              >
                <div
                  className={cn(
                    "h-6 w-6 rounded-full flex items-center justify-center shrink-0 text-[10px] font-bold mt-0.5",
                    isUser
                      ? "bg-slate-900 text-white shadow-xs"
                      : "bg-indigo-50 border border-indigo-200 text-indigo-600"
                  )}
                >
                  {isUser ? <User className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
                </div>
                <div
                  className={cn(
                    "rounded-2xl px-3.5 py-2.5 max-w-[85%] text-xs leading-relaxed",
                    isUser
                      ? "bg-slate-900 text-white shadow-xs rounded-tr-sm"
                      : "bg-white border border-slate-200/90 text-slate-800 rounded-tl-sm shadow-2xs"
                  )}
                >
                  {isUser ? (
                    <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                  ) : (
                    <FormattedContent content={msg.content} />
                  )}
                </div>
              </div>
            );
          })}
          {loading && (
            <div className="flex gap-2 items-center text-slate-400 text-xs pl-8">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-600" />
              <span>Analyzing contract clauses...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      ) : (
        /* Empty State */
        <div className="flex flex-1 flex-col items-center justify-center px-6 py-8 text-center bg-white">
          <motion.div
            animate={{ y: [0, -4, 0] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
            className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-slate-100 border border-slate-200/80 shadow-2xs text-slate-800"
          >
            {icon ?? <MessageCircleDashed className="h-5 w-5 text-slate-800" />}
          </motion.div>
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.15, ease: "easeOut" }}
            className="mt-3.5 text-[15px] font-semibold leading-snug tracking-[-0.02em] text-slate-900"
          >
            {greeting}
          </motion.p>
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.25, ease: "easeOut" }}
            className="mt-1 max-w-[210px] text-xs leading-relaxed text-slate-500"
          >
            {prompt}
          </motion.p>
        </div>
      )}

      {/* Quick Prompts Popup Drawer */}
      {showQuickMenu && (
        <div className="px-4 pb-2 pt-1 border-t border-slate-100 bg-white">
          <div className="text-[10px] font-mono text-slate-400 uppercase tracking-wider mb-1.5 flex items-center justify-between">
            <span>Suggested Questions</span>
            <button
              type="button"
              onClick={() => setShowQuickMenu(false)}
              className="text-slate-400 hover:text-slate-700 cursor-pointer"
            >
              ✕
            </button>
          </div>
          <div className="flex flex-col gap-1 max-h-36 overflow-y-auto">
            {prompts.map((q, qIdx) => (
              <button
                key={qIdx}
                type="button"
                onClick={() => handleSend(q)}
                className="text-left text-xs p-1.5 rounded-lg bg-slate-50 hover:bg-slate-100 border border-slate-200/60 text-slate-700 transition cursor-pointer"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Composer */}
      <div className="px-3.5 pb-3.5 pt-1 bg-white rounded-b-[24px]">
        <div className="rounded-[18px] bg-slate-100/70 border border-slate-200/80 p-2.5 transition-colors focus-within:bg-slate-100 focus-within:border-slate-300">
          {userActive || !autoType || hasMessages ? (
            <textarea
              ref={textareaRef}
              value={userMessage}
              onChange={(event) => setUserMessage(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              rows={2}
              className="w-full resize-none bg-transparent text-xs sm:text-[13px] leading-5 text-slate-900 outline-none placeholder:text-slate-400"
            />
          ) : (
            <div
              onClick={takeOver}
              className="min-h-9 w-full cursor-text text-left text-xs sm:text-[13px] leading-5 text-slate-700"
            >
              {message}
              <motion.span
                aria-hidden
                className="ml-px inline-block h-3.5 w-px bg-slate-800 align-middle"
                animate={{ opacity: [1, 1, 0, 0] }}
                transition={{
                  duration: 1,
                  repeat: Infinity,
                  times: [0, 0.5, 0.5, 1],
                }}
              />
              {!message ? (
                <span className="text-slate-400">{placeholder}</span>
              ) : null}
            </div>
          )}
          <div className="mt-1.5 flex items-center justify-between">
            <motion.button
              type="button"
              onClick={() => {
                setShowQuickMenu((prev) => !prev);
                onAttach?.();
              }}
              whileHover={{ rotate: 90 }}
              whileTap={{ scale: 0.88 }}
              transition={{ type: "spring", bounce: 0.4, duration: 0.4 }}
              aria-label="Suggested prompts"
              title="Suggested prompt ideas"
              className="flex h-[26px] w-[26px] items-center justify-center rounded-[13px] border border-slate-200 bg-white text-slate-600 hover:text-slate-900 shadow-2xs cursor-pointer"
            >
              <Plus className="h-3.5 w-3.5" />
            </motion.button>
            <motion.button
              type="button"
              onClick={() => handleSend()}
              whileHover={{
                scale: 1.08,
                transition: { type: "spring", bounce: 0.5, duration: 0.4 },
              }}
              whileTap={{
                scale: 0.88,
                transition: { type: "spring", bounce: 0.5, duration: 0.4 },
              }}
              animate={
                phase === "holding" && !userActive && !hasMessages
                  ? { scale: [1, 1.14, 1] }
                  : { scale: 1 }
              }
              transition={{
                duration: 0.5,
                ease: "easeInOut",
                times: [0, 0.35, 1],
              }}
              disabled={loading || (!userMessage.trim() && userActive)}
              aria-label="Send message"
              className="group flex h-[26px] w-[26px] items-center justify-center rounded-[13px] bg-slate-900 text-white hover:bg-black shadow-xs cursor-pointer disabled:opacity-40"
            >
              <ArrowUp className="h-3.5 w-3.5 transition-transform duration-200 group-hover:-translate-y-px" />
            </motion.button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AIChatCard;
