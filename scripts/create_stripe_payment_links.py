"""Create Stripe Payment Links from agent-readable offer JSON files.

This script never reads secrets from files. Set STRIPE_SECRET_KEY in the environment when running
with --live. By default it runs as a dry run and prints what it would create.
"""
from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFFERS = sorted((ROOT / "offers").glob("*.json"))


def amount_to_minor_units(amount: str) -> int:
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def load_offer(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_offer(path: Path, offer: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(offer, f, indent=2)
        f.write("\n")


def stripe_metadata(offer: dict) -> dict:
    return {
        "offer_id": offer["offer_id"],
        "source_repository": offer["source_repository"],
    }


def build_creation_plan(offer: dict) -> dict:
    amount = amount_to_minor_units(offer["price"]["amount"])
    currency = offer["price"]["currency"].lower()
    return {
        "product": {
            "name": offer["name"],
            "description": offer["summary"][:500],
            "metadata": stripe_metadata(offer),
        },
        "price": {
            "currency": currency,
            "unit_amount": amount,
            "metadata": stripe_metadata(offer),
        },
        "payment_link": {
            "line_items": [{"quantity": 1}],
            "metadata": stripe_metadata(offer),
        },
    }


def upsert_stripe_method(offer: dict, checkout_url: str) -> None:
    offer["checkout_url"] = checkout_url
    methods = [
        method for method in offer.get("purchase_methods", [])
        if method.get("type") != "stripe_payment_link"
    ]
    methods.insert(0, {
        "type": "stripe_payment_link",
        "url": checkout_url,
        "requires_user_confirmation": True,
    })
    offer["purchase_methods"] = methods
    offer["agent_instructions"]["recommended_action"] = (
        "Ask the user for approval, then direct them to the Stripe checkout URL."
    )


def create_payment_link(offer: dict) -> dict:
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        raise SystemExit("STRIPE_SECRET_KEY is required for --live")
    import stripe

    stripe.api_key = api_key
    plan = build_creation_plan(offer)
    product = stripe.Product.create(**plan["product"])
    price = stripe.Price.create(product=product.id, **plan["price"])
    link_params = plan["payment_link"]
    link_params["line_items"][0]["price"] = price.id
    payment_link = stripe.PaymentLink.create(**link_params)
    return {
        "product_id": product.id,
        "price_id": price.id,
        "payment_link_id": payment_link.id,
        "checkout_url": payment_link.url,
    }


def process_offer(path: Path, live: bool, write: bool, force: bool) -> dict:
    offer = load_offer(path)
    if offer.get("checkout_url") and not force:
        return {"path": str(path), "status": "skipped_existing_checkout_url",
                "checkout_url": offer["checkout_url"]}

    plan = build_creation_plan(offer)
    if not live:
        return {"path": str(path), "status": "dry_run", "plan": plan}

    result = create_payment_link(offer)
    offer["stripe"] = {
        "product_id": result["product_id"],
        "price_id": result["price_id"],
        "payment_link_id": result["payment_link_id"],
    }
    upsert_stripe_method(offer, result["checkout_url"])
    if write:
        save_offer(path, offer)
    return {"path": str(path), "status": "created", **result, "wrote_file": write}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create Stripe Payment Links from offers/*.json."
    )
    parser.add_argument("offers", nargs="*", type=Path, default=DEFAULT_OFFERS)
    parser.add_argument("--live", action="store_true", help="Create real Stripe objects.")
    parser.add_argument("--write", action="store_true", help="Write checkout URLs back to offer JSON.")
    parser.add_argument("--force", action="store_true", help="Create a new link even if checkout_url exists.")
    args = parser.parse_args()

    results = [
        process_offer(path, live=args.live, write=args.write, force=args.force)
        for path in args.offers
    ]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
