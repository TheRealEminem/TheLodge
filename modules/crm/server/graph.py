"""Graph traversal over the snapshot.

The adjacency list is held in memory and walked with BFS. For a personal CRM (thousands to hundreds of
thousands of edges) this is fast and, unlike recursive SQL over all simple paths, doesn't blow up around hub
nodes such as a large employer."""
from collections import defaultdict
from dataclasses import dataclass, field

from . import snapshot, store, views
from .schemas import Graph, GraphLink, GraphNode, GraphPath
from .summaries import subtitle_for


@dataclass
class NodeRow:
    id: str
    kind: str
    name: str
    attributes: dict
    is_self: bool


@dataclass
class EdgeRow:
    id: str
    source: str
    target: str
    kind: str
    strength: int
    ended_at: object


@dataclass
class GraphData:
    nodes: dict[str, NodeRow] = field(default_factory=dict)
    edges: dict[str, EdgeRow] = field(default_factory=dict)
    adj: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    tiers: dict[str, str] = field(default_factory=dict)

    def degree(self, node_id: str) -> int:
        return len({n for n, _ in self.adj.get(node_id, ())})

    def employer(self, node_id: str) -> str | None:
        for other, eid in self.adj.get(node_id, ()):
            e = self.edges[eid]
            if e.kind == "works_at" and e.source == node_id and e.ended_at is None:
                return self.nodes[other].name
        return None

    def to_node(self, node_id: str, depth: int | None = None) -> GraphNode:
        n = self.nodes[node_id]
        employer = self.employer(node_id) if n.kind == "person" else None
        return GraphNode(id=n.id, kind=n.kind, name=n.name, subtitle=subtitle_for(n, employer),
                         degree=self.degree(node_id), is_self=n.is_self, depth=depth, tier=self.tiers.get(node_id))

    def to_link(self, edge_id: str) -> GraphLink:
        e = self.edges[edge_id]
        return GraphLink(id=e.id, source=e.source, target=e.target, kind=e.kind, strength=e.strength)

    def subgraph(self, node_ids: set[str], depths: dict[str, int] | None = None, truncated: bool = False) -> Graph:
        depths = depths or {}
        links = [self.to_link(e.id) for e in self.edges.values() if e.source in node_ids and e.target in node_ids]
        return Graph(nodes=[self.to_node(n, depths.get(n)) for n in node_ids], links=links, truncated=truncated)


_cache: dict[frozenset | None, tuple[int, GraphData]] = {}


def load_graph(kinds: set[str] | None = None) -> GraphData:
    key = frozenset(kinds) if kinds else None
    version = store.version()
    hit = _cache.get(key)
    if hit and hit[0] == version:
        return hit[1]
    snap = snapshot.load()
    g = GraphData()
    v = views.get()
    for e in snap.entities.values():
        if not kinds or e.kind in kinds:
            g.nodes[e.id] = NodeRow(e.id, e.kind, e.name, e.attributes or {}, e.is_self)
            if e.kind == "person" and not e.is_self:
                g.tiers[e.id] = v.tier(e.id)
    for r in snap.edges:
        if r.source_id in g.nodes and r.target_id in g.nodes:
            g.edges[r.id] = EdgeRow(r.id, r.source_id, r.target_id, r.kind, r.strength, r.ended_at)
            g.adj[r.source_id].append((r.target_id, r.id))
            g.adj[r.target_id].append((r.source_id, r.id))
    _cache[key] = (version, g)
    return g


def overview(g: GraphData, max_nodes: int = 400) -> Graph:
    ids = list(g.nodes)
    truncated = len(ids) > max_nodes
    if truncated:
        ids.sort(key=lambda n: (not g.nodes[n].is_self, -g.degree(n)))
        ids = ids[:max_nodes]
    return g.subgraph(set(ids), truncated=truncated)


def ego(g: GraphData, center: str, depth: int = 2, max_nodes: int = 250) -> Graph:
    """Neighborhood of `center` out to `depth` hops, strongest ties first."""
    depths = {center: 0}
    frontier = [center]
    truncated = False
    for d in range(1, depth + 1):
        candidates: dict[str, int] = {}
        for u in frontier:
            for v, eid in g.adj.get(u, ()):
                if v in depths:
                    continue
                candidates[v] = max(candidates.get(v, 0), g.edges[eid].strength)
        ordered = sorted(candidates, key=lambda v: (-candidates[v], -g.degree(v)))
        room = max_nodes - len(depths)
        if len(ordered) > room:
            truncated = True
            ordered = ordered[:room]
        for v in ordered:
            depths[v] = d
        frontier = ordered
        if not frontier or truncated:
            break
    return g.subgraph(set(depths), depths, truncated)


def shortest_paths(g: GraphData, source: str, target: str, max_hops: int = 4, limit: int = 5,
                   through_kinds: set[str] | None = None) -> list[GraphPath]:
    """All shortest paths between two nodes, strongest first. `through_kinds` restricts which kinds may be
    intermediaries (e.g. {"person"} for warm-introduction chains)."""
    if source == target or source not in g.nodes or target not in g.nodes:
        return []

    dist = {source: 0}
    parents: dict[str, list[tuple[str, str]]] = defaultdict(list)
    frontier = [source]
    while frontier and target not in dist and dist[frontier[0]] < max_hops:
        nxt: list[str] = []
        for u in frontier:
            if u != source and through_kinds and g.nodes[u].kind not in through_kinds:
                continue
            for v, eid in g.adj.get(u, ()):
                if v not in dist:
                    dist[v] = dist[u] + 1
                    nxt.append(v)
                    parents[v].append((u, eid))
                elif dist[v] == dist[u] + 1:
                    parents[v].append((u, eid))
        frontier = nxt

    if target not in dist:
        return []

    # Walk parent pointers back from the target. Parallel edges between the same two nodes collapse to the
    # strongest one.
    best: dict[tuple[str, ...], list[str]] = {}

    def walk(node: str, nodes: list[str], edges: list[str]) -> None:
        if len(best) >= 500:
            return
        if node == source:
            key = tuple(reversed(nodes))
            path_edges = list(reversed(edges))
            if key not in best or _strength(g, path_edges) > _strength(g, best[key]):
                best[key] = path_edges
            return
        for prev, eid in parents[node]:
            walk(prev, nodes + [prev], edges + [eid])

    walk(target, [target], [])

    paths = []
    for node_ids, edge_ids in best.items():
        hops = len(edge_ids)
        paths.append(GraphPath(nodes=[g.to_node(n) for n in node_ids], links=[g.to_link(e) for e in edge_ids],
                               hops=hops, score=round(_strength(g, edge_ids) / (5 * hops), 3)))
    paths.sort(key=lambda p: -p.score)
    return paths[:limit]


def _strength(g: GraphData, edge_ids: list[str]) -> int:
    return sum(g.edges[e].strength for e in edge_ids)
