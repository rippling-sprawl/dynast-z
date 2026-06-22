// Orchestrator: loads every adapter in sources/, fetches listings in parallel,
// normalizes them, and writes data.json to the app root.
// Run standalone:  node scrape.mjs
import { readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SOURCES_DIR = join(__dirname, "sources");
export const DATA_FILE = join(__dirname, "data.json");
// The site-served copy that /jane/asheville-rentals reads from.
export const PUBLIC_DATA_FILE = join(__dirname, "..", "data", "asheville-rentals.json");

async function loadSources() {
  const files = (await readdir(SOURCES_DIR)).filter((f) => f.endsWith(".mjs") && !f.startsWith("_"));
  const mods = [];
  for (const f of files) {
    const m = await import(join(SOURCES_DIR, f));
    if (m.meta && typeof m.fetchListings === "function") mods.push(m);
  }
  return mods;
}

function withTimeout(p, ms) {
  return Promise.race([
    p,
    new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout after ${ms}ms`)), ms)),
  ]);
}

// Merge complex-level metadata onto a per-listing row.
function decorate(r, meta) {
  return {
    complex: meta.name,
    floorplan: r.floorplan ?? null,
    unit: r.unit ?? null,
    beds: r.beds ?? null,
    baths: r.baths ?? null,
    sqft: r.sqft ?? null,
    sqftText: r.sqftText ?? (r.sqft != null ? String(r.sqft) : ""),
    price: r.price ?? null,
    priceText: r.priceText ?? "—",
    available: r.available ?? "—",
    granularity: r.granularity ?? "unit",
    petFee: meta.fees.pet,
    parkingFee: meta.fees.parking,
    washerDryerFee: meta.fees.washerDryer,
    outdoor: meta.outdoor,
    washerDryerType: meta.washerDryerType,
    officialUrl: meta.officialUrl,
    note: null,
  };
}

// One row so a complex with no live availability still appears in the table.
function placeholder(meta, error) {
  return {
    ...decorate({}, meta),
    priceText: "—",
    available: error ? "data error" : "See site",
    granularity: "none",
    note: error || "No live availability returned",
  };
}

export async function scrapeAll({ log = () => {}, write = true } = {}) {
  const mods = await loadSources();
  const sources = [];
  const listings = [];

  await Promise.all(
    mods.map(async (m) => {
      const { meta } = m;
      const t0 = Date.now();
      let status, count = 0, error = null;
      try {
        const rows = await withTimeout(Promise.resolve().then(() => m.fetchListings()), 95000);
        count = Array.isArray(rows) ? rows.length : 0;
        if (count > 0) {
          for (const r of rows) listings.push(decorate(r, meta));
          status = "ok";
        } else {
          status = "empty";
          listings.push(placeholder(meta));
        }
      } catch (e) {
        status = "error";
        error = String(e?.message || e);
        listings.push(placeholder(meta, error));
      }
      sources.push({
        id: meta.id, name: meta.name, status, count,
        ms: Date.now() - t0, method: meta.method, error, officialUrl: meta.officialUrl,
      });
      log(`${meta.name}: ${status}${count ? ` (${count})` : ""}${error ? ` — ${error}` : ""}`);
    })
  );

  sources.sort((a, b) => a.name.localeCompare(b.name));
  const data = { generatedAt: new Date().toISOString(), sources, listings };
  if (write) {
    const json = JSON.stringify(data, null, 2);
    await writeFile(DATA_FILE, json);
    // Mirror to the site-served copy so /jane/asheville-rentals reflects the refresh.
    await writeFile(PUBLIC_DATA_FILE, json);
  }
  return data;
}

// CLI entry
if (import.meta.url === `file://${process.argv[1]}`) {
  console.log("Scraping all sources…");
  const data = await scrapeAll({ log: (m) => console.log("  " + m) });
  console.log(`\nDone. ${data.listings.length} listings from ${data.sources.length} complexes.`);
  console.log(`Saved -> ${DATA_FILE}`);
}
