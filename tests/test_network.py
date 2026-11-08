"""Tests for sailab.network, matching the Test Case Register."""
import random
from sailab.network import RoadGraph, find_bridges


def test_TC_NET_01_tarjan_finds_the_bridges():
    """Given a triangle A-B-C, then the roads C-D and D-E, the bridges are C-D and D-E."""
    graph = RoadGraph()
    for u, v in [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D"), ("D", "E")]:
        graph.add_edge(u, v)

    bridges = find_bridges(graph)

    assert bridges == {frozenset({"C", "D"}), frozenset({"D", "E"})}


def test_bridges_match_networkx_reference_on_random_graphs():
    """Reference check (Test Plan, Section 3.4): our bridges should match NetworkX's on the same graph,
    across several random road networks, not just the one hand-built example."""
    import networkx as nx

    random.seed(1)
    for trial in range(20):
        node_count = random.randint(4, 12)
        nx_graph = nx.gnm_random_graph(node_count, random.randint(node_count - 1, node_count + 3), seed=trial)
        if not nx.is_connected(nx_graph):
            continue  # bridges are only meaningful within one connected road network

        ours = RoadGraph()
        for u, v in nx_graph.edges():
            ours.add_edge(str(u), str(v))

        our_bridges = find_bridges(ours)
        reference_bridges = {frozenset({str(u), str(v)}) for u, v in nx.bridges(nx_graph)}

        assert our_bridges == reference_bridges, f"trial {trial}: {nx_graph.edges()}"
