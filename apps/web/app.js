/* SCADS web client.
 *
 * Plain ES modules, no build step, no framework. That is a constraint of this
 * environment (no Node toolchain) turned to advantage: Amplify Hosting serves
 * these files directly, there is no bundle to break, and the whole client is
 * readable in one sitting.
 *
 * Responsibilities, in order of importance:
 *  1. Never overstate a result. The backend decides; this file renders reason
 *     codes and never invents or softens a finding.
 *  2. Show the three evidence dimensions separately, always all three, so a
 *     dimension that was not checked reads as "not checked" and not as "fine".
 *  3. Keep the upload small and direct-to-S3.
 */

const config = window.SCADS_CONFIG || { apiBaseUrl: "" };
const API = (config.apiBaseUrl || "").replace(/\/$/, "");

/* Longest edge of an uploaded image, in pixels.
 *
 * Downscaling in the browser serves three ends at once: it keeps the upload
 * inside Textract's 5 MB synchronous limit, it cuts upload time on a phone
 * connection, and it bounds what the Lambda has to decode. 1600px still leaves
 * far more detail than the comparison needs — the pipeline rectifies to a
 * 900px canonical frame. */
const MAX_EDGE = 1600;
const JPEG_QUALITY = 0.9;

/* ------------------------------------------------------------------ state */

const state = {
  view: "scan",
  locations: [],
  selectedLocation: "BENGALURU_DEMO",
  lastFile: null,
  aborted: false
};

const el = (id) => document.getElementById(id);

const views = {
  scan: el("view-scan"),
  processing: el("view-processing"),
  result: el("view-result"),
  error: el("view-error")
};

function showView(name) {
  state.view = name;
  Object.entries(views).forEach(([key, node]) => {
    node.hidden = key !== name;
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ------------------------------------------------------------------- http */

async function api(path, options = {}) {
  const response = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const text = await response.text();
  let body = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch (_) {
    throw new Error("The server returned something unreadable.");
  }
  if (!response.ok) {
    const message = (body.error && body.error.message) || "The request was rejected.";
    const error = new Error(message);
    error.code = body.error && body.error.code;
    throw error;
  }
  return body;
}

/* ----------------------------------------------------------------- images */

/* Downscale and re-encode, which also strips EXIF.
 *
 * Drawing through a canvas discards every metadata block, so orientation is
 * applied and location tags, device identifiers and timestamps never leave the
 * phone. The privacy promise is kept here, before the network, rather than
 * relying on the server to discard what it was sent. */
async function prepareImage(file) {
  const bitmap = await loadBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const width = Math.max(1, Math.round(bitmap.width * scale));
  const height = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  context.drawImage(bitmap, 0, 0, width, height);
  if (bitmap.close) bitmap.close();

  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY)
  );
  if (!blob) throw new Error("That image could not be prepared for upload.");
  return { blob, width, height, dataUrl: canvas.toDataURL("image/jpeg", 0.6) };
}

async function loadBitmap(file) {
  if (window.createImageBitmap) {
    try {
      /* imageOrientation:"from-image" applies the EXIF rotation, so a photo
         taken in portrait is analysed upright rather than sideways. */
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch (_) {
      /* Safari has historically rejected the options bag; fall through. */
    }
  }
  return await new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("That file could not be read as an image."));
    image.src = URL.createObjectURL(file);
  });
}

/* Decode a QR code in the browser when the platform can.
 *
 * Chrome on Android exposes BarcodeDetector, which covers the primary target
 * for this app. Where it is missing, the payload is simply omitted and the
 * backend falls back to reading the printed serial with Textract — the
 * documented fallback ladder, not a degraded mode. */
async function decodeQr(blob) {
  if (!("BarcodeDetector" in window)) return null;
  try {
    const formats = await window.BarcodeDetector.getSupportedFormats();
    if (!formats.includes("qr_code")) return null;
    const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    const bitmap = await createImageBitmap(blob);
    const codes = await detector.detect(bitmap);
    if (bitmap.close) bitmap.close();
    return codes.length ? codes[0].rawValue : null;
  } catch (_) {
    return null;
  }
}

/* ------------------------------------------------------------- scan flow */

const STAGES = ["upload", "identity", "physical", "history"];

function setStage(name, stateName) {
  const node = document.querySelector('.stage[data-stage="' + name + '"]');
  if (node) node.dataset.state = stateName;
}

