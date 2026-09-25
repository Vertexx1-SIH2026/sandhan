const ALGORITHMS = [
  { key: "integrated", label: "Integrated network", hint: "Case + linked historical cases" },
  { key: "betweenness", label: "Betweenness centrality", hint: "Kingpin / broker candidates" },
  { key: "eigenvector", label: "Eigenvector centrality", hint: "Influence within cluster" },
  { key: "pagerank", label: "PageRank", hint: "Overall importance" },
  { key: "louvain", label: "Louvain modularity", hint: "Gang / cluster detection" },
  { key: "smurfing", label: "Tarjan SCC + cycles", hint: "Laundering cycles" },
];

export default function AlgorithmSidebar({ active, onSelect, ranking = [], labelFor, onFocus, busy }) {
  return (
    <nav className="flex h-full w-64 flex-col gap-1 overflow-y-auto border-r border-[#1D3157] bg-[#0E1B33] p-3">
      <div className="mb-2 px-2 text-xs font-medium tracking-wide text-[#7C8AA3]">Analytics views</div>
      {ALGORITHMS.map((alg) => (
        <button
          key={alg.key}
          onClick={() => onSelect(alg.key)}
          className={`rounded-md px-3 py-2 text-left text-sm transition-colors ${
            active === alg.key ? "bg-[#1D3157] text-[#E7ECF3]" : "text-[#9AA7BD] hover:bg-[#132646] hover:text-[#E7ECF3]"
          }`}
        >
          <div>{alg.label}</div>
          <div className="text-xs text-[#6C7C97]">{alg.hint}</div>
        </button>
      ))}
      {busy && <div className="px-3 py-2 text-xs text-[#7C8AA3]">Running...</div>}
      {ranking.length > 0 && (
        <div className="mt-3 border-t border-[#1D3157] pt-3">
          <div className="mb-2 px-2 text-xs font-medium text-[#7C8AA3]">Top 10</div>
          {ranking.slice(0, 10).map((r, i) => (
            <button key={r.key || r.entity_id} onClick={() => onFocus && onFocus(r.entity_id)}
              className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs text-[#C9D2E0] hover:bg-[#132646]">
              <span className="mono truncate">{i + 1}. {r.label || (labelFor ? labelFor(r.entity_id) : r.entity_id)}</span>
              <span className="ml-2 shrink-0 text-[#7C8AA3]">{r.value}</span>
            </button>
          ))}
        </div>
      )}
    </nav>
  );
}
