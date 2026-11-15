"""Critical link sets: the smallest groups of roads that, if all lost, cut a village off.

Sugiura and Kurauchi (2023), "Isolation vulnerability analysis in road network: Edge connectivity and
critical link sets", Transportation Research Part D 119, 103768, section 3. "paper:" notes point at the
equation or step used.

The idea in plain words. Bridge finding (Tarjan, or chain decomposition) answers "which SINGLE road, if lost,
cuts something off". A village reached by two roads has no such road, yet losing both cuts it off. This
finds, for one village:
  - its local edge connectivity (LEC): the smallest number of roads that must all fail before the village
    is cut off from help (paper, section 3.1); 1 means one bridge road is enough;
  - every set of exactly that many roads whose loss cuts it off: the "critical link sets" (section 3.4).

How (paper, sections 3.2 and 3.4):
  1. Give every road a capacity of 1 and find the maximum flow from the helpers ("supporting bases") to the
     village ("receiving base"). By Menger's theorem the flow equals the LEC (equations 1 to 5).
  2. Build the "complementary" graph (equation 6): a link that carries flow is turned round, one that does
     not keeps its direction.
  3. Split that graph into strongly connected components (groups where every node reaches every other).
  4. Every way of choosing a side X that holds the helpers, not the village, and is "closed" (whenever a
     component is in X, every component it points to is in X too) gives one minimum cut: the roads leaving
     X. This is Picard and Queyranne's (1980) result, which the paper uses.

Roads here are two-way: each road becomes two links, one each way, as the paper does for a road network.
The dummy source joined to every helper uses one link of large capacity, which the paper allows ("it is
possible to connect one link each with a positive large integer capacity", section 3.3).
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Hashable, Iterable

Node = Hashable
SOURCE = ("__source__",)        # dummy start node joined to every supporting base
SINK = ("__sink__",)            # dummy end node (only used when several receiving nodes are given)
LARGE = 10 ** 9                 # capacity of the dummy links: never part of a minimum cut
MAX_CUTS = 10_000               # stop listing after this many (a guard of ours; the count can grow fast)


class FlowNetwork:
    """Directed links with integer capacities, and the flow on each."""

    def __init__(self) -> None:
        self.capacity: dict[tuple[Node, Node], int] = defaultdict(int)
        self.flow: dict[tuple[Node, Node], int] = defaultdict(int)
        self.out: dict[Node, set[Node]] = defaultdict(set)

    def add_link(self, i: Node, j: Node, capacity: int = 1) -> None:
        self.capacity[(i, j)] += capacity
        self.out[i].add(j)
        self.out[j].add(i)              # so the search can also go back along a link that carries flow

    def residual(self, i: Node, j: Node) -> int:
        """How much more can go from i to j: spare capacity on (i, j) plus flow on (j, i) that can be undone."""
        return self.capacity[(i, j)] - self.flow[(i, j)] + self.flow[(j, i)]

    def push(self, i: Node, j: Node, amount: int) -> None:
        undo = min(amount, self.flow[(j, i)])   # first cancel flow coming the other way
        self.flow[(j, i)] -= undo
        self.flow[(i, j)] += amount - undo


def max_flow(net: FlowNetwork, s: Node, t: Node) -> int:
    """paper: equations (1) to (5), the maximum number of link-disjoint paths from s to t, found by
    repeatedly finding a shortest path with spare capacity (breadth-first search) and sending flow along it."""
    total = 0
    while True:
        came_from = {s: None}
        queue = deque([s])
        while queue and t not in came_from:
            i = queue.popleft()
            for j in net.out[i]:
                if j not in came_from and net.residual(i, j) > 0:
                    came_from[j] = i
                    queue.append(j)
        if t not in came_from:
            return total
        path, j = [], t
        while came_from[j] is not None:
            path.append((came_from[j], j))
            j = came_from[j]
        amount = min(net.residual(i, j) for i, j in path)
        for i, j in path:
            net.push(i, j, amount)
        total += amount


def complementary_graph(net: FlowNetwork) -> dict[Node, set[Node]]:
    """paper: equation (6). e((i, j)) = (j, i) if the link carries flow, otherwise (i, j). Written for
    integer capacities: (i, j) stays while it has spare capacity, and (j, i) appears while it carries flow;
    for the unit-capacity road links that is exactly equation (6)."""
    graph: dict[Node, set[Node]] = defaultdict(set)
    for (i, j), cap in list(net.capacity.items()):
        net_flow = net.flow[(i, j)] - net.flow[(j, i)]
        if net_flow < cap:
            graph[i].add(j)
        if net_flow > 0:
            graph[j].add(i)
        graph.setdefault(i, set())
        graph.setdefault(j, set())
    return graph


def strongly_connected_components(graph: dict[Node, set[Node]]) -> dict[Node, int]:
    """paper, step 2. {node: component number}, by Tarjan's method, written with an explicit stack."""
    index: dict[Node, int] = {}
    low: dict[Node, int] = {}
    on_stack: set[Node] = set()
    stack: list[Node] = []
    component: dict[Node, int] = {}
    counter = 0
    for root in graph:
        if root in index:
            continue
        work = [(root, iter(graph[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(graph[child])))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                number = len(set(component.values()))
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component[member] = number
                    if member == node:
                        break
    return component


def minimum_cuts(net: FlowNetwork, s: Node, t: Node) -> list[set[tuple[Node, Node]]]:
    """paper: section 3.4, steps 2 to 4. Every minimum cut, as a set of directed links (i, j) from the s side
    to the t side. Call after max_flow()."""
    graph = complementary_graph(net)
    comp = strongly_connected_components(graph)
    dag: dict[int, set[int]] = defaultdict(set)              # step 3: components joined, links between them kept
    for i, targets in graph.items():
        for j in targets:
            if comp[i] != comp[j]:
                dag[comp[i]].add(comp[j])

    def reach(start: int, edges: dict[int, set[int]]) -> set[int]:
        seen, todo = {start}, [start]
        while todo:
            for nxt in edges.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen

    reverse: dict[int, set[int]] = defaultdict(set)
    for a, targets in dag.items():
        for b in targets:
            reverse[b].add(a)
    must_in = reach(comp[s], dag)          # step 4: s and everything it points to (Vs with its successors)
    must_out = reach(comp[t], reverse)     # t and everything that points to it (Vt with its predecessors)
    free = sorted(set(comp.values()) - must_in - must_out)

    # Every closed choice of the free components (if one is in X, all it points to are in X), as in the
    # paper's binary tree: components further downstream are decided first.
    order = _downstream_first(free, dag)
    choices: list[set[int]] = []

    def extend(position: int, chosen: set[int]) -> None:
        if len(choices) >= MAX_CUTS:
            return
        if position == len(order):
            choices.append(set(chosen))
            return
        component = order[position]
        extend(position + 1, chosen)                                     # leave it out
        if all(nxt in chosen or nxt in must_in for nxt in dag.get(component, ())):
            extend(position + 1, chosen | {component})                    # put it in (allowed: closed)

    extend(0, set())
    nodes_of: dict[int, set[Node]] = defaultdict(set)
    for node, number in comp.items():
        nodes_of[number].add(node)
    cuts = []
    for chosen in choices:
        side = set().union(*(nodes_of[c] for c in must_in | chosen))
        cuts.append({(i, j) for (i, j), cap in net.capacity.items() if cap > 0 and i in side and j not in side})
    return cuts


def _downstream_first(components: list[int], dag: dict[int, set[int]]) -> list[int]:
    """Order components so that every component comes after all the components it points to."""
    wanted, ordered, seen = set(components), [], set()

    def visit(c: int) -> None:
        if c in seen:
            return
        seen.add(c)
        for nxt in dag.get(c, ()):
            if nxt in wanted:
                visit(nxt)
        ordered.append(c)

    for c in components:
        visit(c)
    return ordered


def critical_link_sets(roads: Iterable[tuple[Node, Node]], supporting: Iterable[Node],
                       receiving: Node) -> tuple[int, list[set[frozenset]]]:
    """For one village: (LEC, every smallest set of roads whose loss cuts it off from all supporting bases).
    Each road is (junction, junction) and two-way; each set holds roads as frozenset({a, b})."""
    net = FlowNetwork()
    road_list = [(a, b) for a, b in roads if a != b]
    for a, b in road_list:
        net.add_link(a, b)
        net.add_link(b, a)
    for base in supporting:
        if base == receiving:
            raise ValueError("the receiving base cannot also be a supporting base")
        net.add_link(SOURCE, base, LARGE)
    lec = max_flow(net, SOURCE, receiving)
    if lec == 0:
        return 0, []
    sets = []
    for cut in minimum_cuts(net, SOURCE, receiving):
        roads_cut = {frozenset(link) for link in cut}
        if roads_cut not in sets:
            sets.append(roads_cut)
    return lec, sets