function resetStages() {
  STAGES.forEach((name) => setStage(name, ""));
}

async function runScan(file, meta = {}) {
  state.aborted = false;
  state.lastFile = { file, meta };
  resetStages();
  showView("processing");

  try {
    const prepared = await prepareImage(file);

    const previewWrap = el("preview-wrap");
    el("preview").src = prepared.dataUrl;
    previewWrap.hidden = false;

    setStage("upload", "active");

    const created = await api("/v1/uploads", {
      method: "POST",
      body: JSON.stringify({
        content_type: "image/jpeg",
        content_length: prepared.blob.size
      })
    });
    if (state.aborted) return;

    const upload = created.upload;
    const putResponse = await fetch(upload.url, {
      method: upload.method || "PUT",
      headers: upload.headers || { "Content-Type": "image/jpeg" },
      body: prepared.blob
    });
    if (!putResponse.ok) {
      throw new Error("The photo could not be uploaded. Check your connection and try again.");
    }
    if (state.aborted) return;

    setStage("upload", "done");
    setStage("identity", "active");

    const qrPayload = meta.qrPayload || (await decodeQr(prepared.blob));

    /* The backend runs identity, packaging and history in one call. The stage
       list advances optimistically so the user sees progress; it is not a fake
       progress bar — each stage is marked done only once the response that
       covers it has arrived. */
    const location = state.locations.find((l) => l.key === state.selectedLocation);
    const requestBody = {
      qr_payload: qrPayload || undefined,
      location: location
        ? { mode: "DEMO", label: location.key }
        : { mode: "NONE" }
    };

    setStage("physical", "active");
    const result = await api("/v1/scans/" + created.scan_id + "/analyze", {
      method: "POST",
      body: JSON.stringify(requestBody)
    });
    if (state.aborted) return;

    setStage("identity", "done");
    setStage("physical", "done");
    setStage("history", "done");

    renderResult(result);
    showView("result");
  } catch (error) {
    if (state.aborted) return;
    el("error-message").textContent = error.message || "Something went wrong.";
    showView("error");
  }
}

/* -------------------------------------------------------------- rendering */

const VERDICTS = {
  LOW_OBSERVED_RISK: { state: "ok", title: "No contradictions found" },
  REVIEW_REQUIRED: { state: "warn", title: "Needs a closer look" },
  SUSPICIOUS: { state: "fail", title: "Contradictions found" },
  UNABLE_TO_VERIFY: { state: "unknown", title: "Not enough evidence to judge" }
};

const STATE_GLYPH = { ok: "✓", warn: "!", fail: "✕", unknown: "?" };
const STATE_WORD = { ok: "Consistent", warn: "Check", fail: "Contradiction", unknown: "Not checked" };
const SEVERITY_GLYPH = { SEVERE: "✕", WARNING: "!", NOTICE: "i", INFO: "✓" };

function renderResult(result) {
  const verdict = VERDICTS[result.decision] || VERDICTS.UNABLE_TO_VERIFY;
  const node = el("verdict");
  node.dataset.state = verdict.state;
  el("result-heading").textContent = verdict.title;
  el("verdict-class").textContent = result.decision;
  el("verdict-detail").textContent = summaryLine(result);

  renderProductBanner(result);
  renderDimensions(result);
  renderFindings(result);
  renderTimeline(result);

  el("next-action").textContent = result.next_action || "";
  el("limitation").textContent = result.limitation || "";

  state.lastResult = result;
}

/* One sentence naming what actually drove the verdict.
 *
 * Built from the highest-severity finding rather than from the decision class,
 * so the headline is about the pack and not about our vocabulary. */
function summaryLine(result) {
  const reasons = (result.explanation && result.explanation.primary_reasons) || [];
  if (reasons.length) return reasons[0].detail;
  const all = (result.explanation && result.explanation.reasons) || [];
  const informative = all.find((r) => r.severity !== "INFO");
  if (informative) return informative.detail;
  return (result.explanation && result.explanation.assurance_note) || "";
}

function renderProductBanner(result) {
  const banner = el("product-banner");
  const note = result.explanation && result.explanation.product_status_note;
  if (!note) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  banner.textContent = note;
}

