# LabOverlay Self-Service Architecture

## Objective

A laboratory should be able to subscribe, install one signed application, connect an approved folder,
and receive useful results without a terminal or a consultant. The application must still be able to
index local and network drives without sending laboratory files to a hosted service.

That requires two deliberately separate systems:

```text
Hosted control plane                     Laboratory data plane

Account and organization                 Signed desktop/service agent
Stripe subscription status     lease     Read-only filesystem connector
Device enrollment              ----->    Parsers and extractors
Release/update metadata                   Local SQLite index
Aggregate operational health   <-----    Local browser workspace

No document content                       Source content stays here
No extracted text                          Provenance stays here by default
No customer credentials                   Network-share credentials stay in the OS
```

The hosted website cannot directly index a customer's local or mapped network drive. A local data
plane is not optional for this product.

## Customer Flow

The target customer journey has five steps.

1. The customer creates a laboratory account and completes Stripe Checkout.
2. A verified Stripe webhook provisions the organization entitlement exactly once.
3. The customer downloads a signed Windows or macOS installer from the account page.
4. The application pairs to the organization and asks the customer to connect one approved folder.
5. The first scan starts automatically. Later scans are incremental and scheduled.

Returning use must require only opening LabOverlay. The app remembers the approved folder and
its separate local database. An unavailable remembered network path returns to folder setup instead
of scanning a different path.

## Current Implementation

The repository now implements the local portion of this flow:

- zero-argument graphical startup;
- one-time folder selection with a system dialog or bundled browser fallback;
- owner-only, atomic remembered-workspace settings;
- one database per selected folder;
- automatic first scan and 15-minute incremental scans;
- plain-language Home, Files, Needs review, and System status views;
- local-only document processing and assertion provenance;
- signed-build hooks for Windows and macOS release jobs.

Explicit CLI and controlled-production starts remain configuration-driven. They do not inherit the
desktop convenience defaults.

## Hosted Control Plane Boundary

The control plane should own only:

- users, organizations, and invitations;
- Stripe customer, subscription, product, and entitlement identifiers;
- device identity, enrollment, revocation, and last-seen health;
- signed offline entitlement leases;
- release channels and signed update metadata;
- consented aggregate counters that contain no filenames, paths, extracted text, entity names, or
  assertion values.

It must not own source documents, parsed content, local database backups, network-share credentials,
or local search results in the default product profile.

## Enrollment Contract

Use a short-lived, single-use enrollment code displayed by the authenticated account portal. Do not
use a perpetual license key.

Conceptual endpoints:

```text
POST /v1/device-enrollments       authenticated account creates a one-time code
POST /v1/devices/pair             local app exchanges code and device public key
POST /v1/devices/lease            paired device refreshes its signed entitlement lease
POST /v1/devices/heartbeat        sends bounded version and health state only
DELETE /v1/devices/{device_id}    account owner revokes a device
```

Enrollment codes must be random, hashed at rest, single-use, organization-bound, rate-limited, and
expire within minutes. Device secrets must be stored in the operating-system credential store, not
in `desktop-settings.json`.

Entitlement leases should be signed by a control-plane key and verified locally with an embedded
public key. A temporary billing or network outage must not delete local data. A customer-friendly
policy is to keep existing read/search access and allow a bounded offline grace period for new scans.
No-egress installations use an explicitly generated offline activation file and never silently call
the control plane.

## Stripe Lifecycle

A recurring offer uses a recurring Stripe Price. Checkout alone is not fulfillment. The service must
verify webhook signatures and idempotently process at least:

- `checkout.session.completed`;
- `customer.subscription.created`;
- `customer.subscription.updated`;
- `customer.subscription.deleted`;
- `invoice.paid`;
- `invoice.payment_failed`;
- `entitlements.active_entitlement_summary.updated` when Stripe Entitlements is enabled.

The local entitlement is derived from the stored active entitlement, never from a browser redirect
alone. The Stripe customer portal should handle payment-method updates, invoices, and cancellation.

`scripts/create_stripe_payment_links.py` supports `monthly` and `yearly` prices, but refuses to create
a recurring plan unless the offer declares `fulfillment.mode=webhook_entitlement`, an entitlement ID,
and an HTTPS success URL containing `{CHECKOUT_SESSION_ID}`. This prevents a payment link from being
presented as a complete subscription system.

## Installer and Updates

Self-service depends on distribution quality as much as application code.

- Windows: signed MSI or MSIX, Start menu entry, per-machine service option, uninstall support.
- macOS: signed and notarized package or DMG, launch-agent option, uninstall instructions.
- Linux server: signed package plus the existing hardened systemd deployment.
- Updates: signed manifest, staged channels, rollback, and an administrator-controlled disable switch.

The current ZIP artifacts are useful for pilots but are not the final low-touch installer experience.

## Security Defaults

- Read-only source access.
- Document content local by default.
- No network credentials stored by LabOverlay.
- No inbound internet port on the laboratory device.
- Outbound control-plane traffic limited to enrollment, entitlement, release metadata, and bounded
  health when managed mode is enabled.
- Exact permission-aware result filtering before multi-user rollout.
- Explicit administrator approval for each indexed root.
- No automatic write-back to LIMS, QMS, ELN, or source files.

## Commercial Boundary

This repository and all already published versions are MIT licensed. That permission cannot be
retroactively withdrawn from copies already distributed. A proprietary managed control plane,
installer, update service, and future closed-source agent must therefore be developed and distributed
from a separate private product repository if closed-source licensing remains the business model.

## Remaining Launch Gates

The product is not yet a live self-service subscription. The remaining gates are:

1. seller registration, tax, terms, privacy, DPA, and support identity;
2. hosted identity, organization, and invitation service;
3. Stripe webhook and entitlement persistence with replay/idempotency tests;
4. device pairing and signed offline leases;
5. permission-aware search/result filtering;
6. signed native installers and controlled updates;
7. customer-facing account, billing, device, and deletion controls;
8. production monitoring, backup, incident response, and support workflow;
9. evidence from controlled design-partner pilots.

The next implementation should be the minimal hosted control plane plus device pairing in Stripe test
mode. It should not upload documents or extracted content.
