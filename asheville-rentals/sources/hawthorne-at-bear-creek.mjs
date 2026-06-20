import { directFetch, num, fmtDate } from "./_lib.mjs";

export const meta = {
  id: "hawthorne-at-bear-creek",
  name: "Hawthorne at Bear Creek",
  address: "110 Bear Creek Lane, Asheville, NC 28806",
  officialUrl: "https://hawthorneatbearcreek.com/",
  fees: { pet: "$350 + $25/mo", parking: "Free", washerDryer: "—" },
  outdoor: "Yes — balcony/patio",
  washerDryerType: "Hookups", // in-unit connections; community laundry also on site
  method: "RentCafe API (direct, per-unit)",
};

export async function fetchListings() {
  const url =
    "https://api.rentcafe.com/rentcafeapi.aspx?requestType=apartmentavailability" +
    "&apiToken=8fb544e24f12c399&propertyId=420795&companyId=58269";
  const arr = await directFetch(url, { json: true });
  if (!Array.isArray(arr)) throw new Error("unexpected RentCafe response");
  return arr.map((u) => {
    const price = num(u.MinimumRent);
    const sqft = num(u.SQFT);
    return {
      floorplan: u.FloorplanName || null,
      unit: u.ApartmentName || null,
      beds: num(u.Beds),
      baths: num(u.Baths),
      sqft,
      sqftText: sqft ? String(sqft) : "",
      price,
      priceText: price ? `$${price.toLocaleString()}` : "—",
      available: fmtDate(u.AvailableDate),
      granularity: "unit",
    };
  });
}
