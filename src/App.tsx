import { useMemo, useRef, useState } from "react"
import type { FormEvent } from "react"
import { MapPanel } from "./components/MapPanel.tsx"
import type { MapPoint } from "./components/MapPanel.tsx"
import { geocodePlace } from "./lib/geocode.ts"
import type { GeocodeHit } from "./lib/geocode.ts"
import { TYPE_LABEL, directory, districtIdFromText, districtName, relevantSources, searchDirectory, suggestPlaces } from "./lib/search.ts"
import type { Example, Living, Mode, SearchOutput } from "./lib/types.ts"

const LIVING: { id: Living; title: string; rule: string }[] = [
  { id: "home", title: "住在家中", rule: "對口：長者地區中心／長者鄰舍中心" },
  { id: "hospital", title: "住在醫院", rule: "對口：醫務社工" },
  { id: "rche", title: "住在院舍", rule: "對口：綜合家庭服務中心" },
]

function telHref(phone: string): string {
  const digits = phone.replace(/\D/g, "")
  return digits ? `tel:+852${digits}` : ""
}

function chips(): Example[] {
  const wanted = ["home-st", "home-cw", "home-e", "hosp-pwh", "hosp-cmc", "hss-e"]
  const picked = wanted
    .map((id) => directory.examples.find((example) => example.id === id))
    .filter((example): example is Example => Boolean(example))
  const rche = directory.examples.find((example) => example.living === "rche")
  if (rche) picked.splice(5, 0, rche)
  return picked
}

