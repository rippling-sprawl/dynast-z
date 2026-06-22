import { directFetch, num, parseBeds, parsePrice, fmtDate } from "./_lib.mjs";

export const meta = {
  id: "riverstone-at-long-shoals",
  name: "Riverstone at Long Shoals",
  address: "223 Long Shoals Rd, Arden, NC 28704",
  officialUrl: "https://www.riverstoneapartmentsatlongshoals.com/",
  fees: { pet: "$400 + $25/mo (no breed/wt limits)", parking: "Surface lot", washerDryer: "—" },
  outdoor: "Yes — balcony/patio",
  washerDryerType: "In-unit",
  method: "Apartments247 JSON API (direct, per-unit)",
};

// Apartments247 v3 floorplans feed: an array of floorplans, each with a units[]
// array of genuinely-available units (floorplans with no availability have units: []).
const API =
  "https://www.riverstoneapartmentsatlongshoals.com/api/v3/floorplans/all/" +
  "?api_key=e31d1ddbc244dbb4c004141903d926f983b38621&community=7313";

export async function fetchListings() {
  const d = await directFetch(API, { json: true });
  const fps = Array.isArray(d) ? d : (d.objects || d.floorplans || []);
  if (!Array.isArray(fps) || !fps.length) throw new Error("unexpected Apartments247 response");
  const out = [];
  for (const fp of fps) {
    for (const u of fp.units || []) {
      const p = parsePrice(u.rent);
      const sqft = num(u.sq_ft) ?? num(fp.sq_ft);
      out.push({
        floorplan: fp.name || null,
        unit: u.number || null,
        beds: num(u.bed) ?? parseBeds(u.display_bed) ?? num(fp.bed),
        baths: num(u.bath) ?? num(fp.bath),
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
