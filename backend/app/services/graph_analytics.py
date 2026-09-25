"""
Stage 4 -- analytics over the case NETWORK (the case + its linked historical
and live cases, see case_graph.py).

Algorithms 1-5 measure the confirmed graph (deterministic, no training):
  1. Betweenness centrality   (networkx)
  2. Eigenvector centrality   (networkx; numpy fallback on non-convergence)
  3. PageRank                 (networkx, requires scipy)
  4. Louvain modularity       (python-louvain; networkx greedy fallback)
  5. Tarjan SCC + cycle search over DIRECTED money flow (TRANSFERRED edges):
     strongly connected components first, then elementary cycles inside each
     SCC up to max_depth hops, keeping cycles whose bottleneck amount (money
     that actually went all the way round) is >= threshold.

Algorithm 6 -- link prediction -- returns "predicted (unverified)" leads only.
If a trained HeteroGNN checkpoint is wired into _try_load_torch_model() it is
used; otherwise an interpretable Adamic-Adar score over 2-hop candidate pairs
(same entity type, at least one suspect-side endpoint) is used. Either way the
output must pass the HITL gate before it joins the graph.
"""
from __future__ import annotations

import networkx as nx

from app.services import case_graph

try:
    import community as community_louvain  # python-louvain
except ImportError:  # pragma: no cover
    community_louvain = None


def _rank(scores: dict[str, float], meta: dict, top_n: int) -> list[dict]:
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        {
            "entity_id": node,
            "entity_type": meta.get(node, {}).get("entity_type"),
            "is_subject": meta.get(node, {}).get("is_subject"),
            "cases": meta.get(node, {}).get("cases"),
            "score": round(float(score), 6),
        }
        for node, score in ranked
    ]


def betweenness(g: nx.Graph, meta: dict, top_n: int = 25) -> list[dict]:
    if g.number_of_nodes() == 0:
        return []
    return _rank(nx.betweenness_centrality(g, normalized=True), meta, top_n)


def eigenvector(g: nx.Graph, meta: dict, top_n: int = 25) -> list[dict]:
    if g.number_of_edges() == 0:
        return []
    try:
        scores = nx.eigenvector_centrality(g, max_iter=2000, tol=1e-6)
    except (nx.PowerIterationFailedConvergence, nx.NetworkXException):
        scores = nx.eigenvector_centrality_numpy(g)
    return _rank(scores, meta, top_n)


def pagerank(g: nx.Graph, meta: dict, top_n: int = 25) -> list[dict]:
    if g.number_of_nodes() == 0:
        return []
    return _rank(nx.pagerank(g), meta, top_n)


def louvain(g: nx.Graph, meta: dict) -> list[dict]:
    if g.number_of_nodes() == 0:
        return []
    if community_louvain is not None:
        partition = community_louvain.best_partition(g, random_state=42)
    else:
        partition = {}
        for idx, comm in enumerate(nx.algorithms.community.greedy_modularity_communities(g)):
            for node in comm:
                partition[node] = idx
    grouped: dict[int, list[str]] = {}
    for node, cid in partition.items():
        grouped.setdefault(cid, []).append(node)
    out = []
    for new_id, (_cid, members) in enumerate(sorted(grouped.items(), key=lambda kv: -len(kv[1]))):
        out.append({
            "community_id": new_id,
            "size": len(members),
            "cases": sorted({c for m in members for c in meta.get(m, {}).get("cases", [])}),
            "members": [{"entity_id": m, "entity_type": meta.get(m, {}).get("entity_type")} for m in members],
        })
    return out


