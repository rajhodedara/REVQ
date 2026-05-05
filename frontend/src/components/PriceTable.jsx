import './PriceTable.css'

const PLATFORM_META = {
  blinkit:   { label: 'Blinkit',   color: 'var(--blinkit)',   dim: 'var(--blinkit-dim)' },
  zepto:     { label: 'Zepto',     color: 'var(--zepto)',     dim: 'var(--zepto-dim)' },
  instamart: { label: 'Instamart', color: 'var(--instamart)', dim: 'var(--instamart-dim)' },
}

export default function PriceTable({ platforms }) {
  if (!platforms?.length) return null

  const withPrice = platforms.filter(p => p.price)

  // Find cheapest selling price
  const minPrice = Math.min(...withPrice.map(p => p.price.selling_price))

  return (
    <div className="price-table">
      {/* Header row */}
      <div className="pt-header">
        <div className="pt-cell-platform">Platform</div>
        <div className="pt-cell">MRP</div>
        <div className="pt-cell">Price</div>
        <div className="pt-cell">Discount</div>
        <div className="pt-cell">Savings</div>
        <div className="pt-cell">Status</div>
      </div>

      {/* Platform rows */}
      {platforms.map(p => {
        const meta    = PLATFORM_META[p.platform] || {}
        const price   = p.price
        const isBest  = price && price.selling_price === minPrice && withPrice.length > 1
        const savings = price ? price.mrp - price.selling_price : 0

        return (
          <div
            key={p.platform}
            className={`pt-row ${isBest ? 'best' : ''}`}
            style={isBest ? { '--row-color': meta.color, '--row-dim': meta.dim } : {}}
          >
            <div className="pt-cell-platform">
              <span className="platform-badge" style={{ color: meta.color, '--c': meta.color }}>
                <span className="platform-indicator" style={{ background: meta.color }} />
                {meta.label}
              </span>
              {isBest && <span className="best-badge">Best Price</span>}
            </div>

            <div className="pt-cell mono muted">
              {price ? `₹${price.mrp}` : '—'}
            </div>
            <div className={`pt-cell mono ${isBest ? 'accent-text' : ''}`} style={{ fontWeight: 600 }}>
              {price ? `₹${price.selling_price}` : '—'}
            </div>
            <div className="pt-cell mono">
              {price ? (
                <span className="discount-pill">
                  {price.discount_pct}% off
                </span>
              ) : '—'}
            </div>
            <div className="pt-cell mono muted">
              {price && savings > 0 ? `₹${savings} saved` : '—'}
            </div>
            <div className="pt-cell">
              {price ? (
                <span className="status-dot active" title="Listing active" />
              ) : (
                <span className="status-dot inactive" title="Not listed" />
              )}
            </div>
          </div>
        )
      })}

      {/* No listing placeholder for missing platforms */}
      {['blinkit', 'zepto', 'instamart'].filter(name =>
        !platforms.find(p => p.platform === name)
      ).map(name => {
        const meta = PLATFORM_META[name]
        return (
          <div key={name} className="pt-row not-listed">
            <div className="pt-cell-platform">
              <span className="platform-badge" style={{ color: meta.color }}>
                <span className="platform-indicator" style={{ background: meta.color, opacity: 0.3 }} />
                {meta.label}
              </span>
            </div>
            <div className="pt-cell mono muted">—</div>
            <div className="pt-cell mono muted">—</div>
            <div className="pt-cell mono muted">—</div>
            <div className="pt-cell mono muted">—</div>
            <div className="pt-cell">
              <span className="not-listed-label">Not listed</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
