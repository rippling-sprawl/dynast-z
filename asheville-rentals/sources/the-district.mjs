import { directFetch, num, fmtDate } from "./_lib.mjs";

export const meta = {
  id: "the-district",
  name: "The District",
  address: "100 District Drive, Asheville, NC 28803 (Biltmore Village)",
  officialUrl: "https://www.thedistrictasheville.com/",
  fees: { pet: "$400 (1)/$600 (2) + $20/mo", parking: "Garage rentals", washerDryer: "—" },
  outdoor: "Yes — balcony/patio",
  washerDryerType: "In-unit",
  method: "Knock API (direct, per-unit)",
};

export async function fetchListings() {
  const d = await directFetch("https://doorway-api.knockrentals.com/v1/property/2013903/units", { json: true });
  const units = (d.units_data?.units || []).filter((u) => u.available && !u.leased && !u.hidden);
  return units.map((u) => {
    const price = num(u.price);
    const sqft = u.area || null;
    return {
      floorplan: u.layoutName || null,
      unit: u.name || null,
      beds: num(u.bedrooms),
      baths: num(u.bathrooms),
      sqft,
      sqftText: sqft ? String(sqft) : "",
      price,
      priceText: price ? `$${price.toLocaleString()}` : "—",
      available: fmtDate(u.availableOn),
      granularity: "unit",
    };
  });
}