def smurfing_cycles_from_raw(raw: dict, max_depth: int = 5, threshold: float = 50000) -> dict:
    g, meta = case_graph.to_networkx(raw, directed=True, rel_types={"TRANSFERRED"})
    g.remove_nodes_from([n for n in list(g.nodes) if g.degree(n) == 0])
    sccs = [c for c in nx.strongly_connected_components(g) if len(c) > 1]
    cycles = []
    for scc in sccs:
        sub = g.subgraph(scc)
        for cyc in nx.simple_cycles(sub, length_bound=max_depth):
            hops = [(cyc[i], cyc[(i + 1) % len(cyc)]) for i in range(len(cyc))]
            amounts = [float(sub.edges[a, b]["amount"]) for a, b in hops]
            bottleneck = min(amounts)
            if bottleneck < threshold:
                continue
            cycles.append({
                "cycle": [{"entity_id": n, "entity_type": meta.get(n, {}).get("entity_type"),
                           "cases": meta.get(n, {}).get("cases")} for n in cyc],
                "edges": [{"from": a, "to": b, "amount": amt} for (a, b), amt in zip(hops, amounts)],
                "length": len(cyc),
                "bottleneck_amount": bottleneck,
                "total_amount": sum(amounts),
                "cases": sorted({c for n in cyc for c in meta.get(n, {}).get("cases", [])}),
            })
    cycles.sort(key=lambda c: -c["bottleneck_amount"])
    return {"cycles": cycles[:50], "scc_count": len(sccs),
            "scc_sizes": sorted((len(s) for s in sccs), reverse=True)}


def run_all(case_id: str, top_n: int = 25) -> dict:
    raw = case_graph.load_case_graph(case_id)
    g, meta = case_graph.to_networkx(raw)
    return {
        "network": {"cases": raw["cases"], "nodes": g.number_of_nodes(), "edges": g.number_of_edges()},
        "betweenness_centrality": betweenness(g, meta, top_n),
        "eigenvector_centrality": eigenvector(g, meta, top_n),
        "pagerank": pagerank(g, meta, top_n),
        "louvain_communities": louvain(g, meta),
        "smurfing_cycles": smurfing_cycles_from_raw(raw)["cycles"],
    }


def smurfing_cycles(case_id: str, max_depth: int = 5, threshold: float = 50000) -> dict:
    return smurfing_cycles_from_raw(case_graph.load_case_graph(case_id), max_depth, threshold)


# ---------------------------------------------------------------------
# Algorithm 6 -- link prediction (HITL-gated)
# ---------------------------------------------------------------------
def _try_load_torch_model():
    """Hook for a trained HeteroGNN checkpoint. Returns None -> heuristic path.
    Deliberately not faked: without a model trained on real (synthetic)
    ground truth, the transparent heuristic is the honest choice."""
    try:
        import torch  # noqa: F401
        import torch_geometric  # noqa: F401
    except ImportError:
        return None
    return None


def predict_links_from_raw(raw: dict, exclude: set[tuple[str, str]] | None = None,
                           top_k: int = 5, hub_degree: int = 60) -> list[dict]:
    exclude = exclude or set()
    g, meta = case_graph.to_networkx(raw)
    if g.number_of_nodes() < 3:
        return []
    _try_load_torch_model()

    pairs = set()
    for w in g.nodes:
        nbrs = list(g.neighbors(w))
        if len(nbrs) < 2 or len(nbrs) > hub_degree:
            continue
        for i, u in enumerate(nbrs):
            for v in nbrs[i + 1:]:
                if meta[u]["entity_type"] != meta[v]["entity_type"]:
                    continue
                if not (meta[u]["is_subject"] or meta[v]["is_subject"]):
                    continue  # victim <-> victim links are noise
                if g.has_edge(u, v):
                    continue
                a, b = sorted((u, v))
                if (a, b) in exclude:
                    continue
                pairs.add((a, b))

    scored = []
    for a, b, score in nx.adamic_adar_index(g, pairs):
        common = sorted(nx.common_neighbors(g, a, b))
        scored.append({
            "source": a,
            "source_type": meta[a]["entity_type"],
            "target": b,
            "target_type": meta[b]["entity_type"],
            "shared_neighbors": len(common),
            "via": common[:5],
            "score": round(float(score), 4),
            "method": "adamic_adar",
            "node_id": f"{a}__{b}",
            "cross_case": set(meta[a]["cases"]) != set(meta[b]["cases"]),
            "predicted_unverified": True,
        })
    scored.sort(key=lambda c: (-c["score"], -c["shared_neighbors"]))
    return scored[:top_k]


def predict_links(case_id: str, exclude: set[tuple[str, str]] | None = None, top_k: int = 5) -> list[dict]:
    return predict_links_from_raw(case_graph.load_case_graph(case_id), exclude, top_k)
