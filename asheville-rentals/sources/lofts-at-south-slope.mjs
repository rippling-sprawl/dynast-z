import { directFetch, num, parseBeds, parsePrice, fmtDate } from "./_lib.mjs";

export const meta = {
  id: "lofts-at-south-slope",
  name: "Lofts at South Slope",
  address: "162 Coxe Ave, Asheville, NC 28801",
  officialUrl: "https://www.loftsatsouthslope-nc.com/",
  fees: { pet: "$300 + $25/mo (no breed/wt limits)", parking: "Covered garage", washerDryer: "—" },
  outdoor: "", // no confirmed private patio/balcony — left unknown so the page doesn't hide it
  washerDryerType: "In-unit",
  method: "Apartments247 JSON API (direct, per-unit)",
};

// Apartments247 exposes an open JSON API (api_key is hard-coded in the site HTML).
// Genuinely-available inventory lives in each floorplan's units[]; wait_units[]
// is a waitlist mirror with placeholder pricing, so we ignore it.
const API =
  "https://www.loftsatsouthslope-nc.com/api/v1/floorplans/?format=json&limit=50" +
  "&api_key=4975ce80d6eb30c885584e37eb751da187e7cd83";

export async function fetchListings() {
  const d = await directFetch(API, { json: true });
  if (!d || !Array.isArray(d.objects)) throw new Error("unexpected Apartments247 response");
  const out = [];
  for (const fp of d.objects) {
    const baths = num(fp.bath);
    for (const u of fp.units || []) {
      const p = parsePrice(u.rent);
      const sqft = num(u.sq_ft) ?? num(fp.sq_ft);
      out.push({
        floorplan: fp.name || null,
        unit: u.number || null,
        beds: parseBeds(u.display_bed || fp.display_bed),
        baths,
        sqft,
        sqftText: sqft ? String(sqft) : "",
        price: p.min,
        priceText: p.min ? `$${p.min.toLocaleString()}` : "Call",
        available: fmtDate(u.available_date),
        granularity: "unit",
      });
    }
  }
  return out;
}
