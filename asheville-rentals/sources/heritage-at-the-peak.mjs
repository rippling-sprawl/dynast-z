import { proxyFetch, parseRentCafeFloorplans } from "./_lib.mjs";

export const meta = {
  id: "heritage-at-the-peak",
  name: "Heritage at the Peak",
  address: "50 Barnwood Dr, Asheville, NC 28804 (Woodfin)",
  officialUrl: "https://www.heritageatthepeak.com/",
  fees: { pet: "$300 + $15/mo", parking: "Garages avail", washerDryer: "—" },
  outdoor: "Yes — private patio/balcony",
  washerDryerType: "In-unit",
  method: "RentCafe via render proxy (floorplan-level)",
};

export async function fetchListings() {
  // The official site lists this property on rentcafe.com under its legacy name.
  const url = "https://www.rentcafe.com/apartments/nc/asheville/hawthorne-at-the-park-1/default.aspx";
  const html = await proxyFetch(url, { format: "html", retries: 3, want: (t) => t.includes("data-name=") });
  return parseRentCafeFloorplans(html);
}
