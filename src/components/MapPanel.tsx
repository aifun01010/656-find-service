import { useEffect, useRef } from "react"
import L from "leaflet"

export type MapPoint = {
  id: string
  lat: number
  lng: number
  title: string
  detail: string
  kind: "user" | "unit"
}

type MapPanelProps = {
  points: MapPoint[]
  note: string
}

function spreadOverlaps(points: MapPoint[]): MapPoint[] {
  const placed: MapPoint[] = []
  for (const point of points) {
    let lat = point.lat
    let lng = point.lng
    let step = 0
    while (placed.some((other) => Math.abs(other.lat - lat) < 0.00018 && Math.abs(other.lng - lng) < 0.00018)) {
      step += 1
      const angle = step * 1.2
      lat = point.lat + Math.cos(angle) * 0.00028 * step
      lng = point.lng + Math.sin(angle) * 0.00028 * step
    }
    placed.push({ ...point, lat, lng })
  }
  return placed
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const map: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }
    return map[character] ?? character
  })
}

export function MapPanel({ points, note }: MapPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)

  useEffect(() => {
    const element = containerRef.current
    if (!element || mapRef.current) return
    const map = L.map(element, { scrollWheelZoom: false, zoomControl: true })
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> 貢獻者',
    }).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)
    map.setView([22.35, 114.15], 11)
    mapRef.current = map
    const timer = window.setTimeout(() => map.invalidateSize(), 180)
    return () => {
      window.clearTimeout(timer)
      map.remove()
      mapRef.current = null
      layerRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const layer = layerRef.current
    if (!map || !layer) return
    layer.clearLayers()
    const visible = spreadOverlaps(points)
    let unitIndex = 0
    for (const point of visible) {
      if (point.kind === "unit") unitIndex += 1
      const label = point.kind === "user" ? "住" : String(unitIndex)
      const icon = L.divIcon({
        className: "pin",
        html: `<span class="pin-dot ${point.kind}">${label}</span>`,
        iconSize: [30, 30],
        iconAnchor: [15, 15],
        popupAnchor: [0, -16],
      })
      L.marker([point.lat, point.lng], { icon, title: point.title })
        .bindPopup(`<strong>${escapeHtml(point.title)}</strong><br/>${escapeHtml(point.detail)}`)
        .addTo(layer)
    }
    if (visible.length === 1) {
      const only = visible[0]
      if (only) map.setView([only.lat, only.lng], 16)
    } else if (visible.length > 1) {
      map.fitBounds(L.latLngBounds(visible.map((point) => [point.lat, point.lng])), { padding: [32, 32], maxZoom: 16 })
    } else {
      map.setView([22.35, 114.15], 11)
    }
    map.invalidateSize()
  }, [points])

  return (
    <section className="map-panel" aria-label="地圖">
      <div className="map-head">
        <h2>地圖</h2>
        <p>{note}</p>
      </div>
      <div ref={containerRef} className="map-canvas" />
      <div className="legend">
        <span><i className="swatch user" />你輸入的地點</span>
        <span><i className="swatch unit" />聯絡單位</span>
      </div>
      <ul className="pin-list">
        {points.length === 0 ? <li>未有標記。搜尋後會顯示地點與單位。</li> : points.map((point) => (
          <li key={point.id}>
            <strong>{point.kind === "user" ? "地點" : "單位"} · {point.title}</strong>
            <span>{point.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
