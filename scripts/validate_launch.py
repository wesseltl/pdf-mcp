"""Validate free-hosted and paid-beta metadata without conflating their launch gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OFFER_PATHS = sorted((ROOT / "offers").glob("*.json"))
BETA_PATH = ROOT / "beta" / "free-hosted-beta.json"
SMART_LAB_BETA_PATH = ROOT / "beta" / "smart-lab-index-beta.json"
PUBLIC_FILES = (
    ROOT / "BETA_TERMS.md",
    ROOT / "COMMERCIAL_TERMS.md",
    ROOT / "PRIVACY.md",
    ROOT / "PROFILE_FORMAT.md",
    ROOT / "EVALUATION.md",
    ROOT / "profile.schema.json",
    ROOT / "extraction-result.schema.json",
    BETA_PATH,
    SMART_LAB_BETA_PATH,
    ROOT / "docs" / "index.html",
    ROOT / "docs" / "beta-terms.html",
    ROOT / "docs" / "smart-lab-beta-terms.html",
    ROOT / "docs" / "terms.html",
    ROOT / "docs" / "privacy.html",
    ROOT / "docs" / "success.html",
    ROOT / "docs" / "styles.css",
    ROOT / "docs" / "offers.js",
    ROOT / "docs" / "assets" / "hero-profile-checked-v2.jpg",
    ROOT / "docs" / "assets" / "hero-profile-checked-v2.webp",
    ROOT / "docs" / "assets" / "smart-lab-index-workspace.png",
    ROOT / "docs" / "assets" / "smart-lab-index-workspace-mobile.png",
    ROOT / "docs" / "examples" / "sample-invoice.pdf",
    ROOT / "docs" / "examples" / "sample-invoice-output.xlsx",
)
LIVE_SELLER_FIELDS = (
    "business_registration_number",
    "business_address",
    "phone",
)


def load_offer(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_production_checkout_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "buy.stripe.com"
        and not parsed.path.startswith("/test_")
    )


def validate_offer(path: Path, offer: dict) -> list[str]:
    errors = []
    label = path.name

    if offer.get("audience") != "businesses_and_professionals_only":
        errors.append(f"{label}: offer must be B2B/professional only")
    if offer.get("price", {}).get("tax_included") is not False:
        errors.append(f"{label}: tax_included must be false")
    if not offer.get("included") or not offer.get("excluded"):
        errors.append(f"{label}: included and excluded scope must both be present")
    if not offer.get("refund_policy"):
        errors.append(f"{label}: refund policy is required")

    if offer.get("offer_id") == "document-to-excel-pilot":
        quality = offer.get("quality_contract", {})
        if quality.get("decision_states") != ["accepted", "needs_review", "rejected"]:
            errors.append(f"{label}: reliability decision states changed")
        required_metrics = {
            "field_precision",
            "field_recall",
            "field_f1",
            "exact_record_rate",
            "decision_accuracy",
        }
        if set(quality.get("evaluation_metrics", [])) != required_metrics:
            errors.append(f"{label}: reliability evaluation metrics changed")
        if quality.get("evaluation_report_excludes_cell_values") is not True:
            errors.append(f"{label}: evaluation reports must exclude cell values")

    handling = offer.get("data_handling", {})
    if handling.get("send_documents_by_email") is not False:
        errors.append(f"{label}: documents must not be accepted by email")
    if handling.get("working_files_deleted_days_after_delivery") != 14:
        errors.append(
            f"{label}: working-file retention must match the published 14-day policy"
        )

    instructions = offer.get("agent_instructions", {})
    if instructions.get("requires_user_confirmation") is not True:
        errors.append(f"{label}: agents must require user confirmation")
    if instructions.get("do_not_attach_documents_to_email") is not True:
        errors.append(f"{label}: agents must prohibit email attachments")

    checkout_url = offer.get("checkout_url")
    if checkout_url is None:
        if offer.get("status") != "accepting_requests":
            errors.append(
                f"{label}: an offer without checkout must be accepting_requests"
            )
        if not any(
            method.get("type") == "email_purchase_request"
            for method in offer.get("purchase_methods", [])
        ):
            errors.append(f"{label}: request-only offer needs an email request method")
        return errors

    if offer.get("status") != "available":
        errors.append(f"{label}: offer with checkout must have status available")
    if not is_production_checkout_url(checkout_url):
        errors.append(f"{label}: checkout URL must be a production buy.stripe.com URL")
    if offer.get("stripe", {}).get("mode") != "live":
        errors.append(f"{label}: checkout offer must record stripe.mode as live")

    seller = offer.get("seller", {})
    for field in LIVE_SELLER_FIELDS:
        if not seller.get(field):
            errors.append(f"{label}: live checkout requires seller.{field}")
    if not (seller.get("vat_id") or seller.get("vat_status")):
        errors.append(
            f"{label}: live checkout requires seller.vat_id or seller.vat_status"
        )
    return errors


def validate_beta_offer(path: Path, offer: dict) -> list[str]:
    errors = []
    label = path.name

    if offer.get("offer_id") != "pdf-mcp-hosted-free-beta":
        errors.append(f"{label}: unexpected hosted beta offer ID")
    if offer.get("offer_kind") != "hosted_software_beta":
        errors.append(f"{label}: hosted beta offer kind is required")
    if offer.get("status") != "accepting_beta_requests":
        errors.append(
            f"{label}: beta must remain request-only until an endpoint is published"
        )
    if offer.get("audience") != "businesses_and_professionals_only":
        errors.append(f"{label}: beta must be B2B/professional only")
    if offer.get("price", {}).get("amount") != "0.00":
        errors.append(f"{label}: hosted beta must be free")

    limits = offer.get("limits", {})
    expected_limits = {
        "operations_per_calendar_month": 25,
        "upload_bytes_per_operation": 10_000_000,
        "pdf_pages_per_operation": 50,
    }
    if limits != expected_limits:
        errors.append(
            f"{label}: hosted beta limits do not match the published contract"
        )

    service = offer.get("service", {})
    if service.get("url") is not None:
        errors.append(
            f"{label}: service URL must stay null until deployment is verified"
        )
    if service.get("deployment_status") != "pending":
        errors.append(f"{label}: hosted service must remain deployment_status pending")
    if service.get("authentication") != "individual_beta_api_key":
        errors.append(f"{label}: individual beta API-key authentication is required")
    if service.get("public_client_license") != "MIT":
        errors.append(f"{label}: public bridge license must remain MIT")
    if service.get("hosted_backend_license") != "proprietary_not_source_distributed":
        errors.append(f"{label}: private backend boundary must be explicit")

    handling = offer.get("data_handling", {})
    required_true = (
        "documents_uploaded_for_requested_operation",
        "temporary_upload_deleted_when_request_completes",
    )
    for field in required_true:
        if handling.get(field) is not True:
            errors.append(f"{label}: data_handling.{field} must be true")
    if handling.get("send_documents_by_email") is not False:
        errors.append(f"{label}: documents must not be accepted by email")
    if handling.get("used_for_model_training") is not False:
        errors.append(f"{label}: beta documents must not be used for model training")
    if handling.get("operational_metrics_retention_days") != 90:
        errors.append(f"{label}: operational metric retention must be 90 days")

    required_metrics = {
        "non_secret_api_key_id",
        "timestamp",
        "tool_name",
        "pdf_or_docx",
        "upload_byte_count",
        "page_table_and_warning_counts",
        "duration",
        "success_or_bounded_error_code",
    }
    if set(handling.get("operational_metrics", [])) != required_metrics:
        errors.append(f"{label}: operational metric fields changed")
    excluded_metrics = {
        "raw_api_key",
        "source_filename",
        "document_contents",
        "extracted_text",
        "table_cells",
    }
    if set(handling.get("never_in_operational_metrics", [])) != excluded_metrics:
        errors.append(f"{label}: usage-ledger exclusions changed")

    methods = [
        method
        for method in offer.get("access_methods", [])
        if method.get("type") == "email_beta_request"
    ]
    if len(methods) != 1 or methods[0].get("requires_user_confirmation") is not True:
        errors.append(f"{label}: beta needs one confirmed email access-request method")
    elif "no documents" not in methods[0].get("description", "").lower():
        errors.append(f"{label}: access request must prohibit sending documents")

    instructions = offer.get("agent_instructions", {})
    required_agent_flags = (
        "requires_user_confirmation",
        "do_not_attach_documents_to_email",
        "do_not_upload_without_user_approval",
        "only_redacted_or_non_sensitive_documents",
    )
    for field in required_agent_flags:
        if instructions.get(field) is not True:
            errors.append(f"{label}: agent_instructions.{field} must be true")

    for field in (
        "terms_url",
        "privacy_url",
        "human_readable_url",
        "local_unmeasured_alternative",
    ):
        if urlparse(offer.get(field, "")).scheme != "https":
            errors.append(f"{label}: {field} must be an HTTPS URL")
    return errors


def validate_smart_lab_beta_offer(path: Path, offer: dict) -> list[str]:
    errors = []
    label = path.name
    if offer.get("offer_id") != "smart-lab-index-request-beta":
        errors.append(f"{label}: unexpected Smart Lab beta offer ID")
    if offer.get("offer_kind") != "local_software_beta":
        errors.append(f"{label}: local software beta offer kind is required")
    if offer.get("status") != "accepting_beta_requests":
        errors.append(f"{label}: Smart Lab beta must remain request-only")

    access = offer.get("access", {})
    if access.get("type") != "request_only" or access.get("billing") != "free_beta":
        errors.append(f"{label}: beta access must remain free and request-only")

    rules = offer.get("application_rules", {})
    required_false = (
        "attach_files_to_request",
        "send_document_contents_by_email",
        "invitation_guaranteed",
        "production_sla",
    )
    for field in required_false:
        if rules.get(field) is not False:
            errors.append(f"{label}: application_rules.{field} must be false")

    privacy = offer.get("runtime_privacy", {})
    if privacy.get("source_access") != "read_only":
        errors.append(f"{label}: source access must remain read-only")
    for field in (
        "document_uploads",
        "telemetry",
        "analytics",
        "runtime_external_assets",
    ):
        if privacy.get(field) is not False:
            errors.append(f"{label}: runtime_privacy.{field} must be false")
    if privacy.get("no_egress_mode") is not True:
        errors.append(f"{label}: no-egress mode must remain available")

    methods = offer.get("access_methods", [])
    if len(methods) != 1 or methods[0].get("type") != "email_beta_request":
        errors.append(f"{label}: exactly one email beta request method is required")
    elif "without attaching" not in methods[0].get("description", "").lower():
        errors.append(f"{label}: the request method must prohibit file attachments")

    instructions = offer.get("agent_instructions", {})
    if instructions.get("requires_user_confirmation") is not True:
        errors.append(f"{label}: agents must require user confirmation")
    if instructions.get("do_not_attach_documents_to_email") is not True:
        errors.append(f"{label}: agents must prohibit document attachments")
    if "Never attach" not in instructions.get("recommended_action", ""):
        errors.append(
            f"{label}: agent instructions must explicitly prohibit attachments"
        )

    for field in ("terms_url", "privacy_url", "human_readable_url"):
        if urlparse(offer.get(field, "")).scheme != "https":
            errors.append(f"{label}: {field} must be an HTTPS URL")
    return errors


def validate_repository(
    require_live_checkout: bool = False,
) -> tuple[list[str], list[str]]:
    errors = []
    notes = []
    for path in PUBLIC_FILES:
        if not path.is_file():
            errors.append(f"missing public file: {path.relative_to(ROOT)}")

    offers = [load_offer(path) for path in OFFER_PATHS]
    for path, offer in zip(OFFER_PATHS, offers):
        errors.extend(validate_offer(path, offer))

    if BETA_PATH.is_file():
        beta_offer = load_offer(BETA_PATH)
        errors.extend(validate_beta_offer(BETA_PATH, beta_offer))
        if beta_offer.get("service", {}).get("url") is None:
            notes.append(
                "free hosted beta is accepting requests; endpoint deployment is pending"
            )
        else:
            notes.append("free hosted beta endpoint is published")

    if SMART_LAB_BETA_PATH.is_file():
        smart_lab_offer = load_offer(SMART_LAB_BETA_PATH)
        errors.extend(
            validate_smart_lab_beta_offer(SMART_LAB_BETA_PATH, smart_lab_offer)
        )
        notes.append("Smart Lab Index beta is free and request-only")

    live_offers = [offer for offer in offers if offer.get("checkout_url")]
    if live_offers:
        notes.append(
            f"live checkout configured for {len(live_offers)} of {len(offers)} offers"
        )
        terms_path = ROOT / "docs" / "terms.html"
        terms_html = (
            terms_path.read_text(encoding="utf-8") if terms_path.is_file() else ""
        )
        if (
            "checkout is disabled" in terms_html
            or "checkout remains disabled" in terms_html
        ):
            errors.append(
                "live checkout conflicts with the request-only statement in docs/terms.html"
            )
        for offer in live_offers:
            seller = offer.get("seller", {})
            published_values = [seller.get(field) for field in LIVE_SELLER_FIELDS]
            published_values.append(seller.get("vat_id") or seller.get("vat_status"))
            for value in filter(None, published_values):
                if str(value) not in terms_html:
                    errors.append(
                        f"docs/terms.html must visibly publish seller detail: {value}"
                    )
    else:
        notes.append("request-only paid beta; live checkout is disabled")
    if require_live_checkout and len(live_offers) != len(offers):
        errors.append("live launch requires a production checkout URL for every offer")

    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-live-checkout",
        action="store_true",
        help="Fail unless every offer has validated production checkout metadata.",
    )
    args = parser.parse_args()
    errors, notes = validate_repository(args.require_live_checkout)
    for note in notes:
        print(f"Status: {note}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        f"Validated {len(OFFER_PATHS)} paid offers, 2 beta offers, "
        f"and {len(PUBLIC_FILES)} public launch files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
