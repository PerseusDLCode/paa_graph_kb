"""
Citation-resolution pilot (agenda.org#track-b/citation-resolution-pilot).

Extracts and tier-classifies bibliography citations from the raw
`sources_used` / `other_bibliography` fields in data/perseus/objects.json,
formalizing the ad hoc shape check documented in
docs/citation-resolution/track_b_sample_findings.org. Outputs a full
per-citation CSV and an author-year frequency table; does not attempt
resolution or RDF generation (see docs/citation-resolution/track_b_pilot_results.org
for the write-up that uses this script's output).
"""

import argparse
import csv
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Iterator, NamedTuple, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BIBL_TAG_RE = re.compile(r"<bibl>(.*?)</bibl>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")

# Matches a leading "Author Year" or "Author & Author Year" citation key,
# e.g. "Rossiter 1981", "C.M. Edwards 1985", "von Gerkan 1963-64",
# "Koldewey and Puchstein 1899", "Cohen 1880-1892".
_NAME = (
    r"(?:[A-Z]\.\s*){0,3}"  # optional initials, e.g. "C.M. " or "D. "
    r"(?:(?:von|van|de|der|den|le|la|du|di)\s+)?"  # optional lowercase name-prefix
    r"[A-Z][A-Za-z\'’\-]+"  # capitalized surname
)
AUTHOR_YEAR_RE = re.compile(
    r"^(?P<author>" + _NAME + r"(?:\s*(?:&|and)\s*" + _NAME + r")?)"
    r"\s+(?P<year>\d{3,4}[a-z]?(?:[\-/]\d{2,4})?)\b"
)

QUOTE_CHARS = ('"', "“", "”")


def load_abbreviations(path: Path) -> set[str]:
    """Parse `abbrev: expansion  # note` lines from the manual mapping file."""
    abbrevs = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split(":", 1)[0].strip()
        if key:
            abbrevs.add(key)
    return abbrevs


class CitationRow(NamedTuple):
    object_id: str
    field: str
    tier: str
    subtype: str
    key: str
    raw_text: str


def normalize_author_year(text: str) -> Optional[str]:
    m = AUTHOR_YEAR_RE.match(text.strip())
    if not m:
        return None
    author = re.sub(r"\s+", " ", m.group("author")).strip()
    return f"{author} {m.group('year')}"


def looks_like_bundle(inner: str) -> bool:
    """A single <bibl> span holding more than one locator/sub-citation."""
    if inner.count(";") >= 1:
        return True
    if len(AUTHOR_YEAR_RE.findall(inner)) >= 1 and inner.count(",") >= 3:
        return True
    if inner.count(" s.v. ") >= 1 and inner.count(";") == 0 and " s.v. " in inner[3:]:
        return True
    return False


def classify_bibl_span(inner: str, abbreviations: set[str]) -> tuple[str, str, str]:
    """Return (tier, subtype, key) for the contents of one <bibl>...</bibl> span."""
    # Strip nested markup (e.g. <hi rend="ital">...</hi>) *before* any
    # quote-character check — HTML attribute quotes (rend="ital") would
    # otherwise false-trigger QUOTED_TITLE.
    inner = TAG_RE.sub("", inner)
    inner = re.sub(r"\s+", " ", inner).strip()
    if looks_like_bundle(inner):
        return "OTHER", "BUNDLED_LOCATOR", inner[:80]

    leading_word = re.match(r"^[A-Za-z0-9]+", inner)
    if leading_word and leading_word.group(0) in abbreviations:
        return "ABBREVIATION", "", leading_word.group(0)

    key = normalize_author_year(inner)
    if key:
        return "AUTHOR_YEAR", "", key

    if any(c in inner for c in QUOTE_CHARS):
        return "OTHER", "QUOTED_TITLE", inner[:80]
    return "OTHER", "OTHER_UNCLASSIFIED", inner[:80]


