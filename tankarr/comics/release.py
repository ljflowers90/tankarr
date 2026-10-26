"""Parse and match comic release titles (scene and Mylar-style names)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EXTENSIONS = re.compile(r"\.(cbz|cbr|cb7|cbt|pdf|epub|zip|rar|7z|nzb|torrent)$", re.I)
BRACKETS = re.compile(r"[\(\[]([^()\[\]]*)[\)\]]")
YEAR = re.compile(r"(?:19|20)\d{2}")
YEAR_RANGE = re.compile(r"^((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})$")
COLLECTION = re.compile(
    r"\b(?:tpb|trade paperback|hardcover|hc|omnibus|graphic novel|compendium|"
    r"collection|deluxe edition|library edition)\b",
    re.I,
)
ONE_SHOT = re.compile(r"\bone[\s-]?shot\b", re.I)
VOLUME = re.compile(r"^(?:v|vol\.?|volume)\s*(\d{1,3})(?![A-Za-z0-9])", re.I)
BARE_YEAR = re.compile(r"^((?:19|20)\d{2})(?=\s+#?\d)")
ISSUE = re.compile(
    r"^#?\s*(?P<n>\d{1,4}(?:\.\d+)?[A-Za-z]{0,2})"
    r"(?:\s*-\s*#?(?P<end>\d{1,4}(?:\.\d+)?))?(?![A-Za-z0-9])"
)
ISSUE_TOKEN = re.compile(r"(?<![\w.])#?(\d{1,4}(?:\.\d+)?[A-Za-z]{0,2})(?![\w])")
ISSUE_NUMBER = re.compile(r"^0*(\d+)(?:\.(\d+))?(.*)$")
SEPARATORS = " \t-–—_:.,"


@dataclass
class ParsedRelease:
    series: str
    issue: str | None = None
    issue_end: str | None = None
    volume: int | None = None
    years: list[int] = field(default_factory=list)
    kind: str = "issue"
    extension: str | None = None
    digital: bool = False
    series_matched: bool = False

    @property
    def year(self) -> int | None:
        return self.years[0] if self.years else None

    def as_dict(self) -> dict:
        return {
            "series": self.series,
            "issue": self.issue,
            "issue_end": self.issue_end,
            "volume": self.volume,
            "year": self.year,
            "kind": self.kind,
            "format": self.extension,
            "digital": self.digital,
        }


def _squash(text: str) -> str:
    """Drop punctuation that indexers spell inconsistently."""

    return text.replace("&", " and ").replace("'", "").replace("’", "").replace("`", "")


def clean_series_title(title: str) -> str:
    return " ".join(BRACKETS.sub(" ", title).split())


def _series_pattern(series_title: str) -> re.Pattern[str] | None:
    words = re.findall(
        r"[a-z0-9]+", _squash(clean_series_title(series_title)).casefold()
    )
    if words and words[0] == "the":
        words = words[1:]
    if not words:
        return None
    return re.compile(
        r"^\W*(?:the\W+)?" + r"\W+".join(map(re.escape, words)) + r"(?![A-Za-z0-9])",
        re.I,
    )


def issue_key(number: str | None) -> str:
    """Compare issue numbers regardless of zero padding ("012" == "12.0")."""

    text = str(number or "").strip().casefold()
    match = ISSUE_NUMBER.match(text)
    if match is None:
        return text
    whole, fraction, suffix = match.groups()
    fraction = (fraction or "").rstrip("0")
    return f"{int(whole)}{'.' + fraction if fraction else ''}{suffix.strip()}"


def _whole_number(value: str | None) -> int | None:
    key = issue_key(value)
    return int(key) if key.isdigit() else None


def parse_release(title: str, known_series: str | None = None) -> ParsedRelease:
    """Split a release name into series, issue and the usual markers.

    With ``known_series`` the name must start with that series, which avoids
    guessing where the title ends ("Spider-Man 2099 012").
    """

    text = " ".join(str(title or "").split())
    extension = None
    found = EXTENSIONS.search(text)
    if found:
        extension = found.group(1).casefold()
        text = text[: found.start()]
    if " " not in text:
        text = re.sub(r"[._]+", " ", text)
    else:
        text = text.replace("_", " ")

    years: list[int] = []
    markers: list[str] = []
    for group in BRACKETS.findall(text):
        value = group.strip()
        span = YEAR_RANGE.match(value)
        if span:
            years.extend(int(item) for item in span.groups())
        elif YEAR.fullmatch(value):
            years.append(int(value))
        else:
            markers.append(value.casefold())
    head = " ".join(BRACKETS.sub(" ", text).split())
    digital = any(re.search(r"\b(?:digital|webrip|web)\b", item) for item in markers)
    collection = bool(COLLECTION.search(head)) or any(
        COLLECTION.search(item) for item in markers
    )
    one_shot = bool(ONE_SHOT.search(head)) or any(
        ONE_SHOT.search(item) for item in markers
    )

    squashed = _squash(head)
    series = ""
    remainder = ""
    matched = False
    pattern = _series_pattern(known_series) if known_series else None
    if pattern is not None:
        hit = pattern.match(squashed)
        if hit:
            series = clean_series_title(known_series or "")
            remainder = squashed[hit.end() :]
            matched = True
    if not matched and known_series is None:
        # No series to anchor on: the first number after the first word is
        # taken as the issue.
        for token in ISSUE_TOKEN.finditer(squashed):
            if token.start() > 0 and not YEAR.fullmatch(token.group(1)):
                series = squashed[: token.start()].strip(SEPARATORS + "#")
                remainder = squashed[token.start() :]
                break
        else:
            series = squashed.strip(SEPARATORS)

    volume = None
    issue = issue_end = None
    if not matched:
        # "Batman v3 012" and "Batman 2016 012": the marker is not the title.
        tail = re.search(
            r"\s+(?:(?:v|vol\.?|volume)\s*(\d{1,3})|((?:19|20)\d{2}))$", series, re.I
        )
        while tail:
            if tail.group(1):
                volume = int(tail.group(1))
            else:
                years.append(int(tail.group(2)))
            series = series[: tail.start()].strip(SEPARATORS)
            tail = re.search(
                r"\s+(?:(?:v|vol\.?|volume)\s*(\d{1,3})|((?:19|20)\d{2}))$",
                series,
                re.I,
            )
    rest = remainder.lstrip(SEPARATORS)
    volume_hit = VOLUME.match(rest)
    if volume_hit:
        volume = int(volume_hit.group(1))
        rest = rest[volume_hit.end() :].lstrip(SEPARATORS)
    year_hit = BARE_YEAR.match(rest)
    if year_hit:
        years.append(int(year_hit.group(1)))
        rest = rest[year_hit.end() :].lstrip(SEPARATORS)
    issue_hit = ISSUE.match(rest)
    if issue_hit:
        issue = issue_hit.group("n")
        issue_end = issue_hit.group("end")

    kind = "collection" if collection else "one-shot" if one_shot else "issue"
    return ParsedRelease(
        series=series,
        issue=issue,
        issue_end=issue_end,
        volume=volume,
        years=years,
        kind=kind,
        extension=extension,
        digital=digital,
        series_matched=matched,
    )


@dataclass
class ReleaseMatch:
    parsed: ParsedRelease
    score: int
    pack: bool


def match_issue(
    title: str,
    *,
    series_title: str,
    issue_number: str,
    series_year: int | None = None,
    cover_year: int | None = None,
) -> ReleaseMatch | None:
    """Return a match when ``title`` is this issue of this series, else None.

    The year in a release name is usually the volume's start year, which tells
    two runs of the same title apart; a release naming another year is refused.
    """

    parsed = parse_release(title, known_series=series_title)
    if not parsed.series_matched or parsed.kind != "issue" or parsed.issue is None:
        return None

    wanted = issue_key(issue_number)
    pack = False
    if issue_key(parsed.issue) != wanted:
        start, end, target = (
            _whole_number(parsed.issue),
            _whole_number(parsed.issue_end),
            _whole_number(issue_number),
        )
        if None in (start, end, target) or not start <= target <= end:  # type: ignore[operator]
            return None
        pack = True

    year_matched = False
    if parsed.years:
        allowed = {series_year} if series_year else set()
        if cover_year:
            allowed.update({cover_year - 1, cover_year, cover_year + 1})
        span = (
            parsed.years[0] <= cover_year <= parsed.years[-1]
            if cover_year and len(parsed.years) > 1
            else False
        )
        year_matched = span or any(year in allowed for year in parsed.years)
        if allowed and not year_matched:
            return None

    score = 100 + (20 if year_matched else -10 if series_year else 0)
    score += 5 if parsed.digital else 0
    score += 5 if parsed.extension in {"cbz", "cbr"} else 0
    score -= 15 if pack else 0
    return ReleaseMatch(parsed=parsed, score=score, pack=pack)
