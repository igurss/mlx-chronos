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
