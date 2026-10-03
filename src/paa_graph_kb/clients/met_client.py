"""
Met Public API by Department GREEK_AND_ROMAN_ART only

"""

from __future__ import annotations

import os
from typing import Iterable, Iterator, List, Optional

import requests
from dotenv import load_dotenv
from pydantic import ValidationError

from paa_graph_kb.clients.base_client import Client
from paa_graph_kb.models.met.models import MetObject

load_dotenv()

GREEK_AND_ROMAN_ART = 13  # Met department id


class MetClient(Client):
    """Metropolitan Museum of Art Collection API client (no key; see https://metmuseum.github.io/)."""

    def __init__(self, cache_dir: Optional[str] = None, use_cache: bool = True) -> None:
        if cache_dir is None:
            cache_dir = os.getenv("MET_OBJ_DIR", "data/met/objects")
        super().__init__(
            os.getenv("MET_API_BASE", "https://collectionapi.metmuseum.org/public/collection/v1"),
            cache_dir=cache_dir,
            use_cache=use_cache,
        )

    def object_ids(
        self, department_id: int = GREEK_AND_ROMAN_ART, metadata_date: Optional[str] = None
    ) -> List[int]:
        """All object ids in a department (optionally only those updated after metadata_date, YYYY-MM-DD).

        /objects is the only endpoint that lists a department completely; /v1.1/search caps at 10,000 results.
        The id list is never served from the file cache, so reruns pick up new accessions.
        """
        params = {"departmentIds": department_id, "metadataDate": metadata_date}
        use_cache, self.use_cache = self.use_cache, False
        try:
            data = self._request(self._endpoint("objects"), params=params)
        finally:
            self.use_cache = use_cache
        return data.get("objectIDs") or []

    def get_object(self, object_id: int) -> MetObject:
        return MetObject.model_validate(self._request(self._endpoint(f"objects/{object_id}")))

    def iter_objects(
        self, object_ids: Iterable[int], *, limit: Optional[int] = None, strict: bool = False
    ) -> Iterator[MetObject]:
        yielded = 0
        for oid in object_ids:
            if limit is not None and yielded >= limit:
                return
            try:
                yield self.get_object(oid)
            except ValidationError:
                if strict:
                    raise
                continue
            except requests.HTTPError as e:
                # ids can disappear between listing and fetching (deaccessions); 404 is not an error
                if strict or e.response is None or e.response.status_code != 404:
                    raise
                continue
            yielded += 1
