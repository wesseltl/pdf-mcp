"use strict";

const POLL_INTERVAL_MS = 1500;
const FINAL_REFRESH_DELAY_MS = 250;
const REQUEST_TIMEOUT_MS = 12000;
const SVG_NAMESPACE = ["http:", "", "www.w3.org", "2000", "svg"].join("/");
const SESSION_TOKEN = document.querySelector('meta[name="smart-lab-session"]')?.content || "";
const DETAIL_KEY_ORDER = [
  "subject_name",
  "observed_locations",
  "location_name",
  "provenance",
  "source_external_id",
  "source_path",
  "excerpt",
  "locator",
  "sheet",
  "cell",
  "page",
  "paragraph",
  "line",
  "row",
  "column",
  "table_name",
  "table",
  "assertion_id",
  "location_entity_id",
  "source_record_id",
];

const elements = {
  announcement: document.getElementById("announcement"),
  cancelIndexButton: document.getElementById("cancel-index-button"),
  changeSourceButton: document.getElementById("change-source-button"),
  desktopNav: document.getElementById("desktop-nav"),
  detailBody: document.getElementById("detail-body"),
  detailClose: document.getElementById("detail-close"),
  detailDialog: document.getElementById("detail-dialog"),
  detailSubtitle: document.getElementById("detail-subtitle"),
  detailTitle: document.getElementById("detail-title"),
  egressStatus: document.getElementById("egress-status"),
  filter: document.getElementById("view-filter"),
  filterControl: document.getElementById("filter-control"),
  filterLabel: document.getElementById("view-filter-label"),
  globalSearchButton: document.getElementById("global-search-button"),
  indexButton: document.getElementById("index-button"),
  mobileMenuButton: document.getElementById("mobile-menu-button"),
  mobileMenuClose: document.getElementById("mobile-menu-close"),
  operationStatus: document.getElementById("operation-status"),
  productVersion: document.getElementById("product-version"),
  refreshButton: document.getElementById("refresh-button"),
  sidebarBackdrop: document.getElementById("sidebar-backdrop"),
  sidebarSourceName: document.getElementById("sidebar-source-name"),
  sidebarSourceState: document.getElementById("sidebar-source-state"),
  sidebarTrustDetail: document.getElementById("sidebar-trust-detail"),
  sidebarTrustLabel: document.getElementById("sidebar-trust-label"),
  shutdownButton: document.getElementById("shutdown-button"),
  sourceRoot: document.getElementById("source-root"),
  topbarActions: document.getElementById("topbar-actions"),
  trustButton: document.getElementById("trust-button"),
  viewCount: document.getElementById("view-count"),
  viewContext: document.getElementById("view-context"),
  viewRoot: document.getElementById("view-root"),
  viewTitle: document.getElementById("view-title"),
};

const ui = {
  actionError: "",
  activeViewId: null,
  changingSource: false,
  fetching: false,
  filterByView: new Map(),
  health: null,
  lastOperationState: null,
  loading: true,
  pollTimer: null,
  requestBusy: false,
  returnFocus: null,
  searchError: "",
  searchQuery: "",
  searchResults: [],
  searchTimer: null,
  searching: false,
  state: null,
  stopped: false,
};

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function scalarText(value, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "object") {
    return readableJson(value);
  }
  return String(value);
}

function readableJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return String(value);
  }
}

