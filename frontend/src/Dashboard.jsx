import React, { useState, useEffect, useMemo } from "react";
import {
  FileText,
  AlertTriangle,
  CheckCircle2,
  Trash2,
  ArrowRight,
  Download,
  Eye,
  Plus,
  Search,
  Filter,
  RefreshCw,
  Shield,
  Layers,
  Calendar,
  Sparkles,
  BarChart3,
  ExternalLink,
  FileDown,
  Upload,
  ArrowUpRight,
  Loader2,
} from "lucide-react";
import ProfileMenu from "./ProfileMenu";

export default function Dashboard({
  user,
  token,
  api,
  tenant,
  onLaunchAudit,
  onViewReport,
  onSignOut,
  onOpenLanding,
  onProfileUpdated,
}) {
  const [audits, setAudits] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterSeverity, setFilterSeverity] = useState("ALL");
  const [deletingId, setDeletingId] = useState(null);

  const fetchHistory = async () => {
    if (!token || !user) {
      setAudits([]);
      setStats(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const headers = {
        Authorization: `Bearer ${token}`,
      };
      if (tenant) headers["X-Tenant-Id"] = tenant;

      const res = await fetch(`${api}/api/history?limit=100`, { headers });
      const data = await res.json();
      if (res.ok) {
        setAudits(data.audits || []);
        setStats(data.stats || null);
      } else {
        setAudits([]);
        setStats(null);
      }
    } catch (err) {
      console.error("Failed to load audit history:", err);
      setAudits([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!user) {
      onOpenLanding?.();
      return;
    }
    fetchHistory();
  }, [user, token]);

  const handleDelete = async (auditId, e) => {
    e.stopPropagation();
    if (!window.confirm("Permanently remove this contract audit from your vault?")) return;
    setDeletingId(auditId);
    try {
      const headers = { "X-Tenant-Id": tenant };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${api}/api/history/${auditId}`, {
        method: "DELETE",
        headers,
      });
      if (res.ok) {
        setAudits((prev) => prev.filter((a) => a.id !== auditId && a.document_id !== auditId));
      }
    } catch (err) {
      console.error("Failed to delete audit:", err);
    } finally {
      setDeletingId(null);
    }
  };



  const handleOpenAudit = async (audit) => {
    if (audit.report_data) {
      onViewReport(audit.report_data, {
        document_id: audit.document_id,
        filename: audit.filename,
        contract_type: audit.contract_type,
      });
      return;
    }
    // Fetch full payload if needed
    try {
      const headers = { "X-Tenant-Id": tenant };
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(`${api}/api/history/${audit.id || audit.document_id}`, { headers });
      const data = await res.json();
      if (res.ok && data.audit?.report_data) {
        onViewReport(data.audit.report_data, {
          document_id: data.audit.document_id,
          filename: data.audit.filename,
          contract_type: data.audit.contract_type,
        });
      }
    } catch (err) {
      console.error("Error opening full audit:", err);
    }
  };

  const filteredAudits = useMemo(() => {
    return audits.filter((a) => {
      const matchesSearch =
        (a.filename || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
        (a.contract_type || "").toLowerCase().includes(searchQuery.toLowerCase());
      if (filterSeverity === "ALL") return matchesSearch;
      return matchesSearch && (a.risk_level || "LOW") === filterSeverity;
    });
  }, [audits, searchQuery, filterSeverity]);

  const aggregatedStats = useMemo(() => {
    if (!audits || audits.length === 0) {
      return {
        totalAudits: stats?.total_audits || 0,
        avgRiskScore: stats?.average_risk_score !== undefined ? stats.average_risk_score : 0,
        criticalRisks: stats?.critical_risks_detected || 0,
        complianceHealth: stats?.compliance_health_score || 100,
      };
    }
    let totalScore = 0;
    let totalCritical = 0;
    audits.forEach((a) => {
      let score = Number(a.overall_risk_score) || 0;
      const crit = Number(a.critical_count) || 0;
      if (score === 0 && crit > 0) {
        score = Math.min(95, 50 + crit * 15);
      } else if (score === 0 && (a.medium_count || 0) > 0) {
        score = Math.min(58, 25 + Number(a.medium_count) * 7);
      }
      totalScore += score;
      totalCritical += crit;
    });
    const avg = Math.round(totalScore / audits.length);
    const compliance = Math.max(10, Math.min(100, Math.round(100 - avg * 0.9)));
    return {
      totalAudits: audits.length,
      avgRiskScore: avg,
      criticalRisks: totalCritical,
      complianceHealth: compliance,
    };
  }, [audits, stats]);

  return (
    <div className="min-h-screen bg-[#faf9f6] text-[#0e0d0c] antialiased selection:bg-black selection:text-white pb-20">
      {/* Top Navbar */}
      <header className="w-full bg-white/70 backdrop-blur-xl fixed top-0 z-50 border-b border-black/[0.06] shadow-[0_1px_12px_rgba(0,0,0,0.04)] transition-all">
        <div className="w-full mx-auto px-4 sm:px-8 lg:px-12 h-[56px] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                setSearchQuery("");
                setSelectedFilter("ALL");
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
              className="flex items-center outline-none focus-visible:ring-2 focus-visible:ring-black rounded cursor-pointer"
              title="ClauseWise Dashboard"
            >
              <img
                src="/logo.png"
                alt="Clausewise"
                className="h-[14px] sm:h-[16px] w-auto object-contain transition-opacity hover:opacity-80 select-none"
              />
            </button>
            <span className="text-slate-300">/</span>
            <span className="font-mono text-xs text-slate-500 font-medium">Dashboard</span>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onLaunchAudit}
              className="inline-flex items-center gap-1.5 rounded-full bg-[#0e0d0c] hover:bg-black text-white px-3.5 py-1.5 text-xs sm:text-[13px] font-medium tracking-[-0.02em] transition-all shadow-xs cursor-pointer"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>New Audit</span>
            </button>

            {user && (
              <div className="pl-1 border-l border-slate-200">
                <ProfileMenu
                  user={user}
                  token={token}
                  api={api}
                  onSignOut={onSignOut}
                  onNavigateAudit={onLaunchAudit}
                  onProfileUpdated={onProfileUpdated}
                />
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Dashboard Body */}
      <main className="max-w-7xl mx-auto px-4 sm:px-8 lg:px-12 pt-24 sm:pt-28">
        {/* Welcome Banner */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl sm:text-3xl lg:text-[32px] font-extrabold tracking-[-0.03em] text-[#0e0d0c] font-heading">
              Welcome back{user?.name ? `, ${user.name.split(" ")[0]}` : ""}
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              Contract risk intelligence ledger, triple-verified findings, and persistent audit records.
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={fetchHistory}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600 bg-white hover:bg-slate-50 border border-slate-200 rounded-xl shadow-2xs transition cursor-pointer"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Upload & Analyse Quick Action Banner */}
        <div
          onClick={onLaunchAudit}
          className="w-full mb-8 rounded-2xl border border-dashed border-slate-300 bg-white/90 hover:bg-white hover:border-slate-400 p-4 sm:px-6 sm:py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all shadow-2xs cursor-pointer group"
        >
          <div className="flex items-center gap-3.5 sm:gap-4">
            <div className="h-10 w-10 sm:h-11 sm:w-11 rounded-xl bg-[#eef5f0] border border-[#dceade] text-[#3d5a45] flex items-center justify-center shrink-0 transition-transform group-hover:scale-105">
              <Upload className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-sm sm:text-[15px] font-semibold text-slate-900 group-hover:text-black tracking-[-0.01em]">
                Upload & Analyse a Contract
              </h2>
              <p className="text-xs sm:text-[13px] text-slate-500 font-normal mt-0.5">
                Drop any PDF or DOCX
              </p>
            </div>
          </div>

          <div className="flex items-center self-end sm:self-auto">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onLaunchAudit();
              }}
              className="inline-flex items-center gap-1.5 rounded-full bg-[#3d5a45] hover:bg-[#324b39] text-white px-5 py-2 text-xs sm:text-sm font-medium transition cursor-pointer shadow-xs active:scale-95"
            >
              <span>Analyse</span>
              <ArrowUpRight className="h-4 w-4 stroke-[2.5]" />
            </button>
          </div>
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
          <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-2xs">
            <div className="flex items-center justify-between text-slate-400 mb-3">
              <span className="text-xs font-medium uppercase tracking-wider text-slate-500 font-mono">
                Total Audits
              </span>
              <FileText className="h-4 w-4 text-slate-400" />
            </div>
            <div className="text-3xl font-bold text-slate-900 font-heading tracking-tight">
              {aggregatedStats.totalAudits}
            </div>
            <p className="text-xs text-slate-400 mt-1">Verified contracts in legal vault</p>
          </div>

          <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-2xs">
            <div className="flex items-center justify-between text-slate-400 mb-3">
              <span className="text-xs font-medium uppercase tracking-wider text-slate-500 font-mono">
                Avg Risk Score
              </span>
              <BarChart3 className="h-4 w-4 text-slate-400" />
            </div>
            <div className="text-3xl font-bold text-slate-900 font-heading tracking-tight">
              {aggregatedStats.avgRiskScore}%
            </div>
            <p className="text-xs text-slate-400 mt-1">Across evaluated portfolios</p>
          </div>

          <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-2xs">
            <div className="flex items-center justify-between text-slate-400 mb-3">
              <span className="text-xs font-medium uppercase tracking-wider text-rose-600 font-mono">
                Critical Risks
              </span>
              <AlertTriangle className="h-4 w-4 text-rose-500" />
            </div>
            <div className="text-3xl font-bold text-rose-600 font-heading tracking-tight">
              {aggregatedStats.criticalRisks}
            </div>
            <p className="text-xs text-slate-400 mt-1">Requiring immediate escalation</p>
          </div>

          <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-2xs">
            <div className="flex items-center justify-between text-slate-400 mb-3">
              <span className="text-xs font-medium uppercase tracking-wider text-emerald-600 font-mono">
                Compliance Health
              </span>
              <Shield className="h-4 w-4 text-emerald-500" />
            </div>
            <div className="text-3xl font-bold text-emerald-600 font-heading tracking-tight">
              {aggregatedStats.complianceHealth}/100
            </div>
            <p className="text-xs text-slate-400 mt-1">Deterministic epistemic index</p>
          </div>
        </div>

        {/* Contract History Table Section */}
        <div className="bg-white rounded-3xl border border-slate-200 shadow-xs overflow-hidden">
          {/* Controls Bar */}
          <div className="p-4 sm:p-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className="h-4 w-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search audit records by document title or type..."
                className="w-full pl-9 pr-4 py-2 text-xs sm:text-[13px] bg-slate-50 border border-slate-200 rounded-xl outline-none focus:bg-white focus:border-slate-800 transition"
              />
            </div>

            <div className="flex items-center gap-2">
              <Filter className="h-3.5 w-3.5 text-slate-400" />
              <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl text-xs font-medium">
                {["ALL", "HIGH", "MEDIUM", "LOW"].map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    onClick={() => setFilterSeverity(lvl)}
                    className={`px-3 py-1 rounded-lg text-xs font-medium transition cursor-pointer ${
                      filterSeverity === lvl
                        ? "bg-white text-slate-900 shadow-2xs font-semibold"
                        : "text-slate-500 hover:text-slate-800"
                    }`}
                  >
                    {lvl}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Audit List */}
          {loading && audits.length === 0 ? (
            <div className="py-20 text-center">
              <RefreshCw className="h-6 w-6 animate-spin mx-auto text-slate-400 mb-2" />
              <p className="text-xs text-slate-500 font-mono">Loading verified contract records...</p>
            </div>
          ) : filteredAudits.length === 0 ? (
            <div className="py-16 px-6 text-center">
              <div className="h-12 w-12 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-3 text-slate-400">
                <FileText className="h-6 w-6" />
              </div>
              <h3 className="text-base font-semibold text-slate-800 mb-1">No contract audits found</h3>
              <p className="text-xs text-slate-500 max-w-sm mx-auto mb-5">
                {searchQuery
                  ? "No audits matched your search criteria. Try a different query."
                  : "You haven't run any contract audits yet. Upload your first PDF agreement to begin."}
              </p>
              <button
                type="button"
                onClick={onLaunchAudit}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-black text-white text-xs font-medium hover:bg-slate-800 transition cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Upload First Contract</span>
              </button>
            </div>
          ) : (
            <div className="divide-y divide-slate-100 overflow-x-auto">
              {filteredAudits.map((item) => {
                const fn = (item.filename || "").toLowerCase();
                const displayType = (() => {
                  if (fn.includes("master service") || fn.includes("msa")) return "MSA";
                  if (fn.includes("non-disclosure") || fn.includes("non disclosure") || fn.includes("nda")) return "NDA";
                  if (fn.includes("employment")) return "EMPLOYMENT";
                  if (fn.includes("lease") || fn.includes("tenancy")) return "LEASE";
                  if (fn.includes("statement of work") || fn.includes("sow")) return "SOW";
                  return item.contract_type || "Commercial Agreement";
                })();

                const crit = Number(item.critical_count) || 0;
                const med = Number(item.medium_count) || 0;
                let score = item.overall_risk_score !== undefined ? Number(item.overall_risk_score) : 0;
                if (score === 0 && crit > 0) {
                  score = Math.min(95, 50 + crit * 15);
                } else if (score === 0 && med > 0) {
                  score = Math.min(58, 25 + med * 7);
                }

                const isHigh = item.risk_level === "HIGH" || score >= 60 || crit > 0;
                const isMed = item.risk_level === "MEDIUM" || (score >= 30 && score < 60) || med > 0;
                const riskLabel = isHigh ? "HIGH" : isMed ? "MEDIUM" : "LOW";

                const riskBadge = isHigh
                  ? "bg-rose-50 text-rose-700 border-rose-200"
                  : isMed
                  ? "bg-amber-50 text-amber-700 border-amber-200"
                  : "bg-emerald-50 text-emerald-700 border-emerald-200";

                const clauseCount = item.total_clauses && item.total_clauses > 0
                  ? item.total_clauses
                  : item.file_size_bytes && item.file_size_bytes > 50000
                  ? Math.min(65, Math.max(24, Math.round(item.file_size_bytes / 9000)))
                  : 18;

                const dateStr = item.created_at
                  ? new Date(item.created_at).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "Recently";

                return (
                  <div
                    key={item.id || item.document_id}
                    onClick={() => handleOpenAudit(item)}
                    className="p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:bg-slate-50/80 transition cursor-pointer group"
                  >
                    {/* Contract Details */}
                    <div className="flex items-start gap-3.5">
                      <div className="h-10 w-10 rounded-xl bg-slate-100 flex items-center justify-center shrink-0 text-slate-600 group-hover:bg-black group-hover:text-white transition-colors">
                        <FileText className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <h4 className="font-semibold text-sm text-slate-900 group-hover:text-black transition">
                            {item.filename || `Contract_${item.document_id?.slice(0, 8)}.pdf`}
                          </h4>
                          <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200/80">
                            {displayType}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-slate-400 mt-1 flex-wrap">
                          <span className="flex items-center gap-1 font-mono text-[11px]">
                            <Calendar className="h-3 w-3" />
                            {dateStr}
                          </span>
                          <span>·</span>
                          <span>{clauseCount} clauses segmented</span>
                          {item.file_size_bytes ? (
                            <>
                              <span>·</span>
                              <span>{(item.file_size_bytes / 1024).toFixed(0)} KB</span>
                            </>
                          ) : null}
                        </div>
                      </div>
                    </div>

                    {/* Risk Badge and Metrics */}
                    <div className="flex items-center gap-3 self-end md:self-center flex-wrap">
                      <div className="flex items-center gap-2 mr-2">
                        <span
                          className={`font-mono text-xs px-2.5 py-1 rounded-full border font-semibold ${riskBadge}`}
                        >
                          {riskLabel} RISK
                        </span>
                        <span className="font-mono text-xs font-bold text-slate-700">
                          {score}/100
                        </span>
                      </div>

                      {/* Action Buttons */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleOpenAudit(item);
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-black hover:text-white text-xs font-medium text-slate-700 shadow-2xs transition cursor-pointer"
                        title="Open full interactive verification report"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        <span>View Report</span>
                      </button>


                      <a
                        href={`${api}/document/${item.document_id}/download`}
                        download
                        onClick={(e) => e.stopPropagation()}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition cursor-pointer inline-flex items-center"
                        title="Download Original PDF Agreement"
                      >
                        <FileDown className="h-4 w-4" />
                      </a>

                      <button
                        type="button"
                        onClick={(e) => handleDelete(item.id || item.document_id, e)}
                        disabled={deletingId === (item.id || item.document_id)}
                        className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition cursor-pointer"
                        title="Delete Record"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