def classify_untagged_chunk(chunk: str, abbreviations: set[str]) -> Optional[tuple[str, str, str]]:
    """Classify a plain-text fragment found outside any <bibl> tag. Returns None if not citation-shaped."""
    chunk = TAG_RE.sub("", chunk)
    chunk = re.sub(r"\s+", " ", chunk).strip(" ,;.")
    if not chunk:
        return None

    key = normalize_author_year(chunk)
    if key:
        return "AUTHOR_YEAR", "UNTAGGED", key

    leading_word = re.match(r"^[A-Za-z0-9]+", chunk)
    if leading_word and leading_word.group(0) in abbreviations:
        return "ABBREVIATION", "UNTAGGED", leading_word.group(0)

    has_year = re.search(r"\b\d{4}\b", chunk)
    has_quote = any(c in chunk for c in QUOTE_CHARS)
    if has_year or has_quote:
        return "OTHER", "UNTAGGED", chunk[:80]
    return None


def extract_citations(obj_id: str, field: str, text: str, abbreviations: set[str]) -> Iterator[CitationRow]:
    spans = list(BIBL_TAG_RE.finditer(text))
    for m in spans:
        tier, subtype, key = classify_bibl_span(m.group(1), abbreviations)
        yield CitationRow(obj_id, field, tier, subtype, key, m.group(0)[:200])

    remainder = BIBL_TAG_RE.sub("", text)
    for chunk in remainder.split(";"):
        result = classify_untagged_chunk(chunk, abbreviations)
        if result is None:
            continue
        tier, subtype, key = result
        yield CitationRow(obj_id, field, tier, subtype, key, chunk.strip()[:200])


def run(objects_path: Path, abbreviations_path: Path, out_dir: Path) -> None:
    abbreviations = load_abbreviations(abbreviations_path)
    logger.info(f"Loaded {len(abbreviations)} known abbreviations from {abbreviations_path}")

    logger.info(f"Loading {objects_path}...")
    with objects_path.open(encoding="utf-8") as f:
        objects = json.load(f)
    logger.info(f"Loaded {len(objects)} objects.")

    rows: list[CitationRow] = []
    for obj in objects:
        obj_id = obj.get("id", "")
        for field in ("sources_used", "other_bibliography"):
            text = obj.get(field)
            if not text:
                continue
            rows.extend(extract_citations(obj_id, field, text, abbreviations))

    out_dir.mkdir(parents=True, exist_ok=True)

    citations_path = out_dir / "bibliography_citations_full.csv"
    with citations_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["object_id", "field", "tier", "subtype", "key", "raw_text"])
        writer.writerows(rows)
    logger.info(f"Wrote {len(rows)} citation rows to {citations_path}")

    author_year_counts = Counter(r.key for r in rows if r.tier == "AUTHOR_YEAR")
    author_year_path = out_dir / "bibliography_author_year_keys.csv"
    with author_year_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["key", "occurrence_count"])
        for key, count in author_year_counts.most_common():
            writer.writerow([key, count])
    logger.info(f"Wrote {len(author_year_counts)} unique author-year keys to {author_year_path}")

    tier_counts = Counter(r.tier for r in rows)
    subtype_counts = Counter((r.tier, r.subtype) for r in rows if r.tier == "OTHER")
    logger.info("\nTier totals:")
    for tier, count in tier_counts.most_common():
        logger.info(f"  {tier}: {count}")
    logger.info("\nOTHER subtype breakdown:")
    for (_, subtype), count in subtype_counts.most_common():
        logger.info(f"  {subtype}: {count}")
    logger.info(f"\nUnique author-year keys: {len(author_year_counts)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Citation-resolution pilot: extract and tier-classify bibliography citations.")
    parser.add_argument("--objects", type=Path, default=Path("data/perseus/objects.json"))
    parser.add_argument(
        "--abbreviations",
        type=Path,
        default=Path("data/reconciliation/bibliography_abbreviations_manual.txt"),
    )
    parser.add_argument("--out", type=Path, default=Path("data/reports/citation-resolution"))
    args = parser.parse_args()
    run(args.objects, args.abbreviations, args.out)


if __name__ == "__main__":
    main()
