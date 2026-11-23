import { describe, expect, it } from "vitest"
import { directory } from "./search"
import { formatRebuiltAt } from "./rebuiltAt"

describe("formatRebuiltAt", () => {
  it("shows the published rebuild as a Hong Kong date and time", () => {
    expect(formatRebuiltAt("2026-11-10T21:39:38+08:00")).toBe("2026年11月10日 21:39（香港時間）")
  })

  it("converts UTC to Hong Kong time", () => {
    expect(formatRebuiltAt("2026-11-10T13:39:38Z")).toBe("2026年11月10日 21:39（香港時間）")
  })

  it("rolls a late UTC stamp into the next Hong Kong date", () => {
    expect(formatRebuiltAt("2026-11-10T16:05:00Z")).toBe("2026年11月11日 00:05（香港時間）")
  })

  it("leaves an unreadable value unchanged", () => {
    expect(formatRebuiltAt("not a time")).toBe("not a time")
  })
})

describe("shipped directory rebuild time", () => {
  it("is the Live rebuild from 10 November 2026, with no last-check field", () => {
    expect(directory.rebuiltAt).toBe("2026-11-10T21:39:38+08:00")
    expect(formatRebuiltAt(directory.rebuiltAt)).toBe("2026年11月10日 21:39（香港時間）")
    expect("checkedAt" in directory).toBe(false)
    expect("lastCheckedAt" in directory).toBe(false)
  })
})
