const HKT_OFFSET_MINUTES = 8 * 60

/** Format a directory rebuild timestamp as a Hong Kong date and time. */
export function formatRebuiltAt(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(iso.trim())
  if (!match) return iso
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const hour = Number(match[4])
  const minute = Number(match[5])
  const second = Number(match[6])
  const zone = match[7]
  let offsetMinutes = 0
  if (zone !== "Z") {
    const sign = zone.startsWith("-") ? -1 : 1
    offsetMinutes = sign * (Number(zone.slice(1, 3)) * 60 + Number(zone.slice(4, 6)))
  }
  const utcMs = Date.UTC(year, month - 1, day, hour, minute, second) - offsetMinutes * 60_000
  const hkt = new Date(utcMs + HKT_OFFSET_MINUTES * 60_000)
  const hours = String(hkt.getUTCHours()).padStart(2, "0")
  const minutes = String(hkt.getUTCMinutes()).padStart(2, "0")
  return `${hkt.getUTCFullYear()}年${hkt.getUTCMonth() + 1}月${hkt.getUTCDate()}日 ${hours}:${minutes}（香港時間）`
}
