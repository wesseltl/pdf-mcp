# Stripe Connector

This repo includes a small Stripe Payment Links connector:

```bash
python scripts/create_stripe_payment_links.py
```

By default it runs in dry-run mode and prints the Products, Prices, and Payment Links it would create
from the JSON files in `offers/`.

## Setup

Create a restricted Stripe API key with permission to create Products, Prices, and Payment Links.
Do not commit the key and do not paste it into chat.

Set it only in your shell or deployment environment:

```bash
export STRIPE_SECRET_KEY=sk_live_...
python -m pip install -e ".[commerce]"
```

## Create checkout links

Dry run:

```bash
python scripts/create_stripe_payment_links.py
```

Create real Stripe Payment Links and write the resulting checkout URLs back to the offer files:

```bash
python scripts/create_stripe_payment_links.py --live --write
```

After reviewing the changed offer files:

```bash
git add offers/*.json BUY.md
git commit -m "Add Stripe checkout links"
git push origin main
```

Agents can then read the `checkout_url` fields and direct users to Stripe checkout after explicit
approval.
