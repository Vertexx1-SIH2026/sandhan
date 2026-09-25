import { useState } from "react";

function strip(id) {
  return (id || "").replace(/^[A-Z]+:/, "");
}

export default function AlertsPanel({ sbertAlerts = [], predictedLinks = [], onVerify, onDismiss, onFocus, labelFor }) {
  const [open, setOpen] = useState(null);
  const label = labelFor || strip;
  const totalCount = sbertAlerts.length + predictedLinks.length;

  return (
    <div className="flex-1 overflow-y-auto p-3">
      {totalCount === 0 && (
        <p className="mt-4 px-2 text-sm text-[#6C7C97]">
          No alerts yet. Run link prediction, or ingest an FIR to get M.O. matches against the historical database.
        </p>
      )}

      {predictedLinks.map((link) => (
        <div key={link.node_id || `${link.source}__${link.target}`} className="mb-3 rounded-md border border-signal/40 bg-signal/10 p-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-signal">
            Predicted link &middot; unverified
          </div>
          <button onClick={() => onFocus && onFocus(link.source)} className="mono text-left text-xs text-[#E7ECF3] hover:underline">
            {label(link.source)} &harr; {label(link.target)}
          </button>
          <div className="mt-1 text-xs text-[#9AA7BD]">
            {link.shared_neighbors} shared neighbour(s)
            {link.via?.length ? `: ${link.via.slice(0, 3).map(label).join(", ")}` : ""} &middot; score {link.score}
            {link.cross_case ? " · crosses cases" : ""}
          </div>
          <div className="mt-2 flex gap-2">
            <button onClick={() => onVerify(link)}
              className="flex-1 rounded bg-signal/90 px-2 py-1 text-xs font-medium text-[#0B1F3A] hover:bg-signal">
              Verify intelligence node
            </button>
            <button onClick={() => onDismiss(link)}
              className="rounded border border-[#2C4266] px-2 py-1 text-xs text-[#E7ECF3] hover:bg-[#1D3157]">
              Dismiss
            </button>
          </div>
        </div>
      ))}

      {sbertAlerts.map((alert, i) => (
        <div key={`sb-${i}`} className="mb-3 rounded-md border border-[#2C4266] bg-[#122544] p-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#7C8AA3]">
            M.O. match &middot; advisory
          </div>
          <div className="text-xs text-[#E7ECF3]">
            Resembles {alert.case_id || alert.case_fir_id}
            {alert.historical ? " (historical)" : ""} &middot; similarity {(alert.similarity * 100).toFixed(1)}%
          </div>
          {alert.mo_category && (
            <div className="text-[11px] text-[#7C8AA3]">{alert.mo_category.replace(/_/g, " ")}</div>
          )}
          <p className={`mt-1 text-xs text-[#9AA7BD] ${open === i ? "" : "line-clamp-2"}`}>{alert.excerpt}</p>
          <button onClick={() => setOpen(open === i ? null : i)}
            className="mt-2 w-full rounded border border-[#2C4266] px-2 py-1 text-xs font-medium text-[#E7ECF3] hover:bg-[#1D3157]">
            {open === i ? "Collapse" : "View"}
          </button>
        </div>
      ))}
    </div>
  );
}
