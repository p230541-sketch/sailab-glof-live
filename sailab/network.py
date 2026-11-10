"""RoadGraph and bridge finding (FR-23): which roads, if lost, would cut off a settlement.

An edge (road) is a bridge if removing it disconnects the graph. Tarjan's
algorithm finds every bridge in one pass (Tarjan, 1974): a depth-first search
that tracks, for each node, the earliest-discovered node reachable from it
through a back edge. Written iteratively (an explicit stack rather than
recursive calls) so it scales to a road network larger than Python's
recursion limit would allow.

The newer method is also here: chain decomposition (Schmidt, 2013, "A simple test on 2-vertex- and
2-edge-connectivity", Information Processing Letters 113(7), 241-244). It finds the same bridges, and
each of its steps can be drawn on paper: see chain_decomposition().
"""
from __future__ import annotations
from collections import defaultdict
from typing import Iterator


class RoadGraph:
    """An undirected graph of road junctions and the road segments between them."""

    def __init__(self) -> None:
        self.adjacency: dict[str, list[str]] = defaultdict(list)

    def add_edge(self, u: str, v: str) -> None:
        self.adjacency[u].append(v)
        self.adjacency[v].append(u)

    def neighbours(self, u: str) -> list[str]:
        return self.adjacency[u]

    def nodes(self) -> list[str]:
        return list(self.adjacency.keys())


def find_bridges(graph: RoadGraph) -> set[frozenset[str]]:
    """Every bridge in the graph, each returned as a frozenset({u, v}) so direction does not matter."""
    discovery_time: dict[str, int] = {}
    low_link: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    bridges: set[frozenset[str]] = set()
    timer = 0

    for start in graph.nodes():
        if start in discovery_time:
            continue
        # Each stack frame is (node, iterator over its neighbours, parent); the
        # iterator's position is what lets this resume a partly-visited node.
        stack: list[tuple[str, Iterator[str], str | None]] = [(start, iter(graph.neighbours(start)), None)]
        discovery_time[start] = low_link[start] = timer
        timer += 1
        parent[start] = None

        while stack:
            node, neighbour_iter, _ = stack[-1]
            advanced = False
            for neighbour in neighbour_iter:
                if neighbour == parent.get(node):
                    continue  # do not walk straight back along the edge we arrived on
                if neighbour not in discovery_time:
                    discovery_time[neighbour] = low_link[neighbour] = timer
                    timer += 1
                    parent[neighbour] = node
                    stack.append((neighbour, iter(graph.neighbours(neighbour)), node))
                    advanced = True
                    break
                else:
                    low_link[node] = min(low_link[node], discovery_time[neighbour])
            if advanced:
                continue

            stack.pop()
            if stack:
                child = node
                top_node = stack[-1][0]
                low_link[top_node] = min(low_link[top_node], low_link[child])
                if low_link[child] > discovery_time[top_node]:
                    bridges.add(frozenset({top_node, child}))

    return bridges


# ---------------------------------------------------------------------------
# Chain decomposition (Schmidt, 2013): the newer way to find the same bridges
# ---------------------------------------------------------------------------
def chain_decomposition(graph: RoadGraph) -> list[list[str]]:
    """Split the graph's cycles into "chains" (Schmidt 2013, Section 2). Each chain is a list of junctions.

    The paper's procedure, step by step:
      1. Depth-first search. Each junction gets a number in the order it is first reached (its DFI,
         depth-first index). The roads the search walked along are "tree edges"; every other road is a
         "backedge", and it always joins a junction to one of its own descendants in the search tree.
      2. Mark every junction unvisited.
      3. Take the junctions in ascending DFI order. For every backedge that starts at junction v (v is
         the end nearer the root): walk along the backedge, then up the tree towards the root, marking
         each junction visited, and stop at the first junction that is already visited. The junctions
         walked, in order, are one chain. A chain is a closed loop or an open path.

    Why it works: a backedge plus the tree path between its two ends is a closed loop, so every road on
    it has another way round. A road that no chain ever walks is on no loop at all.

    The paper assumes one connected graph. A road network can be in several pieces, so here the same
    procedure is run once per piece (a bridge is decided inside its own piece, so nothing changes).
    Like find_bridges, this treats the graph as simple: two parallel roads between the same two
    junctions count as one road.
    """
    dfi: dict[str, int] = {}                 # depth-first index of each junction
    parent: dict[str, str | None] = {}       # the junction the search came from (None for a root)
    order: list[str] = []                    # junctions in ascending DFI order

    for root in graph.nodes():
        if root in dfi:
            continue
        dfi[root] = len(order)
        parent[root] = None
        order.append(root)
        stack: list[tuple[str, Iterator[str]]] = [(root, iter(graph.neighbours(root)))]
        while stack:
            node, neighbour_iter = stack[-1]
            for neighbour in neighbour_iter:
                if neighbour not in dfi:
                    dfi[neighbour] = len(order)
                    parent[neighbour] = node
                    order.append(neighbour)
                    stack.append((neighbour, iter(graph.neighbours(neighbour))))
                    break
            else:
                stack.pop()

    visited: set[str] = set()
    chains: list[list[str]] = []
    for v in order:
        for w in graph.neighbours(v):
            # A backedge starting at v: w was reached later than v, and not along the road v-w itself.
            if dfi[w] <= dfi[v] or parent[w] == v:
                continue
            visited.add(v)
            chain = [v]
            current: str | None = w
            while current is not None:
                chain.append(current)
                if current in visited:
                    break                    # stop at the first junction that is already visited
                visited.add(current)
                current = parent[current]    # one step up the tree, towards the root
            chains.append(chain)
    return chains


def find_bridges_by_chains(graph: RoadGraph) -> set[frozenset[str]]:
    """Every bridge, found with chain decomposition: a road is a bridge exactly when no chain contains it
    (Schmidt 2013, Lemma 4). Must always equal find_bridges(), which uses Tarjan's method."""
    in_a_chain: set[frozenset[str]] = set()
    for chain in chain_decomposition(graph):
        for a, b in zip(chain, chain[1:]):
            in_a_chain.add(frozenset({a, b}))
    all_roads = {frozenset({u, v}) for u in graph.nodes() for v in graph.neighbours(u) if u != v}
    return all_roads - in_a_chain
