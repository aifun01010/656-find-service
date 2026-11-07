export type UnitType = "decc" | "nec" | "mssu" | "ifsc" | "hss"
export type Living = "home" | "hospital" | "rche"
export type Mode = "assessment" | "hss"
export type PlaceKind = "estate" | "hospital" | "rche" | "area"

export type District = {
  id: string
  name: string
  nameEn: string
  focus: boolean
}

export type SourceLink = {
  id: string
  title: string
  href: string
}

export type Unit = {
  id: string
  type: UnitType
  name: string
  operator: string
  district: string
  address: string
  phone: string
  hours: string
  serviceArea: string
  searchText: string
  keywords: string[]
  mapUrl: string
  sourceTitle: string
  sourceUrl: string
  sourcePage: string
  lat: number | null
  lng: number | null
  geoSource: string
}

export type Place = {
  id: string
  name: string
  aliases: string[]
  kind: PlaceKind
  district: string
  address: string
  phone: string
  areaKeys: string[]
  featured: boolean
  lat: number | null
  lng: number | null
  geoSource: string
}

export type Example = {
  id: string
  mode: Mode
  living: Living
  query: string
  district: string
  label: string
}

export type Directory = {
  title: string
  generatedFrom: string
  disclaimer: string
  districts: District[]
  sources: SourceLink[]
  coverageNote: string
  units: Unit[]
  places: Place[]
  examples: Example[]
  counts: Record<string, number>
}

export type SearchInput = {
  mode: Mode
  living: Living | null
  query: string
  district: string
  /** True when these hits come from a public lookup, not a directory name match. */
  offCatalog?: boolean
}

export type SearchHit = {
  unit: Unit
  score: number
  keyword: string
  reason: string
  districtOnly: boolean
}

export type SearchOutput = {
  hits: SearchHit[]
  hiddenCount: number
  origin: Place | null
  hint: string | null
  confidence: "match" | "district" | "none"
  directoryLabel: string
  geocodeQuery: string
  inferredLiving: Living
  uncertain: boolean
  routeLabel: string
  offCatalog: boolean
}