function renderDimensions(result) {
  const container = el("dimensions");
  container.textContent = "";
  const dimensions = (result.explanation && result.explanation.dimensions) || [];

  dimensions.forEach((dimension) => {
    const card = document.createElement("article");
    card.className = "dim";
    card.dataset.state = dimension.state.toLowerCase();

    const head = document.createElement("div");
    head.className = "dim__head";

    const label = document.createElement("h4");
    label.className = "dim__label";
    label.textContent = dimension.label;
    head.appendChild(label);

    /* Glyph + word + colour. Colour alone would be unreadable for a
       significant fraction of users, and this is a health context. */
    const badge = document.createElement("span");
    badge.className = "dim__state";
    const key = dimension.state.toLowerCase();
    const glyph = document.createElement("span");
    glyph.className = "dim__glyph";
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = STATE_GLYPH[key] || "?";
    badge.appendChild(glyph);
    badge.appendChild(document.createTextNode(STATE_WORD[key] || dimension.state));
    head.appendChild(badge);

    card.appendChild(head);

    const headline = document.createElement("p");
    headline.className = "dim__headline";
    headline.textContent = dimension.headline;
    card.appendChild(headline);

    if (dimension.available && typeof dimension.score === "number") {
      const meter = document.createElement("div");
      meter.className = "meter";
      const fill = document.createElement("div");
      fill.className = "meter__fill";
      fill.style.width = Math.round(dimension.score * 100) + "%";
      meter.appendChild(fill);
      card.appendChild(meter);

      const value = document.createElement("p");
      value.className = "meter__label";
      value.textContent = Math.round(dimension.score * 100) + " / 100";
      card.appendChild(value);
    } else {
      const why = document.createElement("p");
      why.className = "dim__why";
      why.textContent = "No score: this check did not produce a usable measurement.";
      card.appendChild(why);
    }

    container.appendChild(card);
  });
}

function renderFindings(result) {
  const card = el("findings-card");
  const list = el("findings");
  list.textContent = "";

  const reasons = (result.explanation && result.explanation.reasons) || [];
  /* Confirmations are already visible on the dimension cards; repeating them
     here would bury the findings that need action. */
  const notable = reasons.filter((r) => r.severity !== "INFO");
  if (!notable.length) {
    card.hidden = true;
    return;
  }
  card.hidden = false;

  const findingsByCode = {};
  ((result.history && result.history.findings) || []).forEach((f) => {
    findingsByCode[f.code] = f;
  });

  notable.forEach((reason) => {
    const item = document.createElement("li");
    item.className = "finding";
    item.dataset.sev = reason.severity;

    const glyph = document.createElement("span");
    glyph.className = "finding__glyph";
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = SEVERITY_GLYPH[reason.severity] || "i";
    item.appendChild(glyph);

    const body = document.createElement("div");
    const title = document.createElement("p");
    title.className = "finding__title";
    title.textContent = reason.title;
    body.appendChild(title);

    const detail = document.createElement("p");
    detail.className = "finding__detail";
    detail.textContent = reason.detail;
    body.appendChild(detail);

    /* Where the backend supplied the measurements behind a finding, show them.
       "Seen 1,740 km away 58 minutes ago" is checkable; "anomaly detected" is
       not. */
    const history = findingsByCode[reason.code];
    if (history && history.evidence) {
      const numbers = formatEvidence(history.evidence);
      if (numbers) {
        const line = document.createElement("p");
        line.className = "finding__numbers";
        line.textContent = numbers;
        body.appendChild(line);
      }
    }

    item.appendChild(body);
    list.appendChild(item);
  });
}

function formatEvidence(evidence) {
  const parts = [];
  if (typeof evidence.distance_km === "number") {
    parts.push(Math.round(evidence.distance_km).toLocaleString() + " km apart");
  }
  if (typeof evidence.elapsed_minutes === "number") {
    parts.push(Math.round(evidence.elapsed_minutes) + " min apart");
  }
  if (typeof evidence.implied_speed_kmh === "number") {
    parts.push("implies " + Math.round(evidence.implied_speed_kmh).toLocaleString() + " km/h");
  }
  if (typeof evidence.prior_independent_scans === "number") {
    parts.push(evidence.prior_independent_scans + " prior scan(s)");
  }
  if (evidence.registry_status) {
    parts.push("registry says " + String(evidence.registry_status).toLowerCase());
  }
  return parts.join(" · ");
}

