"""sailab/ods.py and sailab/flood_events.py on small made-up files with known answers."""
from __future__ import annotations

import zipfile
from datetime import date

import pytest

from sailab import flood_events as fe
from sailab.ods import read_sheets


# --- the .ods reader ------------------------------------------------------------------------------
def _write_ods_sheets(path, sheets: dict[str, str]):
    """A minimal .ods file: {sheet name: the XML of its rows}."""
    tables = "".join(f'<table:table table:name="{name}">{rows}</table:table>' for name, rows in sheets.items())
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet>'
        f'{tables}</office:spreadsheet></office:body></office:document-content>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        archive.writestr("content.xml", content)


def _write_ods(path, rows_xml: str, name="Sheet1"):
    _write_ods_sheets(path, {name: rows_xml})


def _cell(text="", repeat=1):
    rep = f' table:number-columns-repeated="{repeat}"' if repeat > 1 else ""
    return f"<table:table-cell{rep}>" + (f"<text:p>{text}</text:p>" if text else "") + "</table:table-cell>"


def test_empty_cells_in_the_middle_of_a_row_keep_later_columns_in_place(tmp_path):
    """The bug found on the real file: two empty cells stored as one repeated cell must stay two cells."""
    path = tmp_path / "t.ods"
    _write_ods(path, "<table:table-row>" + _cell("a") + _cell(repeat=2) + _cell("d") + "</table:table-row>")
    assert read_sheets(path) == {"Sheet1": [["a", "", "", "d"]]}


def test_a_huge_empty_run_at_the_end_is_dropped_not_expanded(tmp_path):
    path = tmp_path / "t.ods"
    row = "<table:table-row>" + _cell("x") + _cell(repeat=16000) + "</table:table-row>"
    empty_rows = '<table:table-row table:number-rows-repeated="1048000">' + _cell(repeat=16000) + "</table:table-row>"
    _write_ods(path, row + empty_rows)
    assert read_sheets(path) == {"Sheet1": [["x"]]}


def test_repeated_text_cells_are_all_kept(tmp_path):
    path = tmp_path / "t.ods"
    _write_ods(path, "<table:table-row>" + _cell("7", repeat=3) + "</table:table-row>")
    assert read_sheets(path)["Sheet1"] == [["7", "7", "7"]]


# --- one flood record -------------------------------------------------------------------------------
def _event(**changes):
    base = dict(source="hma", record_id="1", country="Nepal", lake_name="Test", year=2020, day=date(2020, 6, 1),
                lon=86.123, lat=27.456, location_decimals=3, dam_type="moraine")
    return fe.FloodEvent(**{**base, **changes})


def test_each_filter_on_its_own():
    assert fe.passes(_event(year=2016), "after 2015") and not fe.passes(_event(year=2015), "after 2015")
    assert not fe.passes(_event(year=None), "after 2015")
    assert not fe.passes(_event(day=None), "exact date")
    assert fe.passes(_event(location_decimals=3), "exact location")
    assert not fe.passes(_event(location_decimals=2), "exact location")
    assert not fe.passes(_event(lon=None, lat=None), "exact location")
    assert fe.passes(_event(dam_type="ice"), "moraine or ice dammed")
    assert not fe.passes(_event(dam_type="water pocket"), "moraine or ice dammed")


def test_counts_drop_step_by_step_in_the_stated_order():
    events = [
        _event(),                                   # passes everything
        _event(year=2010),                          # out at step 1
        _event(day=None),                           # out at step 2
        _event(location_decimals=1),                # out at step 3
        _event(dam_type="supraglacial", country="Pakistan"),   # out at step 4
        _event(country="Pakistan"),                 # passes everything
    ]
    steps, left = fe.apply_filters(events)
    assert steps == [("all records", 6, 2), ("after 2015", 5, 2), ("exact date", 4, 2),
                     ("exact location", 3, 2), ("moraine or ice dammed", 2, 1)]
    assert len(left) == 2


def test_the_same_flood_in_both_databases_is_counted_once():
    hma = [_event(source="hma", lon=86.0000, lat=27.0000)]
    same = _event(source="global", lon=86.0100, lat=27.0000)          # about 1 km east, same day
    other_day = _event(source="global", day=date(2020, 6, 2))
    far_away = _event(source="global", lon=86.1000, lat=27.0000)      # about 10 km east
    merged, in_both = fe.merge([same, other_day, far_away], hma)
    assert in_both == 1 and len(merged) == 3
    assert [e.source for e in merged].count("both") == 1


# --- reading the two file formats ------------------------------------------------------------------
def test_global_rows_are_read_with_decimal_commas_and_full_dates_only_as_exact(tmp_path):
    header = ["Country", "Glacier", "Lake", "Lake_type", "Longitude", "Latitude", "Date", "Date_Min"]
    rows = [header, ["desc"] * 8, ["hint"] * 8,
            ["Pakistan", "Shisper", "", "ice", "74,6090", "36,4010", "2022-05-07", ""],
            ["China", "G1", "L1", "moraine", "90,98", "48,62", "2019", ""],
            ["China", "G2", "L2", "water pocket", "91,1234", "30,1234", "", "2018-07-01"]]
    def table(rows_):
        return "".join("<table:table-row>" + "".join(_cell(c) for c in r) + "</table:table-row>" for r in rows_)

    path = tmp_path / "g.ods"
    # The reader opens all three Asia sheets; only the South Asia West one holds rows here.
    _write_ods_sheets(path, {name: table(rows if name == "RGI60_14_SouthAsiaWest" else [header])
                             for name in fe.GLOBAL_HMA_SHEETS})

    shisper, year_only, from_date_min = fe.read_global(path)
    assert (shisper.lon, shisper.lat, shisper.location_decimals) == (74.609, 36.401, 4)
    assert shisper.day == date(2022, 5, 7) and shisper.year == 2022 and shisper.dam_type == "ice"
    assert year_only.day is None and year_only.year == 2019 and year_only.location_decimals == 2
    assert from_date_min.day is None and from_date_min.year == 2018   # a possible date range is not an exact day


def test_hma_rows_need_year_month_and_day_for_an_exact_date(tmp_path):
    path = tmp_path / "h.csv"
    header = "GF_ID,Year_approx,Year_exact,Month,Day,Lake_name,Glacier_name,Lat_lake,Lon_lake,Lake_type,Country\n"
    path.write_bytes((header +
                      "1,2018,2018,7,15,Lake A,,28.123456,86.123456,Moraine dammed,Nepal\n"
                      "2,2019,2019,8,NA,Lake B,,28.1,86.1,Ice dammed,China\n"
                      "3,2020,NA,NA,NA,,Glacier C,28.12,86.12,Water pocket,India\n"
                      "4,2021,2021,6,30,Lake – D,,NA,NA,Moraine dammed,Pakistan\n").encode("cp1252"))   # en dash -> byte 0x96
    a, b, c, d = fe.read_hma(path)
    assert a.day == date(2018, 7, 15) and a.location_decimals == 6 and a.dam_type == "moraine"
    assert b.day is None and b.dam_type == "ice"
    assert c.day is None and c.year == 2020 and c.lake_name == "Glacier C" and c.dam_type == "Water pocket"
    assert d.lon is None and d.lake_name == "Lake – D"          # a Windows-1252 en dash is read correctly


def test_impossible_dates_are_not_exact():
    assert fe._number("74,6090") == (74.609, 4)
    assert fe._number("Aksy") == (None, 0)
    with pytest.raises(ValueError):
        fe.passes(_event(), "no such filter")
