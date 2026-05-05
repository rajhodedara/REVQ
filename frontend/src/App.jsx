import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ProductDetail from './components/ProductDetail.jsx'
import './App.css'

const API = 'http://localhost:5000'

export default function App() {
  const [products, setProducts]       = useState([])
  const [selectedId, setSelectedId]   = useState(null)
  const [loading, setLoading]         = useState(true)

  useEffect(() => {
    fetch(`${API}/api/products`)
      .then(r => r.json())
      .then(data => {
        setProducts(data)
        if (data.length > 0) setSelectedId(data[0].id)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  return (
    <div className="layout">
      {/* Top bar */}
      <header className="topbar">
        <div className="topbar-brand">
          <span className="brand-dot" />
          RevQ
          <span className="brand-tag">Quick Commerce Intelligence</span>
        </div>
        <div className="topbar-meta">
          <span className="meta-pill">Yogabar</span>
          <span className="meta-pill accent">{products.length} SKUs tracked</span>
        </div>
      </header>

      <div className="body">
        <Sidebar
          products={products}
          selectedId={selectedId}
          onSelect={setSelectedId}
          loading={loading}
        />
        <main className="main">
          {selectedId
            ? <ProductDetail key={selectedId} productId={selectedId} api={API} />
            : <div className="empty-state">Select a product</div>
          }
        </main>
      </div>
    </div>
  )
}
