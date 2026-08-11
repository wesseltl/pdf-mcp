const offerSources = {
  "pdf-mcp-hosted-free-beta": "https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/beta/free-hosted-beta.json",
  "sample-conversion": "https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/offers/sample-conversion.json",
  "document-to-excel-pilot": "https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/offers/document-to-excel-pilot.json"
};

function productionCheckoutUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.hostname !== "buy.stripe.com") return null;
    if (url.pathname.startsWith("/test_")) return null;
    return url.href;
  } catch (_error) {
    return null;
  }
}

function emailRequestUrl(offer) {
  const methods = [...(offer.purchase_methods || []), ...(offer.access_methods || [])];
  return methods.find((method) => ["email_purchase_request", "email_beta_request"].includes(method.type))?.url || null;
}

function updateOfferLinks(id, offer) {
  const checkoutUrl = offer.status === "available"
    ? productionCheckoutUrl(offer.checkout_url)
    : null;
  const destination = checkoutUrl || emailRequestUrl(offer);
  if (!destination) return;

  document.querySelectorAll(`[data-offer="${id}"]`).forEach((link) => {
    link.href = destination;
    link.textContent = checkoutUrl
      ? link.dataset.checkoutLabel || link.textContent
      : link.dataset.requestLabel || link.textContent;
    if (checkoutUrl) {
      link.rel = "noopener";
      link.target = "_blank";
    } else {
      link.removeAttribute("rel");
      link.removeAttribute("target");
    }
  });

  document.querySelectorAll(`[data-offer-status="${id}"]`).forEach((status) => {
    if (offer.offer_kind === "hosted_software_beta") {
      status.textContent = offer.service?.url
        ? "Invitation requests are open. Send no documents or document contents by email."
        : "Applications are open. Invitations begin after endpoint deployment. Send no documents by email.";
    } else {
      status.textContent = checkoutUrl
        ? "Live Stripe checkout. Scope is confirmed before fulfillment."
        : "Scope request by email. Do not attach documents.";
    }
  });
}

async function hydrateOfferLinks() {
  await Promise.all(Object.entries(offerSources).map(async ([id, url]) => {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return;
      updateOfferLinks(id, await response.json());
    } catch (_error) {
      // Static request links remain usable if public offer metadata is unavailable.
    }
  }));
}

hydrateOfferLinks();
