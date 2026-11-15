"""sailab/critical_links.py (Sugiura and Kurauchi 2023) on small networks with known answers, starting
with the paper's own Figure 2 example."""
from __future__ import annotations

import random
from itertools import combinations

import pytest

from sailab import critical_links as cl
from sailab.network import RoadGraph, find_bridges


def _paper_figure_2():
    """paper, Figure 2: directed links s-a, s-b, a-t, a-b, b-c, b-d, c-d, d-t, each capacity 1."""
    net = cl.FlowNetwork()
    for i, j in [("s", "a"), ("s", "b"), ("a", "t"), ("a", "b"), ("b", "c"), ("b", "d"), ("c", "d"), ("d", "t")]:
        net.add_link(i, j)
    return net


def test_figure_2_has_lec_2():
    assert cl.max_flow(_paper_figure_2(), "s", "t") == 2


def test_figure_2_has_exactly_the_three_minimum_cuts_the_paper_lists():
    net = _paper_figure_2()
    cl.max_flow(net, "s", "t")
    cuts = cl.minimum_cuts(net, "s", "t")
    expected = [{("s", "a"), ("s", "b")}, {("s", "a"), ("d", "t")}, {("a", "t"), ("d", "t")}]
    assert sorted(map(sorted, cuts)) == sorted(map(sorted, expected))


def test_figure_2_cuts_do_not_depend_on_which_optimal_flow_was_found():
    """paper: "the algorithm can locate the minimum cut irrespective of the uniqueness of the flow"."""
    net = _paper_figure_2()
    cl.max_flow(net, "s", "t")
    first = cl.minimum_cuts(net, "s", "t")
    if net.flow[("b", "d")] == 1:                        # move the flow b-d onto b-c-d, the other optimum
        net.flow[("b", "d")], net.flow[("b", "c")], net.flow[("c", "d")] = 0, 1, 1
    second = cl.minimum_cuts(net, "s", "t")
    assert sorted(map(sorted, first)) == sorted(map(sorted, second))


def test_complementary_graph_turns_round_only_links_with_flow():
    net = cl.FlowNetwork()
    net.add_link("a", "b")
    net.add_link("b", "c")
    net.flow[("a", "b")] = 1
    graph = cl.complementary_graph(net)
    assert "a" in graph["b"] and "b" not in graph["a"]   # carries flow: turned round (equation 6)
    assert "c" in graph["b"]                             # no flow: kept


# --- two-way roads ---------------------------------------------------------------------------------------
def test_a_village_on_one_road_has_lec_1_and_that_road_is_the_set():
    roads = [("town", "x"), ("x", "village")]
    lec, sets = cl.critical_link_sets(roads, ["town"], "village")
    assert lec == 1
    assert sorted(map(sorted, sets)) == sorted(map(sorted, [{frozenset({"town", "x"})}, {frozenset({"x", "village"})}]))


def test_a_village_with_two_separate_roads_needs_two_lost_and_lists_every_pair():
    # Two routes from town to the village: town-a-village and town-b-village.
    roads = [("town", "a"), ("a", "village"), ("town", "b"), ("b", "village")]
    lec, sets = cl.critical_link_sets(roads, ["town"], "village")
    assert lec == 2
    assert len(sets) == 4                                # one road from each route: 2 x 2 choices
    assert all(len(s) == 2 for s in sets)


def test_any_of_several_supporting_bases_is_enough():
    roads = [("town1", "village"), ("town2", "village")]
    lec, sets = cl.critical_link_sets(roads, ["town1", "town2"], "village")
    assert lec == 2 and sets == [{frozenset({"town1", "village"}), frozenset({"town2", "village"})}]


def test_an_already_cut_off_village_has_lec_0():
    assert cl.critical_link_sets([("town", "x"), ("y", "village")], ["town"], "village") == (0, [])


def _cuts_off(roads, removed, supporting, village):
    """Brute force: does losing these roads leave no route from any supporting base to the village?"""
    left = [r for r in roads if frozenset(r) not in removed]
    reached, todo = set(supporting), list(supporting)
    while todo:
        n = todo.pop()
        for a, b in left:
            for x, y in ((a, b), (b, a)):
                if x == n and y not in reached:
                    reached.add(y)
                    todo.append(y)
    return village not in reached


def test_matches_brute_force_on_random_small_road_networks():
    """Every set listed really cuts the village off, no smaller set does, and no set of that size is missed."""
    rng = random.Random(11)
    for trial in range(60):
        junctions = list(range(7))
        possible = list(combinations(junctions, 2))
        roads = rng.sample(possible, rng.randint(6, 12))
        lec, sets = cl.critical_link_sets(roads, [0], 6)
        all_roads = {frozenset(r) for r in roads}
        smallest = next((k for k in range(0, len(all_roads) + 1)
                         if any(_cuts_off(roads, set(c), [0], 6) for c in combinations(all_roads, k))), None)
        assert lec == smallest, f"trial {trial}"
        if lec:
            brute = [set(c) for c in combinations(all_roads, lec) if _cuts_off(roads, set(c), [0], 6)]
            assert sorted(map(sorted, map(lambda s: [tuple(sorted(r)) for r in s], sets))) == \
                   sorted(map(sorted, map(lambda s: [tuple(sorted(r)) for r in s], brute))), f"trial {trial}"


def test_a_road_in_a_set_of_size_1_is_a_bridge():
    """With LEC 1 the critical sets are single roads, and those must be bridges (Tarjan) on the route."""
    roads = [("town", "a"), ("a", "b"), ("b", "a2"), ("a2", "a"), ("b", "village")]
    lec, sets = cl.critical_link_sets(roads, ["town"], "village")
    graph = RoadGraph()
    for a, b in roads:
        graph.add_edge(a, b)
    assert lec == 1
    assert {next(iter(s)) for s in sets} <= find_bridges(graph)


def test_the_village_cannot_be_its_own_helper():
    with pytest.raises(ValueError):
        cl.critical_link_sets([("a", "b")], ["b"], "b")
