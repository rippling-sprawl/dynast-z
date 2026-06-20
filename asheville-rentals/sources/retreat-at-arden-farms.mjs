import { proxyFetch, parseRentCafeFloorplans } from "./_lib.mjs";

export const meta = {
  id: "retreat-at-arden-farms",
  name: "Retreat at Arden Farms",
  address: "10 Arden Farms Lane, Arden, NC 28704",
  officialUrl: "https://www.liveretreatatardenfarms.com/",
  fees: { pet: "$450 + $35/mo", parking: "Garages avail", washerDryer: "—" },
  outdoor: "Yes — balcony/patio",
  washerDryerType: "In-unit",
  method: "RentCafe via render proxy (floorplan-level)",
};

// rentcafe.com is Cloudflare-walled to a plain fetch; the render proxy gets the
// floorplan cards (data-* attributes). Per-unit rows are lazy-loaded on click
// and not in the rendered HTML, so granularity here is floorplan-level.
export async function fetchListings() {
  const url = "https://www.rentcafe.com/apartments/nc/arden/retreat-at-arden-farms0/default.aspx";
  const html = await proxyFetch(url, { format: "html", retries: 3, want: (t) => t.includes("data-name=") });
  return parseRentCafeFloorplans(html);
}
