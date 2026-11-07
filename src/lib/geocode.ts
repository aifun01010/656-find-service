export type GeocodeHit = {
  lat: number
  lng: number
  label: string
}

const memory = new Map<string, GeocodeHit | null>()

function inHongKong(lat: number, lng: number): boolean {
  return lat >= 22.08 && lat <= 22.62 && lng >= 113.75 && lng <= 114.55
}

/** Browser fetches cannot set User-Agent. Nominatim still receives the browser UA; results are cached in memory. */
export async function geocodePlace(query: string): Promise<GeocodeHit | null> {
  const key = query.trim()
  if (!key) return null
  if (memory.has(key)) return memory.get(key) ?? null
  const url = new URL("https://nominatim.openstreetmap.org/search")
  url.searchParams.set("format", "jsonv2")
  url.searchParams.set("limit", "1")
  url.searchParams.set("viewbox", "113.80,22.60,114.50,22.10")
  url.searchParams.set("bounded", "1")
  url.searchParams.set("accept-language", "zh-HK")
  url.searchParams.set("q", key)
  try {
    const response = await fetch(url.toString(), { headers: { "Accept-Language": "zh-HK" } })
    if (!response.ok) {
      memory.set(key, null)
      return null
    }
    const data: unknown = await response.json()
    if (!Array.isArray(data) || data.length === 0) {
      memory.set(key, null)
      return null
    }
    const first = data[0] as { lat?: string; lon?: string; display_name?: string }
    const lat = Number(first.lat)
    const lng = Number(first.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || !inHongKong(lat, lng)) {
      memory.set(key, null)
      return null
    }
    const hit = { lat, lng, label: first.display_name ?? key }
    memory.set(key, hit)
    return hit
  } catch {
    memory.set(key, null)
    return null
  }
}
