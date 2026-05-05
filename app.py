"""
RevQ API
Run: python api/app.py
Base URL: http://localhost:5000

Endpoints:
  GET /api/products              → list all canonical products
  GET /api/products/<id>         → full detail for one product
  GET /api/products/<id>/history → 30-day price history (all platforms)
"""

import sqlite3
from flask import Flask, jsonify, g
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # allow React dev server (localhost:5173) to call this

DB_PATH = 'revq.db'


# ---------------------------------------------------------------------------
# DB connection — one per request, closed after
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        g.db = con
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/products
# Returns the list of all canonical products for the sidebar/home page.
# Includes how many platforms carry it and the best available image.
# ---------------------------------------------------------------------------

@app.route('/api/products')
def list_products():
    db = get_db()

    rows = db.execute("""
        SELECT
            p.id,
            p.canonical_name,
            p.brand,
            p.weight_g,
            p.pack_size,
            p.category,
            COUNT(DISTINCT pl.platform)  AS platform_count,
            GROUP_CONCAT(DISTINCT pl.platform) AS platforms,
            -- pick first non-null image across listings
            MAX(pl.image_url)            AS image_url
        FROM products p
        JOIN platform_listings pl ON pl.product_id = p.id
        GROUP BY p.id
        ORDER BY p.canonical_name
    """).fetchall()

    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/products/<id>
# Full product detail: metadata + per-platform price + availability breakdown.
# This is what the product detail page renders.
# ---------------------------------------------------------------------------

@app.route('/api/products/<int:product_id>')
def get_product(product_id):
    db = get_db()

    # 1. Canonical product
    product = db.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()

    if not product:
        return jsonify({'error': 'Product not found'}), 404

    product = dict(product)

    # 2. Per-platform data
    listings = db.execute(
        "SELECT * FROM platform_listings WHERE product_id = ? ORDER BY platform",
        (product_id,)
    ).fetchall()

    platforms = []
    for listing in listings:
        listing = dict(listing)

        # Latest price snapshot
        price = db.execute("""
            SELECT mrp, selling_price, discount_pct, scraped_at
            FROM price_snapshots
            WHERE listing_id = ?
            ORDER BY scraped_at DESC
            LIMIT 1
        """, (listing['id'],)).fetchone()

        # Latest availability per pincode
        availability = db.execute("""
            SELECT pincode, in_stock, available_qty
            FROM availability_snapshots
            WHERE listing_id = ?
              AND scraped_at = (
                  SELECT MAX(scraped_at)
                  FROM availability_snapshots
                  WHERE listing_id = ?
              )
            ORDER BY pincode
        """, (listing['id'], listing['id'])).fetchall()

        availability = [dict(a) for a in availability]
        in_stock_count = sum(1 for a in availability if a['in_stock'])

        platforms.append({
            'platform':            listing['platform'],
            'platform_product_id': listing['platform_product_id'],
            'platform_name':       listing['platform_name'],
            'image_url':           listing['image_url'],
            'price': dict(price) if price else None,
            'availability': {
                'pincodes':       availability,
                'in_stock_count': in_stock_count,
                'total_count':    len(availability),
            }
        })

    product['platforms'] = platforms

    # Best image = first non-null across platforms
    product['image_url'] = next(
        (p['image_url'] for p in platforms if p['image_url']), None
    )

    return jsonify(product)


# ---------------------------------------------------------------------------
# GET /api/products/<id>/history
# 30-day price history per platform — for the price trend chart.
# ---------------------------------------------------------------------------

@app.route('/api/products/<int:product_id>/history')
def get_price_history(product_id):
    db = get_db()

    product = db.execute(
        "SELECT id, canonical_name FROM products WHERE id = ?", (product_id,)
    ).fetchone()

    if not product:
        return jsonify({'error': 'Product not found'}), 404

    rows = db.execute("""
        SELECT
            pl.platform,
            ps.scraped_at,
            ps.mrp,
            ps.selling_price,
            ps.discount_pct
        FROM platform_listings pl
        JOIN price_snapshots ps ON ps.listing_id = pl.id
        WHERE pl.product_id = ?
          AND ps.scraped_at >= datetime('now', '-30 days')
        ORDER BY pl.platform, ps.scraped_at ASC
    """, (product_id,)).fetchall()

    # Group by platform
    history = {}
    for row in rows:
        platform = row['platform']
        if platform not in history:
            history[platform] = []
        history[platform].append({
            'scraped_at':    row['scraped_at'],
            'mrp':           row['mrp'],
            'selling_price': row['selling_price'],
            'discount_pct':  row['discount_pct'],
        })

    return jsonify({
        'product_id':   product['id'],
        'product_name': product['canonical_name'],
        'history':      history,
    })


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("RevQ API running at http://localhost:5000")
    print("Endpoints:")
    print("  GET /api/products")
    print("  GET /api/products/<id>")
    print("  GET /api/products/<id>/history")
    app.run(debug=True, port=5000)