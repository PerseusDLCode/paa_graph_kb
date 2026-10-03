from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from paa_graph_kb.clients.met_client import MetClient
from paa_graph_kb.harvesters.met_harvester import MetHarvester, met_object_to_staging
from paa_graph_kb.models.met.models import MetObject

STG = Namespace("https://aa.perseus.org/staging#")
EXS = Namespace("https://aa.perseus.org/staging/")


@pytest.fixture
def sample_object_data():
    return {
        "objectID": 254904,
        "accessionNumber": "56.171.49",
        "accessionYear": "1956",
        "isPublicDomain": True,
        "department": "Greek and Roman Art",
        "objectName": "Kylix",
        "title": "Terracotta kylix (drinking cup)",
        "culture": "Greek, Attic",
        "period": "Archaic",
        "objectDate": "ca. 520 BCE",
        "objectBeginDate": -530,
        "objectEndDate": -510,
        "medium": "Terracotta",
        "dimensions": "H. 4 1/4 in. (10.8 cm)",
        "creditLine": "Fletcher Fund, 1956",
        "classification": "Vases",
        "country": "",
        "region": "",
        "primaryImage": "https://images.metmuseum.org/CRDImages/gr/original/x.jpg",
        "primaryImageSmall": "https://images.metmuseum.org/CRDImages/gr/web-large/x.jpg",
        "additionalImages": ["https://images.metmuseum.org/CRDImages/gr/original/y.jpg", ""],
        "constituents": [{"constituentID": 161, "role": "Artist", "name": "Attributed to the Amasis Painter",
                           "constituentULAN_URL": "http://vocab.getty.edu/page/ulan/500028012",
                           "constituentWikidata_URL": "", "gender": ""}],
        "tags": [{"term": "Dionysus", "AAT_URL": "http://vocab.getty.edu/page/aat/300343813",
                  "Wikidata_URL": "https://www.wikidata.org/wiki/Q41680"}],
        "objectURL": "https://www.metmuseum.org/art/collection/search/254904",
        "objectWikidata_URL": "",
        "GalleryNumber": "171",
        "measurements": [{"elementName": "Overall", "elementDescription": None, "elementMeasurements": {"Height": 10.8}}],
    }


@pytest.fixture
def client(tmp_path):
    return MetClient(cache_dir=str(tmp_path / "cache"))


def test_model_normalises_blanks(sample_object_data):
    obj = MetObject.model_validate(sample_object_data)
    assert obj.accessionYear == 1956
    assert obj.country is None and obj.objectWikidata_URL is None
    assert len(obj.additionalImages) == 1
    assert obj.constituents[0].constituentWikidata_URL is None


def test_object_ids_bypasses_cache(client):
    with patch.object(client, "_request", return_value={"total": 2, "objectIDs": [1, 2]}) as req:
        assert client.object_ids(13) == [1, 2]
        assert req.call_args.kwargs["params"] == {"departmentIds": 13}
        assert client.use_cache is True  # restored after the call


def test_iter_objects_skips_404(client, sample_object_data):
    def fake(url, params=None):
        if url.endswith("/objects/9"):
            resp = requests.Response(); resp.status_code = 404
            raise requests.HTTPError(response=resp)
        return sample_object_data

    with patch.object(client, "_request", side_effect=fake):
        got = list(client.iter_objects([254904, 9, 254904], limit=2))
    assert [o.objectID for o in got] == [254904, 254904]


def test_staging_mapping(sample_object_data):
    g = Graph()
    met_object_to_staging(g, MetObject.model_validate(sample_object_data))
    s = EXS["o/met:254904"]
    assert (s, RDF.type, STG.Object) in g
    assert (s, STG.source, Literal("met")) in g
    assert (s, STG.objectnumber, Literal("56.171.49")) in g
    assert (s, STG.datebegin, Literal(-530, datatype=XSD.integer)) in g
    assert (s, STG.cultureAAT, URIRef("http://vocab.getty.edu/aat/300386130")) in g  # "Greek" from "Greek, Attic"
    assert (s, STG.materialAAT, URIRef("http://vocab.getty.edu/aat/300010669")) in g
    assert (s, STG.subject, Literal("Dionysus", lang="en")) in g
    assert len(list(g.objects(s, STG.hasImage))) == 2
    person = URIRef("https://aa.perseus.org/staging/person/met:161")
    assert (s, STG.hasPerson, person) in g
    assert (person, STG.ulanId, URIRef("http://vocab.getty.edu/page/ulan/500028012")) in g
    assert not list(g.objects(s, STG.placeLabel))  # blanks produce no place triple


