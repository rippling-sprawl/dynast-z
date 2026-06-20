import { directFetch, num, fmtEpoch } from "./_lib.mjs";

export const meta = {
  id: "reserve-at-biltmore-park",
  name: "Reserve at Biltmore Park",
  address: "Arden, NC 28704 (Biltmore Park)",
  officialUrl: "https://reserveatbiltmorepark.com/",
  fees: { pet: "PetScreening req (amt not published)", parking: "Attached garage (select)", washerDryer: "—" },
  outdoor: "Yes — private patio/deck",
  washerDryerType: "In-unit",
  method: "Embedded JSON on floorplan pages (direct, per-unit)",
};

const SLUGS = [
  "buncombe", "commodore", "ashworth", "larchmont", "blue-ridge", "merrimon",
  "pisgah", "ramblewood", "olmsted", "montford", "swannanoa", "biltmore", "vanderbilt",
];

function floorplanFromHtml(html) {
  const blocks = [...html.matchAll(/<script[^>]*type=["']application\/json["'][^>]*>([\s\S]*?)<\/script>/gi)];
  for (const b of blocks) {
    try {
      const o = JSON.parse(b[1]);
      if (o && o.type === "floorplan") return o;
    } catch { /* ignore non-JSON blocks */ }
  }
  return null;
}

export async function fetchListings() {
  const out = [];
  for (const slug of SLUGS) {
    let html;
    try {
      html = await directFetch(`https://reserveatbiltmorepark.com/floorplans/${slug}/`);
    } catch {
      continue; // skip a slug that 404s / fails; others still load
    }
    const fp = floorplanFromHtml(html);
    if (!fp || !Array.isArray(fp.units) || !fp.units.length) continue; // no current availability
    const beds = num(fp.bedrooms);
    const baths = num(fp.bathrooms);
    for (const u of fp.units) {
      const price = num(u.rent_min) ?? num(u.price);
      const sqft = num(u.square_feet) ?? num(fp.square_feet);
      out.push({
        floorplan: fp.title || null,
        unit: u.apartment_number || (u.title || "").replace(/^#/, "") || null,
        beds: num(u.bedrooms) ?? beds,
        baths: num(u.bathrooms) ?? baths,
        sqft,
        sqftText: sqft ? String(sqft) : "",
        price,
        priceText: price ? `$${price.toLocaleString()}` : "—",
        available: u.available_display || fmtEpoch(u.available_date),
        granularity: "unit",
      });
    }
  }
  return out;
}
