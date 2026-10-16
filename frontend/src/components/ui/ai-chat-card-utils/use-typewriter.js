import { useEffect, useRef, useState } from "react";

export function useTypewriter(
  prompts = [],
  {
    typeMs = 48,
    deleteMs = 14,
    holdMs = 3400,
    gapMs = 900,
    enabled = true,
  } = {}
) {
  const [text, setText] = useState("");
  const [phase, setPhase] = useState("typing"); // "typing" | "holding" | "deleting" | "idle"
  const promptIdxRef = useRef(0);
  const charIdxRef = useRef(0);

  useEffect(() => {
    if (!enabled || !prompts.length) {
      setPhase("idle");
      return;
    }

    let timeoutId;

    const tick = () => {
      const currentPrompt = prompts[promptIdxRef.current % prompts.length] || "";

      if (phase === "typing") {
        if (charIdxRef.current < currentPrompt.length) {
          charIdxRef.current += 1;
          setText(currentPrompt.slice(0, charIdxRef.current));
          timeoutId = setTimeout(tick, typeMs);
        } else {
          setPhase("holding");
          timeoutId = setTimeout(() => {
            setPhase("deleting");
          }, holdMs);
        }
      } else if (phase === "deleting") {
        if (charIdxRef.current > 0) {
          charIdxRef.current -= 1;
          setText(currentPrompt.slice(0, charIdxRef.current));
          timeoutId = setTimeout(tick, deleteMs);
        } else {
          setPhase("idle");
          timeoutId = setTimeout(() => {
            promptIdxRef.current = (promptIdxRef.current + 1) % prompts.length;
            setPhase("typing");
          }, gapMs);
        }
      } else if (phase === "idle") {
        timeoutId = setTimeout(() => {
          setPhase("typing");
        }, gapMs);
      }
    };

    timeoutId = setTimeout(tick, phase === "typing" ? typeMs : 20);

    return () => clearTimeout(timeoutId);
  }, [enabled, prompts, phase, typeMs, deleteMs, holdMs, gapMs]);

  return { text, phase };
}
