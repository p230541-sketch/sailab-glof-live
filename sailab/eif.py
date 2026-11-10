"""Extended Isolation Forest, written out step by step from the paper.

Hariri, Carrasco Kind and Brunner, "Extended Isolation Forest", IEEE Transactions on Knowledge and Data
Engineering 33(4), 1479-1489, 2021 (read from the authors' arXiv copy, 1811.02141). Every numbered
"paper:" note below points at the equation or algorithm line it implements.

The idea in plain words. Cut the data in two with a random straight line, then cut each half again, and
so on, until every point sits alone. A point that is far from the others ends up alone after very few
cuts; a point in the middle of a crowd needs many. So "how many cuts until this point is alone",
averaged over many random trees, tells how unusual the point is. Fewer cuts = more unusual.

What "extended" changes. The older Isolation Forest only cuts straight up-and-down or left-to-right
(one feature at a time), which leaves stripe-shaped artefacts in the scores. The extended version cuts
along a line with a random slope, which removes them.

No library does the work here: plain Python lists and the random module, so each line can be explained.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from math import ceil, log, log2

EULER_CONSTANT = 0.5772156649          # paper: text under equation (2)

Point = tuple[float, ...]


@dataclass(frozen=True)
class ExternalNode:
    """A leaf: where the cutting stopped. size = how many training points were left here."""
    size: int


@dataclass(frozen=True)
class InternalNode:
    """One cut: a random direction (normal) through a random point (intercept)."""
    left: "ExternalNode | InternalNode"
    right: "ExternalNode | InternalNode"
    normal: Point
    intercept: Point


def c_factor(n: int) -> float:
    """paper: equation (2). c(n) = 2 H(n-1) - 2(n-1)/n, with H(i) estimated by ln(i) + Euler's constant.

    This is the average depth of an unsuccessful search in a binary search tree of n points: the "usual"
    number of cuts for n points, used to put scores from different sample sizes on one scale.
    The equation needs n >= 2 (ln(0) does not exist). For n <= 1 this returns 0: a leaf holding one point,
    or none, needs no further cuts. That case is our own stated choice; the paper does not write it out.
    """
    if n <= 1:
        return 0.0
    return 2.0 * (log(n - 1) + EULER_CONSTANT) - 2.0 * (n - 1) / n


def _dot_from_intercept(x: Point, intercept: Point, normal: Point) -> float:
    """(x - p) . n : which side of the cut the point x is on (paper: inequality (3))."""
    return sum((xi - pi) * ni for xi, pi, ni in zip(x, intercept, normal))


def build_tree(points: list[Point], height: int, height_limit: int, rng: random.Random,
               extension_level: int) -> ExternalNode | InternalNode:
    """paper: Algorithm 2, iTree(X, e, l). The line numbers in the comments are the paper's."""
    if height >= height_limit or len(points) <= 1:                      # line 1
        return ExternalNode(size=len(points))                           # line 2
    dimensions = len(points[0])
    normal = [rng.gauss(0.0, 1.0) for _ in range(dimensions)]           # line 4: each coordinate from N(0, 1)
    intercept = tuple(rng.uniform(min(p[d] for p in points), max(p[d] for p in points))
                      for d in range(dimensions))                       # line 5: inside the range of X at this node
    # line 6: "set coordinates of n to zero according to extension level". Full extension is level
    # dimensions - 1 (nothing zeroed); level 0 leaves one coordinate, which is the standard Isolation Forest.
    for d in rng.sample(range(dimensions), dimensions - 1 - extension_level):
        normal[d] = 0.0
    normal_t = tuple(normal)
    left = [p for p in points if _dot_from_intercept(p, intercept, normal_t) <= 0]    # line 7
    right = [p for p in points if _dot_from_intercept(p, intercept, normal_t) > 0]    # line 8
    return InternalNode(left=build_tree(left, height + 1, height_limit, rng, extension_level),   # line 9
                        right=build_tree(right, height + 1, height_limit, rng, extension_level),
                        normal=normal_t, intercept=intercept)


def path_length(x: Point, tree: ExternalNode | InternalNode) -> float:
    """paper: Algorithm 3, PathLength(x, T, e). How many cuts the point x passes before reaching a leaf,
    plus c(size) for the points the leaf still holds (they would have needed about that many more cuts).
    Written as a loop instead of the paper's recursion; the steps are the same."""
    depth = 0
    node = tree
    while isinstance(node, InternalNode):
        node = node.left if _dot_from_intercept(x, node.intercept, node.normal) <= 0 else node.right
        depth += 1
    return depth + c_factor(node.size)


class ExtendedIsolationForest:
    """paper: Algorithm 1, iForest(X, t, psi): t trees, each built from a random sub-sample of size psi."""

    def __init__(self, n_trees: int, sample_size: int, extension_level: int | None = None, seed: int = 0) -> None:
        self.n_trees = n_trees                    # t
        self.sample_size = sample_size            # psi (the size asked for)
        self.extension_level = extension_level    # None = fully extended (dimensions - 1)
        self.seed = seed
        self.trees: list[ExternalNode | InternalNode] = []
        self.points_per_tree = 0                  # the n of equations (1) and (2)

    def fit(self, points: list[Point]) -> "ExtendedIsolationForest":
        if len(points) < 2:
            raise ValueError("an isolation forest needs at least 2 points")
        dimensions = len(points[0])
        level = dimensions - 1 if self.extension_level is None else self.extension_level
        if not 0 <= level <= dimensions - 1:
            raise ValueError(f"extension level must be between 0 and {dimensions - 1}, got {level}")
        rng = random.Random(self.seed)            # fixed seed: the same data always gives the same forest
        self.points_per_tree = min(self.sample_size, len(points))
        height_limit = ceil(log2(self.points_per_tree))                 # Algorithm 1, line 2
        self.trees = [
            build_tree(rng.sample(points, self.points_per_tree), 0, height_limit, rng, level)   # lines 3-5
            for _ in range(self.n_trees)
        ]
        return self

    def mean_path_length(self, x: Point) -> float:
        """E(h(x)) in equation (1): the average depth x reaches over all trees."""
        return sum(path_length(x, tree) for tree in self.trees) / len(self.trees)

    def anomaly_score(self, x: Point) -> float:
        """paper: equation (1). s(x, n) = 2 ** ( -E(h(x)) / c(n) ), always between 0 and 1.
        Near 1 = alone after very few cuts (unusual). Around 0.5 or below = as deep as an ordinary point."""
        if not self.trees:
            raise ValueError("fit() must be called before scoring")
        return 2.0 ** (-self.mean_path_length(x) / c_factor(self.points_per_tree))
