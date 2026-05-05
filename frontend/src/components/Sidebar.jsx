import './Sidebar.css'

const PLATFORM_COLORS = {
  blinkit:   'var(--blinkit)',
  zepto:     'var(--zepto)',
  instamart: 'var(--instamart)',
}

function PlatformDots({ platforms }) {
  const list = platforms ? platforms.split(',') : []
  return (
    <span className="platform-dots">
      {['blinkit', 'zepto', 'instamart'].map(p => (
        <span
          key={p}
          className="pdot"
          style={{ background: list.includes(p) ? PLATFORM_COLORS[p] : 'var(--border-2)' }}
          title={p}
        />
      ))}
    </span>
  )
}

export default function Sidebar({ products, selectedId, onSelect, loading }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-label">Products</span>
        <span className="sidebar-count">{products.length}</span>
      </div>

      <div className="sidebar-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: 'var(--blinkit)' }} />Blinkit
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: 'var(--zepto)' }} />Zepto
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: 'var(--instamart)' }} />Instamart
        </span>
      </div>

      <nav className="sidebar-list">
        {loading && (
          Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton-item" />
          ))
        )}

        {products.map(p => (
          <button
            key={p.id}
            className={`sidebar-item ${p.id === selectedId ? 'active' : ''}`}
            onClick={() => onSelect(p.id)}
          >
            <div className="item-top">
              <span className="item-name">{p.canonical_name}</span>
            </div>
            <div className="item-bottom">
              <span className="item-weight">
                {p.weight_g >= 1000
                  ? `${(p.weight_g / 1000).toFixed(1)}kg`
                  : `${p.weight_g}g`}
                {p.pack_size > 1 && ` × ${p.pack_size}`}
              </span>
              <PlatformDots platforms={p.platforms} />
            </div>
          </button>
        ))}
      </nav>
    </aside>
  )
}
