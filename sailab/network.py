"""RoadGraph and bridge finding (FR-23): which roads, if lost, would cut off a settlement.

An edge (road) is a bridge if removing it disconnects the graph. Tarjan's
algorithm finds every bridge in one pass (Tarjan, 1974): a depth-first search
that tracks, for each node, the earliest-discovered node reachable from it
through a back edge. Written iteratively (an explicit stack rather than
recursive calls) so it scales to a road network larger than Python's
recursion limit would allow.
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
