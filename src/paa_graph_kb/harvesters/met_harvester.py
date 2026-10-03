"""
Harvest Greek and Roman antiquities from The Met Collection API into staging RDF.

    paa-met-harvester --out data/staging/met_staging.ttl --limit 50
    paa-met-harvester --out data/staging/met_staging.ttl            # whole department (~33k objects)

Records are cached as JSON under MET_OBJ_DIR (default data/met/objects) by the base Client,
so a rerun only fetches what is missing.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable, Optional

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from paa_graph_kb.clients.met_client import GREEK_AND_ROMAN_ART, MetClient
from paa_graph_kb.harvesters import Harvester
from paa_graph_kb.models.met.models import MetObject
from paa_graph_kb.vocabularies import aat_mappings

STG = Namespace("https://aa.perseus.org/staging#")
EXS = Namespace("https://aa.perseus.org/staging/")


def _lit(text: str) -> Literal:
    return Literal(text, lang="en") if all(ord(c) < 128 for c in text) else Literal(text)


def met_object_to_staging(g: Graph, obj: MetObject, source: str = "met") -> None:
    """Map every documented Met object field onto stg: properties.

    HAM-equivalent fields reuse the properties object_to_staging() emits; the rest use the
    "Met Collection API fields" block of stg_vocab.ttl. Empty values produce no triple.
    """
    s = EXS[f"o/{source}:{obj.objectID}"]
    g.add((s, RDF.type, STG.Object))
    g.add((s, STG.source, Literal(source)))
    g.add((s, STG.objectid, Literal(obj.objectID, datatype=XSD.integer)))

    # --- flags -----------------------------------------------------------------
    g.add((s, STG.isHighlight, Literal(obj.isHighlight)))
    g.add((s, STG.isPublicDomain, Literal(obj.isPublicDomain)))
    g.add((s, STG.isTimelineWork, Literal(obj.isTimelineWork)))

    # --- identifiers / institutional ---------------------------------------------
    for value, prop in (
        (obj.accessionNumber, STG.objectnumber), (obj.department, STG.department),
        (obj.repository, STG.repository), (obj.GalleryNumber, STG.galleryNumber),
        (obj.rightsAndReproduction, STG.rightsStatement), (obj.creditLine, STG.creditline),
        (obj.dimensions, STG.dimensions), (obj.objectDate, STG.dated), (obj.classification, STG.classification),
    ):
        if value:
            g.add((s, prop, Literal(value)))
    if obj.accessionYear is not None:
        g.add((s, STG.accessionyear, Literal(obj.accessionYear, datatype=XSD.integer)))
    if obj.metadataDate:
        g.add((s, STG.metadataDate, Literal(obj.metadataDate, datatype=XSD.dateTime)))
    for value, prop in (
        (obj.objectURL, STG.catalogPage), (obj.linkResource, STG.linkResource),
        (obj.objectWikidata_URL, STG.wikidataId),
    ):
        if value:
            g.add((s, prop, URIRef(value)))

    # --- names, culture, type, material, period -----------------------------------
    for value, prop in (
        (obj.title, STG.title), (obj.culture, STG.culture), (obj.period, STG.periodLabel),
        (obj.dynasty, STG.dynasty), (obj.reign, STG.reign), (obj.portfolio, STG.portfolio),
        (obj.medium, STG.material),
    ):
        if value:
            g.add((s, prop, _lit(value)))
    if obj.culture:  # Met cultures are often compound ("Greek, Attic"); map on the first token
        _aat(g, s, STG.cultureAAT, obj.culture.split(",")[0], "cultures")
    for label, category in ((obj.objectName, "object_types"), (obj.classification, "classifications")):
        if label:
            g.add((s, STG.typeLabel, _lit(label)))
            _aat(g, s, STG.aatType, label, category)
    if obj.medium:
        _aat(g, s, STG.materialAAT, obj.medium, "materials")

    # --- dating ------------------------------------------------------------------
    if obj.objectBeginDate is not None:
        g.add((s, STG.datebegin, Literal(obj.objectBeginDate, datatype=XSD.integer)))
    if obj.objectEndDate is not None:
        g.add((s, STG.dateend, Literal(obj.objectEndDate, datatype=XSD.integer)))

    # --- geography: each level, plus one combined label (most specific first) ---------
    if obj.geographyType:
        g.add((s, STG.geographyType, Literal(obj.geographyType)))
    levels = (
        (obj.locus, STG.locus), (obj.locale, STG.locale), (obj.subregion, STG.subregion),
        (obj.region, STG.region), (obj.city, STG.city), (obj.county, STG.county),
        (obj.state, STG.state), (obj.country, STG.country),
    )
    for value, prop in levels:
        if value:
            g.add((s, prop, _lit(value)))
    place = ", ".join(v for v, _ in levels if v)
    if place:
        g.add((s, STG.placeLabel, _lit(place)))
    if obj.excavation:
        g.add((s, STG.excavation, Literal(obj.excavation)))
    if obj.river:
        g.add((s, STG.river, _lit(obj.river)))

    # --- measurements (cm; weights kg). dimensionsParsed is the same data in an older shape ---
    elements = [
        (m.elementName, m.elementDescription, m.elementMeasurements or {})
        for m in obj.measurements or []
    ] or [
        (d.get("element"), None, {d.get("dimensionType"): d.get("dimension")})
        for d in (obj.dimensionsParsed if isinstance(obj.dimensionsParsed, list) else [])
        if isinstance(d, dict)
    ]
    n = 0
    for element, description, values in elements:
        for mtype, value in values.items():
            if not isinstance(value, (int, float)):
                continue
            node = URIRef(f"https://aa.perseus.org/staging/measurement/{source}:{obj.objectID}/{n}")
            n += 1
            g.add((s, STG.hasMeasurement, node))
            g.add((node, STG.measurementType, Literal(mtype)))
            g.add((node, STG.measurementValue, Literal(value, datatype=XSD.decimal)))
            g.add((node, STG.measurementUnit, Literal("kg" if str(mtype).lower().startswith("weight") else "cm")))
            if element:
                g.add((node, STG.measurementElement, Literal(element)))
            if description:
                g.add((node, STG.measurementDescription, Literal(description)))

    # --- images --------------------------------------------------------------------
    if obj.primaryImage:
        g.add((s, STG.primaryImage, URIRef(obj.primaryImage)))
    if obj.primaryImageSmall:
        g.add((s, STG.primaryImageSmall, URIRef(obj.primaryImageSmall)))
    for i, url in enumerate([u for u in (obj.primaryImage, *obj.additionalImages) if u]):
        img = URIRef(f"https://aa.perseus.org/staging/image/{source}:{obj.objectID}/{i}")
        g.add((s, STG.hasImage, img))
        g.add((img, STG.baseImageURL, URIRef(url)))
        g.add((img, STG.displayOrder, Literal(i, datatype=XSD.integer)))
        if obj.rightsAndReproduction:
            g.add((img, STG.copyright, Literal(obj.rightsAndReproduction)))

    # --- subjects ------------------------------------------------------------------
    for tag in obj.tags or []:
        if tag.term:
            g.add((s, STG.subject, _lit(tag.term)))
        if tag.AAT_URL:
            g.add((s, STG.subjectAAT, URIRef(tag.AAT_URL)))
        if tag.Wikidata_URL:
            g.add((s, STG.subjectWikidata, URIRef(tag.Wikidata_URL)))

    # --- people: structured constituents, then the flat artist* block ------------------
    # The artist* fields describe the primary constituent; they land on that person's node
    # (matched by name), or on a synthetic node when the record has no constituents.
    primary = None
    for c in obj.constituents or []:
        if c.constituentID is None:
            continue
        person = URIRef(f"https://aa.perseus.org/staging/person/{source}:{c.constituentID}")
        g.add((s, STG.hasPerson, person))
        g.add((person, RDF.type, STG.Person))
        g.add((person, STG.personid, Literal(c.constituentID, datatype=XSD.integer)))
        for value, prop in ((c.name, STG.personName), (c.role, STG.personRole), (c.gender, STG.personGender)):
            if value:
                g.add((person, prop, Literal(value)))
        for value, prop in ((c.constituentULAN_URL, STG.ulanId), (c.constituentWikidata_URL, STG.wikidataId)):
            if value:
                g.add((person, prop, URIRef(value)))
        if primary is None and (c.name == obj.artistDisplayName or obj.artistDisplayName is None):
            primary = person
    if obj.artistDisplayName and primary is None:
        primary = URIRef(f"https://aa.perseus.org/staging/person/{source}:{obj.objectID}-artist")
        g.add((s, STG.hasPerson, primary))
        g.add((primary, RDF.type, STG.Person))
        g.add((primary, STG.personName, Literal(obj.artistDisplayName)))
    if primary is not None:
        for value, prop in (
            (obj.artistDisplayName, STG.personDisplayName), (obj.artistRole, STG.personRole),
            (obj.artistPrefix, STG.personPrefix), (obj.artistSuffix, STG.personSuffix),
            (obj.artistDisplayBio, STG.personDisplayBio), (obj.artistAlphaSort, STG.personAlphaSort),
            (obj.artistNationality, STG.personCulture), (obj.artistGender, STG.personGender),
        ):
            if value and (primary, prop, Literal(value)) not in g:
                g.add((primary, prop, Literal(value)))
        for value, prop in ((obj.artistBeginDate, STG.personDateBegin), (obj.artistEndDate, STG.personDateEnd)):
            if value and value.lstrip("-").isdigit():
                g.add((primary, prop, Literal(int(value), datatype=XSD.integer)))
        for value, prop in ((obj.artistULAN_URL, STG.ulanId), (obj.artistWikidata_URL, STG.wikidataId)):
            if value:
                g.add((primary, prop, URIRef(value)))


def _aat(g: Graph, s: URIRef, prop: URIRef, term: str, category: str) -> None:
    uri = aat_mappings.get_aat_uri(term, category=category)
    if uri:
        g.add((s, prop, URIRef(uri)))


class MetHarvester(Harvester):
    def __init__(self, client: Optional[MetClient] = None) -> None:
        self.client = client or MetClient()

    def fetch(
        self,
        limit: Optional[int] = None,
        department_id: int = GREEK_AND_ROMAN_ART,
        **kwargs,
    ) -> Iterable[MetObject]:
        ids = self.client.object_ids(department_id)
        return self.client.iter_objects(ids, limit=limit)

    def stage(self, records: Iterable[MetObject], out_path: Path) -> Graph:
        g = Graph()
        g.bind("stg", STG)
        g.bind("exs", EXS)
        for obj in records:
            met_object_to_staging(g, obj)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        return g


def main() -> None:
    ap = argparse.ArgumentParser(description="Harvest Met Greek and Roman Art objects into staging RDF.")
    ap.add_argument("--out", type=Path, default=Path("data/staging/met_staging.ttl"))
    ap.add_argument("--department", type=int, default=GREEK_AND_ROMAN_ART)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    MetHarvester(MetClient(use_cache=not args.no_cache)).run(
        args.out, limit=args.limit, department_id=args.department
    )


if __name__ == "__main__":
    main()
