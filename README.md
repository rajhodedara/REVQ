# RevQ Intern Exercise — Submission

## Running the project

**Prerequisites:** Python 3.10+, Node 18+

```bash
# 1. Clone / unzip the submission folder

# 2. Ingest all three platform files
pip install flask flask-cors
python ingest.py data/blinkit_sample.json
python ingest.py data/zepto_sample.json
python ingest.py data/instamart_sample.json

# 3. Start the API
python api/app.py
# → http://localhost:5000

# 4. Start the frontend (separate terminal)
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

---
<img width="1864" height="838" alt="image" src="https://github.com/user-attachments/assets/f783bd7b-009a-4712-a86f-37a0cf270405" />

## Stack

| Layer     | Choice              | Why                                                                 |
|-----------|---------------------|---------------------------------------------------------------------|
| Database  | SQLite              | Zero setup for the exercise; schema is Postgres-compatible          |
| Ingestion | Python (stdlib)     | No ORM — raw SQL makes the identity logic explicit and easy to audit|
| API       | Flask + flask-cors  | Minimal surface area, easy to follow in a walkthrough               |
| Frontend  | React + Vite        | Fast dev loop; component boundaries map cleanly to the data model   |

---

## Schema design

Four tables: `products`, `platform_listings`, `price_snapshots`, `availability_snapshots`.

The split between `products` and `platform_listings` is the core design decision. A single flat table with nullable platform columns breaks the moment a product exists on only one or two platforms — which is common in this dataset (e.g. Almond Fudge single bar is Blinkit-only). The two-layer model keeps canonical product data platform-agnostic and makes cross-platform queries straightforward joins.

`price_snapshots` and `availability_snapshots` are **append-only**. Nothing is ever updated. This is intentional: the entire value of RevQ is historical data. Overwriting prices on ingest would destroy the time series.

Full design rationale and scale discussion is in `schema.md`.

---

## Cross-platform identity

The hardest problem in the exercise. The same physical product has three different IDs, three different name strings, and three different structural formats across platforms.

**Approach:** compound identity fingerprint — `(brand, variant_slug, weight_g, pack_size)`.

`variant_slug` is computed during ingestion by:
1. Splitting on `|` (Instamart delimiter)
2. Stripping weight patterns (`60g`, `6x60gm`, `38g x 6`), pack patterns (`pack of 6`), and parenthetical notes
3. Expanding platform abbreviations — Zepto writes `CHOC`, Blinkit writes `Chocolate`. Both expand to `chocolate` before slugging
4. Removing structural stop-words (`protein`, `bar`, `wholegrain`, etc.) that appear across many SKUs and don't distinguish variants
5. Sorting remaining tokens — handles word-order differences across platforms
6. Joining with `-`

Result: `"YOGABAR PEANUT BUTTER CHOC PROTEIN BAR 60GM"` and `"Yogabar Peanut Butter Chocolate Protein Bar (60 g)"` both produce `butter-chocolate-peanut`, and match correctly.

**Weight normalisation:** all weights stored in grams. `"38g x 6"` → 228g ×6. `"6X60GM"` → 360g ×6. `"1 kg"` → 1000g. This means the fingerprint is computed on total package weight, not unit weight — two products with identical total weight and pack count are the same SKU.

**Results on the sample data:** 23 canonical products across 48 platform listings. 10 products matched across all 3 platforms. 0 skipped (all weights parsed successfully).

**Known cracks:**

1. **20g vs 21g Double Cocoa bar** — Blinkit says "21g Protein Bar", Zepto says "20G Protein Bar". Same product, different rounding of the protein claim in the title. They don't match because `weight_g` differs (21 vs 20). Judgment call: left as two separate canonical products rather than silently merging on a guess. In production, a manual alias table would resolve this.

2. **Almond + Cashew Crunch Muesli (Instamart) vs Almond Crunch Muesli (Blinkit/Zepto)** — same MRP, same weight, but the name includes "cashew" on Instamart. Treated as a different product. If the formulation is actually identical, a brand-provided product catalog would be the right source of truth — the scraper shouldn't guess.

3. **Slug collisions on very short names** — if a future product's name reduces to a single token after stripping, it could collide with another. The ingest script uses `ON CONFLICT DO NOTHING` and logs a warning rather than silently merging.

---

## Component tree

```
App
├── Sidebar                     — product list with platform dot indicators
└── ProductDetail               — main view, fetches /api/products/:id
    ├── KPI strip               — best price, max discount, pincodes live (derived, not stored)
    ├── PriceTable              — MRP / selling price / discount % / savings per platform
    ├── AvailabilityGrid        — per-pincode stock status + Instamart quantity
    └── Freshness row           — last scraped timestamp with stale warning if >24h
```

`ProductDetail` owns all state for the selected product via a single `useEffect` fetch. Child components receive data as props and are purely presentational — no internal state, no additional fetches. This makes the data flow easy to trace: one network request per product selection, everything derived from that response.

The KPI strip values (best price, max discount, pincodes live) are computed in `ProductDetail` from the API response rather than stored in the DB. They'd become stale the moment a new scrape runs if stored, and they're cheap to compute from the existing data.

---

## API

Three endpoints:

```
GET /api/products              → list of all canonical products (sidebar)
GET /api/products/:id          → full product detail with per-platform price + availability
GET /api/products/:id/history  → 30-day price history per platform (schema supports this;
                                  UI chart not built — see "what's left" below)
```

The history endpoint is implemented and returns correct data. The frontend chart consuming it ran over the 4-hour target so it was cut. The endpoint is there and can be verified directly.

---

## What's fragile / unfinished

**Slug matching degrades with more brands.** The stop-word list and abbreviation map are tuned for Yogabar. A different brand would need its own tuning. The right fix is a brand-provided product catalog as the source of canonical identity, with the slug matching as a fallback for unrecognised products.

**No auth on the API.** Fine for the exercise; would need API key middleware before any external exposure.

**The price history chart is not in the UI.** The endpoint works and the schema was designed specifically for it — it's the most useful RevQ feature and the next thing to build. Cut for time.

**SQLite write locking.** If multiple scrapers run concurrently, SQLite's single-writer model will cause contention. The ingest script uses a single connection with transactions, which is fine for sequential runs but breaks under parallelism. Postgres fixes this.

---

## Next 4 hours (if this were a real sprint)

1. **Price history chart** — 30-day line chart per platform using the `/history` endpoint. This is the core RevQ value prop and the schema already supports it fully.
2. **Manual alias table** — a `product_aliases` table to resolve ambiguous matches (20g vs 21g, Almond vs Almond+Cashew) without changing the matching logic.
3. **Scrape run tracking** — a `scrape_runs` table so availability queries use `run_id` instead of `scraped_at`, making it easier to compare "current" vs "previous" snapshots.
4. **`current_state` denormalisation** — a summary table updated at the end of each scrape run so the product list page doesn't need correlated subqueries for current prices.
