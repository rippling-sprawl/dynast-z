import { proxyFetch, num, fmtDate } from "./_lib.mjs";

export const meta = {
  id: "haw-creek-mews",
  name: "Haw Creek Mews",
  address: "145 Haw Creek Mews Dr, Asheville, NC 28805",
  officialUrl: "https://www.hawcreekmewsapts.com/",
  fees: { pet: "$350 (+$250 2nd pet)", parking: "Surface lot", washerDryer: "—" },
  outdoor: "Yes — patio/balcony",
  washerDryerType: "Hookups",
  method: "RentCafe (Site Editor) via render proxy (per-unit)",
};

// The site is Cloudflare-walled to a plain fetch, but its /availableunits page
// renders (via the proxy) to markdown with one section per floorplan:
//   ## The Abbington Garden       <- real floorplan name
//   1 Bedroom | 1 Bathroom        <- beds/baths
//   ## Floor Plan Video           <- noise header (ignored)
//   | Apartment: #147 | Sq. Ft.: 776 | Rent: $1,374.00 to -$2,299.00 | Date: 8/20/2026 |
// A header only counts as a floorplan when it's followed by a beds/baths line —
// that skips the "Floor Plan Video" and trailing page-section headers.
export async function fetchListings() {
  const md = await proxyFetch("https://www.hawcreekmewsapts.com/availableunits", {
    format: "markdown",
    retries: 4,
    want: (t) => /Apartment:\s*#/.test(t),
  });

  const out = [];
  const lines = md.split("\n");
  const bedsRe = /(\d+(?:\.\d+)?)\s*Bedrooms?\s*\|\s*(\d+(?:\.\d+)?)\s*Bathrooms?/i;
  let floorplan = null, beds = null, baths = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const header = line.match(/^#{2,3}\s+(.+?)\s*$/);
    if (header) {
      let bb = null;
      for (let j = i + 1; j <= i + 3 && j < lines.length; j++) {
        if (/^#{2,3}\s/.test(lines[j])) break; // next header — not a floorplan block
        bb = lines[j].match(bedsRe);
        if (bb) break;
      }
      if (bb) { floorplan = header[1].trim(); beds = Number(bb[1]); baths = Number(bb[2]); }
      continue;
    }
    if (!/Apartment:\s*#/.test(line)) continue;

    const unit = (line.match(/Apartment:\s*#?\s*([\w-]+)/) || [])[1] || null;
    const sqft = num((line.match(/Sq\.?\s*Ft\.?:\s*([\d,]+)/i) || [])[1]);
    const price = num((line.match(/Rent:\s*\$([\d,]+)/) || [])[1]); // low end of the unit's range
    const date = ((line.match(/Date:\s*([^|]+)/) || [])[1] || "").trim();
    out.push({
      floorplan,
      unit,
      beds,
      baths,
      sqft,
      sqftText: sqft ? String(sqft) : "",
      price,
      priceText: price ? `$${price.toLocaleString()}` : "—",
      available: /available/i.test(date) || !date ? "Available" : fmtDate(date),
      granularity: "unit",
    });
  }
  return out;
}