function renderTimeline(result) {
  const card = el("timeline-card");
  const list = el("timeline");
  list.textContent = "";

  const priors = (result.history && result.history.prior_scans) || [];
  if (!priors.length) {
    card.hidden = true;
    return;
  }
  card.hidden = false;

  const entries = priors
    .slice()
    .map((p) => ({
      where: p.location_label || "Location not recorded",
      when: p.event_time,
      note: p.decision ? "Recorded as " + p.decision.replace(/_/g, " ").toLowerCase() : "",
      now: false
    }));

  entries.push({
    where: state.selectedLocation || "This scan",
    when: "just now",
    note: "This scan",
    now: true
  });

  entries.forEach((entry) => {
    const item = document.createElement("li");
    item.className = "tl" + (entry.now ? " tl--now" : "");

    const dot = document.createElement("span");
    dot.className = "tl__dot";
    dot.setAttribute("aria-hidden", "true");
    item.appendChild(dot);

    const body = document.createElement("div");
    const where = document.createElement("p");
    where.className = "tl__where";
    where.textContent = prettyLocation(entry.where);
    body.appendChild(where);

    const when = document.createElement("p");
    when.className = "tl__when";
    when.textContent = entry.when === "just now" ? "Just now" : prettyTime(entry.when);
    body.appendChild(when);

    if (entry.note) {
      const note = document.createElement("p");
      note.className = "tl__note";
      note.textContent = entry.note;
      body.appendChild(note);
    }

    item.appendChild(body);
    list.appendChild(item);
  });
}

function prettyLocation(key) {
  const known = state.locations.find((l) => l.key === key);
  if (known) return known.display_name;
  return String(key).replace(/_DEMO$/, "").replace(/_/g, " ");
}

function prettyTime(iso) {
  const parsed = new Date(iso);
  if (isNaN(parsed.getTime())) return iso;
  const minutes = Math.round((Date.now() - parsed.getTime()) / 60000);
  if (minutes < 1) return "Moments ago";
  if (minutes < 60) return minutes + " minutes ago";
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours + (hours === 1 ? " hour ago" : " hours ago");
  return parsed.toLocaleString();
}

/* -------------------------------------------------------- evidence drawer */

function renderEvidence(result) {
  const body = el("evidence-body");
  body.textContent = "";
  if (!result) return;

  const evidence = result.evidence || {};

  body.appendChild(
    group("Decision", table(
      [["Class", result.decision],
       ["Score shown", result.presentation_score === null ? "not applicable" : result.presentation_score],
       ["Score before caps", evidence.base_score],
       ["Weights applied", JSON.stringify(evidence.weights_used || {})]]
    ))
  );

  if ((evidence.applied_caps || []).length) {
    const wrapper = document.createElement("div");
    wrapper.className = "ev-group";
    const title = document.createElement("p");
    title.className = "ev-group__title";
    title.textContent = "Why the score was capped";
    wrapper.appendChild(title);
    evidence.applied_caps.forEach((cap) => {
      const line = document.createElement("p");
      line.className = "ev-note";
      const code = document.createElement("span");
      code.className = "ev-code";
      code.textContent = cap.code;
      line.appendChild(code);
      line.appendChild(document.createTextNode(" " + cap.rationale));
      wrapper.appendChild(line);
    });
    body.appendChild(wrapper);
  }

  if ((evidence.physical_features || []).length) {
    const rows = evidence.physical_features.map((f) => [
      f.name.replace(/_/g, " "),
      f.value.toFixed(3) + " / " + f.threshold.toFixed(2),
      f.ok ? "pass" : "fail"
    ]);
    body.appendChild(group("Packaging features", table(rows, ["Feature", "Value / threshold", ""], 2)));
    const notes = evidence.physical_features.filter((f) => f.description);
    notes.forEach((f) => {
      const line = document.createElement("p");
      line.className = "ev-note";
      line.textContent = f.name.replace(/_/g, " ") + ": " + f.description;
      body.appendChild(line);
    });
  }

  const quality = evidence.quality_metrics || {};
  if (Object.keys(quality).length) {
    const keys = ["sharpness", "exposure", "resolution", "gradient_p95", "mean_luma", "clipped_fraction", "megapixels"];
    body.appendChild(
      group("Capture quality", table(keys.filter((k) => k in quality).map((k) => [k.replace(/_/g, " "), quality[k]])))
    );
  }

  body.appendChild(
    group("Provenance", table([
      ["Pipeline", evidence.pipeline_version],
      ["Fusion policy", evidence.fusion_policy_version],
      ["Reference artwork", evidence.reference_version || "not applicable"],
      ["Text extraction", evidence.ocr_provider],
      ["Alignment confidence", evidence.registration_confidence],
      ["Latency", (evidence.latency_ms || 0) + " ms"]
    ]))
  );

  if ((evidence.notes || []).length) {
    const wrapper = document.createElement("div");
    wrapper.className = "ev-group";
    const title = document.createElement("p");
    title.className = "ev-group__title";
    title.textContent = "Engine notes";
    wrapper.appendChild(title);
    evidence.notes.forEach((note) => {
      const line = document.createElement("p");
      line.className = "ev-note";
      line.textContent = note;
      wrapper.appendChild(line);
    });
    body.appendChild(wrapper);
  }

  if (result.generated_summary) {
    const wrapper = document.createElement("div");
    wrapper.className = "ev-group";
    const title = document.createElement("p");
    title.className = "ev-group__title";
    title.textContent = "Generated wording";
    wrapper.appendChild(title);
    const text = document.createElement("p");
    text.className = "ev-note";
    text.textContent = result.generated_summary.text;
    wrapper.appendChild(text);
    const caveat = document.createElement("p");
    caveat.className = "ev-note";
    caveat.textContent = result.generated_summary.note;
    wrapper.appendChild(caveat);
    body.appendChild(wrapper);
  }
}