export default function App() {
  const [mode, setMode] = useState<Mode>("assessment")
  const [override, setOverride] = useState<Living | null>(null)
  const [query, setQuery] = useState("")
  const [district, setDistrict] = useState("")
  const [formError, setFormError] = useState("")
  const [result, setResult] = useState<SearchOutput | null>(null)
  const [livePoint, setLivePoint] = useState<GeocodeHit | null>(null)
  const [geoStatus, setGeoStatus] = useState("")
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [activeSuggest, setActiveSuggest] = useState(-1)
  const requestId = useRef(0)

  const suggestions = useMemo(() => (query.trim().length >= 1 ? suggestPlaces(query) : []), [query])
  const focusDistricts = directory.districts.filter((item) => item.focus)
  const otherDistricts = directory.districts.filter(
    (item) => !item.focus && directory.units.some((unit) => unit.district === item.id),
  )

  async function run(next: { mode: Mode; living: Living | null; query: string; district: string }) {
    if (!next.query.trim() && !next.district) {
      setFormError("請輸入地點，或選擇地區。")
      setResult(null)
      return
    }
    setFormError("")
    let output = searchDirectory(next)
    const current = ++requestId.current
    const hasOriginPin = output.origin?.lat != null && output.origin.lng != null
    if (output.confidence === "none" && next.query.trim()) {
      setGeoStatus("呢個地點唔喺本站名冊。正在用 OpenStreetMap Nominatim 補查地區…")
      setLivePoint(null)
      const hit = await geocodePlace(output.geocodeQuery)
      if (requestId.current !== current) return
      setLivePoint(hit)
      const foundDistrict = hit ? districtIdFromText(hit.label) : ""
      if (foundDistrict) {
        output = searchDirectory({ ...next, district: foundDistrict, offCatalog: true })
        output = {
          ...output,
          hint: "呢個地點唔喺本站名冊。下面按公開地圖判斷的地區，列出可能的聯絡單位，請自行核對來源。",
        }
        setGeoStatus("")
      } else {
        setGeoStatus(hit
          ? "公開地圖有這個地名，但對唔上本站已收錄的地區。請直接查來源文件。"
          : "呢個地點唔喺本站名冊，公開地圖亦未定位到。請直接查來源文件。")
      }
    } else if (!hasOriginPin && output.geocodeQuery.trim() && next.query.trim()) {
      setGeoStatus("正在用預先座標以外的 OpenStreetMap Nominatim 補這個地名…")
      setLivePoint(null)
      const hit = await geocodePlace(output.geocodeQuery)
      if (requestId.current !== current) return
      setLivePoint(hit)
      setGeoStatus(hit ? "" : "這個地名沒有預先座標，交給 OpenStreetMap Nominatim 定位亦未成功。結果仍列出地址；未有座標的單位不會出現在地圖上。")
    } else {
      setLivePoint(null)
      setGeoStatus("")
    }
    if (requestId.current !== current) return
    setResult(output)
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    setShowSuggestions(false)
    void run({ mode, living: override, query, district })
  }

  function applyExample(example: Example) {
    setMode(example.mode)
    setOverride(null)
    setQuery(example.query)
    setDistrict(example.district)
    setShowSuggestions(false)
    void run({ mode: example.mode, living: null, query: example.query, district: example.district })
  }

  const points = useMemo<MapPoint[]>(() => {
    const next: MapPoint[] = []
    if (result?.origin?.lat != null && result.origin.lng != null) {
      next.push({
        id: "origin",
        kind: "user",
        lat: result.origin.lat,
        lng: result.origin.lng,
        title: result.origin.name,
        detail: result.origin.address,
      })
    } else if (livePoint) {
      next.push({
        id: "geocoded",
        kind: "user",
        lat: livePoint.lat,
        lng: livePoint.lng,
        title: query.trim() || "你輸入的地點",
        detail: livePoint.label,
      })
    }
    for (const hit of result?.hits ?? []) {
      if (hit.unit.lat == null || hit.unit.lng == null) continue
      next.push({
        id: hit.unit.id,
        kind: "unit",
        lat: hit.unit.lat,
        lng: hit.unit.lng,
        title: hit.unit.name,
        detail: hit.unit.address,
      })
    }
    return next
  }, [livePoint, query, result])

  const missingMap = (result?.hits ?? []).filter((hit) => hit.unit.lat == null || hit.unit.lng == null).length
  const mapNote = !result
    ? "搜尋後會同時標示你輸入的地點，以及有預先座標的聯絡單位。"
    : geoStatus || (points.some((point) => point.kind === "user") && points.some((point) => point.kind === "unit")
      ? `橙色是你輸入的地點，綠色是聯絡單位。${missingMap ? `有 ${missingMap} 個單位未有地圖座標。` : ""}`
      : missingMap
        ? "這些單位未有地圖座標，請以地址為準。"
        : "有座標的標記已放在地圖上。")

  const sources = relevantSources(result ? { mode, living: result.inferredLiving, query, district } : null)

  return (
    <div className="page">
      <header className="mast">
        <div className="wrap mast-inner">
          <p className="mark">非官方查詢工具 · 不是政府網站</p>
          <h1>搵服務</h1>
          <p className="lede">Find Service。輸入屋苑、樓宇、醫院或院舍，查找資助安老服務該聯絡的單位。</p>
        </div>
      </header>

      <div className="wrap">
        <p className="disclaimer">{directory.disclaimer}</p>

        <form className="finder" onSubmit={onSubmit}>
          <fieldset className="mode">
            <legend>查找哪一類聯絡單位</legend>
            <label className={mode === "assessment" ? "mode-option on" : "mode-option"}>
              <input type="radio" name="mode" checked={mode === "assessment"} onChange={() => setMode("assessment")} />
              <span>統一評估申請對口</span>
            </label>
            <label className={mode === "hss" ? "mode-option on" : "mode-option"}>
              <input type="radio" name="mode" checked={mode === "hss"} onChange={() => setMode("hss")} />
              <span>家居支援服務</span>
            </label>
          </fieldset>

          <p className="step-note">
            {mode === "assessment"
              ? "屋苑或樓宇會當居家，醫院會當醫務社工，院舍會當綜合家庭服務中心。如果分錯，搜尋後可以改。"
              : "家居支援服務一般服務居於社區的長者。系統按地名及地區，對上家居照顧及支援服務隊。"}
          </p>

          <div className="step grid-two">
            <div className="field suggest-field">
              <label htmlFor="place"><span>1</span>居住地點</label>
              <input
                id="place"
                name="place"
                value={query}
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={showSuggestions && suggestions.length > 0}
                aria-controls="place-suggestions"
                aria-activedescendant={activeSuggest >= 0 ? `place-option-${activeSuggest}` : undefined}
                autoComplete="off"
                placeholder="屋邨、大廈、醫院或院舍，例如瀝源邨"
                onChange={(event) => {
                  setQuery(event.target.value)
                  setOverride(null)
                  setShowSuggestions(true)
                  setActiveSuggest(-1)
                }}
                onFocus={() => setShowSuggestions(true)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setShowSuggestions(false)
                    setActiveSuggest(-1)
                    return
                  }
                  if (!showSuggestions || suggestions.length === 0) return
                  if (event.key === "ArrowDown") {
                    event.preventDefault()
                    setActiveSuggest((index) => (index + 1) % suggestions.length)
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault()
                    setActiveSuggest((index) => (index <= 0 ? suggestions.length - 1 : index - 1))
                  } else if (event.key === "Enter" && activeSuggest >= 0) {
                    event.preventDefault()
                    const place = suggestions[activeSuggest]
                    if (!place) return
                    setQuery(place.name)
                    if (place.district) setDistrict(place.district)
                    setShowSuggestions(false)
                    setActiveSuggest(-1)
                  }
                }}
              />
              {showSuggestions && suggestions.length > 0 ? (
                <ul id="place-suggestions" className="suggestions" role="listbox" aria-label="地名建議">
                  {suggestions.map((place, index) => (
                    <li key={place.id} role="presentation">
                      <button
                        id={`place-option-${index}`}
                        type="button"
                        role="option"
                        aria-selected={index === activeSuggest}
                        className={index === activeSuggest ? "active" : undefined}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => {
                          setQuery(place.name)
                          if (place.district) setDistrict(place.district)
                          setShowSuggestions(false)
                          setActiveSuggest(-1)
                        }}
                      >
                        <strong>{place.name}</strong>
                        <small>{districtName(place.district)} · {place.kind === "hospital" ? "醫院" : place.kind === "rche" ? "院舍" : "地區／屋苑"}</small>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="district"><span>2</span>地區提示（可選）</label>
              <select id="district" value={district} onChange={(event) => setDistrict(event.target.value)}>
                <option value="">不指定</option>
                <optgroup label="全港地區">
                  {focusDistricts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </optgroup>
                <optgroup label="名冊亦有收錄">
                  {otherDistricts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </optgroup>
              </select>
            </div>
          </div>

          {formError ? <p className="form-error" role="alert">{formError}</p> : null}

          <div className="actions">
            <button type="submit" className="search">查找聯絡單位</button>
            <p className="examples-label">試試例子</p>
            <div className="chips">
              {chips().map((example) => (
                <button key={example.id} type="button" className="chip" onClick={() => applyExample(example)}>
                  {example.label}
                </button>
              ))}
            </div>
          </div>
        </form>

        <div className="layout">
          <section className="results" aria-live="polite">
            {!result ? (
              <div className="intro">
                <h2>怎樣對口</h2>
                <ol className="rules">
                  <li><strong>住在家中</strong><span>聯絡該區長者地區中心或長者鄰舍中心，查詢長期護理服務的申請。</span></li>
                  <li><strong>住在醫院</strong><span>聯絡該院醫務社工。精神科與其他病房的辦事處可能不同。</span></li>
                  <li><strong>住在院舍</strong><span>按院舍所在的服務地域，聯絡綜合家庭服務中心。</span></li>
                </ol>
                <p className="coverage">{directory.coverageNote}</p>
              </div>
            ) : result.hits.length === 0 ? (
              <div className="empty off-catalog">
                <p className="off-badge">唔喺本站名冊</p>
                <h2>未有對上的單位</h2>
                <p>「{query || districtName(district)}」唔喺本站名冊，公開地圖亦未補到已收錄地區。請直接查閱{result.directoryLabel}。</p>
                {result.hint ? <p className="hint">{result.hint}</p> : null}
                <SourceList sources={sources} />
              </div>
            ) : (
              <>
                <div className="result-head">
                  <h2>{result.offCatalog ? "呢個地點唔喺本站名冊" : result.confidence === "district" ? "先按地區列出，請再核實" : `找到 ${result.hits.length} 個聯絡單位`}</h2>
                  <p>名冊：{result.directoryLabel}</p>
                  {result.origin ? <p className="origin">地點：{result.origin.name} · {result.origin.address}</p> : null}
                  {result.hint ? <p className="hint">{result.hint}</p> : null}
                  {mode === "assessment" ? (
                    <fieldset className="route-fix">
                      <legend>對口判斷{result.uncertain ? "：不確定" : ""}</legend>
                      <p>{result.routeLabel}</p>
                      <div className="choices compact">
                        {LIVING.map((item) => (
                          <label key={item.id} className={(override ?? result.inferredLiving) === item.id ? "choice on" : "choice"}>
                            <input
                              type="radio"
                              name="route"
                              value={item.id}
                              checked={(override ?? result.inferredLiving) === item.id}
                              onChange={() => {
                                setOverride(item.id)
                                void run({ mode, living: item.id, query, district })
                              }}
                            />
                            <strong>{item.title}</strong>
                            <small>{item.rule}</small>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ) : null}
                </div>
                <ol className="cards">
                  {result.hits.map((hit) => {
                    const phoneLink = telHref(hit.unit.phone)
                    return (
                      <li key={hit.unit.id} className={`card type-${hit.unit.type}${result.offCatalog ? " off-catalog" : ""}`}>
                        {result.offCatalog ? <p className="off-badge">唔喺本站名冊</p> : null}
                        <p className="kicker">{TYPE_LABEL[hit.unit.type]} · {districtName(hit.unit.district)}</p>
                        <h3>{hit.unit.name}</h3>
                        {hit.unit.operator ? <p className="operator">{hit.unit.operator}</p> : null}
                        <p className="reason">{hit.reason}</p>
                        <dl>
                          <div>
                            <dt>地址</dt>
                            <dd>{hit.unit.address}</dd>
                          </div>
                          {hit.unit.phone ? (
                            <div>
                              <dt>電話</dt>
                              <dd>{phoneLink ? <a href={phoneLink}>{hit.unit.phone}</a> : hit.unit.phone}</dd>
                            </div>
                          ) : (
                            <div>
                              <dt>電話</dt>
                              <dd>名冊未有電話</dd>
                            </div>
                          )}
                          {hit.unit.lat == null || hit.unit.lng == null ? (
                            <div>
                              <dt>地圖</dt>
                              <dd>未有地圖座標</dd>
                            </div>
                          ) : null}
                          {hit.unit.hours ? (
                            <div>
                              <dt>時間</dt>
                              <dd>{hit.unit.hours}</dd>
                            </div>
                          ) : null}
                          {hit.unit.serviceArea ? (
                            <div>
                              <dt>範圍摘錄</dt>
                              <dd>{hit.unit.serviceArea.length > 180 ? `${hit.unit.serviceArea.slice(0, 180)}…` : hit.unit.serviceArea}</dd>
                            </div>
                          ) : null}
                        </dl>
                        <p className="links">
                          <a href={hit.unit.sourceUrl} target="_blank" rel="noreferrer">來源文件</a>
                          <a href={hit.unit.sourcePage} target="_blank" rel="noreferrer">資料頁</a>
                          {hit.unit.mapUrl ? <a href={hit.unit.mapUrl} target="_blank" rel="noreferrer">官方地圖</a> : null}
                        </p>
                      </li>
                    )
                  })}
                </ol>
              </>
            )}
          </section>
          <div className="map-column">
            <MapPanel points={points} note={mapNote} />
            <p className="privacy">
              已收錄地點先用預先座標。沒有預先座標時，瀏覽器才把地名送到 OpenStreetMap Nominatim 查位置，不會送到本網站的伺服器。定位失敗就只顯示地址，並標明未有地圖座標。
            </p>
          </div>
        </div>

        <section className="sources">
          <h2>資料來源</h2>
          <p>{directory.coverageNote} 電話和地址以社署最新文件為準，本工具不會自動更新。</p>
          <SourceList sources={directory.sources} />
        </section>
      </div>

      <footer className="wrap foot">
        <p>搵服務（Find Service）是非官方查詢工具，不是政府網站。請勿把它當成社會福利署、醫院管理局或其他機構的官方服務。</p>
      </footer>
    </div>
  )
}

function SourceList({ sources }: { sources: { id: string; title: string; href: string }[] }) {
  return (
    <ul className="source-list">
      {sources.map((source) => (
        <li key={source.id}>
          <a href={source.href} target="_blank" rel="noreferrer">{source.title}</a>
        </li>
      ))}
    </ul>
  )
}
