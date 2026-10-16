import React, { useState, useEffect } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  Building2,
  Check,
  CheckCircle2,
  ChevronDown,
  FileText,
  Key,
  Lock,
  Scale,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
} from "lucide-react";
import ProfileMenu from "./ProfileMenu";
import RubberSegment from "./RubberSegment";

export default function LandingPage({
  onLaunchAudit,
  hasActiveAudit,
  user,
  token,
  api,
  onOpenAuth,
  onOpenDashboard,
  onSignOut,
  onProfileUpdated,
  onOpenRetention,
  onOpenPrivacy,
  onOpenTerms,
}) {
  const [activeContractTab, setActiveContractTab] = useState("NDA");
  const [openFaqIndex, setOpenFaqIndex] = useState(0);
  const [scrollY, setScrollY] = useState(0);

  // Smooth scroll tracking for parallax depth
  useEffect(() => {
    let ticking = false;
    const handleScroll = () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          setScrollY(window.scrollY);
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // IntersectionObserver for scroll-reveal animations
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("reveal-visible");
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }
    );

    const elements = document.querySelectorAll(".reveal-init");
    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, []);

  // Sample contract data for the interactive risk breakdown demo
  const CONTRACT_SAMPLES = {
    NDA: {
      type: "Non-Disclosure Agreement",
      filename: "Mutual_NDA_Acme_v2.pdf",
      clauseTitle: "Section 4.2 — Indefinite Term of Confidentiality",
      excerpt:
        "The obligations of confidentiality under this Agreement shall survive the termination hereof and shall continue in perpetuity for all proprietary and commercial information disclosed.",
      severity: "HIGH",
      riskBadge: "High Risk · Indefinite Survival",
      explanation:
        "Perpetual survival of confidentiality on standard commercial disclosures creates indefinite litigation exposure. Benchmark industry standard is 2 to 3 years.",
      suggestedRedline:
        "The obligations of confidentiality shall survive for a period of three (3) years from the date of disclosure, except for bona fide Trade Secrets which survive for so long as they remain protected by law.",
      verification: "V1 Entailment 99.4% · V2 Citation §4.2 · V3 Attributed to Receiving Party",
    },
    MSA: {
      type: "Master Services Agreement",
      filename: "Enterprise_MSA_Apex_Global.docx",
      clauseTitle: "Section 11.3 — Uncapped Indemnification & Consequential Damages",
      excerpt:
        "Vendor shall indemnify, defend, and hold harmless Client from any and all claims, liabilities, losses, damages, including indirect, punitive, or consequential damages, without limitation.",
      severity: "HIGH",
      riskBadge: "Critical Risk · Unlimited Vendor Liability",
      explanation:
        "Uncapped indemnification for consequential and indirect damages violates standard enterprise risk allocation. No liability cap applies to third-party claims.",
      suggestedRedline:
        "Vendor's aggregate indemnification liability under this Section shall be capped at the total fees paid by Client to Vendor during the twelve (12) months preceding the claim.",
      verification: "V1 Entailment 98.7% · V2 Citation §11.3 · V3 Attributed to Vendor",
    },
    EMPLOYMENT: {
      type: "Employment Agreement",
      filename: "Executive_Offer_Letter_2026.pdf",
      clauseTitle: "Section 8.1 — Worldwide 24-Month Non-Compete",
      excerpt:
        "During the term of employment and for twenty-four (24) months following termination for any reason, Employee shall not directly or indirectly engage in any competing enterprise worldwide.",
      severity: "MEDIUM",
      riskBadge: "Medium Risk · Restrictive Covenant",
      explanation:
        "A 24-month worldwide non-compete is legally unenforceable under FTC regulations and state public policy, but presents chilling effects during subsequent employment.",
      suggestedRedline:
        "Employee agrees that for twelve (12) months following departure, Employee will not solicit existing clients or core engineering staff within the specific territory of operation.",
      verification: "V1 Entailment 97.2% · V2 Citation §8.1 · V3 Attributed to Employee",
    },
    LEASE: {
      type: "Commercial Lease",
      filename: "Commercial_Property_Lease_HQ.pdf",
      clauseTitle: "Section 14.5 — Uncapped CAM Operating Expense Escalations",
      excerpt:
        "Tenant shall pay Landlord proportionate share of Operating Expenses, including capital expenditures, structural retrofits, and administrative surcharges, payable upon demand.",
      severity: "MEDIUM",
      riskBadge: "Medium Risk · Uncapped Expense Pass-Through",
      explanation:
        "Allows landlord to pass capital expenditures and structural improvements to the tenant without a year-over-year percentage cap or amortization schedule.",
      suggestedRedline:
        "Tenant's share of controllable Operating Expenses shall not increase by more than five percent (5%) compounded annually over the Base Year amount.",
      verification: "V1 Entailment 99.1% · V2 Citation §14.5 · V3 Attributed to Tenant",
    },
  };

  const FAQS = [
    {
      q: "How does ClauseWise eliminate AI hallucinations?",
      a: "Unlike generic chat models that guess answers, ClauseWise implements deterministic triple-verification: V1 Entailment mathematically verifies the logical truth of each finding, V2 Citation matches against raw source text, and V3 Attribution tracks party roles. If a claim cannot be verified against the contract's verbatim words, the critic engine automatically rejects it.",
    },
    {
      q: "Are my confidential contracts stored or used to train models?",
      a: "Never. All documents are processed through an isolated tenant pipeline. Documents and extracted embeddings are purged automatically after 24 hours. No client contract or legal text is ever retained or used for model fine-tuning or training.",
    },
    {
      q: "How does the Auto-Detect contract feature work?",
      a: "When you upload a file with 'Auto-detect (Recommended)' selected, ClauseWise analyzes the document preamble, recitals, and core structural covenants (e.g. Non-Disclosure, Executive Offer, Commercial Lease, or Master Services Agreement) to determine the exact contract type and load appropriate legal benchmark rules.",
    },
    {
      q: "What file formats does ClauseWise support?",
      a: "ClauseWise supports PDF (.pdf), Microsoft Word (.docx), and plain text (.txt) documents. Our parser automatically normalizes headers, numbered clauses, and exhibit schedules for high-precision citation mapping.",
    },
    {
      q: "Is ClauseWise a replacement for outside legal counsel?",
      a: "ClauseWise is an automated risk triage and clause intelligence tool. It helps legal teams, founders, and procurement officers review agreements 10x faster and spot hidden red flags before sending to formal legal sign-off.",
    },
  ];

  const currentSample = CONTRACT_SAMPLES[activeContractTab];

  return (
    <div className="min-h-screen bg-white font-sans selection:bg-neutral-900 selection:text-white flex flex-col justify-between p-0 overflow-x-hidden pt-[56px]">
      
      {/* ────────────────────────────────────────────────────────────────────────────
         PIPESHIFT-STYLE CLEAN TOP BAR (Exact 1:1 dimensions & positions from pipeshift.com)
         Container: 1200px max-width, 56px height, 48px padding, exact typography & colors
         ──────────────────────────────────────────────────────────────────────────── */}
      <header className="w-full bg-white/60 backdrop-blur-xl fixed top-0 z-50 border-b border-black/[0.06] transition-all shadow-[0_1px_12px_rgba(0,0,0,0.04)]">
        <div className="w-full mx-auto px-4 sm:px-8 lg:px-12 h-[56px] flex items-center justify-between relative">
          
          {/* Left: Brand Logo */}
          <div className="flex items-center z-10">
            <button
              type="button"
              onClick={() => {
                if (user) {
                  onOpenDashboard();
                } else {
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }
              }}
              className="flex items-center outline-none focus-visible:ring-2 focus-visible:ring-black rounded cursor-pointer"
              title="ClauseWise"
            >
              <img
                src="/logo.png"
                alt="Clausewise"
                className="h-[14px] sm:h-[16px] w-auto object-contain transition-opacity hover:opacity-80 select-none"
              />
            </button>
          </div>

          {/* Center: Nav Links (Dead center of the navbar) */}
          <nav className="hidden md:flex items-center gap-7 lg:gap-8 text-[14px] font-normal text-[#0e0d0c]/60 tracking-[-0.02em] absolute left-1/2 -translate-x-1/2">
            <a
              href="#audit-engine"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("audit-engine")?.scrollIntoView({ behavior: "smooth" });
              }}
              className="hover:text-[#0e0d0c] transition-colors cursor-pointer"
            >
              Audit Engine
            </a>
            <a
              href="#verification"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("verification")?.scrollIntoView({ behavior: "smooth" });
              }}
              className="hover:text-[#0e0d0c] transition-colors cursor-pointer"
            >
              Triple-Verification
            </a>
            <a
              href="#contracts"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("contracts")?.scrollIntoView({ behavior: "smooth" });
              }}
              className="hover:text-[#0e0d0c] transition-colors cursor-pointer"
            >
              Contract Types
            </a>
            <a
              href="#faq"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("faq")?.scrollIntoView({ behavior: "smooth" });
              }}
              className="hover:text-[#0e0d0c] transition-colors cursor-pointer"
            >
              FAQ
            </a>
          </nav>

          {/* Right: User / Auth Controls */}
          <div className="flex items-center gap-2 sm:gap-3 z-10">
            {user ? (
              <>
                <button
                  type="button"
                  onClick={onOpenDashboard}
                  className="px-3.5 py-1.5 text-[13px] sm:text-[14px] font-medium text-[#0e0d0c] hover:bg-black/5 rounded-lg transition cursor-pointer"
                >
                  Dashboard
                </button>
                <button
                  type="button"
                  onClick={onLaunchAudit}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[#0e0d0c] bg-[#0e0d0c] text-white hover:bg-black px-4 py-1.5 text-[13px] sm:text-[14px] font-medium tracking-[-0.02em] transition-all active:scale-95 cursor-pointer shadow-xs"
                >
                  <span>Audit Engine</span>
                  <ArrowRight className="h-3.5 w-3.5 stroke-[2]" />
                </button>
                <div className="pl-1 border-l border-slate-200">
                  <ProfileMenu
                    user={user}
                    token={token}
                    api={api}
                    onSignOut={onSignOut}
                    onNavigateDashboard={onOpenDashboard}
                    onNavigateAudit={onLaunchAudit}
                    onProfileUpdated={onProfileUpdated}
                  />
                </div>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={onOpenAuth}
                  className="px-3.5 py-1.5 text-[13px] sm:text-[14px] font-medium text-[#0e0d0c] hover:bg-black/5 rounded-lg transition cursor-pointer"
                >
                  Log in
                </button>
                <button
                  type="button"
                  onClick={onOpenAuth}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[#0e0d0c] text-[#0e0d0c] hover:bg-[#0e0d0c] hover:text-white px-4 py-1.5 text-[13px] sm:text-[14px] font-medium tracking-[-0.02em] transition-all active:scale-95 cursor-pointer"
                >
                  <span>Continue with Google</span>
                  <ArrowRight className="h-3.5 w-3.5 stroke-[2]" />
                </button>
              </>
            )}
          </div>

        </div>
      </header>

      {/* ────────────────────────────────────────────────────────────────────────────
         FRAMED HERO CONTAINER (Rounded outer card with a2.jpg background)
         ──────────────────────────────────────────────────────────────────────────── */}
      <div className="pt-10 sm:pt-14 px-6 sm:px-8 pb-2 w-full">
        <div className="relative w-full rounded-[24px] sm:rounded-[36px] overflow-hidden border border-white/40 shadow-2xl text-white">
          
          {/* Background Image Layer with gentle smooth parallax */}
          <div
            className="absolute inset-0 w-full h-[115%] -top-[7%] overflow-hidden pointer-events-none select-none transition-transform ease-out duration-75"
            style={{ transform: `translate3d(0, ${Math.min(scrollY * 0.12, 60)}px, 0)` }}
          >
            <img
              src="/a2.jpg"
              alt=""
              className="w-full h-full object-cover object-center"
            />
          </div>

          {/* Cinematic Vignette Overlay for crisp text contrast */}
          <div className="absolute inset-0 bg-gradient-to-b from-black/55 via-black/45 via-50% to-black/75 backdrop-blur-[1px]" />

        {/* ────────────────────────────────────────────────────────────────────────────
           HERO SECTION (Bold centered white typography, dusk glow, pill CTA)
           ──────────────────────────────────────────────────────────────────────────── */}
        <section className="relative pt-16 sm:pt-24 pb-8 sm:pb-12 px-4 sm:px-8 text-center overflow-hidden">
          
          {/* Main Headline */}
          <h1 className="font-heading text-4xl sm:text-5xl md:text-[62px] font-extrabold tracking-[-0.035em] text-white leading-[1.08] max-w-4xl mx-auto mb-5">
            Autonomous contract review with zero hallucinations
          </h1>

          {/* Subtitle */}
          <p className="text-white/90 text-base sm:text-lg md:text-xl font-normal max-w-2xl mx-auto mb-9 leading-relaxed tracking-[-0.01em]">
            Audit NDAs, MSAs, and employment agreements with deterministic triple-verification, clause-level risk triage, and automated redlines.
          </p>

          {/* Whimsical-Style Pill CTA Button */}
          <div className="flex flex-wrap items-center justify-center gap-3 sm:gap-4 mb-16 sm:mb-20">
            <button
              type="button"
              onClick={user ? onLaunchAudit : onOpenAuth}
              className="inline-flex items-center gap-3 rounded-full bg-[#151121] hover:bg-black text-white font-medium text-sm sm:text-base px-6 sm:px-8 py-3.5 shadow-2xl transition active:scale-95 cursor-pointer border border-white/10 group"
            >
              <span>{hasActiveAudit && user ? "Resume Contract Review" : "Analyze Your Contract Free"}</span>
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-white/15 group-hover:bg-white/25 transition">
                <ArrowRight className="h-3.5 w-3.5 stroke-[2.5]" />
              </span>
            </button>
          </div>

          {/* ────────────────────────────────────────────────────────────────────────────
             SHOWCASE BOARD CONTAINER (Whimsical canvas board with collaborative header)
             ──────────────────────────────────────────────────────────────────────────── */}
          <div className="mx-auto max-w-5xl rounded-2xl sm:rounded-[26px] bg-white border border-white/80 shadow-[0_25px_60px_-15px_rgba(0,0,0,0.45)] overflow-hidden text-slate-800 text-left ring-1 ring-black/5">
            
            
            {/* Showcase Video Canvas */}
            <div className="relative w-full aspect-video bg-black overflow-hidden flex items-center justify-center">
              <video
                src="/hero-video.mp4"
                autoPlay
                loop
                muted
                playsInline
                className="w-full h-full object-cover"
              />
              
              {/* Floating Live Audit CTA Button */}
              <div className="absolute bottom-4 right-4 sm:bottom-6 sm:right-6 z-10">
                <button
                  type="button"
                  onClick={user ? onLaunchAudit : onOpenAuth}
                  className="inline-flex items-center gap-2 rounded-full bg-slate-900/90 hover:bg-black text-white px-4 sm:px-5 py-2 sm:py-2.5 text-xs sm:text-sm font-medium shadow-xl backdrop-blur-md transition active:scale-95 cursor-pointer border border-white/15"
                >
                  <span>Launch Live Audit Engine</span>
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

        </section>

        {/* ────────────────────────────────────────────────────────────────────────────
           FEATURE PILLARS (Clean modern cards matching Whimsical style)
           ──────────────────────────────────────────────────────────────────────────── */}
        <section className="relative px-6 sm:px-10 pb-16 sm:pb-20 pt-10 sm:pt-14 max-w-6xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 sm:gap-6">
            
            {/* Card 1 */}
            <div className="rounded-2xl bg-white/10 backdrop-blur-md border border-white/15 p-6 text-left hover:bg-white/15 transition shadow-lg reveal-init delay-75">
              <div className="w-10 h-10 rounded-xl bg-white/10 border border-white/20 flex items-center justify-center mb-4 text-white">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Deterministic V1·V2·V3</h3>
              <p className="text-sm text-white/80 leading-relaxed">
                Zero AI hallucinations. Every legal claim is verified with V1 entailment, V2 citation, and V3 attribution against raw contract text.
              </p>
            </div>

            {/* Card 2 */}
            <div className="rounded-2xl bg-white/10 backdrop-blur-md border border-white/15 p-6 text-left hover:bg-white/15 transition shadow-lg reveal-init delay-150">
              <div className="w-10 h-10 rounded-xl bg-blue-500/20 border border-blue-400/30 flex items-center justify-center mb-4 text-blue-200">
                <Scale className="h-5 w-5" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Clause Risk Triage</h3>
              <p className="text-sm text-white/80 leading-relaxed">
                Instant classification into High, Medium, and Low risk severity for indemnities, non-competes, liabilities, and termination traps.
              </p>
            </div>

            {/* Card 3 */}
            <div className="rounded-2xl bg-white/10 backdrop-blur-md border border-white/15 p-6 text-left hover:bg-white/15 transition shadow-lg reveal-init delay-225">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-400/30 flex items-center justify-center mb-4 text-emerald-200">
                <CheckCircle2 className="h-5 w-5" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Auto-Detect Contract Type</h3>
              <p className="text-sm text-white/80 leading-relaxed">
                Intelligently detects NDAs, Employment contracts, Commercial Leases, MSAs, and SOWs with custom benchmark audit rules.
              </p>
            </div>

          </div>
        </section>

        </div>
      </div>

      {/* ────────────────────────────────────────────────────────────────────────────
         INFINITE SCROLLING TICKER MARQUEE
         ──────────────────────────────────────────────────────────────────────────── */}
      <div className="w-full overflow-hidden border-y border-black/[0.06] bg-slate-50/70 py-3.5 my-8 sm:my-10 select-none">
        <div className="animate-marquee flex items-center gap-8 text-[12px] sm:text-[13px] font-mono uppercase tracking-[0.18em] text-slate-500 whitespace-nowrap">
          <span>Deterministic V1·V2·V3 Verification</span>
          <span className="text-slate-300">✦</span>
          <span>100% Verbatim Quotation Grounding</span>
          <span className="text-slate-300">✦</span>
          <span>Zero Data Retention · 24h Purge</span>
          <span className="text-slate-300">✦</span>
          <span>Automated Counter-Balanced Redlines</span>
          <span className="text-slate-300">✦</span>
          <span>Commercial Lease CAM Escalation Triage</span>
          <span className="text-slate-300">✦</span>
          <span>FTC-Compliant Non-Compete Review</span>
          <span className="text-slate-300">✦</span>
          <span>Executive Severance &amp; Indemnity Audits</span>
          <span className="text-slate-300">✦</span>
          {/* Duplicate loop */}
          <span>Deterministic V1·V2·V3 Verification</span>
          <span className="text-slate-300">✦</span>
          <span>100% Verbatim Quotation Grounding</span>
          <span className="text-slate-300">✦</span>
          <span>Zero Data Retention · 24h Purge</span>
          <span className="text-slate-300">✦</span>
          <span>Automated Counter-Balanced Redlines</span>
          <span className="text-slate-300">✦</span>
          <span>Commercial Lease CAM Escalation Triage</span>
          <span className="text-slate-300">✦</span>
          <span>FTC-Compliant Non-Compete Review</span>
          <span className="text-slate-300">✦</span>
          <span>Executive Severance &amp; Indemnity Audits</span>
          <span className="text-slate-300">✦</span>
        </div>
      </div>

      {/* ────────────────────────────────────────────────────────────────────────────
         INTERACTIVE CLAUSE RISK INSPECTION DEMO (Live clause analyzer tabbed preview)
         ──────────────────────────────────────────────────────────────────────────── */}
      <section id="audit-engine" className="mt-16 sm:mt-24 mb-12 sm:mb-16 max-w-6xl mx-auto w-full px-4 sm:px-6 scroll-mt-24 reveal-init">
        <div id="contracts" className="text-center max-w-2xl mx-auto mb-8 sm:mb-10 scroll-mt-24 pt-2 sm:pt-4">

          <h2 className="text-2xl sm:text-3xl md:text-[38px] font-bold tracking-[-0.03em] text-slate-900 mb-2.5">
            See how ClauseWise catches traps
          </h2>
          <p className="text-slate-500 text-sm sm:text-base leading-relaxed max-w-xl mx-auto">
            Select a contract type below to inspect how our critic verifies claims and generates surgical redlines.
          </p>
        </div>

        {/* RubberSegment Control from React Bits */}
        <div className="flex items-center justify-center mb-8 overflow-x-auto py-2">
          <RubberSegment
            items={[
              { value: "NDA", label: "Mutual NDA", icon: <Lock className="h-3.5 w-3.5" /> },
              { value: "MSA", label: "Master Services (MSA)", icon: <Briefcase className="h-3.5 w-3.5" /> },
              { value: "EMPLOYMENT", label: "Employment Agreement", icon: <FileText className="h-3.5 w-3.5" /> },
              { value: "LEASE", label: "Commercial Lease", icon: <Building2 className="h-3.5 w-3.5" /> },
            ]}
            value={activeContractTab}
            onChange={(val) => setActiveContractTab(val)}
            trackColor="#0e0d0c"
            thumbColor="#ffffff"
            textColor="#a1a1aa"
            activeTextColor="#0e0d0c"
            size="md"
            radius={14}
            inset={4}
            equalSlots={false}
            stretch={100}
            squash={3}
            speed={1}
            glide={75}
            draggable
          />
        </div>

        {/* Interactive Sample Card */}
        <div className="rounded-2xl sm:rounded-3xl bg-white border border-slate-200 shadow-xl overflow-hidden p-6 sm:p-8">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-5 border-b border-slate-100 gap-3">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-xs text-slate-900 font-bold uppercase tracking-wider">
                  {currentSample.type}
                </span>
                <span className="text-slate-300">·</span>
                <span className="font-mono text-xs text-slate-500">{currentSample.filename}</span>
              </div>
              <h3 className="text-base sm:text-lg font-bold text-slate-900">
                {currentSample.clauseTitle}
              </h3>
            </div>
            <div>
              <span
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${
                  currentSample.severity === "HIGH"
                    ? "bg-rose-50 text-rose-700 border border-rose-200"
                    : "bg-amber-50 text-amber-700 border border-amber-200"
                }`}
              >
                <AlertTriangle className="h-3.5 w-3.5" />
                <span>{currentSample.riskBadge}</span>
              </span>
            </div>
          </div>

          {/* Excerpt vs Explanation vs Redline */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-6">
            <div className="space-y-4">
              <div>
                <span className="text-xs font-mono font-bold uppercase text-slate-400 tracking-wider block mb-1.5">
                  Raw Contract Language
                </span>
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80 font-mono text-xs text-slate-800 leading-relaxed border-l-4 border-l-rose-500">
                  "{currentSample.excerpt}"
                </div>
              </div>

              <div>
                <span className="text-xs font-mono font-bold uppercase text-slate-400 tracking-wider block mb-1.5">
                  Risk Assessment
                </span>
                <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">
                  {currentSample.explanation}
                </p>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <span className="text-xs font-mono font-bold uppercase text-emerald-600 tracking-wider block mb-1.5 flex items-center gap-1.5">
                  <Check className="h-3.5 w-3.5" />
                  Suggested Redline Draft
                </span>
                <div className="p-4 rounded-xl bg-emerald-50/70 border border-emerald-200 font-mono text-xs text-slate-800 leading-relaxed border-l-4 border-l-emerald-500">
                  "{currentSample.suggestedRedline}"
                </div>
              </div>

              <div className="pt-2">
                <span className="text-xs font-mono font-bold uppercase text-slate-700 tracking-wider block mb-1.5">
                  Verification Seal
                </span>
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-100 border border-slate-200 text-slate-800 text-xs font-mono">
                  <ShieldCheck className="h-4 w-4 text-slate-700" />
                  <span>{currentSample.verification}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ────────────────────────────────────────────────────────────────────────────
         FULL-WIDTH BLACK SECTION: TRIPLE-VERIFICATION & WHY CLAUSEWISE
         ──────────────────────────────────────────────────────────────────────────── */}
      <div className="w-full bg-black text-white rounded-t-[36px] sm:rounded-t-[60px] rounded-b-[36px] sm:rounded-b-[60px] border-t border-b border-neutral-900 py-16 sm:py-24 my-12 sm:my-16 shadow-2xl overflow-hidden">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          
          {/* Section 1: Verification Pipeline */}
          <section id="verification" className="scroll-mt-24 mb-16 sm:mb-20">
            <div className="text-center max-w-2xl mx-auto mb-10 pt-2 sm:pt-4">
              <h2 className="text-2xl sm:text-3xl md:text-[38px] font-bold tracking-[-0.03em] text-white mb-2.5">
                How triple-verification works
              </h2>
              <p className="text-white/60 text-sm sm:text-base leading-relaxed max-w-xl mx-auto font-normal">
                Every legal assertion is held to strict mathematical and logical checks before it reaches your report.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="rounded-2xl bg-[#080808] border border-neutral-800 p-6 shadow-xl hover:border-neutral-700 transition reveal-init delay-75">
                <span className="font-mono text-2xl font-bold text-white mb-2 block">01</span>
                <h3 className="text-base font-bold text-white mb-2">Ingest &amp; Classification</h3>
                <p className="text-xs sm:text-sm text-white/70 leading-relaxed mb-4">
                  Contract text is chunked into logical clauses. Preamble and signature blocks are resolved into Disclosing vs Receiving or Vendor vs Client roles.
                </p>
                <div className="text-xs font-mono text-neutral-300 bg-neutral-900 border border-neutral-700 px-2.5 py-1 rounded-md inline-block">
                  Auto-detects NDA, MSA, SOW
                </div>
              </div>

              <div className="rounded-2xl bg-[#080808] border border-neutral-800 p-6 shadow-xl hover:border-neutral-700 transition reveal-init delay-150">
                <span className="font-mono text-2xl font-bold text-white mb-2 block">02</span>
                <h3 className="text-base font-bold text-white mb-2">Multi-Pass Critic</h3>
                <p className="text-xs sm:text-sm text-white/70 leading-relaxed mb-4">
                  Proposed findings pass through an adversarial critic. V1 tests natural language entailment; V2 verifies verbatim quotation boundaries.
                </p>
                <div className="text-xs font-mono text-neutral-300 bg-neutral-900 border border-neutral-700 px-2.5 py-1 rounded-md inline-block">
                  Rejects ungrounded claims
                </div>
              </div>

              <div className="rounded-2xl bg-[#080808] border border-neutral-800 p-6 shadow-xl hover:border-neutral-700 transition reveal-init delay-225">
                <span className="font-mono text-2xl font-bold text-white mb-2 block">03</span>
                <h3 className="text-base font-bold text-white mb-2">Verified Ledger &amp; Redline</h3>
                <p className="text-xs sm:text-sm text-white/70 leading-relaxed mb-4">
                  Verified findings are separated from unconfirmed items. Generates counter-balanced redlines with exportable print-ready audit reports.
                </p>
                <div className="text-xs font-mono text-neutral-300 bg-neutral-900 border border-neutral-700 px-2.5 py-1 rounded-md inline-block">
                  Audit trail &amp; JSON ledger
                </div>
              </div>
            </div>
          </section>

          {/* Section 2: Comparison Matrix */}
          <section className="scroll-mt-24 reveal-init">
            <div className="rounded-3xl bg-[#080808] border border-neutral-800 shadow-2xl overflow-hidden p-6 sm:p-10">
              <div className="text-center max-w-2xl mx-auto mb-8">
                <h2 className="text-2xl sm:text-3xl md:text-[38px] font-bold tracking-[-0.03em] text-white mb-2.5">
                  Why legal teams choose ClauseWise
                </h2>
                <p className="text-white/60 text-sm sm:text-base leading-relaxed max-w-xl mx-auto font-normal">
                  Generic LLM prompts hallucinate clause citations. Outside counsel takes days. ClauseWise delivers verified triage in seconds.
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs sm:text-sm">
                  <thead>
                    <tr className="border-b border-neutral-800">
                      <th className="py-3.5 px-4 font-semibold text-white/50">Capability</th>
                      <th className="py-3.5 px-4 font-bold text-white bg-white/10 border-b border-white/20 rounded-t-xl">
                        ClauseWise AI
                      </th>
                      <th className="py-3.5 px-4 font-semibold text-white/50">Generic Chatbots</th>
                      <th className="py-3.5 px-4 font-semibold text-white/50">Manual Review</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-900 text-white/80">
                    <tr>
                      <td className="py-3.5 px-4 font-medium text-white">Hallucination Prevention</td>
                      <td className="py-3.5 px-4 font-semibold text-white bg-white/[0.04]">
                        <span className="inline-flex items-center gap-1.5 text-emerald-400">
                          <Check className="h-4 w-4" /> Deterministic V1/V2/V3
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-rose-400">High risk of hallucination</td>
                      <td className="py-3.5 px-4 text-white/60">Human error prone</td>
                    </tr>
                    <tr>
                      <td className="py-3.5 px-4 font-medium text-white">Source Grounding</td>
                      <td className="py-3.5 px-4 font-semibold text-white bg-white/[0.04]">
                        <span className="inline-flex items-center gap-1.5 text-emerald-400">
                          <Check className="h-4 w-4" /> 100% Verbatim Quotation
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-white/50">Approximated snippets</td>
                      <td className="py-3.5 px-4 text-white/60">Manual citation</td>
                    </tr>
                    <tr>
                      <td className="py-3.5 px-4 font-medium text-white">Data Confidentiality</td>
                      <td className="py-3.5 px-4 font-semibold text-white bg-white/[0.04]">
                        <span className="inline-flex items-center gap-1.5 text-emerald-400">
                          <Check className="h-4 w-4" /> 24h Purge · Zero Training
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-rose-400">Used for model training</td>
                      <td className="py-3.5 px-4 text-white/60">Confidential</td>
                    </tr>
                    <tr>
                      <td className="py-3.5 px-4 font-medium text-white">Turnaround Speed</td>
                      <td className="py-3.5 px-4 font-semibold text-white bg-white/[0.04]">
                        <span className="inline-flex items-center gap-1.5 text-emerald-400">
                          <Check className="h-4 w-4" /> Instant (Streaming SSE)
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-white/60">Fast (unstructured)</td>
                      <td className="py-3.5 px-4 text-rose-400">2 to 5 business days</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

        </div>
      </div>

      {/* ────────────────────────────────────────────────────────────────────────────
         ACCORDION FAQ SECTION
         ──────────────────────────────────────────────────────────────────────────── */}
      <section id="faq" className="my-10 sm:my-14 max-w-4xl mx-auto w-full px-4 sm:px-6 scroll-mt-20 reveal-init">
        <div className="text-center mb-8">
          <h2 className="text-2xl sm:text-3xl md:text-[38px] font-bold tracking-[-0.03em] text-slate-900 mb-2.5">
            Frequently Asked Questions
          </h2>
          <p className="text-slate-500 text-sm sm:text-base leading-relaxed max-w-xl mx-auto">
            Everything you need to know about ClauseWise AI's review engine.
          </p>
        </div>

        <div className="space-y-3">
          {FAQS.map((faq, idx) => {
            const isOpen = openFaqIndex === idx;
            return (
              <div
                key={idx}
                className="rounded-2xl bg-white border border-slate-200 overflow-hidden transition"
              >
                <button
                  type="button"
                  onClick={() => setOpenFaqIndex(isOpen ? -1 : idx)}
                  className="w-full px-6 py-4.5 text-left flex items-center justify-between gap-4 font-medium text-slate-900 text-sm sm:text-base cursor-pointer hover:bg-slate-50/70"
                >
                  <span>{faq.q}</span>
                  <ChevronDown
                    className={`h-4 w-4 text-slate-500 shrink-0 transition-transform ${
                      isOpen ? "rotate-180 text-black" : ""
                    }`}
                  />
                </button>
                {isOpen && (
                  <div className="px-6 pb-5 text-xs sm:text-sm text-slate-600 leading-relaxed border-t border-slate-100 pt-3">
                    {faq.a}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* ────────────────────────────────────────────────────────────────────────────
         FINAL HIGH-CONVERTING CTA BANNER (Dusk card matching the theme)
         ──────────────────────────────────────────────────────────────────────────── */}
      <section className="my-8 sm:my-12 max-w-6xl mx-auto w-full px-4 sm:px-6 reveal-init">
        <div className="relative rounded-none overflow-hidden shadow-2xl min-h-[320px] sm:min-h-[380px] flex flex-col justify-between">
          
          {/* Background Image Layer */}
          <img
            src="/a.png"
            alt=""
            className="absolute inset-0 w-full h-full object-cover object-center select-none pointer-events-none"
          />
          
          {/* Dark Overlay for text legibility */}
          <div className="absolute inset-0 bg-gradient-to-r from-black/70 via-black/50 to-black/30" />

          {/* Content */}
          <div className="relative z-10 p-8 sm:p-12 lg:p-14 flex flex-col justify-between h-full min-h-[320px] sm:min-h-[380px]">
            
            {/* Decorative Shape */}
            <div className="mb-10 sm:mb-14">
              <div className="grid grid-cols-2 gap-[3px] w-9 h-9">
                <div className="w-full h-full bg-white rounded-[2px] rotate-45 scale-75" />
                <div className="w-full h-full bg-white rounded-[2px] rotate-45 scale-75" />
                <div className="w-full h-full bg-white rounded-[2px] rotate-45 scale-75" />
                <div className="w-full h-full bg-white rounded-[2px] rotate-45 scale-75" />
              </div>
            </div>

            {/* Headline + Subtitle + CTA */}
            <div className="max-w-2xl">
              <h2 className="font-display text-3xl sm:text-4xl md:text-[44px] font-normal tracking-tight text-white leading-[1.15] mb-4">
                Explore ClauseWise in action today
              </h2>
              <p className="text-white/65 text-sm sm:text-base mb-7 leading-relaxed max-w-xl">
                Upload your contract to experience clause-level risk triage and deterministic triple-verification in real time.
              </p>
              <button
                type="button"
                onClick={user ? onLaunchAudit : onOpenAuth}
                className="inline-flex items-center gap-2 rounded-lg bg-white hover:bg-slate-100 text-[#0e0d0c] font-medium text-sm px-5 py-2.5 transition active:scale-95 cursor-pointer shadow-sm"
              >
                <span>{hasActiveAudit && user ? "Resume Live Audit" : "Start Free Audit"}</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ────────────────────────────────────────────────────────────────────────────
         WHIMSICAL / DOKIE-STYLE WHITE ROUNDED CARD FOOTER (Full Ratio & Exact Size)
         ──────────────────────────────────────────────────────────────────────────── */}
      <footer className="w-full max-w-[1400px] mx-auto px-4 sm:px-8 lg:px-12 my-10 sm:my-16 reveal-init">
        <div className="w-full rounded-[32px] sm:rounded-[44px] bg-white border border-slate-200/80 shadow-[0_4px_30px_rgba(0,0,0,0.04)] px-8 sm:px-14 lg:px-16 py-12 sm:py-16 min-h-[380px] sm:min-h-[440px] flex flex-col justify-between transition-all">
          
          {/* Top Section: Logo on Left, Navigation Columns on Right */}
          <div className="flex flex-col md:flex-row justify-between items-start gap-10">
            
            {/* Left: ClauseWise Logo Only (Prominent, clean, matching screenshot) */}
            <div className="flex items-center">
              <button
                type="button"
                onClick={() => {
                  if (user) {
                    onOpenDashboard();
                  } else {
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }
                }}
                className="flex items-center outline-none cursor-pointer"
                title="Clausewise AI"
              >
                <img
                  src="/logo.png"
                  alt="Clausewise"
                  className="h-5 sm:h-6 w-auto object-contain transition-opacity hover:opacity-85"
                />
              </button>
            </div>

            {/* Right: Three Clean Columns (Spacious, tailored to ClauseWise AI) */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-12 sm:gap-16 lg:gap-24 text-left">
              
              {/* Column 1: Audit Platform */}
              <div>
                <h4 className="text-[13px] sm:text-sm font-semibold text-slate-900 mb-3.5 sm:mb-4">
                  Audit Platform
                </h4>
                <ul className="space-y-2 sm:space-y-2.5 text-xs sm:text-[13px] text-slate-500 font-normal">
                  <li>
                    <span
                      onClick={() => document.getElementById("audit-engine")?.scrollIntoView({ behavior: "smooth" })}
                      className="hover:text-slate-900 transition cursor-pointer"
                    >
                      Live Risk Engine
                    </span>
                  </li>
                  <li>
                    <span
                      onClick={() => document.getElementById("verification")?.scrollIntoView({ behavior: "smooth" })}
                      className="hover:text-slate-900 transition cursor-pointer"
                    >
                      Triple-Verification (V1·V2·V3)
                    </span>
                  </li>
                  <li>
                    <span
                      onClick={() => document.getElementById("verification")?.scrollIntoView({ behavior: "smooth" })}
                      className="hover:text-slate-900 transition cursor-pointer"
                    >
                      Deterministic Citations
                    </span>
                  </li>
                  <li>
                    <span
                      onClick={() => document.getElementById("contracts")?.scrollIntoView({ behavior: "smooth" })}
                      className="hover:text-slate-900 transition cursor-pointer"
                    >
                      Automated Redlines
                    </span>
                  </li>
                </ul>
              </div>

              {/* Column 2: Contract Playbooks */}
              <div>
                <h4 className="text-[13px] sm:text-sm font-semibold text-slate-900 mb-3.5 sm:mb-4">
                  Contract Playbooks
                </h4>
                <ul className="space-y-2 sm:space-y-2.5 text-xs sm:text-[13px] text-slate-500 font-normal">
                  <li>
                    <span onClick={() => { setActiveContractTab("NDA"); document.getElementById("contracts")?.scrollIntoView({ behavior: "smooth" }); }} className="hover:text-slate-900 transition cursor-pointer">
                      Mutual NDAs
                    </span>
                  </li>
                  <li>
                    <span onClick={() => { setActiveContractTab("MSA"); document.getElementById("contracts")?.scrollIntoView({ behavior: "smooth" }); }} className="hover:text-slate-900 transition cursor-pointer">
                      Master Services (MSA)
                    </span>
                  </li>
                  <li>
                    <span onClick={() => { setActiveContractTab("EMPLOYMENT"); document.getElementById("contracts")?.scrollIntoView({ behavior: "smooth" }); }} className="hover:text-slate-900 transition cursor-pointer">
                      Employment Agreements
                    </span>
                  </li>
                  <li>
                    <span onClick={() => { setActiveContractTab("LEASE"); document.getElementById("contracts")?.scrollIntoView({ behavior: "smooth" }); }} className="hover:text-slate-900 transition cursor-pointer">
                      Commercial Leases
                    </span>
                  </li>
                  <li>
                    <span onClick={() => document.getElementById("faq")?.scrollIntoView({ behavior: "smooth" })} className="hover:text-slate-900 transition cursor-pointer">
                      Risk Audit FAQs
                    </span>
                  </li>
                </ul>
              </div>

              {/* Column 3: Trust & Legal */}
              <div>
                <h4 className="text-[13px] sm:text-sm font-semibold text-slate-900 mb-3.5 sm:mb-4">
                  Trust & Security
                </h4>
                <ul className="space-y-2 sm:space-y-2.5 text-xs sm:text-[13px] text-slate-500 font-normal">
                  <li>
                    <a
                      href="/zero-retention-policy"
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenRetention();
                      }}
                      className="hover:text-slate-900 transition cursor-pointer block"
                    >
                      Zero-Retention Policy
                    </a>
                  </li>
                  <li>
                    <a
                      href="/deterministic-privacy"
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenPrivacy();
                      }}
                      className="hover:text-slate-900 transition cursor-pointer block"
                    >
                      Deterministic Privacy
                    </a>
                  </li>
                  <li>
                    <a
                      href="/terms-of-service"
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenTerms();
                      }}
                      className="hover:text-slate-900 transition cursor-pointer block"
                    >
                      Terms of Service
                    </a>
                  </li>
                </ul>
              </div>

            </div>
          </div>

          {/* Bottom Section: Copyright */}
          <div className="pt-12 sm:pt-16 flex items-center justify-between text-xs text-slate-400 font-normal">
            <div>©2026 ClauseWise. All rights reserved</div>
          </div>

        </div>
      </footer>

      {/* ────────────────────────────────────────────────────────────────────────────
         END-OF-PAGE SCENIC CLOUD WATERMARK BANNER (Full Bleed 100% Screen Width)
         ──────────────────────────────────────────────────────────────────────────── */}
      <div className="w-full relative mt-8 sm:mt-12 overflow-hidden pointer-events-none select-none leading-none">
        <img
          src="/footer-cloud-watermark.png"
          alt="ClauseWise Clouds"
          className="w-full h-auto object-cover object-bottom block"
        />
      </div>
    </div>
  );
}
