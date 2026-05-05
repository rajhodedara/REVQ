-- =============================================================================
-- RevQ Schema
-- Supports: multi-platform product identity, time-series pricing, availability
-- DB: SQLite (prod would be Postgres)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- PRODUCTS
-- One row per real-world SKU, regardless of how many platforms carry it.
--
-- The hard problem: 3 platforms, 3 different IDs, 3 different name strings
-- for the exact same physical product. We solve this with a compound
-- identity fingerprint: (brand, variant_slug, weight_g, pack_size)
--
-- variant_slug is a normalized keyword key we compute during ingestion
-- e.g. "chocolate-chunk-nuts", "peanut-butter-smooth", "rolled-oats"
-- It's derived from the product name after stripping brand, weight, pack noise.
-- This handles the MRP collision problem: 6 different products all have MRP=399
-- and weight=400g, so (mrp, weight) alone is not enough.
-- -----------------------------------------------------------------------------
CREATE TABLE products (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    brand           TEXT     NOT NULL,
    canonical_name  TEXT     NOT NULL,   -- human-readable, set on first ingest
    variant_slug    TEXT     NOT NULL,   -- normalized matching key (see above)
    weight_g        INTEGER  NOT NULL,   -- total weight in grams (pack_size × unit_weight)
    pack_size       INTEGER  NOT NULL DEFAULT 1,
    category        TEXT,                -- best-effort from platform data
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- This UNIQUE constraint IS the cross-platform identity rule.
    -- If two listings share these 4 values, they are the same product.
    UNIQUE(brand, variant_slug, weight_g, pack_size)
);


-- -----------------------------------------------------------------------------
-- PLATFORM LISTINGS
-- One row per product per platform. A product that exists on all 3 platforms
-- will have 3 rows here, all pointing to the same products.id.
--
-- Stores the original platform-native fields for audit and debugging.
-- We never lose the raw platform data — it lives here.
-- -----------------------------------------------------------------------------
CREATE TABLE platform_listings (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER  NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    platform            TEXT     NOT NULL CHECK(platform IN ('blinkit', 'zepto', 'instamart')),
    platform_product_id TEXT     NOT NULL,  -- native ID: blinkit_id / sku_code / product_id(uuid)
    platform_name       TEXT     NOT NULL,  -- original name string, kept for audit
    image_url           TEXT,               -- nullable: some Blinkit products have null images
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- One listing per platform per native product ID
    UNIQUE(platform, platform_product_id)
);


-- -----------------------------------------------------------------------------
-- PRICE SNAPSHOTS  (time-series, append-only)
-- Every scrape writes a new row. We never UPDATE — historical prices are
-- the entire point of this product. One row per listing per scrape run.
-- -----------------------------------------------------------------------------
CREATE TABLE price_snapshots (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    listing_id      INTEGER  NOT NULL REFERENCES platform_listings(id) ON DELETE CASCADE,
    scraped_at      DATETIME NOT NULL,
    mrp             INTEGER  NOT NULL,   -- in rupees
    selling_price   INTEGER  NOT NULL,   -- in rupees
    discount_pct    REAL,                -- stored (not computed) for query speed

    -- Prevent double-writing if the scraper retries the same run
    UNIQUE(listing_id, scraped_at)
);

-- Covers Query 1: latest price per listing  (ORDER BY scraped_at DESC LIMIT 1)
-- Covers Query 2: 30-day price history      (WHERE scraped_at >= date('now', '-30 days'))
CREATE INDEX idx_price_listing_time ON price_snapshots(listing_id, scraped_at DESC);


-- -----------------------------------------------------------------------------
-- AVAILABILITY SNAPSHOTS  (time-series, append-only)
-- One row per listing × pincode × scrape run.
-- Instamart gives available_qty; Blinkit/Zepto give boolean. Both are stored.
-- available_qty > 0 → in_stock = 1 during ingest (we normalise at write time).
-- -----------------------------------------------------------------------------
CREATE TABLE availability_snapshots (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    listing_id      INTEGER  NOT NULL REFERENCES platform_listings(id) ON DELETE CASCADE,
    scraped_at      DATETIME NOT NULL,
    pincode         TEXT     NOT NULL,
    in_stock        INTEGER  NOT NULL CHECK(in_stock IN (0, 1)),  -- 0=OOS, 1=in stock
    available_qty   INTEGER,  -- nullable; only Instamart provides quantity

    -- Prevent double-writing same listing+pincode for same scrape
    UNIQUE(listing_id, scraped_at, pincode)
);

-- Covers Query 3: OOS pincodes per platform
--   WHERE in_stock = 0 AND scraped_at = <latest run>
CREATE INDEX idx_avail_listing_time ON availability_snapshots(listing_id, scraped_at DESC);

-- Secondary index: query all availability for a specific pincode across products
CREATE INDEX idx_avail_pincode ON availability_snapshots(pincode);


-- =============================================================================
-- THE 3 REQUIRED QUERIES (shown here to validate the schema)
-- =============================================================================

-- Query 1: Current price of product X on all 3 platforms
-- SELECT
--     pl.platform,
--     pl.platform_name,
--     ps.mrp,
--     ps.selling_price,
--     ps.discount_pct,
--     ps.scraped_at
-- FROM products p
-- JOIN platform_listings pl ON pl.product_id = p.id
-- JOIN price_snapshots ps ON ps.listing_id = pl.id
-- WHERE p.id = :product_id
--   AND ps.scraped_at = (
--       SELECT MAX(scraped_at) FROM price_snapshots WHERE listing_id = pl.id
--   );

-- Query 2: 30-day price history of product X on Blinkit
-- SELECT ps.scraped_at, ps.selling_price, ps.mrp, ps.discount_pct
-- FROM products p
-- JOIN platform_listings pl ON pl.product_id = p.id AND pl.platform = 'blinkit'
-- JOIN price_snapshots ps  ON ps.listing_id = pl.id
-- WHERE p.id = :product_id
--   AND ps.scraped_at >= datetime('now', '-30 days')
-- ORDER BY ps.scraped_at ASC;

-- Query 3: Pincodes where product X is OOS, per platform
-- SELECT pl.platform, av.pincode, av.scraped_at
-- FROM products p
-- JOIN platform_listings pl ON pl.product_id = p.id
-- JOIN availability_snapshots av ON av.listing_id = pl.id
-- WHERE p.id = :product_id
--   AND av.in_stock = 0
--   AND av.scraped_at = (
--       SELECT MAX(scraped_at) FROM availability_snapshots WHERE listing_id = pl.id
--   );