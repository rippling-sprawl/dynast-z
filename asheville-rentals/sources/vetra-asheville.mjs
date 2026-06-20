import { proxyFetch, parseBeds, parseBaths, parseSqft, parsePrice } from "./_lib.mjs";

export const meta = {
  id: "vetra-asheville",
  name: "Vetra Asheville",
  address: "300 Long Shoals Road, Arden, NC 28704",
  officialUrl: "https://www.livevetraasheville.com/",
  fees: { pet: "Not published", parking: "Garages avail", washerDryer: "—" },
  outdoor: "Yes — private patio/balcony",
  washerDryerType: "Community",
  method: "RealPage leasing app via render proxy (floorplan-level)",
};

// The RealPage online-leasing SPA, rendered by the proxy, lists each floorplan as:
//   ###### The Maple
//   1 Bed | 1 Bath | 767 sq ft
//   $1,399 - $1,799*
function parseOll(md) {
  const out = [];
  const re = /######\s*([^\n]+)\n+\s*([\d.]+)\s*Beds?\s*\|\s*([\d.]+)\s*Baths?\s*\|\s*([^\n]*?sq ft)\n+\s*([^\n]*\$[\d,][^\n]*)/g;
  let m;
  while ((m = re.exec(md))) {
    const [, name, beds, baths, size, priceLine] = m;
    const sqft = parseSqft(size);
    const price = parsePrice(priceLine);
    out.push({
      floorplan: name.trim(),
      unit: null,
      beds: parseBeds(beds),
      baths: parseBaths(baths),
      sqft: sqft.min,
      sqftText: sqft.text,
      price: price.min,
      priceText: price.text,
      available: price.min ? "Available" : "Call",
      granularity: "floorplan",
    });
  }
  return out;
}

export async function fetchListings() {
  const url = "https://leasing.realpage.com/oll/?siteId=5384615";
  const md = await proxyFetch(url, {
    format: "markdown",
    retries: 4,
    want: (t) => /######[^\n]+\n+[\d.]+\s*Beds?/.test(t),
  });
  return parseOll(md);
}
