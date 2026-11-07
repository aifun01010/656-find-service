# 搵服務 Find Service

輸入屋苑、樓宇、醫院或院舍，查找資助安老服務該聯絡的單位。屋苑和樓宇會當居家，醫院會當醫務社工，院舍會當綜合家庭服務中心。這是非官方查詢工具，不是社會福利署、醫院管理局或任何資助機構的官方網站。

之後若放上 Cloudflare Pages，專案名稱可用 `find-service`，網址會是 `find-service.pages.dev`。建置輸出是網站根路徑 `/`，不用另設 Vite `base`。

## 點樣用

1. 選擇「統一評估申請對口」或「家居支援服務」。
2. 輸入屋苑、大廈、醫院或院舍。地區可以選填。
3. 系統按地名自動對口。如果分錯或不確定，結果頁可以改。
4. 查看單位名稱、地址、電話、對上原因、來源連結，以及地圖。

名冊對不上這個地名時，會用預先座標或 OpenStreetMap Nominatim 補查地區。那種補查結果會標明 **唔喺本站名冊**。如果只是按你選的地區，從本站已收錄的單位列出來，就保持本站樣式，並寫「先按地區列出」。沒有即時爬社署網頁；公開名單的連結會一併列出。

可以試沙田瀝源邨、威爾斯親王醫院，以及名冊上的院舍。

## 對口規則

| 輸入 | 聯絡單位 |
| --- | --- |
| 屋苑、樓宇、地區 | 長者地區中心／長者鄰舍中心 |
| 醫院 | 醫務社工 |
| 院舍 | 綜合家庭服務中心 |

家居支援服務是另一個查找：按地區及服務範圍，對上家居照顧及支援服務隊。院舍不會自動改查家居支援。

系統用已收錄名冊的屋邨、大廈和醫院名稱做文字對上。它不會判斷街號單雙數。結果只供參考，申請前請向單位或對照來源文件確認。

## 本地運行

```bash
npm install
npm run dev
```

開發伺服器預設在 <http://127.0.0.1:43123>。

```bash
npm test
npm run build
```

`npm run build` 產出 `dist/`，路徑是網站根目錄。不需要 API 金鑰或登入。

## 資料從哪裡來

已整理進 `src/data/directory.json` 的內容，來自社會福利署公開名單（下載並轉成 JSON，不是網站即時抓取）：

- [社區支援服務：長者地區中心及長者鄰舍中心](https://www.swd.gov.hk/tc/pubsvc/elderly/elderly_info/susa/su_csse/)
- [醫務社會服務單位](https://www.swd.gov.hk/tc/pubsvc/medical/cat_medical/medicalsoc/)
- [綜合家庭服務中心服務地域範圍](https://www.swd.gov.hk/tc/pubsvc/family/cat_family/ifs/ifscbydistrict/index.html)及[地址名單](https://www.swd.gov.hk/storage/asset/section/260/tc/IFSC_ISC_address_list_tc_Feb_2026.pdf)
- [社區照顧服務／家居支援服務範圍](https://www.swd.gov.hk/tc/pubsvc/elderly/elderly_info/susa/su_ccse/)
- 院舍例子來自[提供資助宿位的安老院舍名單](https://www.swd.gov.hk/storage/asset/section/177/List%20of%20RCHE/4_%20List%20of%20RCHEs%20Providing%20Subsidised%20Places%20for%20the%20Elderly_Q(30_9_2026)_ENG%26TC.xlsx)

長者地區中心、長者鄰舍中心、醫務社工單位、綜合家庭服務中心和家居支援服務隊，收錄社會福利署公開名冊的全港名單。這仍不是逐座樓宇或逐個街號的法律分界，部分單位可能未有地圖座標。

更新資料（需要 Python、`xlrd`、`openpyxl`、`python-docx`、`pymupdf`、`pdftotext`）：

```bash
python3 scripts/build_directory.py --geocode
```

`--geocode` 會用 Nominatim（失敗時才用 Photon）為尚未有座標的單位補座標，並遵守大約每秒一次的查詢節奏。已核對過的座標會保留。瀏覽器搜尋時先用這些預先座標；只有沒有預先座標、或名冊對不上的地名，才會由瀏覽器把地名送到 OpenStreetMap Nominatim。那個請求不會經過本網站的伺服器。定位失敗時，結果仍列出地址，並標明「未有地圖座標」。瀏覽器不能自訂 User-Agent。

地圖圖磚來自 OpenStreetMap。

## 每月巡查來源

`scripts/check_sources.py` 會下載社署四個公開頁面，核對上面的 PDF／Excel／Word 連結是否仍與 `scripts/source-manifest.json` 一致。連結沒變、但同一個網址後面的檔案被換走時，腳本會對每個檔發 HTTP HEAD（HEAD 失敗才改為只讀標頭的 GET），比較 `Last-Modified`、`ETag` 和 `Content-Length`。回應完全沒有這些標頭就跳過，不會每晚誤報；上次有標頭、今次全部消失則算異常。它只出報告，不會下載檔案內容、不會改名冊，也不會部署。

```bash
python3 scripts/check_sources.py
python3 -m unittest discover -s scripts -p 'test_*.py'
```

有新增、消失，或同一網址的標頭有變時，程式以狀態碼 1 結束，方便別人的每月排程發告警。確認新檔可用之後，先更新清單（連同標頭基準）再重建資料：

```bash
python3 scripts/check_sources.py --write-manifest
python3 scripts/build_directory.py --geocode
```

排程本身（例如每月一日）由網站負責人設定。這個儲存庫沒有代為建立雲端排程。

## 限制

- 資料會過時。電話、地址和服務範圍以社署最新文件為準。
- 對上結果不是福利審批，也不是法律意見。
- 街號分界，或名冊裡找不到的地名，要直接查來源文件。標了「唔喺本站名冊」的是公開地圖補查，不是本站名冊的命中。只選地區而列出的單位仍屬本站名冊。
- 請勿將本網站表述為社會福利署、醫院管理局或其他機構的官方產品。

## Origin 儲存庫名稱

程式和文件已用「搵服務 / Find Service」。若要把 Origin 儲存庫由 `ai-fun/an-lo-dui-kou` 改成 `ai-fun/find-service`，需要有儲存庫管理權限的人在 Origin 重新命名。這個環境未能代為完成改名。改名後把 git remote 指向新地址即可，不必改建置路徑。

## Run locally

```bash
npm install
npm run dev
```

Open <http://127.0.0.1:43123>. Find Service helps carers look up a subsidised elderly-service contact. An estate or building is treated as living at home, a hospital as medical social work, and a residential care home as an integrated family service centre. It is **not** an official Social Welfare Department, Hospital Authority, or agency site. Embedded data comes from the public SWD lists for elderly centres, medical social work units, integrated family service centres, and home support teams across Hong Kong. Matches are by place name, not a legal reading of street-number boundaries. Not legal or welfare advice. If a place is not in the bundled directory, the page may ask OpenStreetMap Nominatim for a district and labels those suggestions as outside this site's directory. `python3 scripts/check_sources.py` reports whether the public source links changed and whether a file behind the same URL was replaced, using HTTP Last-Modified, ETag, and Content-Length. Schedule that monthly yourself. `python3 -m unittest discover -s scripts -p 'test_*.py'` checks the comparison logic without contacting SWD.
