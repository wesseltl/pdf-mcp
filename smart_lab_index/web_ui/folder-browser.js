"use strict";

const SESSION_TOKEN = document.querySelector('meta[name="smart-lab-session"]')?.content || "";
const elements = {
  announcement: document.getElementById("announcement"),
  breadcrumbs: document.getElementById("breadcrumbs"),
  cancelButton: document.getElementById("cancel-button"),
  folderHeading: document.getElementById("folder-heading"),
  folderList: document.getElementById("folder-list"),
  folderState: document.getElementById("folder-state"),
  hiddenToggle: document.getElementById("hidden-toggle"),
  quickLocations: document.getElementById("quick-locations"),
  refreshButton: document.getElementById("refresh-button"),
  selectedPath: document.getElementById("selected-path"),
  selectButton: document.getElementById("select-button"),
  upButton: document.getElementById("up-button"),
};

const ui = {
  busy: false,
  current: null,
  stopped: false,
};

function announce(message) {
  elements.announcement.textContent = "";
  window.setTimeout(() => {
    elements.announcement.textContent = message;
  }, 20);
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
    headers: {
      "X-Smart-Lab-Session": SESSION_TOKEN,
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "The folder could not be opened.");
  }
  return payload;
}

function button(label, className, onClick, title = "") {
  const control = document.createElement("button");
  control.type = "button";
  control.className = className;
  control.textContent = label;
  control.title = title;
  control.addEventListener("click", onClick);
  return control;
}

async function loadFolder(path = null) {
  if (ui.busy || ui.stopped) {
    return;
  }
  ui.busy = true;
  updateControls();
  elements.folderState.textContent = "Loading folders…";
  try {
    const query = new URLSearchParams();
    if (path) {
      query.set("path", path);
    }
    if (elements.hiddenToggle.checked) {
      query.set("hidden", "1");
    }
    const suffix = query.toString() ? `?${query}` : "";
    ui.current = await apiRequest(`/api/folders${suffix}`);
    renderFolder();
    announce(`${ui.current.name} opened`);
  } catch (error) {
    elements.folderState.textContent = error instanceof Error ? error.message : "The folder could not be opened.";
  } finally {
    ui.busy = false;
    updateControls();
  }
}

function renderFolder() {
  const current = ui.current;
  if (!current) {
    return;
  }
  elements.folderHeading.textContent = current.name;
  elements.selectedPath.textContent = current.path;
  elements.selectedPath.title = current.path;
  elements.upButton.disabled = !current.parent;
  elements.folderList.replaceChildren();

  for (const folder of current.folders) {
    const row = button(folder.name, "folder-row", () => loadFolder(folder.path), `Open ${folder.name}`);
    const icon = document.createElement("span");
    icon.className = "folder-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "▰";
    const name = document.createElement("span");
    name.className = "folder-name";
    name.textContent = folder.name;
    const arrow = document.createElement("span");
    arrow.className = "folder-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "›";
    row.replaceChildren(icon, name, arrow);
    elements.folderList.append(row);
  }

  if (!current.folders.length) {
    elements.folderState.textContent = "No folders inside this location.";
  } else if (current.truncated) {
    elements.folderState.textContent = "Showing the first 500 folders.";
  } else {
    elements.folderState.textContent = `${current.folders.length} folder${current.folders.length === 1 ? "" : "s"}`;
  }

  elements.breadcrumbs.replaceChildren();
  current.ancestors.forEach((ancestor, index) => {
    const crumb = button(ancestor.name, "breadcrumb", () => loadFolder(ancestor.path), ancestor.path);
    if (index === current.ancestors.length - 1) {
      crumb.setAttribute("aria-current", "page");
    }
    elements.breadcrumbs.append(crumb);
  });

  elements.quickLocations.replaceChildren();
  const locations = [current.home, ...current.roots.filter((root) => root.path !== current.home.path)];
  for (const location of locations) {
    const locationButton = button(location.name, "quick-location", () => loadFolder(location.path), location.path);
    const marker = document.createElement("span");
    marker.setAttribute("aria-hidden", "true");
    marker.textContent = location.name === "Home" ? "⌂" : "▣";
    const label = document.createElement("span");
    label.textContent = location.name;
    locationButton.replaceChildren(marker, label);
    elements.quickLocations.append(locationButton);
  }
}

function updateControls() {
  const disabled = ui.busy || ui.stopped;
  elements.cancelButton.disabled = disabled;
  elements.hiddenToggle.disabled = disabled;
  elements.refreshButton.disabled = disabled;
  elements.selectButton.disabled = disabled || !ui.current;
  elements.upButton.disabled = disabled || !ui.current?.parent;
}

async function selectCurrentFolder() {
  if (!ui.current || ui.busy || ui.stopped) {
    return;
  }
  ui.busy = true;
  updateControls();
  try {
    await apiRequest("/api/select-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: ui.current.path }),
    });
    ui.stopped = true;
    showOpeningState();
    window.setTimeout(waitForWorkspace, 500);
  } catch (error) {
    elements.folderState.textContent = error instanceof Error ? error.message : "The folder could not be selected.";
    ui.busy = false;
    updateControls();
  }
}

async function cancelSelection() {
  if (ui.busy || ui.stopped) {
    return;
  }
  ui.busy = true;
  updateControls();
  try {
    await apiRequest("/api/cancel", { method: "POST" });
    ui.stopped = true;
    document.querySelector(".picker-shell").innerHTML = `
      <section class="closed-state">
        <div class="closed-mark" aria-hidden="true">SL</div>
        <h1>Folder selection cancelled</h1>
        <p>You can close this tab.</p>
      </section>`;
  } catch (error) {
    elements.folderState.textContent = error instanceof Error ? error.message : "The app could not close the chooser.";
    ui.busy = false;
    updateControls();
  }
}

function showOpeningState() {
  document.querySelector(".picker-shell").innerHTML = `
    <section class="closed-state">
      <div class="loading-ring" aria-hidden="true"></div>
      <h1>Opening workspace</h1>
      <p>Your local index is starting.</p>
    </section>`;
}

async function waitForWorkspace() {
  while (ui.stopped) {
    try {
      const response = await fetch("/", { cache: "no-store", credentials: "same-origin" });
      const html = response.ok ? await response.text() : "";
      if (response.ok && html && !html.includes(SESSION_TOKEN)) {
        window.location.reload();
        return;
      }
    } catch (_error) {
      // The loopback server restarts after validating the selected folder.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
}

elements.upButton.addEventListener("click", () => loadFolder(ui.current?.parent));
elements.refreshButton.addEventListener("click", () => loadFolder(ui.current?.path));
elements.hiddenToggle.addEventListener("change", () => loadFolder(ui.current?.path));
elements.selectButton.addEventListener("click", selectCurrentFolder);
elements.cancelButton.addEventListener("click", cancelSelection);

loadFolder();
