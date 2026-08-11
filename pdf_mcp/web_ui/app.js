const sessionToken = document.querySelector('meta[name="pdf-mcp-session"]').content;
const maxFileBytes = 25 * 1024 * 1024;
const supportedExtensions = [".pdf", ".docx"];
const formatNames = { xlsx: "Excel", csv: "CSV", json: "JSON" };

const converter = document.getElementById("converter");
const results = document.getElementById("results");
const fileInput = document.getElementById("file-input");
const dropZone = document.getElementById("drop-zone");
const selectedFilePanel = document.getElementById("selected-file");
const fileName = document.getElementById("file-name");
const fileSize = document.getElementById("file-size");
const fileType = document.getElementById("file-type");
const removeFile = document.getElementById("remove-file");
const convertButton = document.getElementById("convert-button");
const mergePages = document.getElementById("merge-pages");
const errorMessage = document.getElementById("error-message");
const errorTitle = document.getElementById("error-title");
const errorDetail = document.getElementById("error-detail");
const errorHint = document.getElementById("error-hint");
const downloadButton = document.getElementById("download-button");
const convertAnother = document.getElementById("convert-another");
const stopApp = document.getElementById("stop-app");

let selectedFile = null;
let conversionResult = null;

function outputFormat() {
  return document.querySelector('input[name="output-format"]:checked').value;
}

function extensionOf(name) {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function displaySize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function clearError() {
  errorMessage.hidden = true;
  errorTitle.textContent = "";
  errorDetail.textContent = "";
  errorHint.textContent = "";
}

function showError(title, detail = "", hint = "") {
  errorTitle.textContent = title;
  errorDetail.textContent = detail;
  errorDetail.hidden = !detail;
  errorHint.textContent = hint;
  errorHint.hidden = !hint;
  errorMessage.hidden = false;
  errorMessage.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function chooseFile(file) {
  clearError();
  if (!file) return;
  const extension = extensionOf(file.name);
  if (!supportedExtensions.includes(extension)) {
    showError("Choose a PDF or Word document.", "The selected file must end in .pdf or .docx.");
    return;
  }
  if (file.size <= 0) {
    showError("This file is empty.", "Choose a document that contains a table.");
    return;
  }
  if (file.size > maxFileBytes) {
    showError("This file is larger than 25 MB.", "Choose a smaller document and try again.");
    return;
  }
  selectedFile = file;
  fileName.textContent = file.name;
  fileSize.textContent = displaySize(file.size);
  fileType.textContent = extension === ".pdf" ? "PDF" : "DOCX";
  dropZone.hidden = true;
  selectedFilePanel.hidden = false;
  convertButton.disabled = false;
}

function resetFile() {
  selectedFile = null;
  fileInput.value = "";
  dropZone.hidden = false;
  selectedFilePanel.hidden = true;
  convertButton.disabled = true;
  clearError();
}

function setBusy(busy) {
  convertButton.disabled = busy || !selectedFile;
  convertButton.textContent = busy ? "Converting..." : "Convert document";
  fileInput.disabled = busy;
  removeFile.disabled = busy;
}

fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
removeFile.addEventListener("click", resetFile);

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("drag-active");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("drag-active");
  });
});

dropZone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));

