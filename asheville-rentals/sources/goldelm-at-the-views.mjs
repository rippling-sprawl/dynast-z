export const meta = {
  id: "goldelm-at-the-views",
  name: "Goldelm at the Views",
  address: "1680 Hendersonville Rd, Asheville, NC 28803 (South Asheville)",
  officialUrl: "https://www.theviewsapartments.com/apartments/nc/asheville/floor-plans",
  fees: { pet: "$300 (1)/$200 (2)", parking: "Free (surface)", washerDryer: "—" },
  outdoor: "Yes — private patio/balcony",
  washerDryerType: "In-unit",
  method: "No live feed — RealPage SPA behind DataDome bot-wall",
};

// Goldelm's availability lives in a RealPage OLL widget protected by DataDome +
// Akamai bot management. Neither a plain fetch nor the render proxy can reach the
// authenticated unit feed — it requires a full headless browser performing the
// site's own token handshake. We surface the complex (with fees/amenities) but
// cannot pull live units here; the table shows it with a "check site" status.
export async function fetchListings() {
  return [];
}
