import { describe, expect, it } from "vitest"
import { directory, searchDirectory } from "./search"

describe("directory integrity", () => {
  it("has unique unit ids and no header-row medical social work units", () => {
    const ids = directory.units.map((unit) => unit.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(directory.units.some((unit) => unit.name === "辦事處分處")).toBe(false)
    const medical = directory.units.filter((unit) => unit.type === "mssu")
    expect(medical.every((unit) => unit.phone.trim().length > 0 && unit.address.trim().length > 0)).toBe(true)
  })

  it("places Kowloon hospitals in a district", () => {
    const districtOf = (name: string) => directory.units.find((unit) => unit.type === "mssu" && unit.name === name)?.district
    expect(districtOf("伊利沙伯醫院")).toBe("ytm")
    expect(districtOf("廣華醫院")).toBe("ytm")
    expect(districtOf("香港眼科醫院")).toBe("kc")
    expect(districtOf("九龍醫院")).toBe("kc")
  })

  it("does not keep noise words as service-area keywords", () => {
    for (const unit of directory.units) {
      expect(unit.keywords).not.toContain("電郵")
      expect(unit.keywords).not.toContain("其他")
      expect(unit.keywords).not.toContain("西南")
      expect(unit.keywords).not.toContain("醫院")
    }
  })
})

describe("territory coverage", () => {
  const districts = ["cw", "wc", "e", "sou", "is", "ytm", "ssp", "kc", "wts", "kt", "sk", "st", "tp", "n", "yl", "tm", "tw", "kwt"]

  it("includes elderly centres, family centres, and home support in every district", () => {
    for (const district of districts) {
      expect(directory.units.some((unit) => (unit.type === "decc" || unit.type === "nec") && unit.district === district)).toBe(true)
      expect(directory.units.some((unit) => unit.type === "ifsc" && unit.district === district)).toBe(true)
      expect(directory.units.some((unit) => unit.type === "hss" && unit.district === district)).toBe(true)
    }
  })

  it("routes a Tuen Mun estate as living at home", () => {
    const estate = directory.places.find((place) => place.district === "tm" && place.kind === "estate" && place.name.endsWith("邨"))
    expect(estate).toBeTruthy()
    const result = searchDirectory({ mode: "assessment", living: null, query: estate?.name ?? "", district: "tm" })
    expect(result.inferredLiving).toBe("home")
    expect(result.offCatalog).toBe(false)
    expect(result.hits.some((hit) => hit.unit.district === "tm" && (hit.unit.type === "decc" || hit.unit.type === "nec"))).toBe(true)
  })
})

describe("automatic routing", () => {
  it("treats an estate as living at home", () => {
    const result = searchDirectory({ mode: "assessment", living: null, query: "瀝源邨", district: "st" })
    expect(result.inferredLiving).toBe("home")
    expect(result.uncertain).toBe(false)
    expect(result.offCatalog).toBe(false)
    expect(result.hits.some((hit) => hit.unit.type === "decc" || hit.unit.type === "nec")).toBe(true)
  })

  it("treats a hospital as medical social work", () => {
    const result = searchDirectory({ mode: "assessment", living: null, query: "威爾斯親王醫院", district: "" })
    expect(result.inferredLiving).toBe("hospital")
    expect(result.hits.some((hit) => hit.unit.type === "mssu" && hit.unit.name.includes("威爾斯"))).toBe(true)
    expect(result.offCatalog).toBe(false)
  })

  it("treats a residential care home as an integrated family service centre", () => {
    const careHome = directory.examples.find((example) => example.living === "rche")
    expect(careHome).toBeTruthy()
    const result = searchDirectory({
      mode: "assessment",
      living: null,
      query: careHome?.query ?? "",
      district: careHome?.district ?? "",
    })
    expect(result.inferredLiving).toBe("rche")
    expect(result.hits.some((hit) => hit.unit.type === "ifsc")).toBe(true)
  })

  it("marks an unknown place as outside the on-site directory", () => {
    const result = searchDirectory({
      mode: "assessment",
      living: null,
      query: "沒有這個地名xyz",
      district: "st",
      offCatalog: true,
    })
    expect(result.offCatalog).toBe(true)
    expect(result.uncertain).toBe(true)
    expect(result.hits.length).toBeGreaterThan(0)
    expect(result.hits.every((hit) => hit.unit.district === "st")).toBe(true)
  })
})

describe("routing examples", () => {
  it("covers home, hospital, residential care, and home support", () => {
    const modes = new Set(directory.examples.map((example) => `${example.mode}:${example.living}`))
    expect(modes.has("assessment:home")).toBe(true)
    expect(modes.has("assessment:hospital")).toBe(true)
    expect(modes.has("assessment:rche")).toBe(true)
    expect(modes.has("hss:home")).toBe(true)
  })

  for (const example of directory.examples) {
    it(example.label, () => {
      const result = searchDirectory({
        mode: example.mode,
        living: example.living,
        query: example.query,
        district: example.district,
      })
      expect(result.confidence).not.toBe("none")
      expect(result.hits.length).toBeGreaterThan(0)
      const hit = result.hits[0]
      expect(hit?.unit.phone.length).toBeGreaterThan(3)
      expect(hit?.unit.address.length).toBeGreaterThan(4)
      expect(hit?.unit.sourceUrl).toMatch(/^https:\/\/www\.swd\.gov\.hk\//)
      expect(hit?.reason.length).toBeGreaterThan(8)
    })
  }
})

describe("搵服務查詢路徑", () => {
  it("matches a Sha Tin home estate to an elderly centre", () => {
    const result = searchDirectory({ mode: "assessment", living: "home", query: "瀝源邨", district: "st" })
    expect(result.hits.some((hit) => hit.unit.type === "decc" || hit.unit.type === "nec")).toBe(true)
    expect(result.hits.some((hit) => hit.unit.district === "st")).toBe(true)
    expect(result.origin?.name).toBe("瀝源邨")
  })

  it("matches Queen Elizabeth Hospital without a blank contact card", () => {
    const result = searchDirectory({
      mode: "assessment",
      living: "hospital",
      query: "伊利沙伯醫院",
      district: "",
    })
    expect(result.hits.length).toBeGreaterThan(0)
    expect(result.hits.every((hit) => hit.unit.name.includes("伊利沙伯"))).toBe(true)
    expect(result.hits.every((hit) => hit.unit.phone.trim().length > 0)).toBe(true)
    expect(result.hits.every((hit) => hit.unit.district === "ytm")).toBe(true)
    expect(new Set(result.hits.map((hit) => hit.unit.id)).size).toBe(result.hits.length)
  })

  it("matches Prince of Wales Hospital to a medical social work unit", () => {
    const result = searchDirectory({
      mode: "assessment",
      living: "hospital",
      query: "威爾斯親王醫院",
      district: "st",
    })
    expect(result.hits.some((hit) => hit.unit.type === "mssu" && hit.unit.name.includes("威爾斯"))).toBe(true)
    expect(result.hits[0]?.unit.sourcePage).toMatch(/medicalsoc/)
  })

  it("matches a residential care home to an integrated family service centre", () => {
    const example = directory.examples.find((item) => item.living === "rche")
    expect(example).toBeTruthy()
    const result = searchDirectory({
      mode: "assessment",
      living: "rche",
      query: example?.query ?? "",
      district: example?.district ?? "",
    })
    expect(result.hits.some((hit) => hit.unit.type === "ifsc")).toBe(true)
    expect(result.hits[0]?.unit.sourcePage).toMatch(/ifscbydistrict/)
  })

  it("matches Taikoo Shing to a home support team", () => {
    const result = searchDirectory({ mode: "hss", living: "home", query: "太古城", district: "e" })
    expect(result.hits.some((hit) => hit.unit.type === "hss" && hit.unit.district === "e")).toBe(true)
  })

  it("keeps an empty search useful", () => {
    const result = searchDirectory({ mode: "assessment", living: "home", query: "沒有這個地名xyz", district: "" })
    expect(result.hits).toHaveLength(0)
    expect(result.confidence).toBe("none")
    expect(result.directoryLabel).toContain("長者")
  })

  it("pins both the place and a contact unit for the three residence paths", () => {
    const home = searchDirectory({ mode: "assessment", living: "home", query: "瀝源邨", district: "st" })
    expect(home.origin?.lat).toBeTruthy()
    expect(home.hits.some((hit) => hit.unit.lat && hit.unit.lng)).toBe(true)

    const hospital = searchDirectory({
      mode: "assessment",
      living: "hospital",
      query: "威爾斯親王醫院",
      district: "st",
    })
    expect(hospital.origin?.lat).toBeTruthy()
    expect(hospital.hits[0]?.unit.lat).toBeTruthy()

    const careHomes = directory.examples.filter((example) => example.living === "rche")
    const residential = careHomes
      .map((example) => searchDirectory({
        mode: "assessment",
        living: "rche",
        query: example.query,
        district: example.district,
      }))
      .find((result) => result.origin?.lat && result.hits.some((hit) => hit.unit.type === "ifsc" && hit.unit.lat))
    expect(residential).toBeTruthy()
  })

  it("falls back to district elderly centres when only a district is chosen", () => {
    const result = searchDirectory({ mode: "assessment", living: "home", query: "", district: "ssp" })
    expect(result.confidence).toBe("district")
    expect(result.hits.every((hit) => hit.unit.district === "ssp")).toBe(true)
    expect(result.hits.some((hit) => hit.unit.type === "decc")).toBe(true)
    expect(result.offCatalog).toBe(false)
  })
})