function group(titleText, content) {
  const wrapper = document.createElement("div");
  wrapper.className = "ev-group";
  const title = document.createElement("p");
  title.className = "ev-group__title";
  title.textContent = titleText;
  wrapper.appendChild(title);
  wrapper.appendChild(content);
  return wrapper;
}

function table(rows, headers, statusColumn) {
  const node = document.createElement("table");
  node.className = "ev-table";
  if (headers) {
    const head = document.createElement("thead");
    const row = document.createElement("tr");
    headers.forEach((h) => {
      const cell = document.createElement("th");
      cell.textContent = h;
      row.appendChild(cell);
    });
    head.appendChild(row);
    node.appendChild(head);
  }
  const bodyNode = document.createElement("tbody");
  rows.forEach((cells) => {
    const row = document.createElement("tr");
    cells.forEach((value, index) => {
      const cell = document.createElement("td");
      if (index === statusColumn) {
        cell.className = value === "pass" ? "ev-pass" : "ev-fail";
      }
      cell.textContent = value === undefined || value === null ? "—" : String(value);
      row.appendChild(cell);
    });
    bodyNode.appendChild(row);
  });
  node.appendChild(bodyNode);
  return node;
}

/* ------------------------------------------------------------ demo packs */

/* Curated demo entries. Each names what it is and what it demonstrates, so a
   viewer can see the claim being tested rather than trusting a label. */
const DEMO_PACKS = [
  { file: "genuine_clean_a.jpg", name: "Genuine pack", why: "Identity, packaging and history all agree", kind: "genuine", location: "BENGALURU_DEMO" },
  { file: "tamper_logo_shift.jpg", name: "Altered artwork", why: "Valid serial, but a region of the printing does not match", kind: "tamper", location: "BENGALURU_DEMO" },
  { file: "genuine_clone_serial.jpg", name: "Cloned serial", why: "Flawless pack, valid serial, already seen in another city", kind: "tamper", location: "BENGALURU_DEMO" },
  { file: "identity_unknown_serial.jpg", name: "Unissued serial", why: "Convincing pack carrying a serial never issued", kind: "identity", location: "BENGALURU_DEMO" },
  { file: "genuine_expired_batch.jpg", name: "Expired but genuine", why: "Authentic pack, past its expiry date", kind: "identity", location: "BENGALURU_DEMO" },
  { file: "quality_blurred.jpg", name: "Photo too blurry", why: "Returns 'not enough evidence', never an accusation", kind: "quality", location: "BENGALURU_DEMO" },
  { file: "genuine_clean_b.jpg", name: "A second product", why: "Different pack, its own enrolled reference", kind: "genuine", location: "BENGALURU_DEMO" }
];

