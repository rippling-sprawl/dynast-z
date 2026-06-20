import { directFetch, fmtDate } from "./_lib.mjs";

export const meta = {
  id: "ascot-point-village",
  name: "Ascot Point Village",
  address: "23 Ascot Point Circle, Asheville, NC 28803",
  officialUrl: "https://www.ariapts.com/apartments/nc/asheville/ascot-point-village/",
  fees: { pet: "$400 + $25/mo", parking: "Call (garages avail)", washerDryer: "—" },
  outdoor: "Yes — patio/balcony",
  washerDryerType: "Hookups",
  method: "myleasestar API (direct, per-unit)",
};

export async function fetchListings() {
  const d = await directFetch("https://capi.myleasestar.com/v2/property/8791455/units", { json: true });
  const units = (d.units || []).filter((u) => u.leaseStatus === "AVAILABLE_READY" && u.displayed);
  return units.map((u) => {
    const sqft = u.squareFeet || null;
    const price = u.rent != null ? Number(u.rent) : null;
    return {
      floorplan: u.floorplanName || null,
      unit: u.unitNumber || null,
      beds: u.numberOfBeds,
      baths: u.numberOfBaths,
      sqft,
      sqftText: sqft ? String(sqft) : "",
      price,
      priceText: price ? `$${price.toLocaleString()}` : "—",
      available: fmtDate(u.internalAvailableDate),
      granularity: "unit",
    };
  });
}
