import directoryJson from "../data/directory.json" with { type: "json" }
import type { Directory, Living, Mode, Place, SearchHit, SearchInput, SearchOutput, Unit, UnitType } from "./types"

export const directory = directoryJson as Directory

export const TYPE_LABEL: Record<UnitType, string> = {
  decc: "長者地區中心",
  nec: "長者鄰舍中心",
  mssu: "醫務社工單位",
  ifsc: "綜合家庭服務中心",
  hss: "家居支援服務隊",
}

const STOP = new Set(["中心", "服務", "香港", "九龍", "新界", "長者", "地區", "社區", "地下", "單位", "電話", "香港島", "聯絡"])

export function normalize(value: string): string {
  return value
    .toLowerCase()
    .replace(/臺/g, "台")
    .replace(/裡/g, "里")
    .replace(/峯/g, "峰")
    .replace(/\s+/g, "")
    .replace(/[()（）[\]【】／/・,，.。、;；:：'"'’\-—–]/g, "")
}

export function districtName(id: string): string {
  if (!id) return "未能判定地區"
  return directory.districts.find((item) => item.id === id)?.name ?? "未能判定地區"
}

function districtNames(): Set<string> {
  const names = new Set<string>()
  for (const district of directory.districts) {
    names.add(normalize(district.name))
    names.add(normalize(district.name.replace(/區$/, "")))
  }
  return names
}

const DISTRICT_QUERY = districtNames()

function allowed(unit: Unit, mode: Mode, living: Living | null): boolean {
  if (mode === "hss") return unit.type === "hss"
  if (living === "home") return unit.type === "decc" || unit.type === "nec"
  if (living === "hospital") return unit.type === "mssu"
  if (living === "rche") return unit.type === "ifsc"
  return false
}

export function scorePlace(place: Place, query: string): number {
  if (!query || DISTRICT_QUERY.has(query)) return 0
  const names = [place.name, ...place.aliases].map((item) => normalize(item)).filter(Boolean)
  let score = 0
  for (const name of names) {
    if (name === query) score = Math.max(score, 100 + name.length)
    else if (query.length >= 2 && name.includes(query)) score = Math.max(score, 70 + query.length)
    else if (name.length >= 3 && query.includes(name)) score = Math.max(score, 64 + name.length)
  }
  return score
}

export function suggestPlaces(rawQuery: string): Place[] {
  const query = normalize(rawQuery.trim())
  if (query.length < 1) return []
  return directory.places
    .map((place) => ({ place, score: scorePlace(place, query) }))
    .filter((item) => item.score >= 64)
    .sort((a, b) => b.score - a.score || Number(b.place.featured) - Number(a.place.featured) || b.place.name.length - a.place.name.length)
    .slice(0, 6)
    .map((item) => item.place)
}

function haystack(unit: Unit): string {
  return normalize([unit.name, unit.operator, unit.address, unit.serviceArea, unit.searchText, ...unit.keywords].join("\n"))
}

function scoreUnit(unit: Unit, probes: string[]): { score: number; keyword: string } {
  const hay = haystack(unit)
  const name = normalize(unit.name)
  let best = 0
  let keyword = ""
  const consider = (score: number, label: string) => {
    if (score > best) {
      best = score
      keyword = label
    }
  }
  for (const probe of probes) {
    if (!probe || probe.length < 2 || STOP.has(probe)) continue
    if (name === probe) consider(120, unit.name)
    else if (name.includes(probe)) consider(90 + Math.min(probe.length, 24), probe)
    else if (probe.includes(name) && name.length >= 4) consider(88, unit.name)
    if (hay.includes(probe)) consider(36 + Math.min(probe.length, 28), probe)
    for (const raw of unit.keywords) {
      const key = normalize(raw)
      if (!key || key.length < 2 || STOP.has(key)) continue
      if (probe.includes(key) && key.length >= 3) consider(50 + Math.min(key.length, 24), raw)
      else if (key.includes(probe) && probe.length >= 3 && key.length <= probe.length + 3) consider(44 + probe.length, raw)
    }
  }
  if (unit.name.includes("精神科")) best -= 4
  return { score: best, keyword }
}

