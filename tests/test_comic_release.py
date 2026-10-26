from __future__ import annotations

import pytest

from tankarr.comics.release import issue_key, match_issue, parse_release


@pytest.mark.parametrize(
    ("title", "series", "issue", "year", "ext", "digital"),
    [
        (
            "Batman 012 (2016) (digital) (Zone-Empire).cbz",
            "Batman",
            "012",
            2016,
            "cbz",
            True,
        ),
        (
            "Amazing Spider-Man #12 (2018).cbr",
            "Amazing Spider-Man",
            "12",
            2018,
            "cbr",
            False,
        ),
        ("Batman.2016.012.cbr", "Batman", "012", 2016, "cbr", False),
        (
            "The Walking Dead v2 005 (2020)",
            "The Walking Dead",
            "005",
            2020,
            None,
            False,
        ),
    ],
)
def test_parse_release_without_a_known_series(title, series, issue, year, ext, digital):
    parsed = parse_release(title)
    assert (parsed.series, parsed.issue, parsed.year) == (series, issue, year)
    assert parsed.extension == ext
    assert parsed.digital is digital


def test_known_series_keeps_numbers_in_the_title():
    parsed = parse_release(
        "Spider-Man 2099 012 (1992).cbz", known_series="Spider-Man 2099"
    )
    assert parsed.series_matched and parsed.issue == "012"


def test_issue_keys_ignore_padding():
    assert issue_key("012") == issue_key("12.0") == "12"
    assert issue_key("12.1") != issue_key("12")
    assert issue_key("0") == "0"


def match(title, **kw):
    base = {"series_title": "Batman", "issue_number": "12", "series_year": 2016}
    return match_issue(title, **{**base, **kw})


def test_matches_the_right_issue_and_volume():
    assert match("Batman 012 (2016) (digital).cbz")
    assert match("Batman #12.cbz") is not None  # no year: accepted, lower score
    assert match("Batman #12.cbz").score < match("Batman 012 (2016).cbz").score


def test_refuses_other_issues_volumes_and_series():
    assert match("Batman 013 (2016).cbz") is None
    assert match("Batman 012 (2011).cbz") is None  # another volume of Batman
    assert match("Batman Annual 02 (2016).cbz") is None
    assert match("Batman Beyond 012 (2016).cbz") is None
    assert match("Batman Vol 1 TPB (2016).cbz") is None


def test_packs_cover_the_issue_but_rank_lower():
    pack = match("Batman 010-015 (2016).cbz")
    assert pack and pack.pack
    assert pack.score < match("Batman 012 (2016).cbz").score
    assert match("Batman 001-005 (2016).cbz") is None


def test_series_title_punctuation_is_forgiving():
    hit = match_issue(
        "Marvels Avengers 001 (2020).cbz",
        series_title="Marvel's Avengers (2020)",
        issue_number="1",
        series_year=2020,
    )
    assert hit is not None
