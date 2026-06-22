import { proxyFetch, parseRentCafeFloorplans } from "./_lib.mjs";

export const meta = {
  id: "parkway-crossing",
  name: "Parkway Crossing",
  address: "102 La Mancha Dr, Asheville, NC 28803",
  officialUrl: "https://www.parkwaycrossing-apts.com/",
  fees: { pet: "$350 + $150 (2nd) + $20/mo (max 2 / 100 lb)", parking: "Free surface", washerDryer: "—" },
  outdoor: "Yes — patio/balcony (select)",
  washerDryerType: "Hookups",
  method: "RentCafe via render proxy (floorplan-level)",
};

// Both the official domain and rentcafe.com are Cloudflare-walled to a plain
// fetch; the render proxy gets the floorplan cards (data-* attributes). The CF
// challenge stub comes back intermittently, so retry until a card is present.
export async function fetchListings() {
  const url = "https://www.rentcafe.com/apartments/nc/asheville/parkway-crossing-0/default.aspx";
  const html = await proxyFetch(url, { format: "html", retries: 5, want: (t) => t.includes("data-name=") });
  return parseRentCafeFloorplans(html);
}
