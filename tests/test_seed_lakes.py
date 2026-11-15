"""The full list of seed lakes (the two original lakes plus the seven Pakistani lakes added on 2026-11-15)."""
from __future__ import annotations

from conftest import ALL_SEED_LAKES
from sailab import db

ADDED = {"SHP": (74.5623, 36.3607), "KHD": (75.4755, 36.3441), "BDS": (74.0345, 36.5470), "CHJ": (74.00409, 36.78359),
         "PSU": (74.8622, 36.4330), "RSH": (74.8825, 36.1741), "ATB": (74.8650, 36.3400)}


def test_nine_lakes_with_unique_codes_and_the_originals_first():
    codes = [lake["code"] for lake in ALL_SEED_LAKES]
    assert codes[:2] == ["KRB", "ATS"]                    # ids 1 and 2 stay the same for the stored data
    assert len(codes) == 9 and len(set(codes)) == 9
    assert "DMD" not in codes                             # Darmander: excluded by the earlier project (no lake there)


def test_added_lakes_use_the_earlier_projects_positions_exactly():
    by_code = {lake["code"]: lake for lake in ALL_SEED_LAKES}
    for code, (lon, lat) in ADDED.items():
        assert (by_code[code]["centre_lon"], by_code[code]["centre_lat"]) == (lon, lat)


def test_every_lake_is_in_northern_pakistan_and_has_a_window(tmp_path, monkeypatch):
    for lake in ALL_SEED_LAKES:
        assert 73.0 < lake["centre_lon"] < 76.0 and 35.5 < lake["centre_lat"] < 37.5
        assert lake["boundary_radius_m"] > 0 and lake["growth_distance_limit_m"] > 0
    monkeypatch.setattr(db, "SEED_LAKES", ALL_SEED_LAKES)
    conn = db.connect(tmp_path / "t.db")
    ids = db.seed_lakes(conn)
    assert ids == list(range(1, 10))
    assert db.seed_lakes(conn) == ids                     # seeding again changes nothing
