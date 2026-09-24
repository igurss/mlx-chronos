const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "docs", "index.html"), "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const script = scripts.at(-1)[1].replace(/\n\s*loadResults\(\);\s*$/, "");

function fakeElement() {
  return {
    value: "",
    hidden: false,
    dataset: {},
    style: { setProperty() {} },
    classList: { add() {}, remove() {} },
    addEventListener() {},
    setAttribute() {},
    appendChild() {},
    replaceChildren() {},
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 0, bottom: 0 }; },
  };
}

const elements = new Map();
const context = vm.createContext({
  console,
  URLSearchParams,
  Option: function Option(text, value) { this.text = text; this.value = value; },
  localStorage: { getItem() { return null; }, setItem() {} },
  document: {
    documentElement: { dataset: { theme: "light" } },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, fakeElement());
      return elements.get(id);
    },
    querySelector() { return fakeElement(); },
  },
  window: {
    innerHeight: 900,
    location: { search: "", pathname: "/", hash: "" },
    history: { replaceState() {} },
    addEventListener() {},
  },
});
vm.runInContext(script, context);

test("untrusted condition text is escaped before HTML rendering", () => {
  const payload = '<img src=x onerror="globalThis.pwned=true">';
  const rendered = context.safeConditionValue(payload);
  assert.equal(rendered.includes("<img"), false);
  assert.match(rendered, /&lt;img/);
});

test("model variants do not collapse quantization or model reference URL", () => {
  const base = {
    model: "Example-4B",
    quantization: "4bit",
    model_format: "safetensors",
    model_reference_url: "https://example.test/a",
  };
  assert.notEqual(
    context.modelIdentityKey(base),
    context.modelIdentityKey({ ...base, quantization: "8bit" }),
  );
  assert.notEqual(
    context.modelIdentityKey(base),
    context.modelIdentityKey({ ...base, model_reference_url: "https://example.test/b" }),
  );
});

test("engine comparison always ranks by request throughput", () => {
  const rows = [
    { engine: "omlx", timestamp: "2026-01-01T00:00:00Z", tps: 10, decode_tps: 100 },
    { engine: "mlx-lm", timestamp: "2026-01-01T00:00:00Z", tps: 20, decode_tps: 1 },
  ];
  assert.equal(context.representativeRowsByEngine(rows)[0].engine, "mlx-lm");
});

test("the emphasised comparison column is the one the table is ranked by", () => {
  const row = {
    _id: "row-0",
    engine: "omlx",
    timestamp: "2026-01-01T00:00:00Z",
    tps: 20.5,
    decode_tps: 99.5,
    ttft_cold: 0.1,
    ttft_cached: 0.05,
    system_ram_peak_gb: 7,
    system_ram_peak_percent: 90,
    engine_version: "1.0.0",
    thermal_state: "nominal",
    completion_tokens_raw: [100],
    decode_timing_source: "client_stream",
  };
  const rendered = context.compareRowHtml(row, [row], true);

  // Request throughput carries the emphasis; decode throughput must not.
  assert.match(rendered, /<span class="metric-strong">20\.50<\/span>/);
  assert.equal(rendered.includes('<span class="metric-strong">99.50</span>'), false);

  // ... and it is the first metric column, immediately after the engine name.
  assert.ok(rendered.indexOf("20.50") < rendered.indexOf("99.50"));
});

test("comparison header column order matches the rendered cells", () => {
  const headers = [...context.compareHeadHtml(true).matchAll(/<th>([^<]*)<\/th>/g)]
    .map(match => match[1].trim());
  assert.deepEqual(headers.slice(0, 3), ["Engine", "Request tok/s", "Decode tok/s"]);

  const withoutDecode = [...context.compareHeadHtml(false).matchAll(/<th>([^<]*)<\/th>/g)]
    .map(match => match[1].trim());
  assert.equal(withoutDecode.includes("Decode tok/s"), false);
  assert.deepEqual(withoutDecode.slice(0, 2), ["Engine", "Request tok/s"]);

  // Header count must match the colspan used for the details row.
  assert.equal(context.compareHeadHtml(true).match(/<th>/g).length, 8);
  assert.equal(context.compareHeadHtml(false).match(/<th>/g).length, 7);
});

test("submitter handles are escaped and rendered as profile links", () => {
  assert.equal(context.submittedByCell({ submitted_by: "" }), "-");
  const rendered = context.submittedByCell({ submitted_by: "igurss" });
  assert.match(rendered, /href="https:\/\/github\.com\/igurss"/);
  assert.match(rendered, /@igurss/);

  const hostile = context.submittedByCell({ submitted_by: '"><img src=x onerror=1>' });
  assert.equal(hostile.includes("<img"), false);
  assert.match(hostile, /&quot;&gt;&lt;img/);
});

