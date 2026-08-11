"""Create Stripe Payment Links from agent-readable offer JSON files.

This script never reads secrets from files. Set STRIPE_SECRET_KEY in the environment when running
with --live. By default it runs as a dry run and prints what it would create.
"""

from __future__ import annotations

import argparse
import json
import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFFERS = sorted((ROOT / "offers").glob("*.json"))
CHECKOUT_SUCCESS_URL = "https://wesseltl.github.io/pdf-mcp/success.html"
RECURRING_BILLING = {
    "monthly": {"interval": "month"},
    "yearly": {"interval": "year"},
}
LIVE_SELLER_FIELDS = (
    "business_registration_number",
    "business_address",
    "phone",
)


def amount_to_minor_units(amount: str) -> int:
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def stripe_key_mode(api_key: str) -> str:
    """Identify Stripe test/live mode without exposing the key."""
    if api_key.startswith(("sk_test_", "rk_test_")):
        return "test"
    if api_key.startswith(("sk_live_", "rk_live_")):
        return "live"
    raise ValueError("STRIPE_SECRET_KEY must be a Stripe secret or restricted key")


def require_live_seller_identity(offer: dict) -> None:
    """Refuse live commerce until legally identifying seller fields are present."""
    seller = offer.get("seller", {})
    missing = [field for field in LIVE_SELLER_FIELDS if not seller.get(field)]
    if not (seller.get("vat_id") or seller.get("vat_status")):
        missing.append("vat_id or vat_status")
    if missing:
        raise SystemExit(
            f"{offer.get('offer_id', 'offer')}: live checkout requires seller metadata: "
            + ", ".join(missing)
        )


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
    offer_price = offer["price"]
    amount = amount_to_minor_units(offer_price["amount"])
    currency = offer_price["currency"].lower()
    billing = offer_price.get("billing", "one_time")
    if billing != "one_time" and billing not in RECURRING_BILLING:
        raise ValueError("price.billing must be one_time, monthly, or yearly")
    recurring = RECURRING_BILLING.get(billing)
    success_url = CHECKOUT_SUCCESS_URL
    if recurring is not None:
        success_url = _subscription_success_url(offer)
    price = {
        "currency": currency,
        "unit_amount": amount,
        "tax_behavior": "exclusive",
        "metadata": stripe_metadata(offer),
    }
    if recurring is not None:
        price["recurring"] = recurring
    return {
        "product": {
            "name": offer["name"],
            "description": offer["summary"][:500],
            "metadata": stripe_metadata(offer),
        },
        "price": price,
        "payment_link": {
            "line_items": [{"quantity": 1}],
            "automatic_tax": {"enabled": True},
            "billing_address_collection": "required",
            "tax_id_collection": {"enabled": True},
            "after_completion": {
                "type": "redirect",
                "redirect": {"url": success_url},
            },
            "metadata": stripe_metadata(offer),
        },
    }


def _subscription_success_url(offer: dict) -> str:
    fulfillment = offer.get("fulfillment")
    if (
        not isinstance(fulfillment, dict)
        or fulfillment.get("mode") != "webhook_entitlement"
    ):
        raise ValueError(
            "recurring offers require fulfillment.mode=webhook_entitlement"
        )
    entitlement_id = fulfillment.get("entitlement_id")
    if not isinstance(entitlement_id, str) or not entitlement_id.strip():
        raise ValueError("recurring offers require a fulfillment entitlement_id")
    success_url = fulfillment.get("success_url")
    if not isinstance(success_url, str):
        raise TypeError("recurring offers require a fulfillment success_url")
    parsed = urlparse(success_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or "{CHECKOUT_SESSION_ID}" not in success_url
    ):
        raise ValueError(
            "subscription success_url must be HTTPS and contain {CHECKOUT_SESSION_ID}"
        )
    return success_url


def upsert_stripe_method(offer: dict, checkout_url: str) -> None:
    offer["checkout_url"] = checkout_url
    methods = [
        method
        for method in offer.get("purchase_methods", [])
        if method.get("type") != "stripe_payment_link"
    ]
    methods.insert(
        0,
        {
            "type": "stripe_payment_link",
            "url": checkout_url,
            "requires_user_confirmation": True,
        },
    )
    offer["purchase_methods"] = methods
    offer["agent_instructions"]["recommended_action"] = (
        "Show the current scope and terms, ask the user for explicit approval, then direct them "
        "to the Stripe checkout URL. Never email or upload the document during checkout."
    )


def create_payment_link(offer: dict, expected_mode: str | None = None) -> dict:
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        raise SystemExit("STRIPE_SECRET_KEY is required for --live")
    try:
        mode = stripe_key_mode(api_key)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if expected_mode and mode != expected_mode:
        raise SystemExit(
            f"Stripe key is in {mode} mode, but --expected-mode is {expected_mode}."
        )
    if mode == "live":
        require_live_seller_identity(offer)
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
        "stripe_mode": mode,
    }


def process_offer(
    path: Path,
    live: bool,
    write: bool,
    force: bool,
    expected_mode: str | None = None,
) -> dict:
    offer = load_offer(path)
    if offer.get("checkout_url") and not force:
        return {
            "path": str(path),
            "status": "skipped_existing_checkout_url",
            "checkout_url": offer["checkout_url"],
        }

    plan = build_creation_plan(offer)
    if not live:
        return {"path": str(path), "status": "dry_run", "plan": plan}

    result = create_payment_link(offer, expected_mode=expected_mode)
    if result["stripe_mode"] == "test":
        if write:
            raise SystemExit(
                "Test checkout URLs cannot be written to published offer files."
            )
        return {
            "path": str(path),
            "status": "created_test",
            **result,
            "wrote_file": False,
        }

    offer["stripe"] = {
        "product_id": result["product_id"],
        "price_id": result["price_id"],
        "payment_link_id": result["payment_link_id"],
        "mode": result["stripe_mode"],
    }
    upsert_stripe_method(offer, result["checkout_url"])
    offer["status"] = "available"
    if write:
        save_offer(path, offer)
    return {"path": str(path), "status": "created", **result, "wrote_file": write}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create Stripe Payment Links from offers/*.json."
    )
    parser.add_argument("offers", nargs="*", type=Path, default=DEFAULT_OFFERS)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call Stripe and create objects in the mode selected by the API key.",
    )
    parser.add_argument(
        "--write", action="store_true", help="Write checkout URLs back to offer JSON."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create a new link even if checkout_url exists.",
    )
    parser.add_argument(
        "--expected-mode",
        choices=("test", "live"),
        help="Required with --live; abort if the Stripe key is in the other mode.",
    )
    args = parser.parse_args()
    if args.live and not args.expected_mode:
        raise SystemExit(
            "--live calls Stripe; pass --expected-mode test or --expected-mode live."
        )
    if args.live and args.expected_mode == "live" and not args.write:
        raise SystemExit(
            "Live checkout creation requires --write so the URLs are not lost."
        )
    if args.live and args.expected_mode == "test" and args.write:
        raise SystemExit(
            "Test checkout URLs cannot be written to published offer files."
        )
    if not args.live and args.expected_mode:
        raise SystemExit("--expected-mode is only valid with --live.")

    results = [
        process_offer(
            path,
            live=args.live,
            write=args.write,
            force=args.force,
            expected_mode=args.expected_mode,
        )
        for path in args.offers
    ]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
