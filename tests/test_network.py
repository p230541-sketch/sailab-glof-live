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


# --- chain decomposition (Schmidt 2013): the newer method must give the same bridges as Tarjan -----
from sailab.network import chain_decomposition, find_bridges_by_chains  # noqa: E402


def _graph(edges):
    graph = RoadGraph()
    for u, v in edges:
        graph.add_edge(u, v)
    return graph


def _roads(chain):
    return [frozenset(pair) for pair in zip(chain, chain[1:])]


def test_chains_on_a_triangle_with_a_tail_give_the_same_bridges_as_tarjan():
    graph = _graph([("A", "B"), ("B", "C"), ("C", "A"), ("C", "D"), ("D", "E")])
    chains = chain_decomposition(graph)
    assert len(chains) == 1                                          # one chain: the triangle
    assert chains[0][0] == chains[0][-1] == "A" and set(chains[0]) == {"A", "B", "C"}   # a closed loop
    assert find_bridges_by_chains(graph) == {frozenset({"C", "D"}), frozenset({"D", "E"})} == find_bridges(graph)


def test_a_single_line_of_roads_has_no_chain_and_every_road_is_a_bridge():
    graph = _graph([("A", "B"), ("B", "C"), ("C", "D")])
    assert chain_decomposition(graph) == []
    assert find_bridges_by_chains(graph) == {frozenset({"A", "B"}), frozenset({"B", "C"}), frozenset({"C", "D"})}


def test_a_ring_road_has_one_chain_and_no_bridge():
    graph = _graph([("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")])
    chains = chain_decomposition(graph)
    assert len(chains) == 1 and chains[0][0] == chains[0][-1]        # the first chain is always a closed loop
    assert find_bridges_by_chains(graph) == set()


def test_two_loops_joined_by_one_road_have_exactly_that_road_as_bridge():
    graph = _graph([("A", "B"), ("B", "C"), ("C", "A"), ("C", "D"), ("D", "E"), ("E", "F"), ("F", "D")])
    assert find_bridges_by_chains(graph) == {frozenset({"C", "D"})}


def test_the_number_of_chains_is_roads_minus_junctions_plus_one():
    """Stated in the paper for a connected graph: every backedge makes exactly one chain."""
    edges = [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D"), ("D", "A"), ("D", "E")]
    graph = _graph(edges)
    assert len(chain_decomposition(graph)) == len(edges) - len(graph.nodes()) + 1


def test_no_road_is_walked_by_two_chains():
    graph = _graph([("A", "B"), ("B", "C"), ("C", "A"), ("C", "D"), ("D", "A"), ("B", "D")])
    walked = [road for chain in chain_decomposition(graph) for road in _roads(chain)]
    assert len(walked) == len(set(walked))


def test_a_network_in_two_pieces_is_handled_piece_by_piece():
    graph = _graph([("A", "B"), ("B", "C"), ("C", "A"), ("X", "Y")])
    assert find_bridges_by_chains(graph) == {frozenset({"X", "Y"})} == find_bridges(graph)


def test_chains_and_tarjan_agree_on_300_random_road_networks():
    """The check the plan asks for: both methods must give the same bridges, also on networks in pieces."""
    rng = random.Random(7)
    for trial in range(300):
        junctions = [str(i) for i in range(rng.randint(2, 14))]
        possible = [(a, b) for i, a in enumerate(junctions) for b in junctions[i + 1:]]
        edges = rng.sample(possible, rng.randint(1, min(len(possible), len(junctions) + 4)))
        graph = _graph(edges)
        assert find_bridges_by_chains(graph) == find_bridges(graph), f"trial {trial}: {edges}"
