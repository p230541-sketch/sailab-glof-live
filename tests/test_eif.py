"""sailab/eif.py: Extended Isolation Forest (Hariri et al. 2021) on small made-up data with known answers."""
from __future__ import annotations

import random
from math import log

import pytest

from sailab import eif
from sailab.eif import ExtendedIsolationForest, ExternalNode, InternalNode


# --- equation (2): c(n) ---------------------------------------------------------------------------
def test_c_factor_matches_equation_2_worked_by_hand():
    # n = 2:   2 * (ln(1) + 0.5772156649) - 2 * 1 / 2   = 1.1544313298 - 1      = 0.1544313298
    assert eif.c_factor(2) == pytest.approx(0.1544313298)
    # n = 256: 2 * (ln(255) + 0.5772156649) - 2 * 255 / 256
    assert eif.c_factor(256) == pytest.approx(2 * (log(255) + 0.5772156649) - 510 / 256)
    assert eif.c_factor(256) == pytest.approx(10.2448, abs=1e-4)


def test_c_factor_is_zero_for_a_leaf_with_one_point_or_none():
    assert eif.c_factor(1) == 0.0
    assert eif.c_factor(0) == 0.0


# --- inequality (3) and Algorithm 3: which way a point goes, and how deep --------------------------
def test_path_length_follows_the_branch_rule_on_a_hand_built_tree():
    # One cut: normal (1, 0) through intercept (5, 0). (x - p) . n = x[0] - 5.
    #   x[0] <= 5 goes LEFT to a leaf with 1 point  -> depth 1 + c(1) = 1
    #   x[0] >  5 goes RIGHT to a leaf with 2 points -> depth 1 + c(2) = 1.1544313298
    tree = InternalNode(left=ExternalNode(1), right=ExternalNode(2), normal=(1.0, 0.0), intercept=(5.0, 0.0))
    assert eif.path_length((4.0, 99.0), tree) == pytest.approx(1.0)
    assert eif.path_length((5.0, -3.0), tree) == pytest.approx(1.0)          # exactly on the cut counts as left (<= 0)
    assert eif.path_length((5.1, 0.0), tree) == pytest.approx(1.1544313298)


def test_a_sloped_cut_uses_both_coordinates():
    # Normal (1, 1) through (0, 0): left when x + y <= 0.
    tree = InternalNode(left=ExternalNode(1), right=ExternalNode(1), normal=(1.0, 1.0), intercept=(0.0, 0.0))
    two_levels = InternalNode(left=tree, right=ExternalNode(1), normal=(1.0, 1.0), intercept=(10.0, 10.0))
    assert eif.path_length((1.0, -2.0), two_levels) == pytest.approx(2.0)    # left at both cuts
    assert eif.path_length((30.0, 0.0), two_levels) == pytest.approx(1.0)    # right at the first cut


# --- Algorithm 2: building a tree ----------------------------------------------------------------
def _leaf_sizes(node):
    if isinstance(node, ExternalNode):
        return [node.size]
    return _leaf_sizes(node.left) + _leaf_sizes(node.right)


def _depth(node):
    return 0 if isinstance(node, ExternalNode) else 1 + max(_depth(node.left), _depth(node.right))


def _normals(node):
    if isinstance(node, ExternalNode):
        return []
    return [node.normal] + _normals(node.left) + _normals(node.right)


POINTS = [(float(x), float(y)) for x in range(6) for y in range(6)]          # a 6 x 6 grid: 36 points


def test_every_training_point_ends_in_exactly_one_leaf():
    tree = eif.build_tree(POINTS, 0, 20, random.Random(1), extension_level=1)
    assert sum(_leaf_sizes(tree)) == len(POINTS)


def test_tree_stops_at_the_height_limit():
    tree = eif.build_tree(POINTS, 0, 3, random.Random(1), extension_level=1)
    assert _depth(tree) <= 3


