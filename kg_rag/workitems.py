"""Azure DevOps REST API client for fetching and caching work item details."""

from __future__ import annotations

import json
import logging
from base64 import b64encode
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kg_rag.config import settings
from kg_rag.models import CodeEntityType, Entity, KnowledgeGraph

logger = logging.getLogger(__name__)

# ADO REST API returns work items in batches of up to 200
_ADO_BATCH_SIZE = 200


class AdoClient:
    """Lightweight Azure DevOps REST API client (stdlib only — no ``requests`` dep).

    Config is read from environment / ``.env``::

        ADO_ORG=my-org            # Azure DevOps organisation name
        ADO_PROJECT=my-project    # Project name (optional — for scoping queries)
        ADO_PAT=xxxxxxxx          # Personal Access Token with Work Items read scope
    """

    def __init__(
        self,
        org: str | None = None,
        project: str | None = None,
        pat: str | None = None,
    ):
        import os
        self.org = org or os.getenv("ADO_ORG", "")
        self.project = project or os.getenv("ADO_PROJECT", "")
        self.pat = pat or os.getenv("ADO_PAT", "")
        if not self.org or not self.pat:
            raise ValueError(
                "ADO_ORG and ADO_PAT must be set (in .env or environment) "
                "to use Azure DevOps work item hydration."
            )
        # Basic auth header: base64(":" + PAT)
        token = b64encode(f":{self.pat}".encode()).decode()
        self._auth_header = f"Basic {token}"
        self._base = f"https://dev.azure.com/{self.org}"

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _get(self, url: str) -> Any:
        """Issue a GET request and return parsed JSON."""
        req = Request(url, headers={
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
        })
        with urlopen(req, timeout=30) as resp:  # noqa: S310 — trusted ADO URL
            return json.loads(resp.read().decode())

    def _post(self, url: str, body: Any) -> Any:
        """Issue a POST request with a JSON body and return parsed JSON."""
        data = json.dumps(body).encode()
        req = Request(url, data=data, method="POST", headers={
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
        })
        with urlopen(req, timeout=30) as resp:  # noqa: S310 — trusted ADO URL
            return json.loads(resp.read().decode())

    # ------------------------------------------------------------------
    # Work Item API
    # ------------------------------------------------------------------

    def get_work_items(self, ids: list[int]) -> list[dict[str, Any]]:
        """Fetch work items by ID, in batches of 200.

        Returns a flat list of work-item dicts, each containing at minimum:
        ``id``, ``title``, ``work_item_type``, ``state``, ``description``,
        ``tags``, ``area_path``.
        """
        results: list[dict[str, Any]] = []
        for i in range(0, len(ids), _ADO_BATCH_SIZE):
            batch = ids[i : i + _ADO_BATCH_SIZE]
            id_str = ",".join(str(x) for x in batch)
            fields = "System.Title,System.WorkItemType,System.State,System.Description,System.Tags,System.AreaPath"
            url = (
                f"{self._base}/_apis/wit/workitems?ids={id_str}"
                f"&fields={fields}&api-version=7.1"
            )
            try:
                data = self._get(url)
            except (HTTPError, URLError) as exc:
                logger.warning("ADO API error for batch starting %s: %s", batch[0], exc)
                continue

            for item in data.get("value", []):
                fields_map = item.get("fields", {})
                results.append({
                    "id": item["id"],
                    "title": fields_map.get("System.Title", ""),
                    "work_item_type": fields_map.get("System.WorkItemType", ""),
                    "state": fields_map.get("System.State", ""),
                    "description": _strip_html(fields_map.get("System.Description", "") or ""),
                    "tags": fields_map.get("System.Tags", ""),
                    "area_path": fields_map.get("System.AreaPath", ""),
                })
        return results


# ======================================================================
# Cache management
# ======================================================================

_CACHE_FILE = "workitems_cache.json"


def _cache_path() -> Path:
    return settings.DATA_DIR / _CACHE_FILE


def load_cache() -> dict[str, dict[str, Any]]:
    """Load the local work-item cache. Returns ``{id_str: {...}}``."""
    path = _cache_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(cache: dict[str, dict[str, Any]]) -> Path:
    """Persist the work-item cache to disk."""
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ======================================================================
# Hydration: fetch from ADO, update cache, enrich KG
# ======================================================================

def hydrate_work_items(kg: KnowledgeGraph) -> int:
    """Fetch details for all work_item entities in *kg* from Azure DevOps.

    - Reads the local cache first; only fetches missing/new IDs from the API.
    - Updates each work_item entity's metadata and name with title/type/state.
    - Returns the number of work items successfully hydrated.
    """
    # Collect work_item IDs from the graph
    wi_entities = [e for e in kg.entities if e.entity_type == CodeEntityType.WORK_ITEM]
    if not wi_entities:
        return 0

    # Load cache
    cache = load_cache()

    # Determine which IDs need fetching
    ids_to_fetch: list[int] = []
    for e in wi_entities:
        wid = e.metadata.get("id", "")
        if wid and wid not in cache:
            try:
                ids_to_fetch.append(int(wid))
            except ValueError:
                pass

    # Fetch missing from ADO
    if ids_to_fetch:
        try:
            client = AdoClient()
            fetched = client.get_work_items(ids_to_fetch)
            for item in fetched:
                cache[str(item["id"])] = item
            save_cache(cache)
            logger.info("Fetched %d work items from ADO, cache now has %d", len(fetched), len(cache))
        except ValueError as exc:
            logger.warning("Skipping ADO fetch: %s", exc)
        except Exception as exc:
            logger.warning("ADO API call failed: %s", exc)

    # Hydrate entities from cache
    hydrated = 0
    for e in wi_entities:
        wid = e.metadata.get("id", "")
        if wid in cache:
            item = cache[wid]
            e.metadata["title"] = item.get("title", "")
            e.metadata["work_item_type"] = item.get("work_item_type", "")
            e.metadata["state"] = item.get("state", "")
            e.metadata["description"] = item.get("description", "")
            e.metadata["tags"] = item.get("tags", "")
            e.metadata["area_path"] = item.get("area_path", "")
            # Update the entity name to include the title
            title = item.get("title", "")
            if title:
                e.name = f"WI#{wid}: {title}"
            hydrated += 1

    return hydrated


# ======================================================================
# Helpers
# ======================================================================

def _strip_html(text: str) -> str:
    """Remove HTML tags from ADO description fields."""
    import re
    clean = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    return re.sub(r"\s+", " ", clean).strip()
