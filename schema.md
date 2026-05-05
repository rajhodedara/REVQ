# Schema Design Notes

## 1. Cross-platform product identity

**The problem.** The same physical product has 3 different IDs, 3 different name
strings, and 3 different structural formats across Blinkit, Zepto, and Instamart.
A naive approach — one table per platform — makes cross-platform queries painful.
A single flat table with nullable platform columns breaks when a product exists on
only 1 or 2 platforms, which is common (e.g. Almond Fudge single bar is Blinkit-only;
Oats 400g is Zepto + Instamart only).

**The approach.** Two-layer model:

- `products` — one row per real-world SKU, platform-agnostic
- `platform_listings` — one row per product per platform, holding native IDs and raw names

The canonical identity fingerprint is:

```
UNIQUE(brand, variant_slug, weight_g, pack_size)
```

`variant_slug` is a normalized keyword key computed during ingestion by stripping
brand name, weight, pack noise, and lowercasing + slugifying the remaining flavor/variant
tokens. Examples: `chocolate-chunk-nuts`, `peanut-butter-smooth`, `rolled-oats`.

MRP alone is not enough — 6 distinct products in the sample all have MRP=₹399 and
weight=400g. Weight alone is not enough for the same reason. `variant_slug` is the
tiebreaker.

**What this approach breaks on:**

1. **Same-variant, same-weight collision.** If Yogabar ever releases two flavors with
   identical slugs (e.g. two "chocolate" variants at the same weight), the slug must
   be made more specific. The current ingestion script logs a conflict and skips rather
   than silently merging — the operator must resolve manually.

2. **Name format drift.** If a platform changes how it titles products (e.g. Zepto
   stops including weight in the title), slug extraction breaks and the product gets
   inserted as a new canonical product instead of matching the existing one. Fixable
   with a listing-level alias table, but not built yet.

3. **The Almond Crunch Muesli ambiguity.** Blinkit and Zepto list it as
   "Almond Crunch Muesli". Instamart lists it as "Almond + Cashew Crunch Muesli".
   Same MRP (₹399), same weight (400g). Judgment call: treated as the same canonical
   product. If the formulation is actually different, the schema has no way to detect
   this — it relies on the brand having consistent MRP + weight across identical products.

4. **The 20g vs 21g protein bar.** Blinkit says "21g Protein Bar - Double Cocoa",
   Zepto says "20G Protein Bar Double Cocoa". Same MRP (₹720), same pack size (6).
   Treated as the same product — likely a rounding difference in how each platform
   displays the protein claim, not a different SKU.

---

## 2. Denormalization / index for scale

**Index added:** `idx_price_listing_time ON price_snapshots(listing_id, scraped_at DESC)`

This covers the most frequent query pattern: "give me the latest price for this
listing." Without it, every "current price" read scans the full price_snapshots table
for that listing, which grows unboundedly as scrapes accumulate.

**Denormalization I'd add next:** A `current_state` table (or materialized view in
Postgres) that holds the latest price and availability summary per listing, updated
atomically at the end of each scrape run. This makes the product detail screen a
single-table read instead of a correlated subquery per listing. The tradeoff: one
extra write per listing per scrape run, and the current_state can lag by one run if
the update fails partway through (acceptable for a dashboard, not for billing).

---

## 3. What changes at 100× scrape volume

At 100× volume (hundreds of brands, thousands of pincodes, scrapes every few hours),
three things break:

1. **availability_snapshots becomes the largest table by far.** At current scale:
   ~50 listings × 8 pincodes × 1 scrape/day = 400 rows/day. At 100×: ~5000 listings
   × 50 pincodes × 8 scrapes/day = 2M rows/day. SQLite cannot handle this; move to
   **TimescaleDB** (Postgres extension) and partition availability_snapshots by month.
   Older partitions get compressed automatically.

2. **Identity matching becomes a bottleneck.** At 100× volume, computing variant_slug
   and looking up the products table inline during ingest creates lock contention.
   Move matching to an **async pipeline**: raw scrape data lands in a staging table
   first; a separate worker process resolves identity and writes to the canonical
   tables. Ingest speed is no longer coupled to matching complexity.

3. **The correlated subquery for "latest price" becomes expensive.** The
   `idx_price_listing_time` index helps but isn't sufficient at 2M+ rows/day.
   The `current_state` denormalization described above becomes mandatory, not optional.
