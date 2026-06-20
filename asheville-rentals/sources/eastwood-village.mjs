import { proxyFetch, num, parseBeds, fmtDate } from "./_lib.mjs";

export const meta = {
  id: "eastwood-village",
  name: "Eastwood Village Apartment Homes",
  address: "32 Olde Eastwood Village Blvd, Asheville, NC 28803",
  officialUrl: "https://www.eastwoodvillage-apartments.com/",
  fees: { pet: "$300 + $10/mo", parking: "Detached garages avail", washerDryer: "—" },
  outdoor: "Yes — patio/balcony",
  washerDryerType: "Hookups",
  method: "Official floorplan pages via render proxy (per-unit)",
};

const PAGES = [
  "https://www.eastwoodvillage-apartments.com/floorplans/one-bedroom",
  "https://www.eastwoodvillage-apartments.com/floorplans/two-bedroom",
];

// Each available unit is an "Apply" button:
//   onclick="applyGAClick('Two Bedroom','2 Bed(s)','964','1599.00','1599.00','1-125')"
//   href="...oleapplication.aspx?...&MoveInDate=6/19/2026..."
// Eastwood's two plans are 1bd/1ba and 2bd/2ba, so baths == beds here.
function parseUnits(html) {
  const out = [];
  const re = /applyGAClick\('([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'[^']*',\s*'([^']*)'\s*\)/g;
  let m;
  while ((m = re.exec(html))) {
    const [, fp, bedsStr, sqftStr, priceStr, unit] = m;
    const beds = parseBeds(bedsStr);
    const price = num(priceStr);
    const sqft = num(sqftStr);
    // MoveInDate lives in the href a few hundred chars after this onclick.
    const after = html.slice(m.index, m.index + 600);
    const dm = after.match(/MoveInDate=([\d/]+)/);
    out.push({
      floorplan: fp.trim() || null,
      unit: unit.trim() || null,
      beds,
      baths: beds, // 1bd/1ba, 2bd/2ba at this property
      sqft,
      sqftText: sqft ? String(sqft) : "",
      price,
      priceText: price ? `$${price.toLocaleString()}` : "—",
      available: dm ? fmtDate(dm[1]) : "Now",
      granularity: "unit",
    });
  }
  return out;
}

export async function fetchListings() {
  const all = [];
  for (const url of PAGES) {
    const html = await proxyFetch(url, {
      format: "html",
      retries: 3,
      want: (t) => t.includes("applyGAClick('"),
    });
    all.push(...parseUnits(html));
  }
  // de-dupe by unit number
  const seen = new Set();
  return all.filter((u) => {
    const k = u.unit || JSON.stringify(u);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}
