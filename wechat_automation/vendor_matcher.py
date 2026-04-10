"""Fuzzy vendor matching against go_vendors and people_contacts.

Matches vendor names extracted from filenames against:
1. go_vendors collection in shipping-automation DB
2. people_contacts collection in default DB
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from wechat_automation import firestore_store

logger = logging.getLogger(__name__)


@dataclass
class VendorMatch:
    vendor_id: str = ""
    vendor_name: str = ""
    match_method: str = ""  # filename_exact | filename_fuzzy | folder_name | people_contact
    confidence: float = 0.0
    people_contact_id: str = ""
    peak_contact_code: str = ""


class VendorMatcher:
    """Matches vendor names against known vendors across databases."""

    def __init__(self, threshold: int = 85) -> None:
        self._threshold = threshold
        self._vendors: list[dict] = []
        self._people: list[dict] = []
        self._vendor_names: dict[str, dict] = {}  # lowercase name -> vendor dict
        self._people_names: dict[str, dict] = {}  # lowercase name -> contact dict
        self._loaded = False

    def _load(self) -> None:
        """Lazy-load vendor and people data from Firestore."""
        if self._loaded:
            return
        try:
            self._vendors = firestore_store.get_go_vendors()
            for v in self._vendors:
                name = v.get("name", "")
                if name:
                    self._vendor_names[name.lower()] = v
                    # Also index any aliases
                    for alias in v.get("aliases", []):
                        if alias:
                            self._vendor_names[alias.lower()] = v
        except Exception as e:
            logger.warning("Could not load go_vendors: %s", e)

        try:
            self._people = firestore_store.get_people_contacts()
            for p in self._people:
                for name_field in ("full_name", "first_name", "last_name"):
                    name = p.get(name_field, "")
                    if name and len(name) > 1:
                        self._people_names[name.lower()] = p
        except Exception as e:
            logger.warning("Could not load people_contacts: %s", e)

        self._loaded = True

    def match(self, vendor_hint: str, folder_name: str = "") -> VendorMatch:
        """Try to match a vendor name using multiple strategies.

        Args:
            vendor_hint: Vendor name extracted from filename.
            folder_name: Source folder name (for WeChat OneDrive folders with vendor names).
        """
        self._load()

        # Strategy 1: Folder name match (WeChat OneDrive folders have vendor names)
        if folder_name:
            result = self._match_text(folder_name, method="folder_name")
            if result.vendor_id:
                return result

        # Strategy 2: Filename vendor hint
        if vendor_hint:
            result = self._match_text(vendor_hint, method="filename")
            if result.vendor_id:
                return result

        # Strategy 3: People contact name match -> resolve to vendor
        if vendor_hint:
            result = self._match_people(vendor_hint)
            if result.vendor_id:
                return result

        return VendorMatch()

    def _match_text(self, text: str, method: str) -> VendorMatch:
        """Match text against vendor names."""
        if not self._vendor_names:
            return VendorMatch()

        text_lower = text.lower()

        # Exact substring match
        for vname, vdata in self._vendor_names.items():
            if vname in text_lower or text_lower in vname:
                return VendorMatch(
                    vendor_id=vdata.get("_doc_id", ""),
                    vendor_name=vdata.get("name", ""),
                    match_method=f"{method}_exact",
                    confidence=1.0,
                )

        # Fuzzy match
        vendor_list = list(self._vendor_names.keys())
        results = process.extract(
            text_lower,
            vendor_list,
            scorer=fuzz.token_set_ratio,
            limit=3,
        )
        if results and results[0][1] >= self._threshold:
            best_name = results[0][0]
            vdata = self._vendor_names[best_name]
            return VendorMatch(
                vendor_id=vdata.get("_doc_id", ""),
                vendor_name=vdata.get("name", ""),
                match_method=f"{method}_fuzzy",
                confidence=results[0][1] / 100.0,
            )

        return VendorMatch()

    def _match_people(self, text: str) -> VendorMatch:
        """Match against people_contacts, then resolve to vendor via company_name."""
        if not self._people_names:
            return VendorMatch()

        text_lower = text.lower()
        people_list = list(self._people_names.keys())
        results = process.extract(
            text_lower,
            people_list,
            scorer=fuzz.token_set_ratio,
            limit=3,
        )

        if results and results[0][1] >= self._threshold:
            person = self._people_names[results[0][0]]
            company = person.get("company_name", "")

            # Try to resolve company to a vendor
            if company:
                vendor_match = self._match_text(company, method="people_contact")
                if vendor_match.vendor_id:
                    vendor_match.people_contact_id = person.get("_doc_id", "")
                    vendor_match.peak_contact_code = person.get("peak_contact_code", "")
                    return vendor_match

            # Even without vendor resolution, return the contact info
            return VendorMatch(
                people_contact_id=person.get("_doc_id", ""),
                peak_contact_code=person.get("peak_contact_code", ""),
                match_method="people_contact",
                confidence=results[0][1] / 100.0,
                vendor_name=company,
            )

        return VendorMatch()

    def reload(self) -> None:
        """Force reload of vendor and people data."""
        self._loaded = False
        self._vendor_names.clear()
        self._people_names.clear()
        self._load()
