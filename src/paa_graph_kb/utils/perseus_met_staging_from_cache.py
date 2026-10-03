"""
Script to load cached Met JSON objects and convert them to staging RDF triples. 
This bypasses the API client's search/fetch logic and uses local files directly.

Use it after changing met_object_to_staging(), or to stage only the Met objects that the
Perseus staging graph references ("New York 56.171.49" / "MMA 56.171.49" accession numbers):

    python -m paa_graph_kb.utils.met_staging_from_cache
    python -m paa_graph_kb.utils.met_staging_from_cache --perseus data/staging/perseus_objects.ttl
"""

import argparse
import json
import logging
import os
from pathlib import Path

from rdflib import Graph, Namespace

from paa_graph_kb.harvesters.met_harvester import EXS, STG, met_object_to_staging
from paa_graph_kb.models.met.models import MetObject

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def perseus_met_accessions(staging_path: Path) -> set[str]:
    """Accession numbers of Perseus objects whose institution is the Met."""
    g = Graph()
    g.parse(staging_path, format="turtle")
    found = set()
    for s in g.subjects(predicate=STG.institution):
        if "Metropolitan" in str(g.value(s, STG.institution)):
            acc = g.value(s, STG.accessionNumber)
            if acc:
                found.add(str(acc).strip())
    logger.info(f"Found {len(found)} Met accession numbers in Perseus staging.")
    return found


def main():
    parser = argparse.ArgumentParser(description="Convert cached Met JSONs to staging RDF.")
    parser.add_argument("--cache-dir", type=Path, default=Path(os.getenv("MET_OBJ_DIR", "data/met/objects")))
    parser.add_argument("--out", type=Path, default=Path("data/staging/met_staging.ttl"))
    parser.add_argument("--perseus", type=Path, help="Perseus staging TTL; keep only objects it references")
    args = parser.parse_args()

    if not args.cache_dir.exists():
        logger.error(f"Cache directory not found: {args.cache_dir}")
        return

    wanted = perseus_met_accessions(args.perseus) if args.perseus else None

    g = Graph()
    g.bind("stg", STG)
    g.bind("exs", EXS)

    count = errors = skipped = 0
    # The base Client names cache files by request hash, so identify object records by content.
    for file_path in args.cache_dir.glob("*.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "objectID" not in data:
                continue
            obj = MetObject(**data)
            if wanted is not None and obj.accessionNumber not in wanted:
                skipped += 1
                continue
            met_object_to_staging(g, obj)
            count += 1
        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}")
            errors += 1

    logger.info(f"Conversion complete. Processed: {count}, Skipped: {skipped}, Errors: {errors}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=args.out, format="turtle")
    logger.info(f"✅ Wrote {len(g)} triples to {args.out}")


if __name__ == "__main__":
    main()
