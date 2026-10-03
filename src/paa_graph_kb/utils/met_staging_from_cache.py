"""
Script to load cached Met JSON objects and convert them to staging RDF triples. 
This bypasses the API client's search/fetch logic and uses local files directly.

Perseus links are made afterwards by cli/entity_resolution.py --institution Metropolitan.
"""

import argparse
import json
import logging
import os
from pathlib import Path

from rdflib import Graph

from paa_graph_kb.harvesters.met_harvester import EXS, STG, met_object_to_staging
from paa_graph_kb.models.met.models import MetObject

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Convert cached Met JSONs to staging RDF.")
    parser.add_argument("--cache-dir", type=Path, default=Path(os.getenv("MET_OBJ_DIR", "data/met/objects")))
    parser.add_argument("--out", type=Path, default=Path("data/staging/met_staging.ttl"))
    args = parser.parse_args()

    if not args.cache_dir.exists():
        logger.error(f"Cache directory not found: {args.cache_dir}")
        return

    g = Graph()
    g.bind("stg", STG)
    g.bind("exs", EXS)

    count = errors = 0
    # The base Client names cache files by request hash, so identify object records by content.
    for file_path in args.cache_dir.glob("*.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "objectID" not in data:
                continue
            met_object_to_staging(g, MetObject(**data))
            count += 1
        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}")
            errors += 1

    logger.info(f"Conversion complete. Processed: {count}, Errors: {errors}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=args.out, format="turtle")
    logger.info(f"✅ Wrote {len(g)} triples to {args.out}")


if __name__ == "__main__":
    main()
