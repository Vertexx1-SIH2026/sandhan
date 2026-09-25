import { useEffect, useRef } from "react";

export const TYPE_COLORS = {
  Phone: "#E0A22A",
  Device: "#6C8EBF",
  UPIAccount: "#2FA88A",
  BankAccount: "#3FC7A5",
  IPAddress: "#8E6CBF",
  Person: "#E7ECF3",
  Location: "#5C7A9B",
  FIR: "#C4562F",
};

const COMMUNITY_PALETTE = [
  "#E0A22A", "#2FA88A", "#6C8EBF", "#C4562F", "#8E6CBF", "#D66BA0",
  "#4FB3D9", "#A3B84C", "#E57D4F", "#7C8AA3", "#B5895A", "#5FBF7F",
];

function colorFor(type) {
  return TYPE_COLORS[type] || "#9AA7BD";
}

function inr(n) {
  if (!n) return "";
  return "Rs " + Math.round(n).toLocaleString("en-IN");
}

/**
 * Renders a Sandhan case-network snapshot on a vis-network canvas.
 *
 * props:
 *   snapshot      {nodes:[{entity_id, entity_type, display_value, cases, historical_only, is_subject, masked}],
 *                  edges:[{source, target, relation, total_amount, count, verified}]}
 *   mode          "type" | "rank" | "community"
 *   rankMap       {entity_id: 0..1}        (rank mode -> node size)
 *   communityMap  {entity_id: communityId} (community mode -> node colour)
 *   highlightIds  entity ids to ring in amber (pending predictions)
 *   focusId       entity id to select + zoom to
 *   onNodeClick   (entity_id) => void
 */
export default function GraphCanvas({
  snapshot, mode = "type", rankMap = {}, communityMap = {}, highlightIds = [], focusId = null, onNodeClick,
}) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const clickRef = useRef(onNodeClick);
  clickRef.current = onNodeClick;

  useEffect(() => {
    let destroyed = false;

    import("vis-network/standalone/esm/vis-network").then(({ Network, DataSet }) => {
      if (destroyed || !containerRef.current) return;
      const hl = new Set(highlightIds);

      const nodes = new DataSet(
        (snapshot?.nodes || []).map((n) => {
          const hist = n.historical_only;
          let size = n.is_subject ? 16 : 11;
          if (mode === "rank") size = 8 + 34 * (rankMap[n.entity_id] || 0);
          const base = mode === "community" && communityMap[n.entity_id] !== undefined
            ? COMMUNITY_PALETTE[communityMap[n.entity_id] % COMMUNITY_PALETTE.length]
            : colorFor(n.entity_type);
          const dimmed = mode === "community" && communityMap[n.entity_id] === undefined;
          return {
            id: n.entity_id,
            label: n.display_value || (n.entity_id || "").replace(/^[A-Z]+:/, ""),
            shape: hist ? "diamond" : n.entity_type === "FIR" ? "square" : "dot",
            size: hl.has(n.entity_id) ? Math.max(size, 20) : size,
            color: {
              background: dimmed ? "#2C4266" : base,
              border: hl.has(n.entity_id) ? "#E0A22A" : hist ? "#9AA7BD" : "#0B1F3A",
              highlight: { background: base, border: "#FFFFFF" },
            },
            borderWidth: hl.has(n.entity_id) ? 4 : hist ? 2 : 1,
            shapeProperties: { borderDashes: hist ? [4, 3] : false },
            opacity: hist ? 0.85 : 1,
            font: { color: hist ? "#9AA7BD" : "#E7ECF3", size: n.is_subject ? 13 : 11, face: "IBM Plex Sans" },
            title: `${n.entity_type}${n.is_subject ? " (suspect side)" : ""}\n${n.display_value}\ncases: ${(n.cases || []).join(", ")}`
              + (n.masked ? "\n[masked - DPDP]" : ""),
          };
        })
      );

      const edges = new DataSet(
        (snapshot?.edges || []).map((e, i) => {
          const verified = e.relation === "PREDICTED_LINK_VERIFIED";
          const money = e.relation === "TRANSFERRED";
          const context = e.relation === "MENTIONS" || e.relation === "ALIAS_OF";
          return {
            id: i,
            from: e.source,
            to: e.target,
            label: money ? inr(e.total_amount) : verified ? "verified link" : "",
            color: { color: verified ? "#E0A22A" : money ? "#2FA88A" : context ? "#24365a" : "#3A5075", highlight: "#E0A22A" },
            width: verified ? 3 : money ? 1.5 + Math.min(4, (e.total_amount || 0) / 25000) : 1,
            dashes: verified || context,
            font: { color: "#9AA7BD", size: 9, strokeWidth: 0, align: "middle" },
            arrows: { to: { enabled: money || e.relation === "CALLED", scaleFactor: 0.5 } },
            title: `${e.relation} x${e.count || 1}${e.total_amount ? " - " + inr(e.total_amount) : ""}`
              + (e.case_ids ? `\nfrom: ${e.case_ids.join(", ")}` : ""),
          };
        })
      );

      const options = {
        autoResize: true,
        height: "100%",
        physics: {
          stabilization: { iterations: 250 },
          barnesHut: { gravitationalConstant: -3500, springLength: 110, avoidOverlap: 0.2 },
        },
        interaction: { hover: true, tooltipDelay: 120 },
      };

      if (networkRef.current) networkRef.current.destroy();
      const network = new Network(containerRef.current, { nodes, edges }, options);
      networkRef.current = network;
      // freeze the layout once it settles -- keeps big historical networks responsive
      network.once("stabilizationIterationsDone", () => network.setOptions({ physics: false }));
      network.on("click", (params) => {
        if (params.nodes && params.nodes.length > 0 && clickRef.current) clickRef.current(params.nodes[0]);
      });
    });

    return () => {
      destroyed = true;
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot, mode, rankMap, communityMap, highlightIds.join(",")]);

  useEffect(() => {
    const net = networkRef.current;
    if (!net || !focusId) return;
    try {
      net.selectNodes([focusId]);
      net.focus(focusId, { scale: 1.3, animation: { duration: 500 } });
    } catch {
      /* node not in this view */
    }
  }, [focusId]);

  const isEmpty = !snapshot || (snapshot.nodes || []).length === 0;

  return (
    <div className="relative h-full w-full rounded-lg border border-[#1D3157] bg-[#0E2038]">
      {isEmpty && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-[#7C8AA3]">
          No graph data yet &mdash; ingest this case&apos;s files to build its network.
        </div>
      )}
      <div ref={containerRef} className="h-full w-full" />
      {!isEmpty && (
        <div className="pointer-events-none absolute bottom-2 left-2 flex flex-wrap gap-3 rounded bg-[#0B1F3A]/80 px-2 py-1 text-[10px] text-[#9AA7BD]">
          {["Phone", "Device", "UPIAccount", "BankAccount", "IPAddress"].map((t) => (
            <span key={t} className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: colorFor(t) }} />
              {t}
            </span>
          ))}
          <span>&#9670; dashed = historical case</span>
          <span className="text-signal">- - verified predicted link</span>
        </div>
      )}
    </div>
  );
}
