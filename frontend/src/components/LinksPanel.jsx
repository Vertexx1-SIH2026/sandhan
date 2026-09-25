const STATUS_STYLE = {
  confirmed: "border-verified/50 bg-verified/10 text-verified",
  verified: "border-verified/50 bg-verified/10 text-verified",
  probable: "border-signal/50 bg-signal/10 text-signal",
  dismissed: "border-[#2C4266] bg-transparent text-[#6C7C97]",
};

function strip(id) {
  return (id || "").replace(/^[A-Z]+:/, "");
}

function describe(sig, label) {
  if (sig.signal === "shared_identifier") {
    const side = sig.my_role === "subject" && sig.other_role === "subject"
      ? "suspect in both"
      : sig.my_role === "subject" || sig.other_role === "subject" ? "suspect side" : "counterparty";
    return `shares ${sig.id_type} ${label(sig.identifier)} (${side}${sig.cases_sharing > 2 ? `, in ${sig.cases_sharing} cases` : ""})`;
  }
  if (sig.signal === "alias_handle") {
    return `look-alike UPI handle "${sig.handle}": ${strip(sig.identifier)} vs ${strip(sig.other_identifier)}`;
  }
  if (sig.signal === "mo_similarity") {
    return `similar FIR narrative (${Math.round(sig.similarity * 100)}%${sig.mo_category ? ", " + sig.mo_category.replace(/_/g, " ") : ""})`;
  }
  return sig.signal;
}

/**
 * "Which historical (and live) cases is this case connected to, and why?"
 * Confirmed links are already part of the graph; probable links are leads
 * the investigator verifies or dismisses (HITL).
 */
export default function LinksPanel({ report, loading, onRefresh, onDecide, labelFor }) {
  const links = report?.links || [];
  const label = labelFor || strip;
  const counts = links.reduce((acc, l) => ({ ...acc, [l.status]: (acc[l.status] || 0) + 1 }), {});

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[#1D3157] px-3 py-2">
        <div className="text-xs text-[#9AA7BD]">
          <span className="text-verified">{(counts.confirmed || 0) + (counts.verified || 0)} linked</span>
          {" · "}
          <span className="text-signal">{counts.probable || 0} leads</span>
          {report?.cluster?.length > 1 && <> · network of {report.cluster.length} cases</>}
        </div>
        <button onClick={onRefresh} disabled={loading}
          className="rounded border border-[#2C4266] px-2 py-1 text-xs text-[#E7ECF3] hover:bg-[#1D3157] disabled:opacity-50">
          {loading ? "Searching..." : "Re-scan history"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {links.length === 0 && (
          <p className="mt-4 px-2 text-sm text-[#6C7C97]">
            No links yet. After ingestion this case is matched against every historical case
            (identifiers, look-alike UPI handles, similar FIR narratives).
          </p>
        )}
        {links.map((l) => (
          <div key={l.other_case_id} className={`mb-3 rounded-md border p-3 ${STATUS_STYLE[l.status] || ""}`}>
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-[#E7ECF3]">{l.other_case_id}</div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-[#0B1F3A] px-1.5 py-0.5 text-[10px] uppercase text-[#9AA7BD]">
                  {l.other_is_historical ? "historical" : "live"}
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wide">{l.status}</span>
              </div>
            </div>
            <div className="mt-1 h-1 w-full rounded bg-[#0B1F3A]">
              <div className="h-1 rounded bg-current" style={{ width: `${Math.round(l.score * 100)}%` }} />
            </div>
            {l.historical_summary && (
              <div className="mt-1 text-[11px] text-[#7C8AA3]">
                {l.historical_summary.location} · {l.historical_summary.period?.slice(0, 10)}
                {l.historical_summary.mo_category ? ` · ${l.historical_summary.mo_category.replace(/_/g, " ")}` : ""}
              </div>
            )}
            <ul className="mt-2 space-y-0.5 text-[11px] text-[#C9D2E0]">
              {l.evidence.slice(0, 4).map((s, i) => (
                <li key={i} className={s.hard ? "font-medium" : ""}>• {describe(s, label)}</li>
              ))}
            </ul>
            {l.status === "probable" && (
              <div className="mt-2 flex gap-2">
                <button onClick={() => onDecide(l.other_case_id, "verify")}
                  className="flex-1 rounded bg-verified px-2 py-1 text-xs font-medium text-[#0B1F3A] hover:opacity-90">
                  Verify link
                </button>
                <button onClick={() => onDecide(l.other_case_id, "dismiss")}
                  className="flex-1 rounded border border-[#2C4266] px-2 py-1 text-xs text-[#E7ECF3] hover:bg-[#1D3157]">
                  Dismiss
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
