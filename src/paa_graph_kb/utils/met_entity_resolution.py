"""
Entity resolution for linking Perseus and Met objects.

Perseus names Met objects "New York 56.171.49" or "MMA 56.171.49"; perseus_staging_loader
turns that into stg:institution "Metropolitan Museum of Art" + stg:accessionNumber "56.171.49".
Met staging carries the museum's accession number as stg:objectnumber. Where the two agree,
this script emits owl:sameAs between the CRM URIs of the two objects, as entity_resolution.py
does for HAM. The Met staging graph itself is left complete; only links are produced.

    python -m paa_graph_kb.cli.met_entity_resolution \\
        --perseus-staging data/staging/perseus_objects.ttl \\
        --met-staging data/staging/met_staging.ttl \\
        --out data/staging/met_equivalences.ttl
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, Tuple

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDFS

from paa_graph_kb.cli.entity_resolution import generate_hash_from_staging_uri

STG = Namespace("https://aa.perseus.org/staging#")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
CRM_THING = "https://aa.perseus.org/id/thing/"


def normalise_accession(acc: str) -> str:
    """'56.171.49 a, b' -> '56.171.49a,b'; 'X.21.5' -> 'x.21.5'. Whitespace and case only."""
    return re.sub(r"\s+", "", acc).lower()


def find_matches_by_accession(perseus_g: Graph, met_g: Graph) -> Dict[str, Tuple[URIRef, URIRef]]:
    """Return {accession: (perseus_staging_uri, met_staging_uri)} for Perseus objects held by the Met."""
    perseus_met = {}
    for s in perseus_g.subjects(predicate=STG.institution):
        if "Metropolitan" in str(perseus_g.value(s, STG.institution)):
            acc = perseus_g.value(s, STG.accessionNumber)
            if acc:
                perseus_met[normalise_accession(str(acc))] = (str(acc), s)

    met_objects = {}
    for s, objnum in met_g.subject_objects(STG.objectnumber):
        met_objects[normalise_accession(str(objnum))] = s

    return {
        acc: (perseus_uri, met_objects[key])
        for key, (acc, perseus_uri) in perseus_met.items()
        if key in met_objects
    }


def generate_equivalence_graph(matches: Dict[str, Tuple[URIRef, URIRef]]) -> Graph:
    g = Graph()
    g.bind("owl", OWL)
    g.bind("crm", CRM)
    g.bind("rdfs", RDFS)
    for acc, (perseus_staging_uri, met_staging_uri) in matches.items():
        perseus_hash = generate_hash_from_staging_uri(str(perseus_staging_uri))
        met_hash = generate_hash_from_staging_uri(str(met_staging_uri))
        if not (perseus_hash and met_hash):
            continue
        perseus_uri, met_uri = URIRef(CRM_THING + perseus_hash), URIRef(CRM_THING + met_hash)
        g.add((perseus_uri, OWL.sameAs, met_uri))
        g.add((met_uri, OWL.sameAs, perseus_uri))
        g.add((perseus_uri, RDFS.comment, Literal(f"Matched to Met object by accession number: {acc}")))
        g.add((met_uri, RDFS.comment, Literal(f"Matched to Perseus object by accession number: {acc}")))
    return g


def main() -> None:
    ap = argparse.ArgumentParser(description="Link Perseus and Met objects by accession number (owl:sameAs).")
    ap.add_argument("--perseus-staging", type=Path, required=True, help="Perseus staging TTL")
    ap.add_argument("--met-staging", type=Path, required=True, help="Met staging TTL (paa-met-harvester output)")
    ap.add_argument("--out", type=Path, required=True, help="Output TTL of equivalence statements")
    ap.add_argument("--unmatched", type=Path, help="Optional: write Perseus Met accessions with no match, one per line")
    args = ap.parse_args()

    print(f" Loading Perseus staging: {args.perseus_staging}")
    perseus_g = Graph().parse(args.perseus_staging, format="turtle")
    print(f" Loading Met staging: {args.met_staging}")
    met_g = Graph().parse(args.met_staging, format="turtle")

    matches = find_matches_by_accession(perseus_g, met_g)
    perseus_total = sum(1 for s in perseus_g.subjects(STG.institution)
                        if "Metropolitan" in str(perseus_g.value(s, STG.institution)))
    print(f" Found {len(matches)} matches for {perseus_total} Perseus objects held by the Met")
    for acc, (p, m) in list(matches.items())[:5]:
        print(f"   {acc}\n     Perseus: {p}\n     Met:     {m}")

    if args.unmatched:
        matched_keys = {normalise_accession(a) for a in matches}
        missing = sorted(
            str(acc) for s in perseus_g.subjects(STG.institution)
            if "Metropolitan" in str(perseus_g.value(s, STG.institution))
            for acc in [perseus_g.value(s, STG.accessionNumber)] if acc
            and normalise_accession(str(acc)) not in matched_keys
        )
        args.unmatched.write_text("\n".join(missing) + ("\n" if missing else ""))
        print(f" Missing {len(missing)} unmatched accession numbers written to {args.unmatched}")

    equiv_g = generate_equivalence_graph(matches)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    equiv_g.serialize(destination=args.out, format="turtle")
    print(f"✅ Wrote {len(equiv_g)} triples ({len(matches)} entity pairs) to {args.out}")


if __name__ == "__main__":
    main()
