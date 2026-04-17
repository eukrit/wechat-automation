"""Batch-enrich existing products in wechat_products with category + subcategory.

Uses Gemini to classify products by name. Sends batches of 50 at a time.

Usage:
    python -m scripts.enrich_categories [--force] [--limit N]
    --force: re-enrich even if category already set
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_automation import firestore_store

logger = logging.getLogger(__name__)

CATEGORIES = [
    "Lighting", "Furniture", "Playground Equipment", "Flooring", "Hardware",
    "Bathroom/Sanitary", "Kitchen", "Textile/Fabric", "Outdoor/Garden",
    "Sports Equipment", "Climbing Wall", "Water Play", "Window/Door",
    "Wall Panel/Cladding", "Decor/Accessories", "Carpet/Rug", "Umbrella/Shade",
    "HVAC", "Other",
]

BATCH_PROMPT = """You are a product classifier. For each product below, assign:
1. "category": ONE of: Lighting, Furniture, Playground Equipment, Flooring, Hardware,
   Bathroom/Sanitary, Kitchen, Textile/Fabric, Outdoor/Garden, Sports Equipment,
   Climbing Wall, Water Play, Window/Door, Wall Panel/Cladding, Decor/Accessories,
   Carpet/Rug, Umbrella/Shade, HVAC, Other
2. "subcategory": specific sub-type (e.g., "Pendant Lamp", "Sofa", "SPC Flooring", "Hinge",
   "Water Slide", "Climbing Hold", "Outdoor Dining Table", "Toilet", "Kitchen Cabinet")

Return a JSON array with same order as input, each item = {"category": "...", "subcategory": "..."}.
Return ONLY the JSON array, no other text.

Products:
"""


def classify_batch(products: list[dict]) -> list[dict]:
    """Send a batch of products to Gemini, return list of {category, subcategory}."""
    from extractors.gemini_extractor import _init_vertex, MODEL_NAME
    from vertexai.generative_models import GenerativeModel

    _init_vertex()
    model = GenerativeModel(MODEL_NAME)

    # Build product list for prompt
    items = []
    for i, p in enumerate(products, 1):
        name = p.get("product_name", "")
        sku = p.get("sku", "")
        desc = p.get("description", "")[:80]
        material = p.get("material", "")[:40]
        vendor = p.get("vendor_name", "")
        items.append(f"{i}. name={name!r} sku={sku!r} desc={desc!r} material={material!r} vendor={vendor!r}")

    prompt = BATCH_PROMPT + "\n".join(items)

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1, "max_output_tokens": 32768},
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except Exception as e:
        logger.error("Batch classification failed: %s", e)

    return [{"category": "Other", "subcategory": ""} for _ in products]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-enrich all products")
    parser.add_argument("--limit", type=int, default=0, help="Max products to process")
    parser.add_argument("--batch-size", type=int, default=50, help="Products per Gemini call")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = firestore_store._db()
    logger.info("Loading all products...")
    all_products = [(d.id, d.to_dict()) for d in db.collection("wechat_products").stream()]

    # Filter to those needing enrichment
    if args.force:
        targets = all_products
    else:
        targets = [
            (pid, p) for pid, p in all_products
            if not p.get("subcategory", "").strip()
        ]

    if args.limit:
        targets = targets[:args.limit]

    logger.info("Target products: %d / %d total", len(targets), len(all_products))

    total_updated = 0
    for batch_start in range(0, len(targets), args.batch_size):
        batch = targets[batch_start:batch_start + args.batch_size]
        batch_products = [p for _, p in batch]

        logger.info("Batch %d-%d / %d", batch_start + 1, batch_start + len(batch), len(targets))
        classifications = classify_batch(batch_products)

        if len(classifications) != len(batch):
            logger.warning("  Size mismatch: got %d, expected %d", len(classifications), len(batch))
            # Pad or truncate
            while len(classifications) < len(batch):
                classifications.append({"category": "Other", "subcategory": ""})
            classifications = classifications[:len(batch)]

        # Update products in Firestore
        for (pid, p), cls in zip(batch, classifications):
            cat = str(cls.get("category", "") or "").strip()
            subcat = str(cls.get("subcategory", "") or "").strip()

            # Preserve existing category if Gemini returns empty
            if not cat:
                cat = p.get("category", "") or "Other"

            try:
                db.collection("wechat_products").document(pid).update({
                    "category": cat,
                    "subcategory": subcat,
                })
                total_updated += 1
            except Exception as e:
                logger.error("  Failed to update %s: %s", pid, e)

        logger.info("  Updated %d products in batch (total: %d)", len(batch), total_updated)

    logger.info("=== Summary ===")
    logger.info("Total products updated: %d", total_updated)


if __name__ == "__main__":
    main()
