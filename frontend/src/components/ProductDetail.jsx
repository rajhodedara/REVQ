import { useState, useEffect } from 'react'
import PriceTable from './PriceTable.jsx'
import AvailabilityGrid from './AvailabilityGrid.jsx'
import './ProductDetail.css'

export default function ProductDetail({ productId, api }) {
  const [product, setProduct]   = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)

    fetch(`${api}/api/products/${productId}`)
      .then(r => r.json())
      .then(data => {
        setProduct(data)
        setLoading(false)
      })
      .catch(() => {
        setError('Failed to load product data.')
        setLoading(false)
      })
  }, [productId, api])

  if (loading) return (
    <div className="detail-loading">
      <div className="loading-bar" />
      <div className="loading-label">Loading product data...</div>
    </div>
  )

  if (error) return <div className="detail-error">{error}</div>
  if (!product) return null

  // Find the cheapest platform right now
  const cheapest = product.platforms.reduce((best, p) => {
    if (!p.price) return best
    if (!best || p.price.selling_price < best.price.selling_price) return p
    return best
  }, null)

  // Total pincodes in stock across all platforms (union, not sum)
  const allPincodes = new Set(
    product.platforms.flatMap(p =>
      (p.availability?.pincodes || [])
        .filter(a => a.in_stock)
        .map(a => a.pincode)
    )
  )

  return (
    <div className="detail">
      {/* Header */}
      <div className="detail-header">
        <div className="detail-hero">
          {product.image_url
            ? <img src={product.image_url} alt={product.canonical_name} className="detail-img" onError={e => e.target.style.display='none'} />
            : <div className="detail-img-placeholder">YB</div>
          }
          <div className="detail-info">
            <div className="detail-brand">{product.brand}</div>
            <h1 className="detail-name">{product.canonical_name}</h1>
            <div className="detail-tags">
              <span className="tag">
                {product.weight_g >= 1000
                  ? `${(product.weight_g / 1000).toFixed(1)} kg`
                  : `${product.weight_g} g`}
              </span>
              {product.pack_size > 1 && (
                <span className="tag">Pack of {product.pack_size}</span>
              )}
              {product.category && (
                <span className="tag">{product.category.split('>').pop().trim()}</span>
              )}
            </div>
          </div>
        </div>

        {/* KPI strip */}
        <div className="kpi-strip">
          <div className="kpi">
            <div className="kpi-label">Platforms</div>
            <div className="kpi-value">{product.platforms.length}</div>
          </div>
          <div className="kpi-divider" />
          <div className="kpi">
            <div className="kpi-label">Best Price</div>
            <div className="kpi-value accent">
              {cheapest?.price ? `₹${cheapest.price.selling_price}` : '—'}
            </div>
            {cheapest && (
              <div className="kpi-sub">on {cheapest.platform}</div>
            )}
          </div>
          <div className="kpi-divider" />
          <div className="kpi">
            <div className="kpi-label">Max Discount</div>
            <div className="kpi-value">
              {cheapest?.price ? `${cheapest.price.discount_pct}%` : '—'}
            </div>
          </div>
          <div className="kpi-divider" />
          <div className="kpi">
            <div className="kpi-label">Pincodes Live</div>
            <div className="kpi-value">{allPincodes.size}</div>
          </div>
        </div>
      </div>

      {/* Price comparison */}
      <section className="section">
        <div className="section-header">
          <span className="section-title">Price Comparison</span>
          <span className="section-sub">Latest snapshot per platform</span>
        </div>
        <PriceTable platforms={product.platforms} />
      </section>

      {/* Availability */}
      <section className="section">
        <div className="section-header">
          <span className="section-title">Availability by Pincode</span>
          <span className="section-sub">Current stock status</span>
        </div>
        <AvailabilityGrid platforms={product.platforms} />
      </section>

      {/* Scrape freshness */}
      <section className="section">
        <div className="section-header">
          <span className="section-title">Data Freshness</span>
        </div>
        <div className="freshness-row">
          {product.platforms.map(p => {
            const ts = p.price?.scraped_at
            const date = ts ? new Date(ts) : null
            const now = new Date()
            const hoursAgo = date ? Math.round((now - date) / 36e5) : null
            const stale = hoursAgo !== null && hoursAgo > 24

            return (
              <div key={p.platform} className={`freshness-card ${stale ? 'stale' : ''}`}>
                <div className="freshness-platform" data-platform={p.platform}>
                  {p.platform}
                </div>
                <div className="freshness-time">
                  {date ? date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'}
                </div>
                {stale && <div className="stale-badge">Stale</div>}
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}