convertButton.addEventListener("click", async () => {
  if (!selectedFile) return;
  clearError();
  setBusy(true);
  const format = outputFormat();
  const query = new URLSearchParams({
    filename: selectedFile.name,
    format,
    merge_multipage: mergePages.checked ? "1" : "0",
  });
  try {
    const response = await fetch(`/api/convert?${query}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Pdf-Mcp-Session": sessionToken,
      },
      body: selectedFile,
    });
    const payload = await response.json();
    if (!response.ok) throw payload;
    conversionResult = payload;
    renderResult(payload);
  } catch (error) {
    showError(
      error.error || "The document could not be converted.",
      error.detail || "Check that the file opens normally and try again.",
      error.hint || "",
    );
  } finally {
    setBusy(false);
  }
});

function allWarnings(payload) {
  const warnings = [...(payload.warnings || [])];
  payload.tables.forEach((table) => {
    table.warnings.forEach((warning) => warnings.push(`${table.name}: ${warning}`));
  });
  return [...new Set(warnings)];
}

function renderResult(payload) {
  const needsReview = payload.tables_needing_review > 0;
  document.getElementById("result-eyebrow").textContent = needsReview ? "Check before using" : "Conversion complete";
  document.getElementById("result-title").textContent = needsReview
    ? `${payload.n_tables} ${payload.n_tables === 1 ? "table was" : "tables were"} extracted; ${payload.tables_needing_review} need review.`
    : `${payload.n_tables} ${payload.n_tables === 1 ? "table" : "tables"} extracted.`;
  document.getElementById("result-message").textContent = needsReview
    ? "Download the output and check the highlighted warnings before using the rows."
    : "No basic table-structure problems were detected. Check important values before using the rows.";
  document.getElementById("summary-tables").textContent = payload.n_tables;
  document.getElementById("summary-review").textContent = payload.tables_needing_review;
  document.getElementById("summary-format").textContent = formatNames[payload.output_type];
  downloadButton.textContent = `Download ${formatNames[payload.output_type]}`;

  const warnings = allWarnings(payload);
  const warningPanel = document.getElementById("warning-panel");
  const warningList = document.getElementById("warning-list");
  warningList.replaceChildren();
  warnings.forEach((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    warningList.appendChild(item);
  });
  warningPanel.hidden = warnings.length === 0;

  renderTabs(payload.tables);
  showTable(payload.tables[0], 0);
  converter.hidden = true;
  results.hidden = false;
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderTabs(tables) {
  const tabs = document.getElementById("table-tabs");
  tabs.replaceChildren();
  tables.forEach((table, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.role = "tab";
    button.textContent = table.name;
    button.setAttribute("aria-selected", index === 0 ? "true" : "false");
    button.addEventListener("click", () => {
      tabs.querySelectorAll("button").forEach((tab) => tab.setAttribute("aria-selected", "false"));
      button.setAttribute("aria-selected", "true");
      showTable(table, index);
    });
    tabs.appendChild(button);
  });
}

function showTable(table) {
  document.getElementById("preview-location").textContent = `${table.location} | ${table.n_rows} rows`;
  const preview = document.getElementById("preview-table");
  preview.replaceChildren();
  const columnCount = table.rows.length ? table.rows[0].length : 0;
  preview.classList.toggle("compact-preview", columnCount > 0 && columnCount <= 3);
  if (!table.rows.length) {
    const body = document.createElement("tbody");
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.textContent = "This table is empty.";
    row.appendChild(cell);
    body.appendChild(row);
    preview.appendChild(body);
    return;
  }

  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  table.rows[0].forEach((value) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = value || "(blank)";
    headerRow.appendChild(cell);
  });
  head.appendChild(headerRow);
  preview.appendChild(head);

  const body = document.createElement("tbody");
  table.rows.slice(1).forEach((values) => {
    const row = document.createElement("tr");
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      cell.title = value;
      row.appendChild(cell);
    });
    body.appendChild(row);
  });
  preview.appendChild(body);

  const omitted = conversionResult.preview_tables_omitted;
  const notes = [];
  if (table.preview_truncated) notes.push("This preview is shortened; the download contains all rows and columns.");
  if (omitted) notes.push(`${omitted} additional ${omitted === 1 ? "table is" : "tables are"} included in the download.`);
  document.getElementById("preview-note").textContent = notes.join(" ") || "The download contains this complete table and its review information.";
}

downloadButton.addEventListener("click", async () => {
  if (!conversionResult) return;
  downloadButton.disabled = true;
  const originalText = downloadButton.textContent;
  downloadButton.textContent = "Preparing download...";
  try {
    const response = await fetch(`/api/download/${conversionResult.download_id}`, {
      headers: { "X-Pdf-Mcp-Session": sessionToken },
    });
    if (!response.ok) {
      const payload = await response.json();
      throw payload;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = conversionResult.output_name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  } catch (error) {
    alert(error.error || "The download could not be prepared. Convert the document again.");
  } finally {
    downloadButton.disabled = false;
    downloadButton.textContent = originalText;
  }
});

convertAnother.addEventListener("click", () => {
  conversionResult = null;
  results.hidden = true;
  converter.hidden = false;
  resetFile();
  converter.scrollIntoView({ behavior: "smooth", block: "start" });
});

stopApp.addEventListener("click", async () => {
  if (!window.confirm("Stop the pdf-mcp app on this computer?")) return;
  try {
    await fetch("/api/shutdown", {
      method: "POST",
      headers: { "X-Pdf-Mcp-Session": sessionToken },
    });
  } finally {
    document.querySelector("main").innerHTML = `
      <section class="intro">
        <p class="eyebrow">App stopped</p>
        <h1>pdf-mcp is no longer running.</h1>
        <p>You can close this browser tab. Open the app again whenever you need another conversion.</p>
      </section>`;
    stopApp.disabled = true;
  }
});
