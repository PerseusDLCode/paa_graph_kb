from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def _blank_to_none(v: Any) -> Any:
    return None if isinstance(v, str) and not v.strip() else v


class Constituent(BaseModel):
    constituentID: int
    role: Optional[str] = None
    name: Optional[str] = None
    constituentULAN_URL: Optional[HttpUrl] = None
    constituentWikidata_URL: Optional[HttpUrl] = None
    gender: Optional[str] = None

    model_config = ConfigDict(extra="ignore")

    _blank = field_validator("constituentULAN_URL", "constituentWikidata_URL", mode="before")(_blank_to_none)


class Tag(BaseModel):
    term: str
    AAT_URL: Optional[HttpUrl] = None
    Wikidata_URL: Optional[HttpUrl] = None

    model_config = ConfigDict(extra="ignore")

    _blank = field_validator("AAT_URL", "Wikidata_URL", mode="before")(_blank_to_none)


class Measurement(BaseModel):
    elementName: Optional[str] = None
    elementDescription: Optional[str] = None
    elementMeasurements: dict[str, float] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class MetObject(BaseModel):
    """One record from GET /public/collection/v1/objects/{objectID}."""

    objectID: int
    accessionNumber: Optional[str] = None
    accessionYear: Optional[int] = None
    isPublicDomain: bool = False
    isHighlight: bool = False

    department: Optional[str] = None
    objectName: Optional[str] = None
    title: Optional[str] = None
    culture: Optional[str] = None
    period: Optional[str] = None
    dynasty: Optional[str] = None
    reign: Optional[str] = None
    classification: Optional[str] = None

    objectDate: Optional[str] = None
    objectBeginDate: Optional[int] = None
    objectEndDate: Optional[int] = None

    medium: Optional[str] = None
    dimensions: Optional[str] = None
    measurements: Optional[List[Measurement]] = None
    creditLine: Optional[str] = None

    geographyType: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    county: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    subregion: Optional[str] = None
    locale: Optional[str] = None
    locus: Optional[str] = None
    excavation: Optional[str] = None

    primaryImage: Optional[HttpUrl] = None
    primaryImageSmall: Optional[HttpUrl] = None
    additionalImages: List[HttpUrl] = Field(default_factory=list)

    constituents: Optional[List[Constituent]] = None
    tags: Optional[List[Tag]] = None

    objectURL: Optional[HttpUrl] = None
    objectWikidata_URL: Optional[HttpUrl] = None
    GalleryNumber: Optional[str] = None
    metadataDate: Optional[str] = None

    model_config = ConfigDict(extra="ignore")

    _blank = field_validator(
        "accessionNumber", "department", "objectName", "title", "culture", "period", "dynasty", "reign",
        "classification", "objectDate", "medium", "dimensions", "creditLine", "geographyType", "city", "state",
        "county", "country", "region", "subregion", "locale", "locus", "excavation", "primaryImage",
        "primaryImageSmall", "objectURL", "objectWikidata_URL", "GalleryNumber", "accessionYear",
        mode="before",
    )(_blank_to_none)

    @field_validator("additionalImages", mode="before")
    @classmethod
    def _drop_blank_urls(cls, v: Any) -> Any:
        return [u for u in (v or []) if isinstance(u, str) and u.strip()]