export function inferRoute(query: string, origin: Place | null): { living: Living; uncertain: boolean; routeLabel: string } {
  const text = query.trim()
  if (origin?.kind === "hospital") {
    return { living: "hospital", uncertain: false, routeLabel: "醫院 → 醫務社工" }
  }
  if (origin?.kind === "rche") {
    return { living: "rche", uncertain: false, routeLabel: "院舍 → 綜合家庭服務中心" }
  }
  if (/醫院/.test(text)) {
    return { living: "hospital", uncertain: true, routeLabel: "名稱似醫院 → 醫務社工" }
  }
  if (/院舍|安老院|護養院|護理安老/.test(text)) {
    return { living: "rche", uncertain: true, routeLabel: "名稱似院舍 → 綜合家庭服務中心" }
  }
  if (origin && (origin.kind === "estate" || origin.kind === "area")) {
    return { living: "home", uncertain: false, routeLabel: "屋苑或樓宇 → 長者地區中心／長者鄰舍中心" }
  }
  return { living: "home", uncertain: true, routeLabel: "未能確認地點種類，先按居家查找" }
}

export function districtIdFromText(text: string): string {
  const ranked = [...directory.districts].sort((a, b) => b.name.length - a.name.length)
  for (const district of ranked) {
    if (text.includes(district.name) || (district.nameEn && text.toLowerCase().includes(district.nameEn.toLowerCase()))) {
      return district.id
    }
  }
  return ""
}

function ruleText(input: SearchInput): string {
  if (input.mode === "hss") return "家居支援服務按地區及服務範圍，對上家居照顧及支援服務隊。"
  if (input.living === "hospital") return "住在醫院：安老服務統一評估的申請對口是醫務社工。"
  if (input.living === "rche") return "住在院舍：安老服務統一評估的申請對口是綜合家庭服務中心。"
  return "住在家中：安老服務統一評估的申請對口是長者地區中心或長者鄰舍中心。"
}

function directoryLabel(input: SearchInput): string {
  if (input.mode === "hss") return "家居支援服務範圍"
  if (input.living === "hospital") return "醫務社會服務單位名單"
  if (input.living === "rche") return "綜合家庭服務中心服務地域範圍"
  return "長者地區中心及長者鄰舍中心服務範圍"
}

function preference(unit: Unit): number {
  if (unit.type === "decc") return 0
  if (unit.type === "nec") return 1
  if (unit.name.includes("精神科")) return 2
  return 0
}

function selectHits(scored: SearchHit[]): { shown: SearchHit[]; hiddenCount: number } {
  if (!scored.length) return { shown: [], hiddenCount: 0 }
  const best = scored[0]?.score ?? 0
  const close = scored.filter((hit) => hit.score >= best - 8)
  const primary = close.filter((hit) => hit.unit.type !== "nec")
  const neighbourhood = close.filter((hit) => hit.unit.type === "nec")
  const shown = [...primary, ...neighbourhood.slice(0, primary.length ? 3 : 4)]
    .sort((a, b) => b.score - a.score || preference(a.unit) - preference(b.unit))
    .slice(0, 6)
  return { shown, hiddenCount: Math.max(0, close.length - shown.length) }
}

function fallbackUnits(input: SearchInput, district: string): Unit[] {
  const pool = directory.units.filter((unit) => unit.district === district && allowed(unit, input.mode, input.living))
  if (input.mode === "assessment" && input.living === "home") {
    const centres = pool.filter((unit) => unit.type === "decc")
    return (centres.length ? centres : pool).slice(0, 4)
  }
  return pool.slice(0, 5)
}

