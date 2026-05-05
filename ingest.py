"""
RevQ Ingestion Script
Usage: python ingest.py <path-to-json> [db-path]

Supports: blinkit_sample.json, zepto_sample.json, instamart_sample.json
Creates:  revq.db (SQLite) in the current directory, applying schema if needed.
Run with any of the three files in any order — cross-platform identity matching
is handled automatically.
"""

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema (mirrors schema.sql)
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    brand           TEXT     NOT NULL,
    canonical_name  TEXT     NOT NULL,
    variant_slug    TEXT     NOT NULL,
    weight_g        INTEGER  NOT NULL,
    pack_size       INTEGER  NOT NULL DEFAULT 1,
    category        TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(brand, variant_slug, weight_g, pack_size)
);

CREATE TABLE IF NOT EXISTS platform_listings (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER  NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    platform            TEXT     NOT NULL CHECK(platform IN ('blinkit', 'zepto', 'instamart')),
    platform_product_id TEXT     NOT NULL,
    platform_name       TEXT     NOT NULL,
    image_url           TEXT,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform, platform_product_id)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    listing_id      INTEGER  NOT NULL REFERENCES platform_listings(id) ON DELETE CASCADE,
    scraped_at      DATETIME NOT NULL,
    mrp             INTEGER  NOT NULL,
    selling_price   INTEGER  NOT NULL,
    discount_pct    REAL,
    UNIQUE(listing_id, scraped_at)
);

CREATE TABLE IF NOT EXISTS availability_snapshots (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    listing_id      INTEGER  NOT NULL REFERENCES platform_listings(id) ON DELETE CASCADE,
    scraped_at      DATETIME NOT NULL,
    pincode         TEXT     NOT NULL,
    in_stock        INTEGER  NOT NULL CHECK(in_stock IN (0, 1)),
    available_qty   INTEGER,
    UNIQUE(listing_id, scraped_at, pincode)
);

