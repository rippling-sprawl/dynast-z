// Zero-dependency static server + refresh endpoint.
//   node server.mjs   ->   http://localhost:5173
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { scrapeAll, DATA_FILE } from "./scrape.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 5173;
let refreshing = false;

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://localhost");

    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
      const html = await readFile(join(__dirname, "index.html"));
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      return res.end(html);
    }

    if (req.method === "GET" && url.pathname === "/api/data") {
      let data = '{"listings":[],"sources":[],"generatedAt":null}';
      try { data = await readFile(DATA_FILE, "utf8"); } catch { /* no data yet */ }
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(data);
    }

    if (req.method === "POST" && url.pathname === "/api/refresh") {
      if (refreshing) {
        res.writeHead(409, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({ error: "A refresh is already running." }));
      }
      refreshing = true;
      console.log("\n[refresh] starting…");
      try {
        const data = await scrapeAll({ log: (m) => console.log("  " + m) });
        console.log(`[refresh] done — ${data.listings.length} listings`);
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify(data));
      } finally {
        refreshing = false;
      }
    }

    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("Not found");
  } catch (e) {
    console.error(e);
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: String(e?.message || e) }));
  }
});

server.listen(PORT, () => {
  console.log(`Asheville rentals  ->  http://localhost:${PORT}`);
  console.log("Press the Refresh button in the page to re-scrape all sources.");
});