export function searchDirectory(input: SearchInput): SearchOutput {
  const queryText = input.query.trim()
  const query = normalize(queryText)
  const inferredDistrict = directory.districts.find((item) => {
    const full = normalize(item.name)
    const short = normalize(item.name.replace(/區$/, ""))
    return query === full || (short.length >= 2 && query === short)
  })?.id ?? ""
  const forcedDistrict = input.district || inferredDistrict
  const placeRanked = query
    ? directory.places
      .map((place) => ({ place, score: scorePlace(place, query) }))
      .filter((item) => item.score >= 64)
      .sort((a, b) => b.score - a.score || Number(b.place.featured) - Number(a.place.featured) || b.place.name.length - a.place.name.length)
    : []
  const origin = placeRanked[0]?.place ?? null
  const guessed = input.living
    ? { living: input.living, uncertain: false, routeLabel: "已改對口" }
    : input.mode === "hss"
      ? { living: "home" as Living, uncertain: false, routeLabel: "家居支援服務" }
      : inferRoute(queryText, origin)
  const routed: SearchInput = { ...input, living: guessed.living }
  const label = directoryLabel(routed)
  const base: SearchOutput = {
    hits: [],
    hiddenCount: 0,
    origin,
    hint: null,
    confidence: "none",
    directoryLabel: label,
    geocodeQuery: [queryText, forcedDistrict ? districtName(forcedDistrict) : "", "香港"].filter(Boolean).join(" "),
    inferredLiving: guessed.living,
    uncertain: guessed.uncertain,
    routeLabel: guessed.routeLabel,
    offCatalog: Boolean(input.offCatalog),
  }
  if (!query && !forcedDistrict) return base
  const probes = new Set<string>()
  if (query && !DISTRICT_QUERY.has(query)) probes.add(query)
  if (origin) {
    probes.add(normalize(origin.name))
    for (const alias of origin.aliases) probes.add(normalize(alias))
    for (const key of origin.areaKeys) probes.add(normalize(key))
  }

  const hints: string[] = []
  if (origin && forcedDistrict && origin.district && origin.district !== forcedDistrict) {
    hints.push(`這個地名較似屬${districtName(origin.district)}，你選了${districtName(forcedDistrict)}。下面的結果跟你選的地區。`)
  }
  if (guessed.uncertain) {
    hints.push("對口不確定。如果分錯，可以改為居家、醫院或院舍。")
  }

  const districtBoost = forcedDistrict || origin?.district || ""
  let ranked = directory.units
    .filter((unit) => allowed(unit, routed.mode, routed.living))
    .map((unit) => {
      const scored = scoreUnit(unit, [...probes])
      const boost = districtBoost && unit.district === districtBoost && scored.score > 0 ? 6 : 0
      return { unit, score: scored.score + boost, keyword: scored.keyword, reason: "", districtOnly: false }
    })
    .filter((hit) => hit.score >= 38)
    .sort((a, b) => b.score - a.score || preference(a.unit) - preference(b.unit))

  if (forcedDistrict) ranked = ranked.filter((hit) => hit.unit.district === forcedDistrict)
  else if (origin?.district) {
    const sameDistrict = ranked.filter((hit) => hit.unit.district === origin.district)
    if (sameDistrict.length) ranked = sameDistrict
  }

  let districtOnly = false
  let selected = selectHits(ranked)
  if (!selected.shown.length) {
    const district = forcedDistrict || origin?.district || ""
    if (district) {
      districtOnly = true
      selected = {
        shown: fallbackUnits(routed, district).map((unit) => ({
          unit,
          score: 1,
          keyword: "",
          reason: "",
          districtOnly: true,
        })),
        hiddenCount: 0,
      }
    }
  }

  const rule = ruleText(routed)
  const hits = selected.shown.map((hit) => {
    const where = districtName(hit.unit.district)
    const reason = districtOnly
      ? `${rule} 未能在公開服務範圍文字對上這個地名，所以先列出${where}的${TYPE_LABEL[hit.unit.type]}。請向單位核實，或打開來源文件核對範圍。`
      : `${rule} 對上的範圍文字包含「${hit.keyword || hit.unit.name}」。單位屬${where}。街號單雙數等細節仍要以社署文件為準。`
    return { ...hit, districtOnly, reason }
  })

  if (hits.length && hits.every((hit) => hit.unit.name.includes("精神科")) && !queryText.includes("精神")) {
    hints.push("對上的名冊單位名稱包含「精神科」。其他病房的醫務社工可能另有辦事處，請對照來源名單或向醫院查詢。")
  }
  if (selected.hiddenCount > 0) {
    hints.push("這個範圍由多間中心共同服務，這裡先列出最對口的幾間。完整名單見來源文件。")
  }

  const confidence: SearchOutput["confidence"] = hits.length === 0 ? "none" : districtOnly ? "district" : "match"
  const offCatalog = Boolean(input.offCatalog)
  const geocodeQuery = origin
    ? `${origin.name} ${districtName(origin.district)}`
    : [queryText, forcedDistrict ? districtName(forcedDistrict) : "", "香港"].filter(Boolean).join(" ")

  return {
    hits,
    hiddenCount: selected.hiddenCount,
    origin,
    hint: hints.length ? hints.join(" ") : null,
    confidence,
    directoryLabel: label,
    geocodeQuery,
    inferredLiving: guessed.living,
    uncertain: guessed.uncertain || confidence !== "match",
    routeLabel: guessed.routeLabel,
    offCatalog,
  }
}

export function relevantSources(input: SearchInput | null) {
  const order = input?.mode === "hss"
    ? ["ccse", "hss", "csse", "mss", "ifsc"]
    : input?.living === "hospital"
      ? ["mss", "csse", "ifsc", "ccse"]
      : input?.living === "rche"
        ? ["ifsc", "ifsc-list", "csse", "mss", "ccse"]
        : ["csse", "ifsc", "mss", "ccse"]
  const ranked = [...directory.sources].sort((a, b) => {
    const ai = order.indexOf(a.id)
    const bi = order.indexOf(b.id)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
  return ranked
}