def test_one_point_or_none_is_a_leaf_straight_away():
    assert eif.build_tree([(1.0, 2.0)], 0, 5, random.Random(1), 1) == ExternalNode(1)
    assert eif.build_tree([], 0, 5, random.Random(1), 1) == ExternalNode(0)


def test_extension_level_0_cuts_along_one_axis_only_like_the_standard_isolation_forest():
    tree = eif.build_tree(POINTS, 0, 6, random.Random(3), extension_level=0)
    assert all(sum(1 for value in normal if value != 0.0) == 1 for normal in _normals(tree))


def test_full_extension_uses_sloped_cuts():
    tree = eif.build_tree(POINTS, 0, 6, random.Random(3), extension_level=1)
    assert all(all(value != 0.0 for value in normal) for normal in _normals(tree))


# --- Algorithm 1 and equation (1): the forest and its score --------------------------------------
def _cluster(seed=5, n=60):
    rng = random.Random(seed)
    return [(rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)) for _ in range(n)]


def test_a_far_away_point_scores_higher_than_every_point_in_the_crowd():
    cluster = _cluster()
    outlier = (12.0, 12.0)
    forest = ExtendedIsolationForest(n_trees=100, sample_size=256, seed=11).fit(cluster + [outlier])
    far_away = forest.anomaly_score(outlier)
    assert far_away > max(forest.anomaly_score(p) for p in cluster)
    assert far_away > 0.7
    assert forest.anomaly_score((0.0, 0.0)) < 0.5                            # the middle of the crowd is ordinary


def test_a_far_away_point_that_was_not_in_the_training_data_still_scores_highest():
    """Scored from outside, the gap is smaller (cuts are only placed inside the range of the training
    data), which is why the lake scoring puts the new reading into the forest together with its history."""
    cluster = _cluster()
    forest = ExtendedIsolationForest(n_trees=100, sample_size=256, seed=11).fit(cluster)
    assert forest.anomaly_score((12.0, 12.0)) > max(forest.anomaly_score(p) for p in cluster)


def test_score_is_always_between_0_and_1():
    forest = ExtendedIsolationForest(n_trees=50, sample_size=32, seed=2).fit(_cluster())
    for point in [(0.0, 0.0), (3.0, -3.0), (1e6, -1e6)]:
        assert 0.0 < forest.anomaly_score(point) < 1.0


def test_same_seed_gives_the_same_score_and_another_seed_a_slightly_different_one():
    cluster = _cluster()
    a = ExtendedIsolationForest(50, 256, seed=4).fit(cluster).anomaly_score((5.0, 5.0))
    b = ExtendedIsolationForest(50, 256, seed=4).fit(cluster).anomaly_score((5.0, 5.0))
    c = ExtendedIsolationForest(50, 256, seed=5).fit(cluster).anomaly_score((5.0, 5.0))
    assert a == b
    assert a != c and abs(a - c) < 0.1


def test_sub_sample_is_never_larger_than_the_data():
    forest = ExtendedIsolationForest(n_trees=10, sample_size=256, seed=1).fit(_cluster(n=20))
    assert forest.points_per_tree == 20
    assert all(sum(_leaf_sizes(tree)) == 20 for tree in forest.trees)


def test_height_limit_is_ceiling_of_log2_of_the_sub_sample_size():
    forest = ExtendedIsolationForest(n_trees=20, sample_size=20, seed=1).fit(_cluster(n=60))
    assert max(_depth(tree) for tree in forest.trees) <= 5                   # ceiling(log2(20)) = 5


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        ExtendedIsolationForest(10, 256).fit([(1.0, 1.0)])                   # one point cannot be compared with anything
    with pytest.raises(ValueError):
        ExtendedIsolationForest(10, 256, extension_level=2).fit(_cluster())  # 2-D data: levels 0 and 1 only
    with pytest.raises(ValueError):
        ExtendedIsolationForest(10, 256).anomaly_score((0.0, 0.0))           # not fitted yet
