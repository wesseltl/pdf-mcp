# Stripe Payment Links

The connector builds Stripe Products, Prices, and Payment Links from `offers/*.json`. It enables
automatic tax, collects billing addresses and tax IDs, and redirects successful checkouts to the
order instructions page.

Live checkout is a launch gate, not a development default. Before creating live links:

- Complete the Stripe business profile and activate live payments.
- Publish the seller's business registration number, VAT status/ID, address, and phone in the terms.
- Configure and verify Stripe Tax for the countries where the offer will be sold.
- Review the offer scope, refund policy, privacy notice, and success-page instructions.

Install the optional dependency:

```bash
python -m pip install -e ".[commerce]"
```

Use a restricted Stripe key with only the permissions needed for Products, Prices, and Payment
Links. Set it in the current shell; do not save it in the repository or paste it into chat.

## Dry run

This performs no network calls and writes no files:

```bash
python scripts/create_stripe_payment_links.py
```

## Test links

Test mode creates disposable Stripe objects and prints their URLs. It refuses to write test URLs to
the published offer files.

```bash
export STRIPE_SECRET_KEY=sk_test_...
python scripts/create_stripe_payment_links.py --live --expected-mode test
unset STRIPE_SECRET_KEY
```

## Live links

This command aborts if the supplied key is not a live key. It writes the resulting URLs and marks
the offers `available`.

```bash
export STRIPE_SECRET_KEY=rk_live_...
python scripts/create_stripe_payment_links.py --live --write --expected-mode live
unset STRIPE_SECRET_KEY
```

Review the changed offer files and run the complete test suite before publishing them. Agents only
use checkout when an offer has `status: available`; otherwise they use the purchase-request flow.