test("system RAM peak remains primary and the whole-Mac rise is diagnostic", () => {
  const rendered = context.systemRamCell({
    system_ram_peak_gb: 7,
    system_ram_peak_percent: 87.5,
    system_ram_delta_gb: 2,
  });
  assert.match(rendered, /<span class="metric-strong">7\.00 GB \/ 88%<\/span>/);
  assert.match(rendered, /whole-Mac rise \+2\.00 GB/);
  assert.equal(context.systemRamCell({
    system_ram_peak_gb: 7,
    system_ram_peak_percent: 87.5,
  }).includes("whole-Mac rise"), false);
});

test("csvEscapeCell only quotes cells that need it", () => {
  assert.equal(context.csvEscapeCell("plain"), "plain");
  assert.equal(context.csvEscapeCell(42), "42");
  assert.equal(context.csvEscapeCell("has,comma"), '"has,comma"');
  assert.equal(context.csvEscapeCell('has"quote'), '"has""quote"');
  assert.equal(context.csvEscapeCell("has\nnewline"), '"has\nnewline"');
  assert.equal(context.csvEscapeCell("=1+1"), "'=1+1");
  assert.equal(context.csvEscapeCell("  @SUM(A1)"), "'  @SUM(A1)");
  assert.equal(context.csvEscapeCell(-2), "-2");
});

test("columnPlainValue reads the raw field named by sortKey, not the rendered HTML", () => {
  const column = { sortKey: "tps", value: row => `<strong>${row.tps}</strong>` };
  assert.equal(context.columnPlainValue(column, { tps: 12.34 }), 12.34);
  assert.equal(context.columnPlainValue(column, {}), "");
  assert.equal(context.columnPlainValue(column, { tps: null }), "");
  assert.equal(context.columnPlainValue({ sortKey: "percent", exportKey: "gb" }, {
    percent: 90, gb: 7.2,
  }), 7.2);
});

test("buildCsvExport produces a header row plus one row per record, using plain values", () => {
  const columns = [
    { label: "Engine", sortKey: "engine" },
    { label: "tok/s", sortKey: "tps" },
  ];
  const rows = [
    { engine: "omlx", tps: 27.4 },
    { engine: "ollama, mlx", tps: 24.6 },
  ];

  const csv = context.buildCsvExport(columns, rows);

  const lines = csv.trimEnd().split("\n");
  assert.equal(lines[0], "Engine,tok/s");
  assert.equal(lines[1], "omlx,27.4");
  // A comma inside a field value must be quoted, not misread as a new column.
  assert.equal(lines[2], '"ollama, mlx",24.6');
  assert.equal(csv.endsWith("\n"), true);
});

test("CSV RAM column exports GB rather than its percent sort key", () => {
  const ramColumn = vm.runInContext(
    'BASE_RAW_COLUMNS.find(column => column.key === "system_ram_peak")', context,
  );
  const csv = context.buildCsvExport([ramColumn], [{
    system_ram_peak_percent: 90,
    system_ram_peak_gb: 7.2,
  }]);
  assert.equal(csv, "System RAM peak (GB)\n7.2\n");
});

test("buildJsonExport returns valid, pretty-printed JSON of the given rows", () => {
  const rows = [{ engine: "omlx", tps: 27.4 }];

  const json = context.buildJsonExport(rows);

  assert.deepEqual(JSON.parse(json), rows);
  assert.match(json, /\n\s+"engine"/); // pretty-printed, not minified
});

test("buildCompareChartMarkup draws one bar per engine with request tok/s widths", () => {
  const representatives = [
    { engine: "rapid-mlx", tps: 27.46 },
    { engine: "omlx", tps: 27.18 },
    { engine: "mlx-lm", tps: 24.59 },
  ];

  const { viewBox, inner } = context.buildCompareChartMarkup(representatives);

  assert.match(viewBox, /^0 0 \d+ \d+$/);
  assert.equal((inner.match(/<rect/g) || []).length, 3);
  assert.equal((inner.match(/<text class="compare-chart-label"/g) || []).length, 3);
  // The engine with the highest tok/s (first in `representatives`, since the
  // table is already ranked that way) must get the widest bar.
  const widths = [...inner.matchAll(/width="([\d.]+)"/g)].map(m => Number(m[1]));
  assert.equal(widths[0], Math.max(...widths));
});

test("buildCompareChartMarkup escapes an engine label safely", () => {
  const { inner } = context.buildCompareChartMarkup([
    { engine: '<img src=x onerror=alert(1)>', tps: 10 },
    { engine: "omlx", tps: 5 },
  ]);
  assert.equal(inner.includes("<img"), false);
});

test("renderCompareChart hides the chart with fewer than 2 engines", () => {
  context.renderCompareChart([{ engine: "omlx", tps: 10 }]);
  assert.equal(context.document.getElementById("compare-chart-wrap").hidden, true);

  context.renderCompareChart([
    { engine: "omlx", tps: 10 },
    { engine: "ollama", tps: 8 },
  ]);
  assert.equal(context.document.getElementById("compare-chart-wrap").hidden, false);
});
