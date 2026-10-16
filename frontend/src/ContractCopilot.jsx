import React, { useState } from "react";
import { Sparkles } from "lucide-react";
import AIChatCard from "@/components/ui/ai-chat-card";

export default function ContractCopilot({
  doc,
  report,
  token,
  api = import.meta.env.VITE_API_URL || "http://localhost:8000",
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState([]);

  const quickPrompts = [
    "What are the highest risk findings in this agreement?",
    "Is there an uncapped liability or consequential damages clause?",
    "Summarize the termination rights and notice periods",
    "Are intellectual property ownership rights mutual?",
  ];

  const handleSendMessage = async (text) => {
    if (!text || loading) return;

    const userMsg = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${api}/api/audit/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          document_id: doc?.document_id,
          message: text,
          history: messages,
          report_data: report,
        }),
      });

      const data = await res.json();
      if (res.ok && data.reply) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: data.reply },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content:
              data.detail ||
              "Could not complete analysis. Please try asking again.",
          },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Network issue contacting analysis engine. Please try again.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setMessages([]);
  };

  // Minimized state: Simple, clean floating pill button
  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 z-40 inline-flex items-center gap-2 rounded-full bg-[#0e0d0c] hover:bg-black text-white px-4 py-2.5 text-xs font-medium shadow-xl transition-all hover:scale-105 active:scale-95 cursor-pointer border border-white/10 no-print"
        title="Open Contract Assistant"
      >
        <Sparkles className="h-3.5 w-3.5 text-indigo-300" />
        <span>Ask Copilot</span>
      </button>
    );
  }

  // Expanded floating card window in bottom right using AIChatCard
  return (
    <aside
      className="fixed bottom-6 right-6 z-40 w-[380px] max-w-[calc(100vw-32px)] no-print animate-in fade-in zoom-in-95 duration-150"
      aria-label="Contract Review Assistant"
    >
      <AIChatCard
        title="Contract Copilot"
        subtitle={doc?.filename || "Agreement intelligence"}
        greeting="Contract Review Copilot"
        prompt="Ask about verified risks, uncapped liabilities, or termination clauses"
        prompts={quickPrompts}
        messages={messages}
        loading={loading}
        onSend={handleSendMessage}
        onReset={handleReset}
        onClose={() => setIsOpen(false)}
        className="max-h-[520px]"
      />
    </aside>
  );
}