def test_harvester_run(tmp_path, client, sample_object_data):
    with patch.object(client, "_request", side_effect=lambda url, params=None:
                      {"objectIDs": [254904, 1]} if url.endswith("/objects") else sample_object_data):
        out = MetHarvester(client).run(tmp_path / "staging" / "met.ttl", limit=1)
    g = Graph().parse(out, format="turtle")
    assert len(list(g.subjects(RDF.type, STG.Object))) == 1


def test_awkward_real_world_values_do_not_drop_record(sample_object_data):
    d = dict(sample_object_data)
    d["primaryImage"] = "https://images.metmuseum.org/CRDImages/gr/original/DP 1234 (detail).jpg"  # space + parens
    d["measurements"] = [{"elementName": "Overall", "elementMeasurements": None}, None]
    d["constituents"] = [{"constituentID": None, "role": "Artist", "name": "Unknown"}]
    d["tags"] = [{"term": None, "AAT_URL": None}]
    obj = MetObject.model_validate(d)
    assert obj.primaryImage.endswith("(detail).jpg")
    assert len(obj.measurements) == 1
    g = Graph()
    met_object_to_staging(g, obj)
    assert not list(g.objects(EXS["o/met:254904"], STG.subject))
    assert not list(g.objects(EXS["o/met:254904"], STG.hasPerson))


def test_every_model_field_is_mapped():
    """Each MetObject field must be referenced by met_object_to_staging."""
    import inspect
    from paa_graph_kb.harvesters import met_harvester
    src = inspect.getsource(met_harvester.met_object_to_staging)
    missing = [f for f in MetObject.model_fields if f"obj.{f}" not in src]
    assert not missing, missing


def test_full_record_round_trip(sample_object_data):
    d = dict(sample_object_data, isHighlight=True, isTimelineWork=True, dynasty="", reign="", portfolio="Series A",
             artistRole="Artist", artistPrefix="Attributed to", artistDisplayName="Attributed to the Amasis Painter",
             artistDisplayBio="Greek, active ca. 560–515 BCE", artistSuffix="", artistAlphaSort="Amasis Painter",
             artistNationality="Greek", artistBeginDate="-560", artistEndDate="-515", artistGender="",
             artistWikidata_URL="https://www.wikidata.org/wiki/Q1", artistULAN_URL="http://vocab.getty.edu/page/ulan/500028012",
             geographyType="Found in", country="Italy", region="Etruria", locale="Vulci", excavation="", river="",
             rightsAndReproduction="", linkResource="", repository="Metropolitan Museum of Art, New York, NY",
             metadataDate="2025-03-01T10:00:00.000Z", dimensionsParsed=[{"element": "Overall", "dimensionType": "Height", "dimension": 10.8}])
    g = Graph()
    met_object_to_staging(g, MetObject.model_validate(d))
    s = EXS["o/met:254904"]
    assert (s, STG.isHighlight, Literal(True)) in g
    assert (s, STG.geographyType, Literal("Found in")) in g
    assert (s, STG.placeLabel, Literal("Vulci, Etruria, Italy", lang="en")) in g
    assert (s, STG.metadataDate, Literal("2025-03-01T10:00:00.000Z", datatype=XSD.dateTime)) in g
    assert (s, STG.subjectWikidata, URIRef("https://www.wikidata.org/wiki/Q41680")) in g
    m = next(g.objects(s, STG.hasMeasurement))  # from `measurements`, not dimensionsParsed
    assert (m, STG.measurementType, Literal("Height")) in g and (m, STG.measurementUnit, Literal("cm")) in g
    person = URIRef("https://aa.perseus.org/staging/person/met:161")
    assert (person, STG.personPrefix, Literal("Attributed to")) in g
    assert (person, STG.personDateBegin, Literal(-560, datatype=XSD.integer)) in g
    assert (person, STG.wikidataId, URIRef("https://www.wikidata.org/wiki/Q1")) in g
    assert len(list(g.objects(s, STG.hasPerson))) == 1  # artist* merged onto the constituent, no duplicate node
    assert not list(g.objects(s, STG.dynasty))  # empty -> no triple


DOCUMENTED_FIELDS = """objectID isHighlight accessionNumber accessionYear isPublicDomain primaryImage primaryImageSmall
additionalImages constituents department objectName title culture period dynasty reign portfolio artistRole
artistPrefix artistDisplayName artistDisplayBio artistSuffix artistAlphaSort artistNationality artistBeginDate
artistEndDate artistGender artistWikidata_URL artistULAN_URL objectDate objectBeginDate objectEndDate medium
dimensions dimensionsParsed measurements creditLine geographyType city state county country region subregion locale
locus excavation river classification rightsAndReproduction linkResource metadataDate repository objectURL tags
objectWikidata_URL isTimelineWork GalleryNumber""".split()  # https://metmuseum.github.io/#object


def test_model_matches_api_documentation():
    assert len(DOCUMENTED_FIELDS) == 58
    assert set(DOCUMENTED_FIELDS) == set(MetObject.model_fields)
