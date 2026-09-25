import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/router";
import {
  getSession, clearSession, getMe, ingestFiles, getJob, getIntegratedGraph, getSubgraph,
  runRingleaders, getSmurfingCycles, predictLinks, getPendingPredictions, verifyNode,
  dismissPrediction, getHistoricalLinks, decideCaseLink, escalateEntity, searchEntities,
} from "@/services/api";
import { connectGraphStream } from "@/services/socket";

import AlgorithmSidebar from "@/components/AlgorithmSidebar";
import GraphCanvas from "@/components/GraphCanvas";
import AlertsPanel from "@/components/AlertsPanel";
import LinksPanel from "@/components/LinksPanel";
import NodeDetail from "@/components/NodeDetail";
import UploadModal from "@/components/UploadModal";
import VerifyNodeModal from "@/components/VerifyNodeModal";
import EvidenceExportButton from "@/components/EvidenceExportButton";

const RANK_KEYS = { betweenness: "betweenness_centrality", eigenvector: "eigenvector_centrality", pagerank: "pagerank" };
const EMPTY = { nodes: [], edges: [], cases: [], stats: {} };

function inr(n) {
  return "Rs " + Math.round(n || 0).toLocaleString("en-IN");
}

export default function CasesPage() {
  const router = useRouter();
  const [session, setSession] = useState(null);
  const [caseIds, setCaseIds] = useState([]);
  const [caseId, setCaseId] = useState(null);

  const [snapshot, setSnapshot] = useState(EMPTY);
  const [subSnapshot, setSubSnapshot] = useState(null);
  const [activeView, setActiveView] = useState("integrated");
  const [analytics, setAnalytics] = useState(null);
  const [smurfing, setSmurfing] = useState(null);
  const [busy, setBusy] = useState(false);

  const [linksReport, setLinksReport] = useState(null);
  const [linksLoading, setLinksLoading] = useState(false);
  const [sbertAlerts, setSbertAlerts] = useState([]);
  const [predictedLinks, setPredictedLinks] = useState([]);
  const [predicting, setPredicting] = useState(false);

  const [rightTab, setRightTab] = useState("links");
  const [selectedId, setSelectedId] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const [searchQ, setSearchQ] = useState("");
  const [searchHits, setSearchHits] = useState([]);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progressLog, setProgressLog] = useState([]);
  const [verifyTarget, setVerifyTarget] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState(null);
  const activeJob = useRef(null);

  // ---------------------------------------------------------------- session
  useEffect(() => {
    const s = getSession();
    if (!s || s.role !== "investigator") {
      router.push("/");
      return;
    }
    setSession(s);
    setCaseIds(s.assigned_case_ids || []);
    if (s.assigned_case_ids?.length) setCaseId(s.assigned_case_ids[0]);
    getMe().then((me) => {                         // picks up cases assigned after login
      if (me.assigned_case_ids) setCaseIds(me.assigned_case_ids);
    }).catch(() => {});
  }, [router]);

  // ---------------------------------------------------------------- loaders
  const refreshGraph = useCallback(async () => {
    if (!caseId) return;
    try {
      setSnapshot(await getIntegratedGraph(caseId));
    } catch (err) {
      setError("Could not load the case network -- is the backend running? " + (err?.message || ""));
    }
  }, [caseId]);

  const refreshLinks = useCallback(async (rescan = false) => {
    if (!caseId) return;
    setLinksLoading(true);
    try {
      setLinksReport(await getHistoricalLinks(caseId, rescan));
    } catch {
      /* shown as empty */
    } finally {
      setLinksLoading(false);
    }
  }, [caseId]);

  const refreshPredictions = useCallback(async () => {
    if (!caseId) return;
    try {
      const r = await getPendingPredictions(caseId);
      setPredictedLinks(r.predicted_links || []);
    } catch {
      /* ignore */
    }
  }, [caseId]);

  const finishIngest = useCallback((payload) => {
    if (!payload || activeJob.current === "done") return;
    activeJob.current = "done";
    setUploading(false);
    if (payload.error) {
      setProgressLog((log) => [...log, `FAILED: ${payload.error}`]);
      return;
    }
    const mo = (payload.alerts || []).filter((a) => a.type === "sbert_mo_match");
    if (mo.length) setSbertAlerts((prev) => [...mo, ...prev]);
    if (payload.links) {
      setProgressLog((log) => [...log,
        `linked to ${payload.links.confirmed} case(s), ${payload.links.probable} probable lead(s)`]);
    }
    setAnalytics(null);
    setSmurfing(null);
    refreshGraph();
    refreshLinks();
    setRightTab("links");
  }, [refreshGraph, refreshLinks]);

  // ---------------------------------------------------------------- case switch
  useEffect(() => {
    if (!caseId) return;
    setSnapshot(EMPTY);
    setSubSnapshot(null);
    setAnalytics(null);
    setSmurfing(null);
    setSbertAlerts([]);
    setSelectedId(null);
    setActiveView("integrated");
    setError(null);
    refreshGraph();
    refreshLinks();
    refreshPredictions();

    const cleanup = connectGraphStream(caseId, (payload) => {
      if (payload.stage && payload.stage !== "alert") {
        setProgressLog((log) => [...log, `${payload.stage}${payload.file ? " -> " + payload.file : ""}`]);
      }
      if (payload.stage === "ingestion_complete") finishIngest(payload);
      if (payload.stage === "ingestion_failed") finishIngest({ error: payload.error });
    });
    return cleanup;
  }, [caseId, refreshGraph, refreshLinks, refreshPredictions, finishIngest]);

  // ---------------------------------------------------------------- actions
  async function handleUpload(files, declaredType) {
    setUploading(true);
    setProgressLog([]);
    try {
      const { job_id } = await ingestFiles(caseId, files, declaredType);
      activeJob.current = job_id;
      // Fallback poll in case a WebSocket frame is missed.
      const poll = async () => {
        if (activeJob.current !== job_id) return;
        try {
          const job = await getJob(job_id);
          if (job.status === "complete") return finishIngest(job.result);
          if (job.status === "failed") return finishIngest({ error: job.error });
        } catch {
          /* keep polling */
        }
        setTimeout(poll, 2000);
      };
      setTimeout(poll, 2000);
    } catch (err) {
      setProgressLog((log) => [...log, "FAILED: upload rejected - " + (err?.response?.data?.detail || err?.message)]);
      setUploading(false);
    }
  }

  async function handleSelectView(key) {
    setActiveView(key);
    setSubSnapshot(null);
    if (["betweenness", "eigenvector", "pagerank", "louvain"].includes(key) && !analytics) {
      setBusy(true);
      try {
        setAnalytics(await runRingleaders(caseId));
      } finally {
        setBusy(false);
      }
    } else if (key === "smurfing") {
      setBusy(true);
      try {
        setSmurfing(await getSmurfingCycles(caseId));
      } finally {
        setBusy(false);
      }
    }
  }

  async function handlePredictLinks() {
    setPredicting(true);
    try {
      const result = await predictLinks(caseId);
      setPredictedLinks(result.predicted_links || []);
      setRightTab("alerts");
    } finally {
      setPredicting(false);
    }
  }

  async function handleConfirmVerify() {
    if (!verifyTarget) return;
    setVerifying(true);
    try {
      await verifyNode(caseId, verifyTarget.source, verifyTarget.target, verifyTarget.score);
      setVerifyTarget(null);
      await refreshPredictions();
      refreshGraph();
    } finally {
      setVerifying(false);
    }
  }

  async function handleDismiss(link) {
    await dismissPrediction(caseId, link.source, link.target, "dismissed by investigator");
    refreshPredictions();
  }

  async function handleDecideLink(otherCaseId, decision) {
    await decideCaseLink(caseId, otherCaseId, decision);
    refreshLinks();
    refreshGraph();
    setAnalytics(null);
  }

  async function handleEscalate() {
    if (!selectedId) return;
    await escalateEntity(caseId, selectedId, "escalated from graph canvas");
    refreshGraph();
  }

  async function handleExpand() {
    if (subSnapshot) {
      setSubSnapshot(null);
      return;
    }
    if (!selectedId) return;
    setSubSnapshot(await getSubgraph(caseId, selectedId, 2));
  }

  async function handleSearch(q) {
    setSearchQ(q);
    if (q.trim().length < 3) {
      setSearchHits([]);
      return;
    }
    try {
      setSearchHits(await searchEntities(caseId, q.trim()));
    } catch {
      setSearchHits([]);
    }
  }

  function focusNode(id) {
    setSubSnapshot(null);
    setActiveView((v) => (v === "smurfing" ? "integrated" : v));
    setSelectedId(id);
    setFocusId(null);
    setTimeout(() => setFocusId(id), 50);
    setRightTab("node");
  }

  // ---------------------------------------------------------------- derived
  const nodeById = useMemo(() => {
    const m = {};
    for (const n of snapshot.nodes || []) m[n.entity_id] = n;
    return m;
  }, [snapshot]);
  const labelFor = useCallback(
    (id) => nodeById[id]?.display_value || (id || "").replace(/^[A-Z]+:/, ""),
    [nodeById]
  );

  const rankMap = useMemo(() => {
    const key = RANK_KEYS[activeView];
    const list = key && analytics ? analytics[key] || [] : [];
    const max = list.length ? Math.max(...list.map((r) => r.score)) || 1 : 1;
    const m = {};
    for (const r of list) m[r.entity_id] = r.score / max;
    return m;
  }, [activeView, analytics]);

  const communityMap = useMemo(() => {
    const m = {};
    for (const c of analytics?.louvain_communities || []) for (const mem of c.members) m[mem.entity_id] = c.community_id;
    return m;
  }, [analytics]);

  const ranking = useMemo(() => {
    const key = RANK_KEYS[activeView];
    if (key && analytics) {
      return (analytics[key] || []).map((r) => ({ entity_id: r.entity_id, value: r.score.toFixed(3) }));
    }
    if (activeView === "louvain" && analytics) {
      return (analytics.louvain_communities || []).map((c) => ({
        key: `c${c.community_id}`,
        entity_id: c.members[0]?.entity_id,
        label: `Community ${c.community_id + 1} · ${c.cases.slice(0, 2).join(", ")}${c.cases.length > 2 ? "…" : ""}`,
        value: c.size,
      }));
    }
    return [];
  }, [activeView, analytics]);

  const mode = RANK_KEYS[activeView] ? "rank" : activeView === "louvain" ? "community" : "type";
  const highlightIds = useMemo(
    () => predictedLinks.flatMap((l) => [l.source, l.target]),
    [predictedLinks]
  );
  const selectedNode = selectedId ? nodeById[selectedId] : null;
  const stats = snapshot.stats || {};

  if (!session) return null;

  return (
    <div className="flex h-screen flex-col bg-ink">
      <header className="flex items-center justify-between gap-3 border-b border-[#1D3157] bg-[#0E1B33] px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-[#E7ECF3]">Sandhan</span>
          <select value={caseId || ""} onChange={(e) => setCaseId(e.target.value)}
            className="rounded border border-[#2C4266] bg-[#0B1F3A] px-2 py-1 text-sm text-[#E7ECF3]">
            {caseIds.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <div className="relative">
            <input value={searchQ} onChange={(e) => handleSearch(e.target.value)} placeholder="Find phone / IMEI / UPI..."
              className="w-56 rounded border border-[#2C4266] bg-[#0B1F3A] px-2 py-1 text-sm text-[#E7ECF3]" />
            {searchHits.length > 0 && (
              <div className="absolute left-0 top-full z-20 mt-1 w-72 rounded border border-[#2C4266] bg-[#0E1B33] shadow-lg">
                {searchHits.map((h) => (
                  <button key={h.entity_id} onClick={() => { focusNode(h.entity_id); setSearchHits([]); setSearchQ(""); }}
                    className="block w-full px-3 py-1.5 text-left text-xs text-[#E7ECF3] hover:bg-[#1D3157]">
                    <span className="mono">{h.display_value}</span>
                    <span className="ml-2 text-[#7C8AA3]">{h.entity_type} · {h.cases.join(", ")}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <a href="/baseline" className="text-xs text-[#7C8AA3] hover:text-[#E7ECF3]">Baseline SQL lookup</a>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handlePredictLinks} disabled={predicting}
            className="rounded border border-[#2C4266] px-3 py-2 text-sm text-[#E7ECF3] hover:bg-[#1D3157] disabled:opacity-50">
            {predicting ? "Predicting..." : "Run link prediction"}
          </button>
          <button onClick={() => setUploadOpen(true)}
            className="rounded bg-signal px-3 py-2 text-sm font-medium text-[#0B1F3A] hover:opacity-90">
            Ingest files
          </button>
          <EvidenceExportButton caseId={caseId} pendingCount={predictedLinks.length} />
          <button onClick={() => { clearSession(); router.push("/"); }}
            className="ml-2 text-sm text-[#7C8AA3] hover:text-[#E7ECF3]">
            Sign out
          </button>
        </div>
      </header>

      <div className="flex items-center gap-4 border-b border-[#1D3157] bg-[#0B1A30] px-4 py-1 text-xs text-[#7C8AA3]">
        <span>
          Network: <span className="text-[#E7ECF3]">{stats.cases || 0}</span> case(s) &middot;{" "}
          <span className="text-[#E7ECF3]">{stats.historical_cases || 0}</span> historical &middot;{" "}
          {stats.nodes || 0} entities &middot; {stats.edges || 0} relationships
        </span>
        {(snapshot.cases || []).length > 1 && (
          <span className="truncate">
            {(snapshot.cases || []).filter((c) => c.depth > 0).map((c) => c.case_id).join(" · ")}
          </span>
        )}
        {subSnapshot && <span className="text-signal">Showing 2-hop neighbourhood of {labelFor(selectedId)}</span>}
        {error && <span className="text-alertred">{error}</span>}
      </div>

      <div className="flex flex-1 overflow-hidden">
        <AlgorithmSidebar active={activeView} onSelect={handleSelectView} ranking={ranking}
          labelFor={labelFor} onFocus={focusNode} busy={busy} />

        <main className="flex-1 p-4">
          {activeView === "smurfing" ? (
            <div className="h-full overflow-y-auto rounded-lg border border-[#1D3157] bg-[#0E2038] p-4">
              <h2 className="text-sm font-medium text-[#E7ECF3]">Laundering cycles (money that returns to its origin)</h2>
              <p className="mb-3 text-xs text-[#7C8AA3]">
                Tarjan SCC over directed UPI transfers across the whole case network, then cycles of up to 5 hops
                whose smallest transfer is at least Rs 50,000.
                {smurfing && ` ${smurfing.scc_count} strongly connected component(s) found.`}
              </p>
              {smurfing && smurfing.cycles.length === 0 && <p className="text-sm text-[#7C8AA3]">No cycles above the threshold.</p>}
              {(smurfing?.cycles || []).map((c, i) => (
                <div key={i} className="mb-3 rounded border border-[#2C4266] bg-[#0B1F3A] p-3">
                  <div className="mono text-xs text-[#E7ECF3]">
                    {c.edges.map((e, j) => (
                      <span key={j}>
                        <button className="hover:underline" onClick={() => focusNode(e.from)}>{labelFor(e.from)}</button>
                        <span className="text-verified"> &rarr;{inr(e.amount)}&rarr; </span>
                      </span>
                    ))}
                    <span>{labelFor(c.edges[0]?.from)}</span>
                  </div>
                  <div className="mt-1 text-xs text-[#9AA7BD]">
                    {c.length} hops · bottleneck {inr(c.bottleneck_amount)} · cases: {c.cases.join(", ")}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <GraphCanvas snapshot={subSnapshot || snapshot} mode={mode} rankMap={rankMap}
              communityMap={communityMap} highlightIds={highlightIds} focusId={focusId}
              onNodeClick={(id) => { setSelectedId(id); setRightTab("node"); }} />
          )}
        </main>

        <aside className="flex h-full w-80 flex-col border-l border-[#1D3157] bg-[#0E1B33]">
          <div className="flex border-b border-[#1D3157] text-xs">
            {[
              ["links", `Historical links${linksReport?.links?.length ? ` (${linksReport.links.length})` : ""}`],
              ["alerts", `Alerts${predictedLinks.length + sbertAlerts.length ? ` (${predictedLinks.length + sbertAlerts.length})` : ""}`],
              ["node", "Node"],
            ].map(([k, label]) => (
              <button key={k} onClick={() => setRightTab(k)}
                className={`flex-1 px-2 py-2 ${rightTab === k ? "bg-[#1D3157] text-[#E7ECF3]" : "text-[#9AA7BD] hover:text-[#E7ECF3]"}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="flex min-h-0 flex-1 flex-col">
            {rightTab === "links" && (
              <LinksPanel report={linksReport} loading={linksLoading} onRefresh={() => refreshLinks(true)}
                onDecide={handleDecideLink} labelFor={labelFor} />
            )}
            {rightTab === "alerts" && (
              <AlertsPanel sbertAlerts={sbertAlerts} predictedLinks={predictedLinks} labelFor={labelFor}
                onVerify={(link) => setVerifyTarget(link)} onDismiss={handleDismiss} onFocus={focusNode} />
            )}
            {rightTab === "node" && (
              <NodeDetail node={selectedNode} expanded={!!subSnapshot} onExpand={handleExpand}
                onEscalate={handleEscalate} onClose={() => { setSelectedId(null); setSubSnapshot(null); }} />
            )}
          </div>
        </aside>
      </div>

      <UploadModal open={uploadOpen} caseId={caseId} onClose={() => setUploadOpen(false)} onUpload={handleUpload}
        progressLog={progressLog} uploading={uploading} />
      <VerifyNodeModal link={verifyTarget} labelFor={labelFor} onConfirm={handleConfirmVerify}
        onCancel={() => setVerifyTarget(null)} submitting={verifying} />
    </div>
  );
}
