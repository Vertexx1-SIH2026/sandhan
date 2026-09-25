export default function NodeDetail({ node, onEscalate, onExpand, onClose, expanded }) {
  if (!node) {
    return <p className="mt-4 px-4 text-sm text-[#6C7C97]">Click a node on the canvas to see its details.</p>;
  }
  return (
    <div className="p-4 text-sm">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-[#7C8AA3]">{node.entity_type}</div>
          <div className="mono mt-1 break-all text-[#E7ECF3]">{node.display_value}</div>
        </div>
        <button onClick={onClose} className="text-xs text-[#7C8AA3] hover:text-[#E7ECF3]">close</button>
      </div>
      <div className="mt-3 space-y-1 text-xs text-[#9AA7BD]">
        <div>Side: {node.is_subject ? <span className="text-signal">suspect</span> : "third party"}</div>
        <div>Appears in: {(node.cases || []).join(", ")}</div>
        {node.historical_only && <div className="text-[#C9D2E0]">Known only from the historical database</div>}
        {node.luhn_valid === false && <div>IMEI check digit invalid (kept, flagged)</div>}
        {node.masked && <div className="text-alertred">Masked under DPDP Sec. 17 safeguards</div>}
      </div>
      <div className="mt-4 flex flex-col gap-2">
        <button onClick={onExpand}
          className="rounded border border-[#2C4266] px-3 py-1.5 text-xs text-[#E7ECF3] hover:bg-[#1D3157]">
          {expanded ? "Back to full network" : "Show 2-hop neighbourhood"}
        </button>
        {node.masked && (
          <button onClick={onEscalate}
            className="rounded bg-alertred/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-alertred">
            Escalate &amp; unmask (logged)
          </button>
        )}
      </div>
    </div>
  );
}