function renderDemoPacks() {
  const container = el("demo-list");
  container.textContent = "";
  DEMO_PACKS.forEach((pack) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "demo";

    const text = document.createElement("span");
    const name = document.createElement("span");
    name.className = "demo__name";
    name.textContent = pack.name;
    text.appendChild(name);
    const why = document.createElement("span");
    why.className = "demo__why";
    why.textContent = pack.why;
    text.appendChild(document.createElement("br"));
    text.appendChild(why);
    button.appendChild(text);

    const badge = document.createElement("span");
    badge.className = "demo__badge";
    badge.dataset.kind = pack.kind;
    badge.textContent = { genuine: "genuine", tamper: "altered", identity: "identity", quality: "capture" }[pack.kind];
    button.appendChild(badge);

    button.addEventListener("click", () => loadDemoPack(pack));
    container.appendChild(button);
  });
}

async function loadDemoPack(pack) {
  try {
    const response = await fetch("/fixtures/" + pack.file);
    if (!response.ok) {
      throw new Error(
        "Demo images are not available. Run: python scripts/seed_demo.py"
      );
    }
    const blob = await response.blob();
    const file = new File([blob], pack.file, { type: "image/jpeg" });
    if (pack.location) {
      state.selectedLocation = pack.location;
      const select = el("location-select");
      if (select) select.value = pack.location;
    }
    await runScan(file, { demo: pack.file });
  } catch (error) {
    el("error-message").textContent = error.message;
    showView("error");
  }
}

/* ----------------------------------------------------------------- sheets */

let lastFocused = null;

function openSheet(id) {
  lastFocused = document.activeElement;
  const sheet = el(id);
  sheet.hidden = false;
  const closeButton = sheet.querySelector("[data-close]");
  if (closeButton && closeButton.focus) closeButton.focus();
  document.body.style.overflow = "hidden";
}

function closeSheet(id) {
  el(id).hidden = true;
  document.body.style.overflow = "";
  if (lastFocused && lastFocused.focus) lastFocused.focus();
}

function wireSheet(id) {
  const sheet = el(id);
  sheet.querySelectorAll("[data-close]").forEach((node) => {
    node.addEventListener("click", () => closeSheet(id));
  });
}

/* ------------------------------------------------------------------- init */

async function loadLocations() {
  try {
    const body = await api("/v1/locations");
    state.locations = body.locations || [];
  } catch (_) {
    state.locations = [];
  }

  const select = el("location-select");
  select.textContent = "";
  state.locations.forEach((location) => {
    const option = document.createElement("option");
    option.value = location.key;
    option.textContent = location.display_name;
    select.appendChild(option);
  });
  if (state.locations.some((l) => l.key === state.selectedLocation)) {
    select.value = state.selectedLocation;
  } else if (state.locations.length) {
    state.selectedLocation = state.locations[0].key;
    select.value = state.selectedLocation;
  }
  select.addEventListener("change", (event) => {
    state.selectedLocation = event.target.value;
  });
}

async function loadBuildInfo() {
  try {
    const health = await api("/v1/health");
    const parts = [
      health.service + " " + health.version,
      health.environment,
      "pipeline " + health.pipeline_version,
      "policy " + health.fusion_policy_version
    ];
    /* Surfaced deliberately. A deployed environment running on offline stubs
       would otherwise look identical to a real one. */
    if (health.backends) {
      parts.push(
        "backends " + [health.backends.store, health.backends.registry, health.backends.ocr].join("/")
      );
    }
    el("build-info").textContent = parts.join(" · ");
  } catch (_) {
    el("build-info").textContent = "API unreachable";
  }
}

function init() {
  el("file-input").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) runScan(file);
    event.target.value = "";
  });

  el("rescan-btn").addEventListener("click", () => {
    resetStages();
    showView("scan");
  });

  el("error-retry").addEventListener("click", () => {
    showView("scan");
  });

  el("cancel-btn").addEventListener("click", () => {
    state.aborted = true;
    showView("scan");
  });

  el("evidence-open").addEventListener("click", () => {
    renderEvidence(state.lastResult);
    openSheet("evidence-dialog");
  });

  el("about-open").addEventListener("click", () => openSheet("about-dialog"));

  wireSheet("evidence-dialog");
  wireSheet("about-dialog");

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      ["evidence-dialog", "about-dialog"].forEach((id) => {
        if (!el(id).hidden) closeSheet(id);
      });
    }
  });

  renderDemoPacks();
  loadLocations();
  loadBuildInfo();
}

init();
