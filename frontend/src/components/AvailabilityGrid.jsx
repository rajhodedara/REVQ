import './AvailabilityGrid.css'

const PLATFORM_META = {
  blinkit:   { label: 'Blinkit',   color: 'var(--blinkit)' },
  zepto:     { label: 'Zepto',     color: 'var(--zepto)' },
  instamart: { label: 'Instamart', color: 'var(--instamart)' },
}

export default function AvailabilityGrid({ platforms }) {
  if (!platforms?.length) return null

  // Collect all unique pincodes across all platforms
  const allPincodes = [...new Set(
    platforms.flatMap(p => (p.availability?.pincodes || []).map(a => a.pincode))
  )].sort()

  // Build a lookup: platform → pincode → {in_stock, available_qty}
  const lookup = {}
  for (const p of platforms) {
    lookup[p.platform] = {}
    for (const a of (p.availability?.pincodes || [])) {
      lookup[p.platform][a.pincode] = a
    }
  }

  return (
    <div className="avail-wrapper">
      {/* Summary cards */}
      <div className="avail-summary">
        {platforms.map(p => {
          const avail = p.availability
          if (!avail) return null
          const meta = PLATFORM_META[p.platform] || {}
          const pct = avail.total_count
            ? Math.round((avail.in_stock_count / avail.total_count) * 100)
            : 0

          return (
            <div key={p.platform} className="avail-card">
              <div className="avail-card-platform" style={{ color: meta.color }}>
                {meta.label}
              </div>
              <div className="avail-bar-wrap">
                <div
                  className="avail-bar-fill"
                  style={{ width: `${pct}%`, background: meta.color }}
                />
              </div>
              <div className="avail-card-stat">
                <span className="avail-big" style={{ color: meta.color }}>
                  {avail.in_stock_count}
                </span>
                <span className="avail-denom">/ {avail.total_count} pincodes</span>
              </div>
              {avail.in_stock_count < avail.total_count && (
                <div className="avail-oos-note">
                  {avail.total_count - avail.in_stock_count} OOS
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Pincode grid */}
      {allPincodes.length > 0 && (
        <div className="pincode-table">
          {/* Header */}
          <div className="pin-header">
            <div className="pin-cell-code">Pincode</div>
            {platforms.map(p => (
              <div key={p.platform} className="pin-cell" style={{ color: PLATFORM_META[p.platform]?.color }}>
                {PLATFORM_META[p.platform]?.label}
              </div>
            ))}
          </div>

          {/* Rows */}
          {allPincodes.map(pin => (
            <div key={pin} className="pin-row">
              <div className="pin-cell-code mono">{pin}</div>
              {platforms.map(p => {
                const entry = lookup[p.platform]?.[pin]
                if (!entry) return (
                  <div key={p.platform} className="pin-cell">
                    <span className="pin-status na">—</span>
                  </div>
                )
                return (
                  <div key={p.platform} className="pin-cell">
                    {entry.in_stock ? (
                      <span className="pin-status in-stock">
                        ✓
                        {entry.available_qty != null && (
                          <span className="pin-qty">{entry.available_qty}</span>
                        )}
                      </span>
                    ) : (
                      <span className="pin-status oos">OOS</span>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