CREATE INDEX IF NOT EXISTS idx_price_listing_time  ON price_snapshots(listing_id, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_scraped_at    ON price_snapshots(scraped_at);
CREATE INDEX IF NOT EXISTS idx_avail_listing_time  ON availability_snapshots(listing_id, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_avail_pincode       ON availability_snapshots(pincode);
"""


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Abbreviations to expand before slugging.
# Zepto is the main offender: "CHOC" for "CHOCOLATE".
_ABBREVS = {
    'choc':  'chocolate',
    'pb':    'peanutbutter',
    'alm':   'almond',
    'cran':  'cranberry',
}

# Words to strip when building a variant_slug.
# Keep anything that DISTINGUISHES one variant from another.
# NOTE: "peanut" and "butter" are intentionally KEPT — they distinguish
# "Peanut Butter Chocolate" bar from "Chocolate Chunk & Nuts" bar.
_STRIP_WORDS = {
    "yogabar", "bar", "bars", "protein", "energy", "multigrain", "multi",
    "grain", "wholegrain", "natural", "breakfast", "cereal",
    "pack", "of", "and", "the", "with", "mixed",
    "x", "g", "gm", "gms", "kg", "ml",
}

# Pre-compiled regex patterns
_PAREN_RE       = re.compile(r'\(.*?\)')
_PIPE_RE        = re.compile(r'\|')
_NON_ALPHA_RE   = re.compile(r'[^a-z0-9\s]')

# Quantity patterns — stripped before tokenising
# "Ng x M"  e.g. "38g x 6"  → weight_per_unit=38, pack=6
_UNIT_X_PACK_RE = re.compile(r'\d+\s*(?:g|gm)\s*x\s*\d+', re.IGNORECASE)
# "M x Ng"  e.g. "6x60g", "6X60GM"  → pack=6, weight_per_unit=60
_PACK_X_UNIT_RE = re.compile(r'\d+\s*x\s*\d+\s*(?:g|gm)', re.IGNORECASE)
# "pack of N"
_PACK_OF_RE     = re.compile(r'pack\s+of\s+\d+', re.IGNORECASE)
# "N bars mixed"
_N_BARS_RE      = re.compile(r'\d+\s*bars?(?:\s+mixed)?', re.IGNORECASE)
# Plain weight: "400g", "400GM", "1kg", "1KG"
_PLAIN_WEIGHT_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:g|gm|gms|kg)', re.IGNORECASE)

# For actual weight value extraction
_WEIGHT_VAL_RE  = re.compile(r'(\d+(?:\.\d+)?)\s*(g|gm|gms|kg)', re.IGNORECASE)
# For pack count in "pack of N" / "N bars"
_PACK_OF_VAL_RE = re.compile(r'pack\s+of\s+(\d+)', re.IGNORECASE)
_N_BARS_VAL_RE  = re.compile(r'(\d+)\s*bars?(?:\s+mixed)?', re.IGNORECASE)
_UNIT_X_PACK_VAL_RE = re.compile(r'(\d+)\s*(?:g|gm)\s*x\s*(\d+)', re.IGNORECASE)
_PACK_X_UNIT_VAL_RE = re.compile(r'(\d+)\s*x\s*(\d+)\s*(?:g|gm)', re.IGNORECASE)


def parse_weight_and_pack(name: str, weight_field=None, weight_unit_field=None) -> tuple[int, int]:
    """
    Returns (total_weight_g, pack_size).

    Priority:
      1. Explicit weight/unit fields (Instamart)
      2. "Ng x M" pattern  — unit weight × count  (Blinkit energy bars: "38g x 6")
      3. "M x Ng" pattern  — count × unit weight  (Zepto: "6X60GM")
      4. "pack of N" + last plain weight
      5. Last plain weight + pack_size=1
    """
    # 1. Instamart explicit fields
    if weight_field is not None and weight_unit_field is not None:
        try:
            w    = float(weight_field)
            unit = weight_unit_field.lower().strip()
            if unit == 'kg':
                w *= 1000
            pack = _extract_pack_count(name)
            return int(w), pack
        except (ValueError, TypeError):
            pass

    # 2. "Ng x M"  e.g. "38g x 6"
    m = _UNIT_X_PACK_VAL_RE.search(name)
    if m:
        unit_w = int(float(m.group(1)))
        pack   = int(m.group(2))
        return unit_w * pack, pack

    # 3. "M x Ng"  e.g. "6x60g", "6X60GM"
    m = _PACK_X_UNIT_VAL_RE.search(name)
    if m:
        pack   = int(m.group(1))
        unit_w = int(float(m.group(2)))
        return unit_w * pack, pack

    # 4 & 5. Plain weight + separate pack count
    pack     = _extract_pack_count(name)
    weight_g = _extract_plain_weight(name)
    return weight_g, pack


def _extract_pack_count(name: str) -> int:
    m = _PACK_OF_VAL_RE.search(name)
    if m:
        return int(m.group(1))
    m = _N_BARS_VAL_RE.search(name)
    if m:
        return int(m.group(1))
    return 1


def _extract_plain_weight(name: str) -> int:
    matches = _WEIGHT_VAL_RE.findall(name)
    if not matches:
        return 0
    val, unit = matches[-1]
    val = float(val)
    return int(val * 1000) if unit.lower() == 'kg' else int(val)


def make_variant_slug(name: str) -> str:
    """
    Normalised keyword slug for cross-platform identity matching.

    Pipeline:
      1. Lowercase + split on |
      2. Remove parenthetical notes
      3. Strip quantity patterns (Ng x M, M x Ng, pack of N, weights)
      4. Remove non-alphanumeric chars
      5. Expand abbreviations (choc → chocolate)
      6. Remove stop-words
      7. Sort + deduplicate tokens
      8. Join with '-'

    Examples:
      "Yogabar Chocolate Chunk & Nuts Protein Bar (60 g)"  → "chocolate-chunk-nuts"
      "YOGABAR CHOCOLATE CHUNK NUTS PROTEIN BAR 60GM"      → "chocolate-chunk-nuts"
      "Yogabar Protein Bar | Chocolate Chunk & Nuts | 60g" → "chocolate-chunk-nuts"
      "Yogabar Peanut Butter Chocolate Protein Bar (60 g)" → "butter-chocolate-peanut"
      "YOGABAR PEANUT BUTTER CHOC PROTEIN BAR 60GM"        → "butter-chocolate-peanut"
    """
    text = name.lower()
    text = _PIPE_RE.sub(' ', text)
    text = _PAREN_RE.sub(' ', text)

    # Strip quantity patterns (order: compound first, then simple)
    text = _UNIT_X_PACK_RE.sub(' ', text)
    text = _PACK_X_UNIT_RE.sub(' ', text)
    text = _PACK_OF_RE.sub(' ', text)
    text = _N_BARS_RE.sub(' ', text)
    text = _PLAIN_WEIGHT_RE.sub(' ', text)

    text = _NON_ALPHA_RE.sub(' ', text)

    tokens = text.split()
    tokens = [_ABBREVS.get(t, t) for t in tokens]           # expand abbreviations
    tokens = [t for t in tokens if t not in _STRIP_WORDS and len(t) > 1]
    tokens = sorted(set(tokens))

    return '-'.join(tokens) if tokens else name.lower().replace(' ', '-')


def compute_discount(mrp: int, selling_price: int) -> float:
    if mrp and mrp > 0:
        return round((mrp - selling_price) / mrp * 100, 2)
    return 0.0


# ---------------------------------------------------------------------------
# Platform-specific parsers
# ---------------------------------------------------------------------------

def parse_blinkit(raw: dict) -> tuple[str, str, list[dict]]:
    platform   = raw['platform']
    scraped_at = raw['scraped_at']
    brand      = raw.get('brand', 'Unknown')
    products   = []

    for p in raw['products']:
        name           = p['name']
        weight_g, pack = parse_weight_and_pack(name)
        mrp            = p['mrp']
        sell_price     = p['selling_price']

        products.append({
            'platform_product_id': p['blinkit_id'],
            'platform_name':       name,
            'brand':               brand,
            'category':            p.get('category'),
            'image_url':           p.get('image_url'),
            'mrp':                 mrp,
            'selling_price':       sell_price,
            'discount_pct':        compute_discount(mrp, sell_price),
            'weight_g':            weight_g,
            'pack_size':           pack,
            'variant_slug':        make_variant_slug(name),
            'availability': [
                {'pincode': str(a['pincode']), 'in_stock': 1 if a['in_stock'] else 0, 'available_qty': None}
                for a in p.get('availability', [])
            ],
        })

    return platform, scraped_at, products


def parse_zepto(raw: dict) -> tuple[str, str, list[dict]]:
    platform   = 'zepto'
    scraped_at = raw['fetched_on'] + 'T00:00:00Z'
    products   = []

    for p in raw['items']:
        name           = p['title']
        weight_g, pack = parse_weight_and_pack(name)
        mrp            = p['price']['mrp']
        sell_price     = p['price']['final']

        products.append({
            'platform_product_id': p['sku_code'],
            'platform_name':       name,
            'brand':               'Yogabar',
            'category':            ' > '.join(p.get('category_path', [])) or None,
            'image_url':           p.get('image'),
            'mrp':                 mrp,
            'selling_price':       sell_price,
            'discount_pct':        compute_discount(mrp, sell_price),
            'weight_g':            weight_g,
            'pack_size':           pack,
            'variant_slug':        make_variant_slug(name),
            'availability': [
                {'pincode': str(pin), 'in_stock': 1 if status == 'available' else 0, 'available_qty': None}
                for pin, status in p.get('stock_by_pincode', {}).items()
            ],
        })

    return platform, scraped_at, products


def parse_instamart(raw: dict) -> tuple[str, str, list[dict]]:
    platform   = 'instamart'
    scraped_at = datetime.fromtimestamp(int(raw['snapshot_time']), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    products   = []

    for p in raw['results']:
        name           = p['display_name']
        weight_g, pack = parse_weight_and_pack(name, p.get('weight'), p.get('weight_unit'))
        mrp            = p['store_mrp']
        sell_price     = p['store_selling_price']

        products.append({
            'platform_product_id': p['product_id'],
            'platform_name':       name,
            'brand':               'Yogabar',
            'category':            None,
            'image_url':           p.get('image'),
            'mrp':                 mrp,
            'selling_price':       sell_price,
            'discount_pct':        compute_discount(mrp, sell_price),
            'weight_g':            weight_g,
            'pack_size':           pack,
            'variant_slug':        make_variant_slug(name),
            'availability': [
                {'pincode': str(a['pin']), 'in_stock': 1 if a.get('available_qty', 0) > 0 else 0, 'available_qty': a.get('available_qty')}
                for a in p.get('store_availability', [])
            ],
        })

    return platform, scraped_at, products


def detect_and_parse(raw: dict) -> tuple[str, str, list[dict]]:
    if raw.get('platform') == 'blinkit':
        return parse_blinkit(raw)
    elif 'zepto' in raw.get('source', '').lower():
        return parse_zepto(raw)
    elif 'snapshot_time' in raw:
        return parse_instamart(raw)
    raise ValueError("Unrecognised JSON format — cannot detect platform.")


# ---------------------------------------------------------------------------
# Database writes
# ---------------------------------------------------------------------------

def upsert_product(cur: sqlite3.Cursor, p: dict) -> int:
    cur.execute("""
        INSERT INTO products (brand, canonical_name, variant_slug, weight_g, pack_size, category)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(brand, variant_slug, weight_g, pack_size) DO NOTHING
    """, (p['brand'], p['platform_name'], p['variant_slug'], p['weight_g'], p['pack_size'], p['category']))

    return cur.execute("""
        SELECT id FROM products WHERE brand=? AND variant_slug=? AND weight_g=? AND pack_size=?
    """, (p['brand'], p['variant_slug'], p['weight_g'], p['pack_size'])).fetchone()[0]


def upsert_listing(cur: sqlite3.Cursor, product_id: int, platform: str, p: dict) -> int:
    cur.execute("""
        INSERT INTO platform_listings (product_id, platform, platform_product_id, platform_name, image_url)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_product_id) DO UPDATE
            SET image_url = COALESCE(excluded.image_url, platform_listings.image_url)
    """, (product_id, platform, p['platform_product_id'], p['platform_name'], p['image_url']))

    return cur.execute("""
        SELECT id FROM platform_listings WHERE platform=? AND platform_product_id=?
    """, (platform, p['platform_product_id'])).fetchone()[0]


def insert_price_snapshot(cur: sqlite3.Cursor, listing_id: int, scraped_at: str, p: dict):
    cur.execute("""
        INSERT OR IGNORE INTO price_snapshots (listing_id, scraped_at, mrp, selling_price, discount_pct)
        VALUES (?, ?, ?, ?, ?)
    """, (listing_id, scraped_at, p['mrp'], p['selling_price'], p['discount_pct']))


def insert_availability(cur: sqlite3.Cursor, listing_id: int, scraped_at: str, availability: list):
    cur.executemany("""
        INSERT OR IGNORE INTO availability_snapshots (listing_id, scraped_at, pincode, in_stock, available_qty)
        VALUES (?, ?, ?, ?, ?)
    """, [(listing_id, scraped_at, a['pincode'], a['in_stock'], a['available_qty']) for a in availability])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ingest(json_path: str, db_path: str = 'revq.db'):
    path = Path(json_path)
    if not path.exists():
        print(f"ERROR: File not found: {json_path}")
        sys.exit(1)

    print(f"Loading {path.name}...")
    with open(path) as f:
        raw = json.load(f)

    platform, scraped_at, products = detect_and_parse(raw)
    print(f"Platform : {platform}")
    print(f"Scraped  : {scraped_at}")
    print(f"Products : {len(products)}")
    print()

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)

    stats = {'new': 0, 'matched': 0, 'skipped': 0, 'avail_rows': 0}

    with con:
        cur = con.cursor()
        for p in products:
            if p['weight_g'] == 0:
                print(f"  SKIP   {p['platform_name'][:60]} — could not parse weight")
                stats['skipped'] += 1
                continue

            existing = cur.execute("""
                SELECT id FROM products WHERE brand=? AND variant_slug=? AND weight_g=? AND pack_size=?
            """, (p['brand'], p['variant_slug'], p['weight_g'], p['pack_size'])).fetchone()

            product_id = upsert_product(cur, p)
            listing_id = upsert_listing(cur, product_id, platform, p)
            insert_price_snapshot(cur, listing_id, scraped_at, p)
            insert_availability(cur, listing_id, scraped_at, p['availability'])

            status = 'MATCH' if existing else 'NEW  '
            if existing:
                stats['matched'] += 1
            else:
                stats['new'] += 1

            print(f"  {status}  {p['platform_name'][:58]}")
            print(f"         slug={p['variant_slug']} | {p['weight_g']}g ×{p['pack_size']}")
            stats['avail_rows'] += len(p['availability'])

    print()
    print(f"Done.")
    print(f"  New canonical products : {stats['new']}")
    print(f"  Matched existing       : {stats['matched']}")
    print(f"  Skipped (no weight)    : {stats['skipped']}")
    print(f"  Availability rows      : {stats['avail_rows']}")
    print(f"  Database               : {db_path}")
    con.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <path-to-json> [db-path]")
        print("  e.g. python ingest.py data/blinkit_sample.json")
        sys.exit(1)
    db = sys.argv[2] if len(sys.argv) > 2 else 'revq.db'
    ingest(sys.argv[1], db)
