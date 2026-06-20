// Shared fetch + parse helpers for all source adapters.
// Zero dependencies — Node 18+ global fetch only.

export const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

// ---- network ----------------------------------------------------------

// Direct fetch (used by sources whose data feed isn't bot-walled).
export async function directFetch(url, { json = false, headers = {}, timeout = 30000 } = {}) {
  const r = await fetch(url, {
    headers: { "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", ...headers },
    signal: AbortSignal.timeout(timeout),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  const text = await r.text();
  return json ? JSON.parse(text) : text;
}

// Render proxy (r.jina.ai) — runs a real browser server-side, so it gets
// past the Cloudflare/RealPage walls that block a plain fetch. Free public
// service with rate limits; the app degrades gracefully if it's unavailable.
// Retries because the toughest sites intermittently return a challenge stub.
export async function proxyFetch(url, { format = "html", retries = 3, timeout = 60000, want = () => true } = {}) {
  let last;
  for (let i = 0; i < retries; i++) {
    try {
      const r = await fetch("https://r.jina.ai/" + url, {
        headers: { "User-Agent": UA, "x-respond-with": format, "x-timeout": "40" },
        signal: AbortSignal.timeout(timeout),
      });
      const text = await r.text();
      if (r.ok && want(text)) return text;
      last = new Error(`proxy HTTP ${r.status}, len ${text.length} (attempt ${i + 1})`);
    } catch (e) {
      last = e;
    }
  }
  throw last || new Error("proxy failed");
}

// ---- field parsing ----------------------------------------------------

export function num(x) {
  if (x == null) return null;
  const n = Number(String(x).replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) ? n : null;
}

export function parseBeds(s) {
  if (s == null) return null;
  const t = String(s).toLowerCase();
  if (t.includes("studio")) return 0;
  const m = t.match(/[\d.]+/);
  return m ? Number(m[0]) : null;
}

export function parseBaths(s) {
  if (s == null) return null;
  const m = String(s).match(/[\d.]+/);
  return m ? Number(m[0]) : null;
}

// "724 - 793 Sqft" -> { min: 724, text: "724–793" }
export function parseSqft(s) {
  if (s == null) return { min: null, text: "" };
  const nums = (String(s).match(/[\d,]+/g) || []).map((x) => num(x)).filter((x) => x != null);
  if (!nums.length) return { min: null, text: "" };
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  return { min, text: min === max ? String(min) : `${min}–${max}` };
}

// "$1,363 - $1,983" / "From $1,699*" / "Ask for pricing" -> { min, text }
export function parsePrice(s) {
  if (s == null) return { min: null, text: "—" };
  const nums = (String(s).match(/\$[\d,]+/g) || []).map((x) => num(x)).filter((x) => x != null);
  if (!nums.length) return { min: null, text: String(s).trim() || "—" };
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  return {
    min,
    text: min === max ? `$${min.toLocaleString()}` : `$${min.toLocaleString()}–$${max.toLocaleString()}`,
  };
}

// Decode common HTML entities found in embedded JSON / attributes.
export function decodeEntities(s) {
  return String(s)
    .replace(/&quot;/g, '"').replace(/&#34;/g, '"')
    .replace(/&#39;/g, "'").replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ");
}

// "2025-10-26 00:00 -0500" -> "Oct 26, 2025", or "Now" if already available.
export function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d)) return String(s);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (d <= today) return "Now";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// epoch seconds (number or string) -> short date
export function fmtEpoch(s) {
  const n = Number(s);
  if (!Number.isFinite(n) || n <= 0) return "Now";
  return fmtDate(new Date(n * 1000));
}

// ---- RentCafe ---------------------------------------------------------

// RentCafe floorplan cards carry data-* attributes on a single tag:
//   data-name data-beds data-baths data-size data-rent
// Returns floorplan-level listings (the per-unit table is lazy-loaded on click
// and not present in the rendered HTML, so floorplan granularity is the
// reliable signal for these bot-walled sites).
export function parseRentCafeFloorplans(html) {
  const out = [];
  const re = /data-name="([^"]*)"[^>]*?data-beds="([^"]*)"[^>]*?data-baths="([^"]*)"[^>]*?data-size="([^"]*)"[^>]*?data-rent="([^"]*)"/g;
  let m;
  const seen = new Set();
  while ((m = re.exec(html))) {
    const [, name, beds, baths, size, rent] = m.map((x) => decodeEntities(x));
    const key = `${name}|${beds}|${size}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const price = parsePrice(rent);
    const sqft = parseSqft(size);
    out.push({
      floorplan: name.trim() || null,
      unit: null,
      beds: parseBeds(beds),
      baths: parseBaths(baths),
      sqft: sqft.min,
      sqftText: sqft.text,
      price: price.min,
      priceText: price.text,
      available: price.min ? "Available" : "Call",
      granularity: "floorplan",
    });
  }
  return out;
}

// Pull all distinct $X,XXX prices from rendered text (fallback for RealPage
// renders where only price tokens survive).
export function pricesFromText(text) {
  return [...new Set((text.match(/\$[0-9],?[0-9]{3}/g) || []))].map((x) => num(x)).filter(Boolean).sort((a, b) => a - b);
}