function humanize(value) {
  const text = scalarText(value, "");
  if (!text) {
    return "";
  }
  return text
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function issueLabel(value) {
  const text = humanize(value).toLocaleLowerCase();
  return text ? `${text.charAt(0).toLocaleUpperCase()}${text.slice(1)}` : "Issue";
}

function formatPredicate(value) {
  return scalarText(value).replace(/[._-]+/g, " ");
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat().format(number) : "0";
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return scalarText(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "—";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && size >= 1024; index += 1) {
    size /= 1024;
    unit = units[index];
  }
  return `${size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${unit}`;
}

function contentTypeLabel(value) {
  const contentType = String(value || "").toLocaleLowerCase();
  if (contentType.includes("wordprocessingml") || contentType.includes("msword")) {
    return "Word document";
  }
  if (contentType.includes("spreadsheetml") || contentType.includes("excel")) {
    return "Excel workbook";
  }
  if (contentType.includes("pdf")) {
    return "PDF";
  }
  if (contentType.includes("csv")) {
    return "CSV";
  }
  if (contentType.startsWith("text/")) {
    return "Text file";
  }
  return humanize(value) || "File";
}

function formatConfidence(value) {
  const confidence = Number(value);
  if (!Number.isFinite(confidence)) {
    return "—";
  }
  const percent = confidence <= 1 ? confidence * 100 : confidence;
  return `${Math.round(percent)}%`;
}

function summarizeMetadata(value) {
  const metadata = asObject(value);
  const entries = Object.entries(metadata);
  if (!entries.length) {
    return "—";
  }
  return entries
    .slice(0, 3)
    .map(([key, item]) => `${humanize(key)}: ${scalarText(item)}`)
    .join(" · ");
}

function node(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function svgNode(tagName, className = "", attributes = {}) {
  const element = document.createElementNS(SVG_NAMESPACE, tagName);
  if (className) {
    element.setAttribute("class", className);
  }
  Object.entries(attributes).forEach(([name, value]) => {
    element.setAttribute(name, String(value));
  });
  return element;
}

function iconNode(name, className = "ui-icon") {
  const icon = svgNode("svg", className, { "aria-hidden": "true", focusable: "false" });
  const use = svgNode("use");
  use.setAttribute("href", `/icons.svg#${name}`);
  icon.append(use);
  return icon;
}

function announce(message) {
  elements.announcement.textContent = "";
  window.setTimeout(() => {
    elements.announcement.textContent = message;
  }, 10);
}

function operationState() {
  return String(ui.state?.operation?.state || "IDLE").toUpperCase();
}

function operationIsActive(state = operationState()) {
  return state === "STARTING" || state === "INDEXING";
}

function currentViews() {
  return asArray(ui.state?.views);
}

function activeView() {
  return currentViews().find((view) => String(view.view_id) === ui.activeViewId) || null;
}

function currentFilter() {
  return (ui.filterByView.get(ui.activeViewId) || "").trim().toLocaleLowerCase();
}

function includesQuery(value, query) {
  if (!query) {
    return true;
  }
  if (value === null || value === undefined) {
    return false;
  }
  if (Array.isArray(value)) {
    return value.some((item) => includesQuery(item, query));
  }
  if (typeof value === "object") {
    return Object.entries(value).some(
      ([key, item]) => key.toLocaleLowerCase().includes(query) || includesQuery(item, query),
    );
  }
  return String(value).toLocaleLowerCase().includes(query);
}

function filteredRows(rows) {
  const query = currentFilter();
  return query ? rows.filter((row) => includesQuery(row, query)) : rows;
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  headers.set("X-Smart-Lab-Session", SESSION_TOKEN);
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      ...options,
      cache: "no-store",
      credentials: "same-origin",
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`.trim();
      try {
        const payload = await response.json();
        message = scalarText(payload.message || payload.error || message);
      } catch (_error) {
        // Keep the status text when the server does not return JSON.
      }
      throw new Error(message || "Request failed");
    }

    if (response.status === 204) {
      return null;
    }
    const contentType = response.headers.get("content-type") || "";
    return contentType.includes("application/json") ? response.json() : null;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("The local LabOverlay service did not respond within 12 seconds.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function clearPoll() {
  if (ui.pollTimer !== null) {
    window.clearTimeout(ui.pollTimer);
    ui.pollTimer = null;
  }
}

function schedulePoll() {
  clearPoll();
  if (!ui.stopped) {
    ui.pollTimer = window.setTimeout(() => refreshState(), POLL_INTERVAL_MS);
  }
}

function selectInitialView() {
  const views = currentViews();
  if (!views.length) {
    ui.activeViewId = null;
    return;
  }
  const stillAvailable = views.some((view) => String(view.view_id) === ui.activeViewId);
  if (!stillAvailable) {
    const overview = views.find((view) => viewCategory(view) === "overview");
    ui.activeViewId = String((overview || views[0]).view_id);
  }
}

async function refreshState(options = {}) {
  if (ui.fetching || ui.stopped || ui.changingSource) {
    return;
  }
  ui.fetching = true;
  ui.actionError = "";
  elements.refreshButton.disabled = true;
  elements.refreshButton.classList.add("is-busy");
  clearPoll();

  const previousOperation = ui.lastOperationState;
  try {
    const [state, health] = await Promise.all([
      apiRequest("/api/state"),
      apiRequest("/api/health").catch(() => null),
    ]);
    if (!state || typeof state !== "object") {
      throw new Error("The application returned an invalid state response.");
    }
    ui.state = state;
    ui.health = health && typeof health === "object" ? health : null;
    ui.loading = false;
    selectInitialView();
    ui.lastOperationState = operationState();
    renderApplication();

    if (options.announceRefresh) {
      announce("Data refreshed");
    }

    if (operationIsActive(ui.lastOperationState)) {
      schedulePoll();
    } else if (operationIsActive(previousOperation) && !options.finalRefresh) {
      announce(ui.lastOperationState === "FAILED" ? "File scan failed" : "File scan complete");
      ui.pollTimer = window.setTimeout(
        () => refreshState({ finalRefresh: true }),
        FINAL_REFRESH_DELAY_MS,
      );
    }
  } catch (error) {
    ui.loading = false;
    ui.actionError = error instanceof Error ? error.message : "Unable to load application state.";
    renderApplication();
  } finally {
    ui.fetching = false;
    elements.refreshButton.classList.remove("is-busy");
    updateCommandState();
  }
}

async function startIndex() {
  if (ui.requestBusy || operationIsActive() || ui.stopped) {
    return;
  }
  ui.requestBusy = true;
  ui.actionError = "";
  updateCommandState();

  try {
    await apiRequest("/api/index", { method: "POST" });
    if (ui.state) {
      ui.state.operation = {
        ...asObject(ui.state.operation),
        error: null,
        result: null,
        started_at: new Date().toISOString(),
        state: "INDEXING",
      };
      ui.lastOperationState = "INDEXING";
    }
    announce("File scan started");
    renderApplication();
    ui.pollTimer = window.setTimeout(() => refreshState(), FINAL_REFRESH_DELAY_MS);
  } catch (error) {
    ui.actionError = error instanceof Error ? error.message : "Unable to start the file scan.";
    renderApplication();
    announce("File scan could not be started");
  } finally {
    ui.requestBusy = false;
    updateCommandState();
  }
}

async function cancelIndex() {
  if (ui.requestBusy || !operationIsActive() || ui.stopped) {
    return;
  }
  ui.requestBusy = true;
  ui.actionError = "";
  updateCommandState();
  try {
    await apiRequest("/api/cancel-index", { method: "POST" });
    if (ui.state?.operation) {
      ui.state.operation.cancel_requested = true;
    }
    announce("File scan cancellation requested");
    renderOperationStatus();
    schedulePoll();
  } catch (error) {
    ui.actionError = error instanceof Error ? error.message : "Unable to cancel indexing.";
    renderApplication();
  } finally {
    ui.requestBusy = false;
    updateCommandState();
  }
}

async function changeSource() {
  if (ui.requestBusy || ui.stopped || ui.changingSource) {
    return;
  }
  ui.requestBusy = true;
  ui.actionError = "";
  updateCommandState();
  try {
    await apiRequest("/api/change-source", { method: "POST" });
    ui.changingSource = true;
    clearPoll();
    announce("Folder selection opened");
    renderApplication();
    window.setTimeout(waitForSourceRestart, 750);
  } catch (error) {
    ui.actionError = error instanceof Error ? error.message : "Unable to change the source folder.";
    renderApplication();
  } finally {
    ui.requestBusy = false;
    updateCommandState();
  }
}

async function waitForSourceRestart() {
  while (ui.changingSource) {
    try {
      const response = await fetch("/", {
        cache: "no-store",
        credentials: "same-origin",
      });
      const html = response.ok ? await response.text() : "";
      if (response.ok && html && !html.includes(SESSION_TOKEN)) {
        window.location.reload();
        return;
      }
    } catch (_error) {
      // The loopback server is intentionally offline while the chooser is open.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
}

async function stopApplication() {
  if (ui.requestBusy || ui.stopped) {
    return;
  }
  const confirmed = window.confirm("Close LabOverlay on this computer?");
  if (!confirmed) {
    return;
  }

  ui.requestBusy = true;
  ui.actionError = "";
  updateCommandState();
  try {
    await apiRequest("/api/shutdown", { method: "POST" });
    ui.stopped = true;
    clearPoll();
    renderStopped();
    announce("LabOverlay closed");
  } catch (error) {
    ui.actionError = error instanceof Error ? error.message : "Unable to stop the application.";
    renderApplication();
  } finally {
    ui.requestBusy = false;
    updateCommandState();
  }
}

function updateCommandState() {
  const indexing = operationIsActive();
  const disabled = ui.requestBusy || ui.stopped || ui.changingSource;
  elements.indexButton.disabled = disabled || indexing || !ui.state;
  elements.indexButton.hidden = indexing;
  elements.cancelIndexButton.hidden = !indexing;
  elements.cancelIndexButton.disabled = disabled || !indexing || ui.state?.operation?.cancel_requested === true;
  elements.changeSourceButton.disabled = disabled || indexing || !ui.state;
  elements.refreshButton.disabled = disabled || ui.fetching;
  elements.shutdownButton.disabled = disabled;
  elements.globalSearchButton.disabled = ui.stopped || !currentViews().length;
  elements.trustButton.disabled = ui.stopped || !ui.state;
  elements.filter.disabled = ui.stopped || !activeView();
}

function chooseView(viewId) {
  if (!currentViews().some((view) => String(view.view_id) === viewId)) {
    return;
  }
  ui.filterByView.set(ui.activeViewId, elements.filter.value);
  ui.activeViewId = viewId;
  elements.filter.value = ui.filterByView.get(viewId) || "";
  renderNavigation();
  renderViewHeader();
  renderActiveView();
  if (viewCategory(activeView()) === "search" && elements.filter.value.trim().length >= 2) {
    scheduleSearch();
  }
  elements.viewTitle.focus?.({ preventScroll: true });
}

function viewCategory(view) {
  const kind = String(view?.kind || "").toLocaleLowerCase();
  const id = String(view?.view_id || "").toLocaleLowerCase();
  const combined = `${kind} ${id}`;

  if (combined.includes("overview") || combined.includes("dashboard")) {
    return "overview";
  }
  if (combined.includes("search")) {
    return "search";
  }
  if (view?.predicate || combined.includes("responsib") || combined.includes("relationship") || combined.includes("assertion")) {
    return "responsibilities";
  }
  if (view?.entity_type || view?.entity_types || combined.includes("entity") || combined.includes("equipment") || combined.includes("location") || combined.includes("people") || combined.includes("person") || combined.includes("organization")) {
    return "entities";
  }
  if (combined.includes("document")) {
    return "documents";
  }
  if (combined.includes("issue") || combined.includes("review")) {
    return "issues";
  }
  if (combined.includes("source")) {
    return "sources";
  }
  if (combined.includes("module") || combined.includes("status")) {
    return "modules";
  }
  return "unknown";
}

function navigationIcon(view) {
  const category = viewCategory(view);
  const icons = {
    documents: "file-text",
    entities: "package",
    issues: "circle-alert",
    modules: "activity",
    overview: "layout-dashboard",
    search: "search",
    responsibilities: "link",
    sources: "folder",
    unknown: "activity",
  };
  if (category === "entities") {
    const type = String(view.entity_type || asArray(view.entity_types).join(" ") || view.view_id || "").toUpperCase();
    if (type.includes("ASSET") || type.includes("EQUIPMENT")) {
      return "package";
    }
    if (type.includes("PERSON") || type.includes("PEOPLE")) {
      return "user";
    }
    if (type.includes("ORGANIZATION")) {
      return type.includes("UNIT") ? "users" : "building";
    }
    if (type.includes("LOCATION")) {
      return "map-pin";
    }
  }
  return icons[category];
}

function displayViewLabel(view) {
  const category = viewCategory(view);
  if (category === "overview") {
    return "Overview";
  }
  if (category === "sources") {
    return "Sources";
  }
  if (category === "modules") {
    return "System health";
  }
  if (category === "issues" && String(view.status || "").toUpperCase() === "OPEN") {
    return "Review queue";
  }
  return scalarText(view.label, view.view_id);
}

function navigationGroup(view) {
  const category = viewCategory(view);
  if (["overview", "search"].includes(category)) {
    return "Workspace";
  }
  if (category === "issues") {
    return "Review";
  }
  if (category === "sources") {
    return "Data";
  }
  if (category === "modules") {
    return "Administration";
  }
  return "Knowledge";
}

function renderNavigation() {
  const views = currentViews();
  const navFragment = document.createDocumentFragment();
  let previousGroup = "";

  if (!views.length) {
    navFragment.append(node("div", "navigation-empty", "No views available"));
  }

  views.forEach((view) => {
    const viewId = String(view.view_id);
    const group = navigationGroup(view);
    if (group !== previousGroup) {
      const heading = node("div", "nav-group-label", group);
      heading.setAttribute("role", "heading");
      heading.setAttribute("aria-level", "2");
      navFragment.append(heading);
      previousGroup = group;
    }
    const button = node("button", "nav-button");
    button.type = "button";
    button.dataset.viewId = viewId;
    button.title = displayViewLabel(view);
    if (viewId === ui.activeViewId) {
      button.setAttribute("aria-current", "page");
    }

    const icon = node("span", "nav-icon");
    icon.setAttribute("aria-hidden", "true");
    icon.append(iconNode(navigationIcon(view)));
    button.append(icon, node("span", "nav-label", displayViewLabel(view)));
    if (view.count !== null && view.count !== undefined) {
      button.append(node("span", "nav-count", formatNumber(view.count)));
    }
    button.addEventListener("click", () => {
      chooseView(viewId);
      closeNavigation();
    });
    navFragment.append(button);
  });

  elements.desktopNav.replaceChildren(navFragment);
}

function renderChrome() {
  const source = asObject(ui.state?.source);
  const root = scalarText(source.root, "No source configured");
  const sourceName = scalarText(source.display_name, root);
  elements.sourceRoot.textContent = sourceName;
  elements.sourceRoot.title = root;
  elements.sidebarSourceName.textContent = sourceName;
  elements.sidebarSourceName.title = root;
  elements.productVersion.textContent = `Version ${scalarText(ui.state?.product_version)}`;
  elements.changeSourceButton.hidden = source.can_change_source !== true;
  elements.topbarActions.classList.toggle(
    "has-source-picker",
    source.can_change_source === true,
  );

  const noEgress = source.no_egress === true;
  const health = asObject(ui.health);
  const healthReady = health.ready !== false;
  const trustTone = !healthReady ? "danger" : noEgress ? "success" : "warning";
  elements.trustButton.dataset.tone = trustTone;
  elements.egressStatus.textContent = !healthReady
    ? "System needs attention"
    : noEgress
      ? "Local mode"
      : "External access allowed";
  elements.trustButton.title = noEgress
    ? "External connections are blocked. Open trust status."
    : "This workspace allows configured external connections. Open trust status.";
  elements.sidebarTrustLabel.textContent = healthReady ? "Private workspace" : "Check system health";
  elements.sidebarTrustDetail.textContent = noEgress
    ? "Local and read-only"
    : "Read-only · External access allowed";

  const latestRun = asObject(ui.state?.summary?.latest_run);
  const state = operationState();
  if (operationIsActive(state)) {
    elements.sidebarSourceState.textContent = "Sync in progress";
  } else if (state === "FAILED") {
    elements.sidebarSourceState.textContent = "Last sync failed";
  } else if (latestRun.completed_at) {
    elements.sidebarSourceState.textContent = `Updated ${formatDate(latestRun.completed_at)}`;
  } else {
    elements.sidebarSourceState.textContent = "Ready for first sync";
  }
}

function renderViewHeader() {
  const view = activeView();
  const label = view ? displayViewLabel(view) : "Workspace";
  const category = viewCategory(view);
  elements.viewTitle.textContent = label;
  const contexts = {
    documents: "Indexed knowledge",
    entities: "Indexed knowledge",
    issues: "Evidence review",
    modules: "Administration",
    overview: "Workspace overview",
    responsibilities: "Indexed knowledge",
    search: "Workspace search",
    sources: "Connected data",
    unknown: "Workspace",
  };
  elements.viewContext.textContent = contexts[category] || "Workspace";
  elements.viewTitle.tabIndex = -1;
  elements.filterControl.hidden = category === "overview";
  elements.filter.placeholder = category === "search"
    ? "Search all indexed knowledge"
    : `Filter ${label.toLocaleLowerCase()}`;
  elements.filterLabel.textContent = category === "search"
    ? "Search all indexed knowledge"
    : `Filter ${label}`;
  elements.filter.value = ui.filterByView.get(ui.activeViewId) || "";
  setViewCount(view?.count ?? null);
}

function setViewCount(total, filtered = null) {
  if (total === null || total === undefined) {
    elements.viewCount.textContent = "";
    return;
  }
  const totalText = formatNumber(total);
  elements.viewCount.textContent = filtered !== null && filtered !== total
    ? `${formatNumber(filtered)} of ${totalText}`
    : totalText;
}

function summarizeOperationResult(result) {
  const data = asObject(result);
  const stats = asObject(data.stats);
  const preferredFields = [
    ["discovered", "Files checked"],
    ["unchanged", "Unchanged"],
    ["changed", "Updated"],
    ["parsed", "Documents read"],
    ["failed", "Could not read"],
    ["entities", "Items added"],
    ["assertions", "Connections added"],
    ["issues", "Review items"],
  ];
  const parts = preferredFields
    .map(([key, label]) => [label, data[key] ?? stats[key]])
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([label, value]) => `${label} ${formatNumber(value)}`);
  return parts.length ? parts.join(" · ") : "Scan state updated";
}

function progressDetail(operation) {
  const progress = asObject(operation.progress);
  if (operation.cancel_requested) {
    return "Cancelling after the current file";
  }
  const phases = {
    DISCOVERY: "Checking files",
    FINALIZING: "Finishing scan",
    PARSING: "Reading documents",
    OPENING_WORKSPACE: "Opening workspace",
    PREFLIGHT: "Checking folder",
    PROCESSING: "Reading documents",
    STARTING: "Starting scan",
  };
  const phase = phases[String(progress.phase || "").toUpperCase()] || "Scanning files";
  const current = Number(progress.current);
  const total = Number(progress.total);
  const count = Number.isFinite(current) && Number.isFinite(total) && total > 0
    ? `${formatNumber(current)} of ${formatNumber(total)}`
    : Number.isFinite(current) && current > 0
      ? formatNumber(current)
      : "";
  const bytes = progress.bytes_total ? formatBytes(progress.bytes_total) : "";
  const directories = Number(progress.directories_scanned);
  const folderCount = Number.isFinite(directories) && directories > 0
    ? `${formatNumber(directories)} folder${directories === 1 ? "" : "s"}`
    : "";
  const path = progress.path ? scalarText(progress.path) : "";
  return [phase, folderCount, count, bytes, path].filter(Boolean).join(" · ") || "Starting scan";
}

function renderOperationStatus() {
  elements.operationStatus.replaceChildren();

  if (ui.actionError) {
    elements.operationStatus.append(
      createOperationStrip("failed", "Request failed", ui.actionError, "!"),
    );
    return;
  }

  const operation = asObject(ui.state?.operation);
  const state = operationState();
  if (operationIsActive(state)) {
    elements.operationStatus.append(
      createOperationStrip(
        "indexing",
        "Scanning files",
        progressDetail(operation),
        "spinner",
        formatDate(operation.started_at),
      ),
    );
  } else if (state === "FAILED") {
    elements.operationStatus.append(
      createOperationStrip(
        "failed",
        "Scan failed",
        scalarText(operation.error, "The indexing run did not complete."),
        "!",
        formatDate(operation.completed_at),
      ),
    );
  } else if (ui.state?.source?.scope_warning) {
    elements.operationStatus.append(
      createOperationStrip(
        "warning",
        "System drive selected",
        scalarText(ui.state.source.scope_warning),
        "!",
      ),
    );
  } else if (
    operation.completed_at
    && operation.result
    && viewCategory(activeView()) !== "overview"
  ) {
    const cancelled = String(operation.result.status || "").toUpperCase() === "CANCELLED";
    elements.operationStatus.append(
      createOperationStrip(
        cancelled ? "warning" : "success",
        cancelled ? "Scan cancelled" : "Scan complete",
        summarizeOperationResult(operation.result),
        cancelled ? "■" : "✓",
        formatDate(operation.completed_at),
      ),
    );
  }
}

function createOperationStrip(tone, title, detail, symbol, time = "") {
  const strip = node("div", `operation-strip is-${tone}`);
  let icon;
  if (symbol === "spinner") {
    icon = node("span", "spinner");
  } else {
    const badgeTone = tone === "failed"
      ? "status-danger"
      : tone === "warning"
        ? "status-warning"
        : "status-success";
    icon = node("span", `status-badge ${badgeTone}`, symbol);
  }
  icon.setAttribute("aria-hidden", "true");

  const copy = node("div", "operation-copy");
  copy.append(node("strong", "operation-title", title), node("span", "operation-detail", detail));
  strip.append(icon, copy);
  if (time && time !== "—") {
    strip.append(node("time", "operation-time", time));
  }
  return strip;
}

function renderApplication() {
  if (ui.stopped) {
    renderStopped();
    return;
  }
  if (ui.loading && !ui.state) {
    renderLoading();
    return;
  }
  if (!ui.state) {
    renderUnavailable();
    return;
  }

  if (ui.changingSource) {
    renderChangingSource();
    return;
  }

  renderChrome();
  renderNavigation();
  renderViewHeader();
  renderOperationStatus();
  renderActiveView();
  updateCommandState();
}

function renderChangingSource() {
  elements.operationStatus.replaceChildren();
  const panel = emptyState(
    "Choose a folder",
    "Folder selection is open.",
    "⌖",
  );
  panel.classList.add("stopped-panel");
  elements.viewRoot.replaceChildren(panel);
  elements.viewRoot.setAttribute("aria-busy", "true");
  updateCommandState();
}

function renderLoading() {
  elements.viewRoot.setAttribute("aria-busy", "true");
  const panel = node("div", "state-panel state-panel-loading");
  const spinner = node("span", "spinner");
  spinner.setAttribute("aria-hidden", "true");
  panel.append(spinner, node("strong", "", "Opening workspace"));
  elements.viewRoot.replaceChildren(panel);
}

function renderUnavailable() {
  elements.viewRoot.setAttribute("aria-busy", "false");
  elements.operationStatus.replaceChildren();
  if (ui.actionError) {
    elements.operationStatus.append(createOperationStrip("failed", "Connection failed", ui.actionError, "!"));
  }
  const panel = emptyState("Workspace unavailable", "The application did not return its current state.", "↻");
  panel.append(commandButton("Retry", "↻", () => refreshState()));
  elements.viewRoot.replaceChildren(panel);
  updateCommandState();
}

function renderStopped() {
  clearPoll();
  elements.operationStatus.replaceChildren();
  const panel = emptyState("Application closed", "You can close this browser tab.", "■");
  panel.classList.add("stopped-panel");
  elements.viewRoot.replaceChildren(panel);
  elements.viewRoot.setAttribute("aria-busy", "false");
  updateCommandState();
}

function renderActiveView() {
  elements.viewRoot.setAttribute("aria-busy", "false");
  const view = activeView();
  if (!view) {
    elements.viewRoot.replaceChildren(emptyState("No views available", "No interface capabilities are currently enabled.", "◇"));
    setViewCount(0);
    return;
  }

  const category = viewCategory(view);
  const renderers = {
    documents: renderDocuments,
    entities: renderEntities,
    issues: renderIssues,
    modules: renderModules,
    overview: renderOverview,
    responsibilities: renderResponsibilities,
    search: renderSearch,
    sources: renderSources,
    unknown: renderUnknownView,
  };
  renderers[category](view);
}

function emptyState(title, message, symbol = "○") {
  const panel = node("div", "empty-state");
  const icon = node("span", "empty-state-symbol", symbol);
  icon.setAttribute("aria-hidden", "true");
  panel.append(icon, node("h2", "", title));
  if (message) {
    panel.append(node("p", "", message));
  }
  return panel;
}

function commandButton(label, symbol, action, className = "button button-primary") {
  const button = node("button", className);
  button.type = "button";
  const iconName = {
    "→": "arrow-right",
    "↻": "refresh-cw",
    "⌕": "search",
    "✓": "check",
    "×": "x",
  }[symbol];
  const icon = iconName ? iconNode(iconName) : node("span", "", symbol);
  icon.setAttribute("aria-hidden", "true");
  button.append(icon, node("span", "", label));
  button.addEventListener("click", action);
  return button;
}

function scheduleSearch() {
  if (ui.searchTimer !== null) {
    window.clearTimeout(ui.searchTimer);
  }
  const query = elements.filter.value.trim();
  if (query.length < 2) {
    ui.searchQuery = query;
    ui.searchResults = [];
    ui.searchError = "";
    ui.searching = false;
    renderSearch(activeView());
    return;
  }
  ui.searching = true;
  ui.searchError = "";
  announce("Searching indexed knowledge");
  renderSearch(activeView());
  ui.searchTimer = window.setTimeout(() => performSearch(query), 250);
}

async function performSearch(query) {
  ui.searchTimer = null;
  try {
    const payload = await apiRequest(`/api/search?q=${encodeURIComponent(query)}&limit=50`);
    if (viewCategory(activeView()) !== "search" || elements.filter.value.trim() !== query) {
      return;
    }
    ui.searchQuery = query;
    ui.searchResults = asArray(payload?.results);
    ui.searchError = "";
    announce(`${formatNumber(ui.searchResults.length)} search result${ui.searchResults.length === 1 ? "" : "s"}`);
  } catch (error) {
    ui.searchError = error instanceof Error ? error.message : "Search could not be completed.";
    ui.searchResults = [];
    announce("Search failed");
  } finally {
    if (viewCategory(activeView()) === "search" && elements.filter.value.trim() === query) {
      ui.searching = false;
      renderSearch(activeView());
    }
  }
}

function renderSearch(view) {
  const query = elements.filter.value.trim();
  if (query.length < 2) {
    elements.viewRoot.replaceChildren(
      emptyState("Search the index", "Enter a name, identifier, location, document, or issue.", "⌕"),
    );
    setViewCount(null);
    return;
  }
  if (ui.searching && ui.searchQuery !== query) {
    const panel = node("div", "state-panel state-panel-loading");
    const spinner = node("span", "spinner");
    spinner.setAttribute("aria-hidden", "true");
    panel.append(spinner, node("strong", "", "Searching index"));
    elements.viewRoot.replaceChildren(panel);
    setViewCount(null);
    return;
  }
  if (ui.searchError) {
    elements.viewRoot.replaceChildren(emptyState("Search failed", ui.searchError, "!"));
    setViewCount(0);
    return;
  }
  const rows = ui.searchQuery === query ? ui.searchResults : [];
  setViewCount(rows.length);
  if (!rows.length) {
    elements.viewRoot.replaceChildren(
      emptyState("No search results", "No indexed record matches this query.", "⌕"),
    );
    return;
  }
  elements.viewRoot.replaceChildren(createTable({
    caption: scalarText(view?.label, "Search results"),
    columns: [
      { label: "Type", value: (row) => statusBadge(row.kind) },
      { key: "title", label: "Result", className: "primary-cell" },
      { key: "subtitle", label: "Context" },
      { key: "snippet", label: "Match", className: "cell-muted" },
      { key: "source_path", label: "Source", className: "cell-mono" },
    ],
    rows,
    rowLabel: (row) => `Open search result for ${scalarText(row.title, "record")}`,
    onOpen: openSearchResult,
  }));
}

function openSearchResult(result) {
  if (result.kind === "issue") {
    const issue = asArray(ui.state?.issues).find(
      (item) => item.issue_id === result.issue_id,
    ) || asObject(result.record);
    if (issue) {
      openIssueDetails(issue);
      return;
    }
  }
  openDetails(
    scalarText(result.title, "Search result"),
    [humanize(result.kind), result.subtitle].filter(Boolean).join(" · "),
    result,
  );
}

function renderOverview(view) {
  const summary = asObject(ui.state.summary);
  const hasData = Number(summary.sources || 0) > 0
    || Number(summary.documents || 0) > 0
    || Number(summary.entities || 0) > 0
    || Number(summary.active_assertions || 0) > 0;

  if (!hasData) {
    const scanning = operationIsActive();
    const scanned = Boolean(summary.latest_run);
    const scopeWarning = scalarText(ui.state?.source?.scope_warning, "");
    const panel = emptyState(
      scanning
        ? "Building your workspace"
        : scanned
          ? "No supported files found"
          : scopeWarning
            ? "System drive connected"
            : "Your source is connected",
      scanning
        ? "The first results will appear here automatically."
        : scanned
          ? "Choose another folder or scan again after files are added."
          : scopeWarning || "Start the first sync to create this workspace.",
      scanning ? "↻" : scanned ? "⌕" : "✓",
    );
    panel.append(renderSetupProgress(scanning, scanned));
    if (!scanning) {
      panel.append(commandButton(
        scanned ? "Sync again" : scopeWarning ? "Sync full drive" : "Sync now",
        "↻",
        startIndex,
      ));
    }
    elements.viewRoot.replaceChildren(panel);
    setViewCount(null);
    return;
  }

  const priority = { CRITICAL: 5, HIGH: 4, MEDIUM: 3, LOW: 2, INFO: 1 };
  const openIssues = asArray(ui.state.issues)
    .filter((issue) => String(issue.status || "OPEN").toUpperCase() === "OPEN")
    .sort((left, right) => (
      (priority[String(right.severity || "").toUpperCase()] || 0)
      - (priority[String(left.severity || "").toUpperCase()] || 0)
    ));
  const entities = asArray(ui.state.entities);
  const assertions = asArray(ui.state.assertions);
  const latestRun = asObject(summary.latest_run);

  const container = node("div", "home-command-center");
  container.append(renderWorkspaceSummary(summary, openIssues, latestRun));

  const commandGrid = node("div", "home-command-grid");
  commandGrid.append(
    renderKnowledgeMap(entities, assertions, openIssues),
    renderDecisionPanel(openIssues, latestRun),
  );
  container.append(commandGrid);

  if (Object.keys(latestRun).length) {
    container.append(renderLatestScanFooter(latestRun));
  }

  elements.viewRoot.replaceChildren(container);
  setViewCount(null);
}

function renderWorkspaceSummary(summary, openIssues, latestRun) {
  const section = node("section", "overview-summary");
  const status = node("div", `overview-status${openIssues.length ? " needs-review" : " is-current"}`);
  const marker = node("span", "overview-status-marker", openIssues.length ? "!" : "✓");
  marker.setAttribute("aria-hidden", "true");
  const copy = node("div", "overview-status-copy");
  copy.append(
    node(
      "strong",
      "",
      openIssues.length
        ? "Workspace needs attention"
        : "Workspace is up to date",
    ),
    node(
      "span",
      "",
      latestRun.completed_at
        ? `${openIssues.length ? `${formatNumber(openIssues.length)} review item${openIssues.length === 1 ? "" : "s"} · ` : ""}Latest sync ${formatDate(latestRun.completed_at)}`
        : "No completed sync recorded",
    ),
  );
  status.append(marker, copy);
  if (openIssues.length) {
    status.append(commandButton("Open review queue", "→", openReviewQueue, "button button-secondary"));
  } else {
    status.append(commandButton("Search workspace", "⌕", focusSearch, "button button-secondary"));
  }

  const metrics = node("dl", "overview-metrics");
  [
    ["Source files", summary.sources],
    ["Documents read", summary.documents],
    ["Lab items", summary.entities],
    ["Connections", summary.active_assertions],
  ].forEach(([label, value]) => {
    const metric = node("div", "overview-metric");
    metric.append(node("dt", "", label), node("dd", "", formatNumber(value)));
    metrics.append(metric);
  });
  section.append(status, metrics);
  return section;
}

function focusSearch() {
  const search = currentViews().find((view) => viewCategory(view) === "search");
  if (!search) {
    return;
  }
  chooseView(String(search.view_id));
  elements.filter.focus();
}

function openReviewQueue() {
  const review = currentViews().find(
    (view) => viewCategory(view) === "issues" && String(view.status || "").toUpperCase() === "OPEN",
  );
  if (review) {
    chooseView(String(review.view_id));
  }
}

function openNavigation() {
  document.body.classList.add("navigation-open");
  elements.mobileMenuButton.setAttribute("aria-expanded", "true");
  elements.sidebarBackdrop.tabIndex = 0;
  elements.mobileMenuClose.focus();
}

function closeNavigation({ restoreFocus = false } = {}) {
  const wasOpen = document.body.classList.contains("navigation-open");
  document.body.classList.remove("navigation-open");
  elements.mobileMenuButton.setAttribute("aria-expanded", "false");
  elements.sidebarBackdrop.tabIndex = -1;
  if (wasOpen && restoreFocus) {
    elements.mobileMenuButton.focus();
  }
}

function openTrustCenter() {
  const source = asObject(ui.state?.source);
  const health = asObject(ui.health);
  const automation = asObject(source.automation);
  const noEgress = source.no_egress === true;
  const parserIsolation = asObject(health.parser_isolation || source.parser_isolation);
  const healthLabel = health.ready === false ? "Needs attention" : "Healthy";
  const parserLabel = parserIsolation.enabled === false ? "Unavailable" : "Enabled";
  const schedule = automation.enabled
    ? `Automatic sync every ${formatNumber(automation.interval_minutes)} minutes`
    : "Automatic sync is off";
  openDetails(
    "Trust status",
    `${healthLabel} · Checked locally`,
    {
      "Data location": noEgress
        ? "Index data and extracted content stay on this computer."
        : "This workspace permits configured external connections.",
      Network: noEgress
        ? "External connections are blocked."
        : "External connections are allowed; review enabled modules before using sensitive data.",
      "Source safety": "Source files are read only and are never modified by LabOverlay.",
      Permissions: "Basic file permissions are observed. Access is not enforced by LabOverlay.",
      "System health": healthLabel,
      "Parser isolation": parserLabel,
      Automation: schedule,
    },
    ["Data location", "Network", "Source safety", "Permissions", "System health", "Parser isolation", "Automation"],
  );
}

function renderKnowledgeMap(entities, assertions, openIssues) {
  const panel = node("section", "knowledge-panel");
  const header = node("div", "knowledge-panel-header");
  const heading = node("div", "");
  heading.append(
    node("span", "panel-eyebrow", "Explore"),
    node("h2", "", "Knowledge map"),
  );
  header.append(heading, node("span", "map-live-badge", "Connected view"));

  const graph = knowledgeGraphData(entities, assertions, openIssues);
  const surface = node("div", "knowledge-map-surface");
  if (!graph.entities.length) {
    surface.append(node("p", "knowledge-map-empty", "Connections will appear after related lab items are found."));
  } else {
    surface.append(renderKnowledgeSvg(graph, openIssues));
  }
  panel.append(header, surface, renderKnowledgeLinks(graph.assertions, openIssues));

  const shown = graph.entities.length;
  const note = shown < entities.length
    ? `Showing ${formatNumber(shown)} of ${formatNumber(entities.length)} connected items`
    : `${formatNumber(shown)} items · ${formatNumber(graph.assertions.length)} visible connections`;
  panel.append(node("p", "knowledge-map-note", note));
  return panel;
}

function knowledgeGraphData(entities, assertions, openIssues) {
  const byId = new Map(entities.map((entity) => [String(entity.entity_id), entity]));
  const degree = new Map();
  assertions.forEach((assertion) => {
    [assertion.subject_entity_id, assertion.object_entity_id].forEach((identifier) => {
      if (identifier) {
        degree.set(String(identifier), (degree.get(String(identifier)) || 0) + 1);
      }
    });
  });
  const issueIds = new Set(openIssues.map((issue) => String(issue.entity_id || "")).filter(Boolean));
  const ordered = [...entities].sort((left, right) => {
    const leftIssue = issueIds.has(String(left.entity_id)) ? 1 : 0;
    const rightIssue = issueIds.has(String(right.entity_id)) ? 1 : 0;
    return rightIssue - leftIssue
      || (degree.get(String(right.entity_id)) || 0) - (degree.get(String(left.entity_id)) || 0)
      || scalarText(left.canonical_name, "").localeCompare(scalarText(right.canonical_name, ""));
  });

  const selected = [];
  const laneCounts = { center: 0, left: 0, right: 0 };
  for (const entity of ordered) {
    const lane = entityLane(entity);
    if (laneCounts[lane] >= 3 || selected.length >= 7) {
      continue;
    }
    selected.push(entity);
    laneCounts[lane] += 1;
  }
  const selectedIds = new Set(selected.map((entity) => String(entity.entity_id)));
  const selectedAssertions = assertions.filter(
    (assertion) => selectedIds.has(String(assertion.subject_entity_id))
      && selectedIds.has(String(assertion.object_entity_id))
      && byId.has(String(assertion.subject_entity_id))
      && byId.has(String(assertion.object_entity_id)),
  ).slice(0, 8);
  return { assertions: selectedAssertions, entities: selected };
}

function entityLane(entity) {
  const type = String(entity.entity_type || "").toUpperCase();
  if (["PERSON", "ORGANIZATION", "ORGANIZATIONAL_UNIT", "DOCUMENT"].includes(type)) {
    return "left";
  }
  if (type === "LOCATION") {
    return "right";
  }
  return "center";
}

function entityTypeLabel(entity) {
  const labels = {
    ASSET: "Equipment",
    DOCUMENT: "Document",
    LOCATION: "Location",
    ORGANIZATION: "Organization",
    ORGANIZATIONAL_UNIT: "Team",
    PERSON: "Person",
    PROCESS: "Process",
  };
  return labels[String(entity.entity_type || "").toUpperCase()] || humanize(entity.entity_type) || "Item";
}

function graphPositions(entities) {
  const lanes = { center: [], left: [], right: [] };
  entities.forEach((entity) => lanes[entityLane(entity)].push(entity));
  const xByLane = { left: 130, center: 380, right: 630 };
  const positions = new Map();
  Object.entries(lanes).forEach(([lane, items]) => {
    const yValues = items.length === 1
      ? [150]
      : items.length === 2
        ? [92, 208]
        : [54, 150, 246];
    items.forEach((entity, index) => {
      positions.set(String(entity.entity_id), { x: xByLane[lane], y: yValues[index] });
    });
  });
  return positions;
}

function renderKnowledgeSvg(graph, openIssues) {
  const svg = svgNode("svg", "knowledge-map", {
    "aria-hidden": "true",
    focusable: "false",
    viewBox: "0 0 760 300",
  });
  const title = svgNode("title");
  title.textContent = "Indexed laboratory knowledge map";
  const description = svgNode("desc");
  description.textContent = "Items are connected by relationships extracted from source evidence.";
  const definitions = svgNode("defs");
  const marker = svgNode("marker", "", {
    id: "knowledge-arrow",
    markerHeight: 7,
    markerWidth: 7,
    orient: "auto",
    refX: 6,
    refY: 3.5,
  });
  marker.append(svgNode("path", "knowledge-arrow", { d: "M 0 0 L 7 3.5 L 0 7 z" }));
  definitions.append(marker);
  svg.append(title, description, definitions);

  const positions = graphPositions(graph.entities);
  const conflictedAssertions = new Set(
    openIssues.flatMap((issue) => asArray(issue.assertion_ids).map(String)),
  );
  graph.assertions.forEach((assertion) => {
    const start = positions.get(String(assertion.subject_entity_id));
    const end = positions.get(String(assertion.object_entity_id));
    if (!start || !end) {
      return;
    }
    const conflicted = conflictedAssertions.has(String(assertion.assertion_id));
    const line = svgNode("line", `knowledge-edge${conflicted ? " is-conflicted" : ""}`, {
      "marker-end": "url(#knowledge-arrow)",
      x1: start.x,
      x2: end.x,
      y1: start.y,
      y2: end.y,
    });
    svg.append(line);

    const label = formatPredicate(assertion.predicate);
    const labelWidth = Math.min(126, Math.max(64, label.length * 5.8 + 16));
    const midpointX = (start.x + end.x) / 2;
    const midpointY = (start.y + end.y) / 2;
    const labelY = Math.abs(start.y - end.y) < 8 ? midpointY - 18 : midpointY;
    const labelGroup = svgNode("g", "knowledge-edge-label");
    labelGroup.append(
      svgNode("rect", "knowledge-edge-label-bg", {
        height: 20,
        rx: 4,
        width: labelWidth,
        x: midpointX - labelWidth / 2,
        y: labelY - 10,
      }),
    );
    const text = svgNode("text", "knowledge-edge-label-text", {
      "text-anchor": "middle",
      x: midpointX,
      y: labelY + 4,
    });
    text.textContent = label;
    labelGroup.append(text);
    svg.append(labelGroup);
  });

  const issueIds = new Set(openIssues.map((issue) => String(issue.entity_id || "")).filter(Boolean));
  graph.entities.forEach((entity) => {
    const position = positions.get(String(entity.entity_id));
    const type = String(entity.entity_type || "unknown").toLocaleLowerCase();
    const conflicted = issueIds.has(String(entity.entity_id));
    const group = svgNode("g", `knowledge-node node-${type}${conflicted ? " is-conflicted" : ""}`, {
      transform: `translate(${position.x - 82} ${position.y - 29})`,
    });
    group.append(svgNode("rect", "knowledge-node-shape", { height: 58, rx: 7, width: 164 }));
    const typeText = svgNode("text", "knowledge-node-type", { x: 14, y: 20 });
    typeText.textContent = entityTypeLabel(entity);
    const name = svgNode("text", "knowledge-node-name", { x: 14, y: 42 });
    const fullName = scalarText(entity.canonical_name, "Unnamed item");
    name.textContent = fullName.length > 20 ? `${fullName.slice(0, 19)}…` : fullName;
    group.append(typeText, name);
    if (conflicted) {
      group.append(svgNode("circle", "knowledge-node-alert", { cx: 151, cy: 13, r: 9 }));
      const alert = svgNode("text", "knowledge-node-alert-text", {
        "text-anchor": "middle",
        x: 151,
        y: 17,
      });
      alert.textContent = "!";
      group.append(alert);
    }
    const open = () => openDetails(
      fullName,
      [entity.entity_type, entity.subtype].filter(Boolean).map(humanize).join(" · "),
      entity,
    );
    group.addEventListener("click", open);
    svg.append(group);
  });
  return svg;
}

function renderKnowledgeLinks(assertions, openIssues = []) {
  const list = node("div", "knowledge-links");
  if (!assertions.length) {
    list.append(node("p", "knowledge-link-empty", "No relationships have been found yet."));
    return list;
  }
  const conflictedAssertions = new Set(
    openIssues.flatMap((issue) => asArray(issue.assertion_ids).map(String)),
  );
  assertions.forEach((assertion) => {
    const button = node("button", "knowledge-link");
    button.type = "button";
    const conflicted = conflictedAssertions.has(String(assertion.assertion_id));
    if (conflicted) {
      button.classList.add("is-conflicted");
    }
    const relation = node("span", "knowledge-link-relation");
    relation.append(
      node("strong", "", scalarText(assertion.subject_name, "Item")),
      node("span", "", formatPredicate(assertion.predicate)),
      node("strong", "", scalarText(assertion.object_name || assertion.literal, "Item")),
    );
    button.append(
      relation,
      node("span", "knowledge-link-source", scalarText(assertion.source_path, "Source evidence")),
    );
    button.setAttribute(
      "aria-label",
      `${scalarText(assertion.subject_name, "Item")} ${formatPredicate(assertion.predicate)} ${scalarText(assertion.object_name || assertion.literal, "Item")}. Source: ${scalarText(assertion.source_path, "unknown")}${conflicted ? ". Conflicting evidence" : ""}`,
    );
    button.addEventListener("click", () => openDetails(
      `${scalarText(assertion.subject_name, "Item")} ${formatPredicate(assertion.predicate)}`,
      scalarText(assertion.source_path, "Source evidence"),
      assertion,
    ));
    list.append(button);
  });
  return list;
}

function renderDecisionPanel(openIssues, latestRun) {
  const panel = node("section", `decision-panel${openIssues.length ? " has-issue" : " is-clear"}`);
  const issue = openIssues[0];
  if (!issue) {
    panel.append(
      node("span", "panel-eyebrow", "Review queue"),
      node("div", "decision-clear-mark", "✓"),
      node("h2", "", "Review queue is clear"),
      node("p", "decision-copy", "No open review items were reported by the latest completed sync."),
    );
    if (latestRun.completed_at) {
      panel.append(node("p", "decision-meta", `Checked ${formatDate(latestRun.completed_at)}`));
    }
    return panel;
  }

  const evidence = asObject(issue.evidence);
  const observations = asArray(evidence.observed_locations);
  panel.append(
    node("span", "panel-eyebrow", "Review queue"),
    statusBadge(issue.severity),
    node("h2", "", observations.length > 1 ? "Which location should LabOverlay use?" : issueLabel(issue.code)),
    node("p", "decision-subject", scalarText(issue.entity_name || evidence.subject_name, "Indexed item")),
    node(
      "p",
      "decision-copy",
      observations.length > 1
        ? `${formatNumber(observations.length)} sources disagree. Both original claims will remain preserved.`
        : "Review the source evidence and record your decision.",
    ),
  );

  if (observations.length) {
    const choices = node("div", "decision-evidence");
    observations.slice(0, 3).forEach((observation) => {
      const item = asObject(observation);
      const row = node("div", "decision-evidence-row");
      row.append(
        node("strong", "", scalarText(item.location_name, "Unknown location")),
        node("span", "", sourceEvidenceLabel(item.provenance)),
      );
      choices.append(row);
    });
    panel.append(choices);
  }

  const action = commandButton("Review and decide", "→", () => openIssueDetails(issue));
  action.classList.add("decision-action");
  panel.append(action);
  if (openIssues.length > 1) {
    panel.append(node("p", "decision-meta", `${formatNumber(openIssues.length - 1)} more review item${openIssues.length === 2 ? "" : "s"}`));
  }
  return panel;
}

function sourceEvidenceLabel(value) {
  const provenance = asObject(value);
  const locator = asObject(provenance.locator);
  const source = scalarText(provenance.source_external_id || provenance.source_path, "Source evidence");
  if (locator.cell) {
    return `${source} · ${[locator.sheet, locator.cell].filter(Boolean).join(" ")}`;
  }
  if (locator.page) {
    return `${source} · page ${locator.page}`;
  }
  if (locator.paragraph) {
    return `${source} · paragraph ${locator.paragraph}`;
  }
  return source;
}

function renderLatestScanFooter(run) {
  const status = String(run.status || "COMPLETED").toUpperCase();
  const tone = ["FAILED", "ERROR"].includes(status)
    ? "danger"
    : status === "CANCELLED"
      ? "warning"
      : status === "COMPLETED"
        ? "success"
        : "neutral";
  const footer = node("section", `latest-scan-footer is-${tone}`);
  const marker = node("span", "latest-scan-marker");
  marker.setAttribute("aria-hidden", "true");
  const copy = node("div", "latest-scan-copy");
  copy.append(
    node("strong", "", `Latest sync ${humanize(run.status || "completed").toLocaleLowerCase()}`),
    node("span", "", run.completed_at ? formatDate(run.completed_at) : "Sync details available"),
  );
  const details = commandButton(
    "View sync details",
    "→",
    () => openDetails("Latest sync", "Processing summary", run),
    "button button-secondary",
  );
  footer.append(marker, copy, details);
  return footer;
}

function renderSetupProgress(scanning, scanned) {
  const progress = node("div", "setup-progress");
  [
    ["Folder connected", "done"],
    ["Files synced", scanned ? "done" : scanning ? "active" : "waiting"],
    ["Ready to search", "waiting"],
  ].forEach(([label, state]) => {
    const row = node("div", `setup-step is-${state}`);
    const marker = node("span", "setup-step-marker", state === "done" ? "✓" : state === "active" ? "" : "·");
    if (state === "active") {
      marker.classList.add("spinner");
    }
    marker.setAttribute("aria-hidden", "true");
    row.append(marker, node("span", "", label));
    progress.append(row);
  });
  return progress;
}

function inferEntityType(view) {
  if (view.entity_type) {
    return String(view.entity_type).toUpperCase();
  }
  const identity = `${view.view_id || ""} ${view.label || ""}`.toUpperCase();
  if (identity.includes("EQUIPMENT") || identity.includes("ASSET")) {
    return "ASSET";
  }
  if (identity.includes("LOCATION")) {
    return "LOCATION";
  }
  if (identity.includes("PEOPLE") || identity.includes("PERSON")) {
    return "PERSON";
  }
  if (identity.includes("ORGANIZATION")) {
    return identity.includes("UNIT") ? "ORGANIZATIONAL_UNIT" : "ORGANIZATION";
  }
  return "";
}

function inferEntityTypes(view) {
  const configured = asArray(view.entity_types)
    .map((value) => String(value).toUpperCase())
    .filter(Boolean);
  if (configured.length) {
    return configured;
  }
  const inferred = inferEntityType(view);
  return inferred ? [inferred] : [];
}

function renderEntities(view) {
  const entityTypes = inferEntityTypes(view);
  const allRows = asArray(ui.state.entities).filter(
    (entity) => !entityTypes.length || entityTypes.includes(String(entity.entity_type).toUpperCase()),
  );
  const rows = filteredRows(allRows);
  setViewCount(view.count ?? allRows.length, rows.length);

  if (!rows.length) {
    elements.viewRoot.replaceChildren(
      emptyState(
        currentFilter() ? "No matching entities" : `No ${scalarText(view.label, "entities").toLocaleLowerCase()}`,
        currentFilter() ? "Change the current filter to see other records." : "No records are available in this view.",
        "⌖",
      ),
    );
    return;
  }

  const columns = [
    { key: "canonical_name", label: "Name", className: "primary-cell" },
    { label: "Type", value: (row) => typePair(row.entity_type, row.subtype) },
    { key: "identifier", label: "Identifier", className: "cell-mono" },
  ];
  if (entityTypes.includes("ASSET")) {
    columns.push(
      { label: "Current location", value: entityLocation },
      { label: "Responsible", value: entityResponsibility },
    );
  } else if (entityTypes.includes("LOCATION")) {
    columns.push({ label: "Equipment", value: locationEquipmentCount });
  } else if (entityTypes.includes("PERSON")) {
    columns.push({ label: "Responsibilities", value: personResponsibilityCount });
  }
  columns.push(
    { label: "Review", value: entityReviewStatus },
    { label: "First observed", value: entityFirstObserved, className: "cell-muted" },
  );

  const table = createTable({
    caption: scalarText(view.label, "Entities"),
    columns,
    rows,
    rowLabel: (row) => `Open ${scalarText(row.canonical_name, "entity")} details`,
    onOpen: (row) => openDetails(
      scalarText(row.canonical_name, "Entity"),
      [row.entity_type, row.subtype].filter(Boolean).map(humanize).join(" · "),
      row,
    ),
  });
  elements.viewRoot.replaceChildren(table);
}

function assertionsForEntity(entityId, predicate, direction = "subject") {
  const idKey = direction === "object" ? "object_entity_id" : "subject_entity_id";
  return asArray(ui.state?.assertions).filter(
    (assertion) => String(assertion[idKey] || "") === String(entityId || "")
      && String(assertion.predicate || "").toLocaleLowerCase() === predicate,
  );
}

function entityLocation(entity) {
  const locations = assertionsForEntity(entity.entity_id, "located_in")
    .map((assertion) => scalarText(assertion.object_name || assertion.literal, ""))
    .filter(Boolean);
  const unique = [...new Set(locations)];
  if (!unique.length) {
    return node("span", "cell-muted", "Not found");
  }
  if (unique.length > 1) {
    return node("span", "status-badge status-warning", `${formatNumber(unique.length)} locations`);
  }
  return unique[0];
}

function entityResponsibility(entity) {
  const people = assertionsForEntity(entity.entity_id, "responsible_for", "object")
    .map((assertion) => scalarText(assertion.subject_name, ""))
    .filter(Boolean);
  return [...new Set(people)].join(", ") || node("span", "cell-muted", "Not assigned");
}

function locationEquipmentCount(entity) {
  const count = assertionsForEntity(entity.entity_id, "located_in", "object").length;
  return `${formatNumber(count)} item${count === 1 ? "" : "s"}`;
}

function personResponsibilityCount(entity) {
  const count = assertionsForEntity(entity.entity_id, "responsible_for").length;
  return `${formatNumber(count)} item${count === 1 ? "" : "s"}`;
}

function entityReviewStatus(entity) {
  const open = asArray(ui.state?.issues).some(
    (issue) => String(issue.entity_id || "") === String(entity.entity_id || "")
      && String(issue.status || "OPEN").toUpperCase() === "OPEN",
  );
  return statusBadge(open ? "OPEN" : "CLEAR");
}

function entityFirstObserved(entity) {
  const metadata = asObject(entity.metadata);
  const firstObserved = asObject(metadata.first_observed);
  const provenance = asObject(firstObserved.provenance || metadata.provenance);
  return Object.keys(provenance).length ? sourceEvidenceLabel(provenance) : "—";
}

function typePair(primary, secondary) {
  const wrapper = node("span", "inline-pair");
  wrapper.append(node("span", "", humanize(primary)));
  if (secondary) {
    wrapper.append(node("span", "inline-secondary", humanize(secondary)));
  }
  return wrapper;
}

function responsibilityRows(view) {
  const explicit = asArray(ui.state.responsibilities);
  const source = explicit.length ? explicit : asArray(ui.state.assertions);
  const predicate = view.predicate ? String(view.predicate).toLocaleLowerCase() : "";
  return source.filter((assertion) => {
    if (predicate) {
      return String(assertion.predicate || "").toLocaleLowerCase() === predicate;
    }
    return explicit.length || String(assertion.predicate || "").toLocaleLowerCase().includes("responsib");
  });
}

function renderResponsibilities(view) {
  const allRows = responsibilityRows(view);
  const rows = filteredRows(allRows);
  setViewCount(view.count ?? allRows.length, rows.length);
  if (!rows.length) {
    elements.viewRoot.replaceChildren(
      emptyState(
        currentFilter() ? "No matching responsibilities" : "No responsibilities found",
        currentFilter() ? "Change the current filter to see other records." : "No responsibility records were found in the connected folder.",
        "✓",
      ),
    );
    return;
  }

  elements.viewRoot.replaceChildren(assertionTable(rows, scalarText(view.label, "Responsibilities")));
}

function assertionTable(rows, caption) {
  return createTable({
    caption,
    columns: [
      { key: "subject_name", label: "Who", className: "primary-cell" },
      { label: "Relationship", value: (row) => formatPredicate(row.predicate) },
      { label: "For", value: (row) => scalarText(row.object_name || row.literal) },
      { label: "Evidence", value: (row) => scalarText(row.source_path, "Unknown file") },
      { label: "Confidence", value: (row) => formatConfidence(row.confidence) },
    ],
    rows,
    rowLabel: (row) => `Open assertion details for ${scalarText(row.subject_name, "subject")}`,
    onOpen: (row) => openDetails(
      `${scalarText(row.subject_name, "Subject")} ${formatPredicate(row.predicate)}`,
      scalarText(row.object_name || row.literal, "Assertion evidence"),
      row,
      ["assertion_id", "status", "confidence", "source_path", "source_record_id", "provenance"],
    ),
  });
}

function sourcePair(path, id) {
  const wrapper = node("span", "inline-pair");
  wrapper.append(node("span", "", scalarText(path, "Unknown source")));
  if (id) {
    wrapper.append(node("span", "inline-secondary cell-mono", scalarText(id)));
  }
  return wrapper;
}

function renderDocuments(view) {
  const allRows = asArray(ui.state.documents);
  const rows = filteredRows(allRows);
  setViewCount(view.count ?? allRows.length, rows.length);
  if (!rows.length) {
    elements.viewRoot.replaceChildren(
      emptyState(
        currentFilter() ? "No matching documents" : "No documents found",
        currentFilter() ? "Change the current filter to see other records." : "No supported documents were found in the connected folder.",
        "▧",
      ),
    );
    return;
  }

  elements.viewRoot.replaceChildren(createTable({
    caption: scalarText(view.label, "Documents"),
    columns: [
      { key: "source_path", label: "Document", className: "primary-cell" },
      { label: "Type", value: (row) => contentTypeLabel(row.content_type) },
      { label: "Information found", value: extractionCoverage },
      { label: "Warnings", value: extractionWarnings },
      { label: "Last scanned", value: (row) => formatDate(row.created_at) },
    ],
    rows,
    rowLabel: (row) => `Open document details for ${scalarText(row.source_path, "document")}`,
    onOpen: (row) => openDetails(
      scalarText(row.source_path, "Document"),
      scalarText(row.content_type, "Document record"),
      row,
    ),
  }));
}

function extractionCoverage(row) {
  const entities = Number(row.extracted_entity_count || 0);
  const assertions = Number(row.extracted_assertion_count || 0);
  return `${formatNumber(entities)} items · ${formatNumber(assertions)} connections`;
}

function extractionWarnings(row) {
  const parserWarnings = asArray(row.parser_warnings);
  const extractionWarnings = asArray(row.processing).flatMap(
    (item) => asArray(item.warnings),
  );
  const count = parserWarnings.length + extractionWarnings.length;
  return node(
    "span",
    `status-badge ${count ? "status-warning" : "status-success"}`,
    count ? `${count} warning${count === 1 ? "" : "s"}` : "Clear",
  );
}

function modulePair(moduleId, version) {
  const wrapper = node("span", "inline-pair");
  wrapper.append(node("span", "cell-mono", scalarText(moduleId)));
  if (version) {
    wrapper.append(node("span", "inline-secondary", `v${version}`));
  }
  return wrapper;
}

function issueTable(rows, caption) {
  return createTable({
    caption,
    columns: [
      { label: "Priority", value: (row) => statusBadge(row.severity) },
      { label: "Finding", value: (row) => issueLabel(row.code), className: "primary-cell" },
      { key: "entity_name", label: "Item" },
      { label: "Evidence", value: (row) => evidenceSummary(row.evidence), className: "cell-muted" },
      { label: "Status", value: (row) => statusBadge(row.status) },
    ],
    rows,
    rowLabel: (row) => `Open issue details for ${scalarText(row.code, "issue")}`,
    onOpen: openIssueDetails,
  });
}

function openIssueDetails(issue) {
  const observations = asArray(asObject(issue.evidence).observed_locations);
  openDetails(
    observations.length > 1 ? "Which location should LabOverlay use?" : issueLabel(issue.code),
    scalarText(issue.entity_name, "Review source evidence"),
    issue,
    ["severity", "status", "entity_name", "evidence", "reviews"],
  );
  if (String(issue.status || "").toUpperCase() !== "OPEN") {
    return;
  }

  const section = node("section", "detail-group review-form");
  section.append(node("span", "detail-label", "Record a decision"));
  const form = document.createElement("form");
  if (observations.length) {
    const fieldset = document.createElement("fieldset");
    fieldset.append(node("legend", "review-legend", "Authoritative location"));
    observations.forEach((observation, index) => {
      const item = asObject(observation);
      const option = node("label", "review-option");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "assertion_id";
      radio.value = scalarText(item.assertion_id, "");
      radio.required = true;
      const copy = node("span", "inline-pair");
      copy.append(
        node("strong", "", `Use ${scalarText(item.location_name, `location ${index + 1}`)}`),
        node("span", "inline-secondary", locationEvidenceSummary(item)),
      );
      option.append(radio, copy);
      fieldset.append(option);
    });
    form.append(fieldset);
  }

  form.append(node(
    "p",
    "review-impact",
    "The selected value becomes current in the index. Source files and original claims will not change.",
  ));

  const reasonLabel = node("label", "review-reason-label", "Decision rationale");
  const reason = document.createElement("textarea");
  reason.name = "reason";
  reason.required = true;
  reason.maxLength = 1000;
  reason.rows = 3;
  reasonLabel.append(reason);

  const error = node("p", "review-error");
  error.setAttribute("role", "alert");
  const actions = node("div", "review-actions");
  if (observations.length) {
    const confirm = commandButton("Confirm decision", "✓", () => {
      const selected = form.querySelector('input[name="assertion_id"]:checked');
      if (!form.reportValidity() || !selected) {
        return;
      }
      submitIssueReview(issue, "CONFIRM_ASSERTION", selected.value, reason.value, form, error);
    });
    confirm.type = "button";
    actions.append(confirm);
  }
  const dismiss = commandButton("Dismiss finding", "×", () => {
    if (!reason.reportValidity()) {
      return;
    }
    submitIssueReview(issue, "DISMISS", null, reason.value, form, error);
  }, "button button-secondary");
  dismiss.type = "button";
  actions.append(dismiss);
  form.append(reasonLabel, error, actions);
  section.append(form);
  elements.detailBody.prepend(section);
}

async function submitIssueReview(issue, decision, assertionId, reason, form, errorElement) {
  Array.from(form.elements).forEach((control) => {
    control.disabled = true;
  });
  errorElement.textContent = "";
  announce("Saving decision");
  try {
    await apiRequest("/api/review-issue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        issue_id: issue.issue_id,
        decision,
        assertion_id: assertionId,
        reason,
      }),
    });
    closeDetails();
    await refreshState({ announceRefresh: false });
    announce(decision === "DISMISS" ? "Issue dismissed" : "Location confirmed");
  } catch (error) {
    errorElement.textContent = error instanceof Error ? error.message : "Review could not be saved.";
    Array.from(form.elements).forEach((control) => {
      control.disabled = false;
    });
  }
}

function evidenceSummary(evidence) {
  if (Array.isArray(evidence)) {
    return evidence.length ? `${formatNumber(evidence.length)} evidence record${evidence.length === 1 ? "" : "s"}` : "—";
  }
  if (evidence && typeof evidence === "object") {
    const observedLocations = asArray(evidence.observed_locations);
    if (observedLocations.length) {
      return observedLocations.map(locationEvidenceSummary).join("; ");
    }
    return summarizeMetadata(evidence);
  }
  return scalarText(evidence);
}

function locationEvidenceSummary(value) {
  const item = asObject(value);
  const provenance = asObject(item.provenance);
  const locator = asObject(provenance.locator);
  const source = scalarText(
    provenance.source_external_id || provenance.source_path,
    "unknown source",
  );
  let position = "";
  if (locator.cell) {
    position = [locator.sheet || locator.table_name, locator.cell].filter(Boolean).join(" ");
  } else if (locator.page) {
    position = `page ${locator.page}`;
  } else if (locator.paragraph) {
    position = `paragraph ${locator.paragraph}`;
  } else if (locator.line) {
    position = `line ${locator.line}`;
  }
  const reference = [source, position].filter(Boolean).join(", ");
  return `${scalarText(item.location_name, "Unknown location")} (${reference})`;
}

function renderIssues(view) {
  const requestedStatus = view.status ? String(view.status).toUpperCase() : "";
  const allRows = asArray(ui.state.issues).filter(
    (issue) => !requestedStatus || String(issue.status || "").toUpperCase() === requestedStatus,
  );
  const rows = filteredRows(allRows);
  setViewCount(view.count ?? allRows.length, rows.length);
  if (!rows.length) {
    elements.viewRoot.replaceChildren(
      emptyState(
        currentFilter() ? "Nothing matches this filter" : "Nothing needs review",
        currentFilter() ? "Change the current filter to see other records." : "There are no review items in this view.",
        currentFilter() ? "⌕" : "✓",
      ),
    );
    return;
  }
  elements.viewRoot.replaceChildren(issueTable(rows, scalarText(view.label, "Issues")));
}

function renderSources(view) {
  const allRows = asArray(ui.state.sources);
  const rows = filteredRows(allRows);
  setViewCount(view.count ?? allRows.length, rows.length);
  if (!rows.length) {
    elements.viewRoot.replaceChildren(
      emptyState(
        currentFilter() ? "No matching files" : "No files found",
        currentFilter() ? "Change the current filter to see other records." : "The connected folder does not contain supported files.",
        "↗",
      ),
    );
    return;
  }

  elements.viewRoot.replaceChildren(createTable({
    caption: scalarText(view.label, "Files"),
    columns: [
      { label: "File", value: (row) => scalarText(row.path || row.name), className: "primary-cell" },
      { label: "Type", value: (row) => contentTypeLabel(row.content_type) },
      { label: "Size", value: (row) => formatBytes(row.size_bytes) },
      { label: "Modified", value: (row) => formatDate(row.modified_at) },
      { label: "Access", value: sourceAccess },
      { label: "State", value: (row) => statusBadge(row.deleted_at ? "Deleted" : "Active") },
    ],
    rows,
    rowLabel: (row) => `Open source details for ${scalarText(row.path || row.name, "source")}`,
    onOpen: (row) => openDetails(
      scalarText(row.name || row.path, "Source record"),
      scalarText(row.path, scalarText(row.source_record_id)),
      row,
    ),
  }));
}

function sourceAccess(row) {
  const permissions = asObject(row.permission_metadata);
  const owner = asObject(permissions.owner);
  const group = asObject(permissions.group);
  const parts = [];
  if (owner.name || owner.id !== undefined) {
    parts.push(`Owner ${scalarText(owner.name ?? owner.id)}`);
  }
  if (group.name || group.id !== undefined) {
    parts.push(`Group ${scalarText(group.name ?? group.id)}`);
  }
  return parts.length ? parts.join(" · ") : humanize(permissions.permission_model || "Basic");
}

function normalizedModules() {
  const raw = ui.state?.modules;
  let modules;
  if (Array.isArray(raw)) {
    modules = raw;
  } else if (Array.isArray(raw?.modules)) {
    modules = raw.modules;
  } else if (raw && typeof raw === "object") {
    modules = Object.entries(raw).map(([moduleId, value]) => ({
      module_id: moduleId,
      ...asObject(value),
    }));
  } else {
    modules = [];
  }

  return modules.map((entry) => {
    const manifest = asObject(entry.manifest);
    const health = asObject(entry.health);
    const directHealth = typeof entry.health === "string" ? entry.health : null;
    return {
      ...entry,
      capabilities: entry.capabilities ?? manifest.capabilities,
      dependencies: entry.dependencies ?? manifest.dependencies,
      description: entry.description ?? manifest.description,
      enabled: entry.enabled !== false,
      health_message: entry.health_message ?? entry.health_detail ?? health.message ?? entry.message,
      health_state: entry.health_state ?? directHealth ?? health.state ?? entry.status ?? "UNKNOWN",
      module_id: entry.module_id ?? manifest.module_id ?? entry.id,
      module_type: entry.module_type ?? manifest.module_type ?? entry.type,
      name: entry.name ?? manifest.name,
      version: entry.version ?? manifest.version,
    };
  });
}

function renderModules(view) {
  const allRows = normalizedModules();
  const rows = filteredRows(allRows);
  setViewCount(view.count ?? allRows.length, rows.length);
  if (!rows.length) {
    elements.viewRoot.replaceChildren(
      emptyState(
        currentFilter() ? "No matching system components" : "System status unavailable",
        currentFilter() ? "Change the current filter to see other records." : "No system components reported their status.",
        "◇",
      ),
    );
    return;
  }

  elements.viewRoot.replaceChildren(createTable({
    caption: scalarText(view.label, "System status"),
    columns: [
      { label: "Component", value: (row) => scalarText(row.name, scalarText(row.module_id)), className: "primary-cell" },
      { label: "Status", value: (row) => statusBadge(row.enabled ? row.health_state : "Disabled") },
      { key: "health_message", label: "Details", className: "cell-muted" },
    ],
    rows,
    rowLabel: (row) => `Open module details for ${scalarText(row.module_id, "module")}`,
    onOpen: (row) => openDetails(
      scalarText(row.name, scalarText(row.module_id, "Module")),
      `${scalarText(row.module_id)} · v${scalarText(row.version)}`,
      row,
      ["module_id", "module_type", "version", "enabled", "health_state", "health_message", "dependencies", "capabilities", "description"],
    ),
  }));
}

function moduleName(row) {
  const wrapper = node("span", "inline-pair");
  wrapper.append(node("span", "", scalarText(row.name, scalarText(row.module_id))));
  if (row.name && row.module_id) {
    wrapper.append(node("span", "inline-secondary cell-mono", scalarText(row.module_id)));
  }
  return wrapper;
}

function renderUnknownView(view) {
  const assertions = asArray(ui.state.assertions);
  if (assertions.length) {
    const rows = filteredRows(assertions);
    setViewCount(assertions.length, rows.length);
    if (rows.length) {
      elements.viewRoot.replaceChildren(assertionTable(rows, scalarText(view.label, "Assertions")));
      return;
    }
  }
  elements.viewRoot.replaceChildren(
    emptyState("No records", "This enabled view has no records to display.", "◇"),
  );
  setViewCount(view.count ?? 0, 0);
}

function statusTone(value) {
  const status = String(value || "").toUpperCase();
  if (["HEALTHY", "ACTIVE", "ENABLED", "COMPLETED", "CONFIRMED", "DIRECT", "RESOLVED", "CLOSED", "CLEAR"].includes(status)) {
    return "status-success";
  }
  if (["ERROR", "FAILED", "CRITICAL", "HIGH", "CONFLICTED", "REJECTED", "UNAVAILABLE"].includes(status)) {
    return "status-danger";
  }
  if (["WARNING", "MEDIUM", "OPEN", "DEGRADED", "MISCONFIGURED", "UNKNOWN", "INFERRED"].includes(status)) {
    return "status-warning";
  }
  if (["INDEXING", "RUNNING", "INFO", "LOW"].includes(status)) {
    return "status-blue";
  }
  return "status-neutral";
}

function statusBadge(value) {
  const status = String(value || "").toUpperCase();
  const labels = {
    DEGRADED: "Limited",
    DIRECT: "From source",
    ERROR: "Important",
    MISCONFIGURED: "Setup needed",
    OPEN: "Needs review",
  };
  return node(
    "span",
    `status-badge ${statusTone(value)}`,
    labels[status] || humanize(value) || "Unknown",
  );
}

function createTable({ caption, columns, rows, onOpen, rowLabel }) {
  const frame = node("div", "table-frame");
  const table = node("table", "data-table");
  table.append(node("caption", "visually-hidden", caption));

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const heading = node("th", "", column.label);
    heading.scope = "col";
    headRow.append(heading);
  });
  if (onOpen) {
    const actionHeading = node("th", "row-action-heading");
    actionHeading.scope = "col";
    actionHeading.append(node("span", "visually-hidden", "Open record"));
    headRow.append(actionHeading);
  }
  head.append(headRow);
  table.append(head);

  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const tableRow = document.createElement("tr");
    columns.forEach((column) => {
      const cell = node("td", column.className || "");
      cell.dataset.label = column.label;
      const value = column.value ? column.value(row) : row[column.key];
      if (value instanceof Node) {
        cell.append(value);
      } else {
        cell.textContent = scalarText(value);
      }
      tableRow.append(cell);
    });

    if (onOpen) {
      tableRow.classList.add("is-clickable");
      const open = () => onOpen(row);
      tableRow.addEventListener("click", open);
      const actionCell = node("td", "row-action-cell");
      actionCell.dataset.label = "Open";
      const action = node("button", "row-open-button");
      action.type = "button";
      action.append(iconNode("arrow-right"));
      action.setAttribute("aria-haspopup", "dialog");
      action.setAttribute("aria-label", rowLabel ? rowLabel(row) : "Open record details");
      action.addEventListener("click", (event) => {
        event.stopPropagation();
        open();
      });
      actionCell.append(action);
      tableRow.append(actionCell);
    }
    body.append(tableRow);
  });
  table.append(body);
  frame.append(table);
  return frame;
}

function activateOnKeyboard(event, action) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

function orderedEntries(record, preferredKeys = []) {
  const source = asObject(record);
  const preferred = preferredKeys
    .filter((key, index) => key in source && preferredKeys.indexOf(key) === index)
    .map((key) => [key, source[key]]);
  const preferredSet = new Set(preferred.map(([key]) => key));
  const remaining = Object.entries(source)
    .filter(([key]) => !preferredSet.has(key))
    .sort(([left], [right]) => left.localeCompare(right));
  return [...preferred, ...remaining];
}

function isTechnicalDetailKey(key) {
  const normalized = String(key || "").toLocaleLowerCase();
  return normalized === "metadata"
    || normalized === "processing"
    || normalized === "configuration"
    || normalized === "capabilities"
    || normalized === "dependencies"
    || normalized === "checksum"
    || normalized === "content_hash"
    || normalized === "version"
    || normalized.endsWith("_version")
    || normalized.endsWith("_id")
    || normalized.endsWith("_ids")
    || normalized.includes("module_id")
    || normalized.includes("external_id");
}

function defaultDetailKeys(record) {
  const preferred = [
    "canonical_name",
    "name",
    "entity_type",
    "subtype",
    "identifier",
    "subject_name",
    "predicate",
    "object_name",
    "literal",
    "severity",
    "status",
    "code",
    "description",
    "source_path",
    "path",
    "content_type",
    "extracted_entity_count",
    "extracted_assertion_count",
    "parser_warnings",
    "health_state",
    "health_message",
    "permission_metadata",
    "evidence",
    "reviews",
    "size_bytes",
    "modified_at",
    "created_at",
    "started_at",
    "completed_at",
  ];
  return preferred.filter((key) => key in asObject(record));
}

function detailGroup(key, value) {
  const group = node("section", "detail-group");
  group.append(node("span", "detail-label", humanize(key)));
  group.append(renderDetailValue(value));
  return group;
}

function openDetails(title, subtitle, record, preferredKeys = []) {
  ui.returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  elements.detailTitle.textContent = title;
  elements.detailSubtitle.textContent = subtitle;

  const fragment = document.createDocumentFragment();
  const visibleKeys = preferredKeys.length ? preferredKeys : defaultDetailKeys(record);
  const entries = orderedEntries(record, visibleKeys);
  const visibleEntries = entries.filter(
    ([key]) => visibleKeys.includes(key) && !isTechnicalDetailKey(key),
  );
  const visibleSet = new Set(visibleEntries.map(([key]) => key));
  visibleEntries.forEach(([key, value]) => fragment.append(detailGroup(key, value)));

  const technicalEntries = entries.filter(([key]) => !visibleSet.has(key));
  if (technicalEntries.length) {
    const disclosure = node("details", "technical-details");
    disclosure.append(node("summary", "", "Technical details"));
    const body = node("div", "technical-details-body");
    technicalEntries.forEach(([key, value]) => body.append(detailGroup(key, value)));
    disclosure.append(body);
    fragment.append(disclosure);
  }
  elements.detailBody.replaceChildren(fragment);

  if (typeof elements.detailDialog.showModal === "function") {
    elements.detailDialog.showModal();
  } else {
    elements.detailDialog.setAttribute("open", "");
  }
  elements.detailClose.focus();
}

function renderDetailValue(value, depth = 0) {
  if (value === null || value === undefined || value === "") {
    return node("p", "detail-value cell-muted", "—");
  }
  if (depth >= 5 && typeof value === "object") {
    return node("pre", "detail-value cell-mono", readableJson(value));
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return node("p", "detail-value cell-muted", "None");
    }
    const list = node("ul", "detail-list");
    value.forEach((item) => {
      const listItem = document.createElement("li");
      listItem.append(renderDetailValue(item, depth + 1));
      list.append(listItem);
    });
    return list;
  }
  if (typeof value === "object") {
    const entries = orderedEntries(value, DETAIL_KEY_ORDER);
    if (!entries.length) {
      return node("p", "detail-value cell-muted", "None");
    }
    const details = node("dl", "nested-details");
    entries.forEach(([key, item]) => {
      details.append(node("dt", "", humanize(key)));
      const description = document.createElement("dd");
      description.append(renderDetailValue(item, depth + 1));
      details.append(description);
    });
    return details;
  }
  return node("p", "detail-value", scalarText(value));
}

function closeDetails() {
  if (typeof elements.detailDialog.close === "function") {
    elements.detailDialog.close();
  } else {
    elements.detailDialog.removeAttribute("open");
  }
}

elements.refreshButton.addEventListener("click", () => refreshState({ announceRefresh: true }));
elements.changeSourceButton.addEventListener("click", changeSource);
elements.indexButton.addEventListener("click", startIndex);
elements.cancelIndexButton.addEventListener("click", cancelIndex);
elements.shutdownButton.addEventListener("click", stopApplication);
elements.globalSearchButton.addEventListener("click", focusSearch);
elements.trustButton.addEventListener("click", openTrustCenter);
elements.mobileMenuButton.addEventListener("click", openNavigation);
elements.mobileMenuClose.addEventListener("click", () => closeNavigation({ restoreFocus: true }));
elements.sidebarBackdrop.addEventListener("click", () => closeNavigation({ restoreFocus: true }));
elements.filter.addEventListener("input", (event) => {
  ui.filterByView.set(ui.activeViewId, event.target.value);
  if (viewCategory(activeView()) === "search") {
    scheduleSearch();
  } else {
    renderActiveView();
  }
});
elements.detailClose.addEventListener("click", closeDetails);
elements.detailDialog.addEventListener("click", (event) => {
  if (event.target === elements.detailDialog) {
    closeDetails();
  }
});
elements.detailDialog.addEventListener("close", () => {
  ui.returnFocus?.focus();
  ui.returnFocus = null;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("navigation-open")) {
    closeNavigation({ restoreFocus: true });
    return;
  }
  const target = event.target;
  const typing = target instanceof HTMLInputElement
    || target instanceof HTMLTextAreaElement
    || target instanceof HTMLSelectElement
    || target?.isContentEditable;
  if (event.key === "/" && !typing && !elements.detailDialog.open) {
    event.preventDefault();
    focusSearch();
  }
});

refreshState();
