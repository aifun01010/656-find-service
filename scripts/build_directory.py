#!/usr/bin/env python3
"""Build src/data/directory.json from Social Welfare Department public lists.

The demo ships the generated JSON. Re-run this script only when refreshing data.
It downloads public PDF/Excel/Word files into scripts/.cache (gitignored).
Geocoding is optional (--geocode) and uses Nominatim with a fallback cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pymupdf
import xlrd
from docx import Document
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "scripts" / ".cache"
OUT = ROOT / "src" / "data" / "directory.json"
GEO_CACHE_PATH = ROOT / "scripts" / "geocode-cache.json"
UA = "find-service/0.1 (Find Service educational prototype; public-data refresh)"
SWD = "https://www.swd.gov.hk"

DISTRICTS = [
    {"id": "cw", "name": "中西區", "nameEn": "Central and Western", "focus": True},
    {"id": "e", "name": "東區", "nameEn": "Eastern", "focus": True},
    {"id": "kt", "name": "觀塘", "nameEn": "Kwun Tong", "focus": True},
    {"id": "ssp", "name": "深水埗", "nameEn": "Sham Shui Po", "focus": True},
    {"id": "st", "name": "沙田", "nameEn": "Sha Tin", "focus": True},
    {"id": "wc", "name": "灣仔", "nameEn": "Wan Chai", "focus": True},
    {"id": "sou", "name": "南區", "nameEn": "Southern", "focus": True},
    {"id": "is", "name": "離島", "nameEn": "Islands", "focus": True},
    {"id": "wts", "name": "黃大仙", "nameEn": "Wong Tai Sin", "focus": True},
    {"id": "sk", "name": "西貢", "nameEn": "Sai Kung", "focus": True},
    {"id": "ytm", "name": "油尖旺", "nameEn": "Yau Tsim Mong", "focus": True},
    {"id": "kc", "name": "九龍城", "nameEn": "Kowloon City", "focus": True},
    {"id": "tp", "name": "大埔", "nameEn": "Tai Po", "focus": True},
    {"id": "n", "name": "北區", "nameEn": "North", "focus": True},
    {"id": "yl", "name": "元朗", "nameEn": "Yuen Long", "focus": True},
    {"id": "tw", "name": "荃灣", "nameEn": "Tsuen Wan", "focus": True},
    {"id": "kwt", "name": "葵青", "nameEn": "Kwai Tsing", "focus": True},
    {"id": "tm", "name": "屯門", "nameEn": "Tuen Mun", "focus": True},
    {"id": "twkw", "name": "荃灣及葵青", "nameEn": "Tsuen Wan and Kwai Tsing", "focus": False},
]
DISTRICT_NAME = {d["id"]: d["name"] for d in DISTRICTS}
FOCUS = {d["id"] for d in DISTRICTS if d["focus"]}

KEEP_IFSC_SECTIONS = None

ADDRESS_RULES = [
    ("is", ["長洲", "坪洲", "東涌", "梅窩", "南丫", "大嶼", "愉景灣", "離島"]),
    ("sou", ["香港仔", "鴨脷洲", "華富", "華貴", "赤柱", "石澳", "田灣", "黃竹坑", "利東", "海怡", "石排灣", "漁光", "薄扶林", "置富", "壽臣山", "深灣", "舂磡角"]),
    ("cw", ["西營盤", "上環", "中環", "堅尼地", "石塘咀", "西環", "半山", "金鐘", "山頂", "高街", "摩星嶺"]),
    ("e", ["柴灣", "小西灣", "筲箕灣", "西灣河", "鰂魚涌", "北角", "杏花", "太古", "康山", "阿公岩", "愛秩序", "興華", "環翠"]),
    ("wc", ["灣仔", "跑馬地", "銅鑼灣", "大坑", "軒尼詩"]),
    ("kt", ["觀塘", "藍田", "秀茂坪", "油塘", "九龍灣", "牛頭角", "茶果嶺", "順利", "翠屏", "四順", "彩雲"]),
    ("ssp", ["深水埗", "長沙灣", "石硤尾", "美孚", "荔枝角", "南昌", "蘇屋", "李鄭屋", "大坑東"]),
    ("wts", ["黃大仙", "慈雲山", "鑽石山", "樂富", "新蒲崗", "竹園", "彩虹"]),
    ("ytm", ["油麻地", "旺角", "尖沙咀", "大角咀", "佐敦", "太子", "加士居道", "窩打老道"]),
    ("kc", ["九龍城", "土瓜灣", "紅磡", "何文田", "啟德", "馬頭圍", "亞皆老街"]),
    ("sk", ["將軍澳", "西貢", "坑口", "調景嶺", "寶琳"]),
    ("st", ["沙田", "馬鞍山", "大圍", "火炭", "亞公角", "石門", "小瀝源", "秦石"]),
    ("tp", ["大埔"]),
    ("n", ["上水", "粉嶺"]),
    ("tm", ["屯門"]),
    ("yl", ["元朗", "天水圍"]),
    ("tw", ["荃灣"]),
    ("kwt", ["葵涌", "青衣", "葵青"]),
]

# Nominatim results captured for the demo pins. Used when live geocoding is off
# or a query misses. These are public OpenStreetMap coordinates.
MANUAL_COORDS = {
    "威爾斯親王醫院": (22.379609, 114.202193),
    "瀝源邨": (22.385041, 114.191529),
    "東區尤德夫人那打素醫院": (22.270224, 114.236770),
    "明愛醫院": (22.341558, 114.153395),
    "基督教聯合醫院": (22.322499, 114.227379),
    "東華醫院": (22.285424, 114.146855),
    "美孚新邨": (22.335798, 114.139961),
    "太古城": (22.287585, 114.215207),
    "順安邨": (22.328181, 114.225992),
    "沙田醫院": (22.399008, 114.213111),
    "啟業邨": (22.328573, 114.208407),
    "漁灣邨": (22.266041, 114.241501),
    "禾輋邨": (22.388055, 114.195404),
    "堅尼地城": (22.282435, 114.128417),
    "伊利沙伯醫院": (22.3092, 114.1754),
    "廣華醫院": (22.3154, 114.1724),
    "香港眼科醫院": (22.3236, 114.1804),
    "九龍醫院": (22.3248, 114.1806),
}

# Checked before street rules so hospital names are not left without a district.
HOSPITAL_DISTRICTS = [
    ("伊利沙伯", "ytm"),
    ("廣華醫院", "ytm"),
    ("香港眼科醫院", "kc"),
    ("九龍醫院", "kc"),
    ("東華東院", "wc"),
    ("東華醫院", "cw"),
    ("瑪麗醫院", "sou"),
    ("贊育醫院", "cw"),
    ("葛量洪", "sou"),
    ("律敦治", "wc"),
    ("鄧肇堅", "wc"),
    ("長洲醫院", "is"),
]

# Pins corrected after a bad geocode. Applied by exact unit or place name.
PIN_OVERRIDES = {
    "沙田多元化金齡服務中心": (22.385041, 114.191529),
    "路德會富欣花園長者中心": (22.265422, 114.248968),
    "雅研社鄰里康齡中心": (22.2828, 114.1302),
    "嘉頤薈": (22.372069, 114.198003),
    "明愛麗閣苑": (22.332790, 114.157135),
    "恩耆頤養院": (22.319305, 114.232632),
    "救世軍德田長者之家": (22.308646, 114.239080),
    "嘉瑞園護養院": (22.329346, 114.150944),
    "東華三院陳嫺安老院": (22.419827, 114.230876),
    "明儒松柏社區服務中心-家居照顧及支援服務隊 (東區)": (22.284420, 114.222578),
}

NOISE_KEYWORDS = {
    "電郵", "其他", "醫院", "西南", "東北", "東南", "西北", "備註", "附註",
    "例如", "以及", "或者", "本部", "分處", "辦事處", "病人", "病房", "資源",
    "除外", "計劃", "下載", "版本", "表格", "附件", "註釋", "名稱", "電話",
}

HOSPITAL_ALIASES = {
    "威爾斯親王醫院": ["威院", "Prince of Wales Hospital", "PWH"],
    "東區尤德夫人那打素醫院": ["東區醫院", "PYNEH", "Pamela Youde Nethersole Eastern Hospital"],
    "明愛醫院": ["Caritas Medical Centre"],
    "基督教聯合醫院": ["聯合醫院", "United Christian Hospital", "UCH"],
    "東華醫院": ["Tung Wah Hospital"],
    "沙田醫院": ["Shatin Hospital"],
    "瑪麗醫院": ["Queen Mary Hospital", "QMH"],
}

ESTATE_EN = {
    "瀝源邨": "Lek Yuen Estate",
    "美孚新邨": "Mei Foo Sun Chuen",
    "太古城": "Taikoo Shing",
    "啟業邨": "Kai Yip Estate",
    "順安邨": "Shun On Estate",
    "禾輋邨": "Wo Che Estate",
    "漁灣邨": "Yue Wan Estate",
    "水泉澳邨": "Shui Chuen O Estate",
    "榮昌邨": "Wing Cheong Estate",
    "愛東邨": "Oi Tung Estate",
    "興華邨": "Hing Wah Estate",
    "小西灣邨": "Siu Sai Wan Estate",
}

PLACE_RE = re.compile(r"[\u4e00-\u9fff]{2,14}(?:邨|苑|花園|大廈|廣場|中心|閣|軒|臺|台|居|城|灣|庭|峰|園)")
STREET_RE = re.compile(r"[\u4e00-\u9fff]{2,10}(?:街|道|路|里|徑|坊|巷)")
PHONE_RE = re.compile(r"\d{4}\s?\d{4}")


def sid(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def deprivate(text: str) -> str:
    # SWD spreadsheets still use HKSCS private-use code points for two characters.
    return (text or "").replace("\ue473", "邨").replace("\ue88c", "埗")


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", deprivate(text)).strip()


def phone_fmt(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 8:
        return f"{digits[:4]} {digits[4:]}"
    return squash(raw)


def phones_in(text: str) -> list[str]:
    found = []
    for raw in PHONE_RE.findall(text or ""):
        fmt = phone_fmt(raw)
        if fmt not in found:
            found.append(fmt)
    return found


def pkey(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def zh_lines(text: str) -> list[str]:
    text = deprivate(str(text or ""))
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip(">").strip()
        if re.search(r"[\u4e00-\u9fff]", line):
            out.append(line)
    return out


def first_zh(text: str) -> str:
    lines = zh_lines(text)
    return lines[0] if lines else ""


def join_zh(text: str) -> str:
    lines = zh_lines(text)
    return "；".join(lines)


def bad_keyword(tok: str) -> bool:
    if not tok or len(tok) < 2:
        return True
    blocked = (
        "服務", "福利", "家庭", "社署", "共同", "提供", "分界", "以上", "以下",
        "單數", "雙數", "全部", "電話", "傳真", "星期", "查詢", "開放", "地域",
        "名單", "註", "機構", "地址", "序號", "住宅", "範圍", "包括", "部份", "部分",
    )
    if any(x in tok for x in blocked):
        return True
    if tok in NOISE_KEYWORDS or any(noise in tok for noise in ("電郵", "辦事處分處", "居者有其屋", "私人屋苑", "公營屋邨")):
        return True
    if any(mark in tok for mark in ("沿", "至", "經", "向")) or tok.startswith(("由", "再", "近", "從")):
        return True
    if "號" in tok and not tok.endswith("號"):
        return True
    if re.search(r"[A-Za-z0-9]", tok):
        return True
    if tok in {"中心", "社區", "地區", "香港", "九龍", "新界", "單位", "樓宇", "街道", "屋邨"}:
        return True
    return False


def keywords_from_text(text: str) -> list[str]:
    found: set[str] = set()
    for match in PLACE_RE.finditer(text or ""):
        tok = match.group()
        if not bad_keyword(tok):
            found.add(tok)
    for match in STREET_RE.finditer(text or ""):
        tok = match.group()
        if not bad_keyword(tok):
            found.add(tok)
    for part in re.split(r"[、，,；;\n/（）()\[\]【】]+", text or ""):
        part = part.strip()
        if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", part) and not bad_keyword(part):
            found.add(part)
    # Longer, more specific names first.
    return sorted(found, key=lambda s: (-len(s), s))[:120]


def infer_district(text: str) -> str:
    for needle, code in HOSPITAL_DISTRICTS:
        if needle in text:
            return code
    for code, keys in ADDRESS_RULES:
        if any(k in text for k in keys):
            return code
    return ""


def manual_coord(*texts: str) -> tuple[float, float] | None:
    blob = " ".join(texts)
    best = None
    best_len = 0
    for key, coord in MANUAL_COORDS.items():
        if key in blob and len(key) > best_len:
            best = coord
            best_len = len(key)
    return best


def ensure_cache() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    staged = Path("/tmp/swd")
    if staged.exists():
        for path in staged.glob("*"):
            if path.is_file():
                dest = CACHE / path.name
                if not dest.exists():
                    shutil.copy(path, dest)
        files = staged / "files"
        if files.exists():
            for path in files.iterdir():
                if path.is_file():
                    dest = CACHE / path.name
                    if not dest.exists():
                        shutil.copy(path, dest)


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 800:
        return
    print("download", dest.name)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as response:
        dest.write_bytes(response.read())
    time.sleep(0.35)


def centre_group(filename: str) -> str:
    upper = filename.upper()
    if "CWSI" in upper:
        return "cwsi"
    if "WTSSK" in upper:
        return "wtssk"
    if "KCYTM" in upper:
        return "kcytm"
    if "TPN" in upper:
        return "tpn"
    if "TWKWT" in upper:
        return "twkw"
    if "EW_" in upper:
        return "ew"
    if "SSP" in upper:
        return "ssp"
    if "YL_" in upper:
        return "yl"
    if "TM_" in upper:
        return "tm"
    if "KT_" in upper:
        return "kt"
    if "ST_" in upper:
        return "st"
    return ""


def discover_centre_workbooks() -> list[dict]:
    html = (CACHE / "csse.html").read_text(encoding="utf-8", errors="ignore")
    found = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, flags=re.S):
        excel = re.search(r'href="([^"]+\.(?:xls|xlsx))"', row, flags=re.I)
        pdf = re.search(r'href="([^"]+\.pdf)"', row, flags=re.I)
        if not excel:
            continue
        url = urllib.parse.urljoin(SWD, excel.group(1))
        filename = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        group = centre_group(filename)
        if not group:
            print("skip unrecognised centre workbook", filename)
            continue
        found.append({
            "file": filename,
            "url": url,
            "pdf": urllib.parse.urljoin(SWD, pdf.group(1)) if pdf else "",
            "group": group,
        })
    if len(found) < 8:
        raise RuntimeError(f"expected territory-wide centre workbooks, found {len(found)}")
    return found


def fetch_inputs() -> None:
    ensure_cache()
    pages = {
        "ifsc.html": f"{SWD}/tc/pubsvc/family/cat_family/ifs/ifscbydistrict/index.html",
        "csse.html": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_csse/index.html",
        "ccse.html": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_ccse/",
        "mss.html": f"{SWD}/tc/pubsvc/medical/cat_medical/medicalsoc/",
    }
    for name, url in pages.items():
        download(url, CACHE / name)
    for item in discover_centre_workbooks():
        download(item["url"], CACHE / item["file"])
    files = {
        "mssu-swd.docx": f"{SWD}/storage/asset/section/290/tc/MSSU-SWD_Chi_102026.docx",
        "mssu-ha.docx": f"{SWD}/storage/asset/section/290/tc/MSSU-HA_Chi_082025.docx",
        "ehcs.xlsx": f"{SWD}/storage/asset/section/734/en/List%20of%20Home%20Care%20and%20Support%20Services%20Teams_TC_Eng%20(as%20at%2016%20Oct%202026).xlsx",
        "hss-boundary.pdf": f"{SWD}/storage/asset/section/734/tc/Service%20Boundary%20of%20HCSST%20of%20HSS_TC%20(26%20October%202026).pdf",
        "ifsc-address.pdf": f"{SWD}/storage/asset/section/260/tc/IFSC_ISC_address_list_tc_Feb_2026.pdf",
        "rche.xlsx": f"{SWD}/storage/asset/section/177/List%20of%20RCHE/4_%20List%20of%20RCHEs%20Providing%20Subsidised%20Places%20for%20the%20Elderly_Q(30_9_2026)_ENG%26TC.xlsx",
    }
    for name, url in files.items():
        download(url, CACHE / name)


def read_table(path: Path) -> list[list]:
    if path.suffix.lower() == ".xls":
        book = xlrd.open_workbook(path)
        sheet = book.sheet_by_index(0)
        return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
    book = load_workbook(path, data_only=True, read_only=True)
    sheet = book.active
    return [[cell if cell is not None else "" for cell in row] for row in sheet.iter_rows(values_only=True)]


def district_for_centre(group: str, address: str, name: str) -> str:
    blob = address + name
    if group == "cwsi":
        found = infer_district(blob)
        return found if found in {"cw", "sou", "is"} else "cw"
    if group == "ew":
        if any(key in address for key in ["北角", "柴灣", "筲箕灣", "西灣河", "鰂魚涌", "小西灣", "杏花", "太古", "康山"]):
            return "e"
        return "e" if infer_district(address) == "e" else "wc"
    if group == "wtssk":
        found = infer_district(blob)
        if found in {"wts", "sk"}:
            return found
        return "sk" if any(key in blob for key in ["將軍澳", "西貢", "坑口", "調景嶺", "寶琳"]) else "wts"
    if group == "kcytm":
        found = infer_district(address)
        return found if found in {"kc", "ytm"} else "ytm"
    if group == "tpn":
        found = infer_district(blob)
        if found in {"tp", "n"}:
            return found
        return "n" if any(key in blob for key in ["上水", "粉嶺"]) else "tp"
    if group == "twkw":
        found = infer_district(blob)
        if found in {"tw", "kwt"}:
            return found
        return "kwt" if any(key in blob for key in ["葵涌", "青衣", "葵青"]) else "tw"
    return {"kt": "kt", "ssp": "ssp", "st": "st", "yl": "yl", "tm": "tm"}.get(group, "")


def source_for_centre(district: str) -> dict[str, str]:
    mapping = {
        "cw": ("中西南及離島區長者中心服務範圍", f"{SWD}/storage/asset/section/733/CWSI_Service_boundary_of_Elderly_Centre.pdf"),
        "sou": ("中西南及離島區長者中心服務範圍", f"{SWD}/storage/asset/section/733/CWSI_Service_boundary_of_Elderly_Centre.pdf"),
        "is": ("中西南及離島區長者中心服務範圍", f"{SWD}/storage/asset/section/733/CWSI_Service_boundary_of_Elderly_Centre.pdf"),
        "e": ("東區及灣仔區長者中心服務範圍", f"{SWD}/storage/asset/section/733/tc/EW_Service_boundary_of_Elderly_Centre.pdf"),
        "wc": ("東區及灣仔區長者中心服務範圍", f"{SWD}/storage/asset/section/733/tc/EW_Service_boundary_of_Elderly_Centre.pdf"),
        "kt": ("觀塘區長者中心服務範圍", f"{SWD}/storage/asset/section/733/tc/KT_Service_boundary_of_Elderly_Centre.pdf"),
        "ssp": ("深水埗區長者中心服務範圍", f"{SWD}/storage/asset/section/733/tc/SSP_Service_boundary_of_Elderly_Centre.pdf"),
        "st": ("沙田區長者中心服務範圍", f"{SWD}/storage/asset/section/733/tc/ST_Service_boundary_of_Elderly_Centre.pdf"),
    }
    title, url = mapping[district]
    return {
        "sourceTitle": title,
        "sourceUrl": url,
        "sourcePage": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_csse/",
    }


def parse_centres() -> list[dict]:
    specs = discover_centre_workbooks()
    units = []
    for spec in specs:
        filename = spec["file"]
        group = spec["group"]
        rows = read_table(CACHE / filename)
        header_row = None
        headers: list[str] = []
        for r, row in enumerate(rows[:10]):
            vals = [str(cell) for cell in row]
            if any("Centre" in value for value in vals) and any("Address" in value for value in vals):
                header_row = r
                headers = vals
                break
        if header_row is None:
            raise RuntimeError(f"no header in {filename}")

        def col(*names: str) -> int:
            for i, header in enumerate(headers):
                if any(name.lower() in header.lower() for name in names):
                    return i
            raise RuntimeError(f"{filename} missing {names}")

        i_agency = col("Agency")
        i_centre = col("Centre")
        i_type = col("Type of Centre", "Type")
        i_addr = col("Address")
        i_tel = col("Tel")
        i_area = col("Service Area")
        previous = None
        for r in range(header_row + 2, len(rows)):
            row = rows[r]
            def cell(index: int) -> str:
                return str(row[index]) if index < len(row) and row[index] is not None else ""

            centre_raw = cell(i_centre)
            area_raw = deprivate(cell(i_area))
            if "Cont'd" in centre_raw or "續" in centre_raw:
                if previous is not None:
                    extra_zh = join_zh(area_raw)
                    extra_en = "\n".join(
                        line.strip()
                        for line in area_raw.splitlines()
                        if line.strip() and not re.search(r"[\u4e00-\u9fff]", line)
                    )
                    if extra_zh:
                        previous["serviceArea"] = (previous["serviceArea"] + "\n" + extra_zh).strip()
                    if extra_en:
                        previous["searchText"] = (previous["searchText"] + "\n" + extra_en).strip()
                    previous["keywords"] = keywords_from_text(
                        previous["serviceArea"] + "\n" + previous["searchText"]
                    )
                continue
            name = first_zh(centre_raw) or squash(centre_raw)
            if not name or name in {"中心", "Centre"}:
                continue
            address = join_zh(cell(i_addr)) or squash(cell(i_addr))
            type_raw = cell(i_type)
            kind = "decc" if ("地區中心" in type_raw or "District Elderly" in type_raw) else "nec"
            district = district_for_centre(group, address, name)
            nums = phones_in(cell(i_tel))
            phone = nums[0] if nums else ""
            zh_area = "\n".join(zh_lines(area_raw))
            en_area = "\n".join(
                line.strip() for line in area_raw.splitlines() if line.strip() and not re.search(r"[\u4e00-\u9fff]", line)
            )
            src = {
                "sourceTitle": "長者地區中心及長者鄰舍中心服務範圍",
                "sourceUrl": spec.get("pdf") or f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_csse/",
                "sourcePage": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_csse/",
            }
            unit = {
                "id": sid("centre", district, name, address[:24]),
                "type": kind,
                "name": name,
                "operator": first_zh(cell(i_agency)) or squash(cell(i_agency)),
                "district": district,
                "address": address,
                "phone": phone,
                "hours": "",
                "serviceArea": zh_area,
                "searchText": en_area,
                "keywords": keywords_from_text(zh_area + "\n" + en_area),
                "mapUrl": "",
                **src,
            }
            units.append(unit)
            previous = unit
    return units


def parse_mssu() -> list[dict]:
    specs = [
        ("mssu-swd.docx", "社會福利署", f"{SWD}/storage/asset/section/290/tc/MSSU-SWD_Chi_102026.pdf", f"{SWD}/tc/pubsvc/medical/cat_medical/medicalsoc/", "https://www.map.gov.hk/gm/map/search/faci/MSS?lg=tc", "社署醫務社會服務單位名單（2026年10月）"),
        ("mssu-ha.docx", "醫院管理局", f"{SWD}/storage/asset/section/290/tc/MSSU-HA_Chi_082025.pdf", f"{SWD}/tc/pubsvc/medical/cat_medical/medicalsoc/", "https://www.map.gov.hk/gm/map/search/faci/HAMSSU?lg=tc", "醫管局醫務社會服務單位名單（2025年8月）"),
    ]
    units = []
    for filename, operator, pdf, page, map_url, title in specs:
        document = Document(CACHE / filename)
        for table in document.tables:
            for row in table.rows[1:]:
                cells = [squash(c.text) for c in row.cells]
                if len(cells) < 4:
                    continue
                # Some rows repeat a section label in every cell.
                if len(set(cells)) <= 2:
                    continue
                name = cells[1]
                if not re.search(r"[\u4e00-\u9fff]", name):
                    continue
                if any(k in name for k in ["兒童體能", "智力測驗", "醫院／診所", "醫院名稱", "辦事處分處"]):
                    continue
                if name in {"分處", "辦事處", "地址", "電話號碼", "開放時間"}:
                    continue
                address = cells[2]
                nums = phones_in(cells[3])
                # Title rows and split header cells have hours but no contact.
                if not address or not nums:
                    continue
                hours = squash(cells[5]) if len(cells) > 5 else ""
                district = infer_district(name + address)
                keyword_names = []
                for label in (re.sub(r"[（(].*?[）)]", "", name).strip(), name):
                    if label and label not in keyword_names:
                        keyword_names.append(label)
                units.append({
                    "id": sid("mssu", operator, name, address, " / ".join(nums)),
                    "type": "mssu",
                    "name": name,
                    "operator": operator,
                    "district": district,
                    "address": address,
                    "phone": " / ".join(nums),
                    "hours": hours,
                    "serviceArea": name,
                    "searchText": name,
                    "keywords": keyword_names,
                    "mapUrl": map_url,
                    "sourceTitle": title,
                    "sourceUrl": pdf,
                    "sourcePage": page,
                })
    return units


def parse_ifsc_catalog() -> list[dict]:
    html = (CACHE / "ifsc.html").read_text(encoding="utf-8", errors="ignore")
    centres = []
    section = ""
    for row in re.findall(r"<tr>(.*?)</tr>", html, flags=re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
        if len(cells) < 3:
            continue

        def clean(value: str) -> str:
            value = re.sub(r"<[^>]+>", "", value)
            value = value.replace("\xa0", "").replace("&nbsp;", "")
            return re.sub(r"\s+", "", value).strip()

        name = clean(cells[0]).replace("*", "")
        operator = clean(cells[1])
        if operator == "社署":
            operator = "社會福利署"
        pdf = re.search(r'href="([^"]+\.pdf)"', cells[2])
        mp = re.search(r'href="(https://www\.map\.gov\.hk[^"]+)"', cells[2])
        if not pdf:
            section = name
            continue
        if "綜合" not in name and "家庭" not in name:
            section = name
            continue
        centres.append({
            "section": section,
            "name": name,
            "operator": operator,
            "pdf": urllib.parse.urljoin(SWD, pdf.group(1)),
            "map": mp.group(1) if mp else "",
        })

    document = pymupdf.open(CACHE / "ifsc-address.pdf")
    lines = "\n".join(page.get_text(sort=True) for page in document).splitlines()
    records = []
    for index, line in enumerate(lines):
        match = re.search(r"(\d{4} \d{4})\s+(\d{4} \d{4})", line)
        if not match:
            continue
        pre = line[: match.start()].strip()
        cols = re.split(r"\s{2,}", pre)
        address = tidy_address(cols[-1].strip() if cols else pre)
        if index + 1 < len(lines):
            nxt = lines[index + 1].strip()
            floor = re.search(r"([0-9A-Z及至\-–－]+樓)\s*$", nxt)
            if floor and "中心" in nxt and floor.group(1) not in address:
                address += floor.group(1)
            if "分處" in nxt:
                frag = re.sub(r"\s+", "", nxt.split("分處", 1)[-1])
                frag = re.sub(r"^[:：︰]+", "", frag)
                if frag:
                    address += "；分處：" + frag
        records.append({"address": address, "phone": match.group(1)})

    if len(records) != len(centres):
        raise RuntimeError(f"IFSC address rows {len(records)} != centres {len(centres)}")

    name_rules = [
        ("東涌", "is"), ("香港仔", "sou"), ("田灣", "sou"), ("薄扶林", "sou"),
        ("中區及離島", "cw"), ("高街", "cw"), ("恩悅", "cw"),
        ("銅鑼灣", "wc"), ("灣仔", "wc"),
        ("北角", "e"), ("鰂魚涌", "e"), ("柴灣", "e"), ("筲箕灣", "e"),
        ("啟坪", "kt"), ("秀寶", "kt"), ("藍田", "kt"), ("牛頭角", "kt"),
        ("順利", "kt"), ("油塘", "kt"), ("活力", "kt"),
        ("長沙灣", "ssp"), ("大坑東", "ssp"), ("深水埗", "ssp"), ("家情", "ssp"),
        ("馬鞍山", "st"), ("沙田", "st"), ("蘇沙", "st"),
        ("將軍澳", "sk"), ("西貢", "sk"), ("慈雲山", "wts"), ("黃大仙", "wts"), ("東頭", "wts"),
        ("啟德", "kc"), ("馬頭圍", "kc"), ("土瓜灣", "kc"), ("紅磡", "kc"),
        ("油麻地", "ytm"), ("旺角", "ytm"), ("天倫", "ytm"),
        ("粉嶺", "n"), ("上水", "n"), ("大埔", "tp"),
        ("天水圍", "yl"), ("元朗", "yl"), ("朗情", "yl"),
        ("青衣", "kwt"), ("葵涌", "kwt"), ("荃灣", "tw"),
        ("屯門", "tm"),
    ]
    section_fallback = {
        "觀塘區": "kt", "深水埗區": "ssp", "沙田區": "st", "元朗區": "yl", "屯門區": "tm",
    }
    units = []
    for centre, record in zip(centres, records):
        district = ""
        for key, code in name_rules:
            if key in centre["name"]:
                district = code
                break
        if not district:
            district = infer_district(record["address"] + centre["name"]) or section_fallback.get(centre["section"], "")
        if not district:
            print("IFSC district unresolved", centre["section"], centre["name"])
        pdf_name = centre["pdf"].rsplit("/", 1)[-1]
        local = CACHE / pdf_name
        download(centre["pdf"], local)
        keywords: list[str] = []
        try:
            pdf = pymupdf.open(local)
            text = "\n".join(page.get_text() for page in pdf)
            keywords = keywords_from_text(text)
        except Exception as exc:  # noqa: BLE001
            print("boundary parse failed", pdf_name, exc)
        area = "、".join(keywords[:24])
        units.append({
            "id": sid("ifsc", centre["name"]),
            "type": "ifsc",
            "name": centre["name"],
            "operator": centre["operator"],
            "district": district,
            "address": record["address"],
            "phone": record["phone"],
            "hours": "",
            "serviceArea": area,
            "searchText": " ".join(keywords),
            "keywords": keywords,
            "mapUrl": centre["map"],
            "sourceTitle": f"{centre['name']}服務地域範圍",
            "sourceUrl": centre["pdf"],
            "sourcePage": f"{SWD}/tc/pubsvc/family/cat_family/ifs/ifscbydistrict/index.html",
        })
    return units


def parse_hss() -> list[dict]:
    text = subprocess.check_output(
        ["pdftotext", "-layout", str(CACHE / "hss-boundary.pdf"), "-"],
        text=True,
        errors="ignore",
    )
    parts = re.split(r"([^\n]{2,16}區)\s*家居支援服務的服務範圍", text)
    bodies = {label.strip(): body for label, body in zip(parts[1::2], parts[2::2])}
    teams_by_phone: dict[str, dict] = {}
    book = load_workbook(CACHE / "ehcs.xlsx", data_only=True)
    sheet = book.active
    for row in sheet.iter_rows(min_row=4, values_only=True):
        if not row or not row[1] or not row[3]:
            continue
        district_name = squash(str(row[1]))
        district = ""
        for code, label in sorted(DISTRICT_NAME.items(), key=lambda item: -len(item[1])):
            if label and label in district_name:
                district = code
                break
        if not district:
            district = infer_district(district_name)
        info = {
            "name": squash(str(row[3])),
            "operator": squash(str(row[2] or "")),
            "address": " ".join(zh_lines(str(row[4] or ""))) or squash(str(row[4] or "")),
            "district": district,
            "fax": phone_fmt(str(row[10] or "")) if row[10] else "",
        }
        for phone in phones_in(str(row[9] or "")):
            teams_by_phone.setdefault(pkey(phone), info)

    section_code = {
        "中西區": "cw", "東區": "e", "灣仔區": "wc", "南區": "sou", "離島區": "is",
        "觀塘區": "kt", "黃大仙區": "wts", "西貢區": "sk", "油尖旺區": "ytm",
        "九龍城區": "kc", "深水埗區": "ssp", "沙田區": "st", "大埔區": "tp",
        "北區": "n", "元朗區": "yl", "屯門區": "tm", "荃灣及葵青區": "twkw",
    }
    units = []
    pdf_url = f"{SWD}/storage/asset/section/734/tc/Service%20Boundary%20of%20HCSST%20of%20HSS_TC%20(26%20October%202026).pdf"
    page = f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_ccse/"
    for label, body in bodies.items():
        tels = list(re.finditer(r"(\d{4} \d{4})(?=\s*/)", body))
        for index, match in enumerate(tels):
            phone = match.group(1)
            end = tels[index + 1].start() if index + 1 < len(tels) else len(body)
            chunk = body[match.end() : end]
            kept = []
            for line in chunk.splitlines():
                if re.match(r"\s*\d+[A-Z]?\s+[\u4e00-\u9fff]", line):
                    break
                if any(token in line for token in ["服務隊", "序號", "機構"]):
                    # Keep the line only when it also carries estate names.
                    if not any(mark in line for mark in ["邨", "苑", "、"]):
                        continue
                if "、" in line or "包括" in line or "全島" in line or any(
                    mark in line for mark in ["邨", "苑", "街", "道"]
                ):
                    kept.append(line)
            preview = re.sub(r"\s+", "", "".join(kept))
            preview = re.sub(r"\d{8}", "", preview).replace("/", "")
            preview = re.sub(r"(家居照顧及支援|援服務隊|服務隊|序號機構服務單位地址電話傳真服務範圍)", "", preview)
            keywords = keywords_from_text(preview)
            info = teams_by_phone.get(pkey(phone), {})
            district = info.get("district") or section_code.get(label, infer_district(label))
            name = tidy_hss_name(info.get("name") or f"{DISTRICT_NAME.get(district, label)}家居支援服務隊")
            units.append({
                "id": sid("hss", phone, name),
                "type": "hss",
                "name": name,
                "operator": info.get("operator") or "",
                "district": district,
                "address": info.get("address") or "地址見社署家居支援服務範圍文件",
                "phone": phone,
                "hours": "家居支援服務隊的辦公時間見名冊；範圍內細節以文件為準",
                "serviceArea": "、".join(keywords[:28]),
                "searchText": preview[:800],
                "keywords": keywords,
                "mapUrl": "",
                "sourceTitle": "各區家居照顧及支援服務隊（家居支援服務）服務範圍",
                "sourceUrl": pdf_url,
                "sourcePage": page,
            })
    return units


def tidy_hss_name(name: str) -> str:
    name = squash(name)
    if re.search(r"(?:^|\s)i\)", name, flags=re.I):
        name = re.sub(r"^[ivx]+\)\s*", "", name, flags=re.I)
        name = re.split(r"\s+[ivx]+\)\s*", name, maxsplit=1, flags=re.I)[0].strip(" ；;")
    return name or "家居支援服務隊"


def tidy_address(pre: str) -> str:
    markers = ["香港", "九龍", "新界", "大嶼山", "西貢", "將軍澳"]
    candidates: list[str] = []
    for marker in markers:
        start = 0
        while True:
            index = pre.find(marker, start)
            if index < 0:
                break
            candidates.append(pre[index:].strip())
            start = index + len(marker)
    numbered = [item for item in candidates if "號" in item]
    pool = numbered or candidates
    address = min(pool, key=len) if pool else pre.strip()
    return address.replace("香港香港", "香港").replace("九龍九龍", "九龍")


def strip_mark(text: str) -> str:
    return re.sub(r"[†@*#±&]", "", text or "").strip()


def parse_rche_places(ifsc_units: list[dict]) -> list[dict]:
    keys_by_district: dict[str, set[str]] = {}
    for unit in ifsc_units:
        keys_by_district.setdefault(unit["district"], set()).update(
            k for k in unit["keywords"] if k.endswith(("邨", "苑", "花園", "大廈"))
        )
    book = load_workbook(CACHE / "rche.xlsx", data_only=True)
    sheet = book.active
    picked: dict[str, list[dict]] = {}
    for row in sheet.iter_rows(min_row=5, values_only=True):
        if not row or not row[1] or not row[3] or not row[4]:
            continue
        district = infer_district(str(row[1]))
        if district not in DISTRICT_NAME or district == "twkw":
            continue
        name_lines = [strip_mark(line) for line in str(row[3]).splitlines() if line.strip()]
        zh_name = next((line for line in name_lines if re.search(r"[\u4e00-\u9fff]", line)), "")
        en_name = next((line for line in name_lines if line and line != zh_name), "")
        address = join_zh(str(row[4])) or squash(str(row[4]))
        phone_nums = phones_in(str(row[5] or ""))
        if not zh_name or not phone_nums:
            continue
        matched = [key for key in keys_by_district.get(district, set()) if key and key in address]
        matched.sort(key=len, reverse=True)
        if not matched:
            continue
        picked.setdefault(district, []).append({
            "id": sid("rche", zh_name),
            "name": zh_name,
            "aliases": [en_name] if en_name else [],
            "kind": "rche",
            "district": district,
            "address": address,
            "phone": phone_nums[0],
            "areaKeys": matched[:2],
            "featured": False,
            "lat": None,
            "lng": None,
        })
    places = []
    for district, rows in picked.items():
        rows.sort(key=lambda item: (len(item["name"]) > 18, len(item["name"]), -len(item["areaKeys"][0])))
        # Two homes per focus district, preferring different estates.
        seen = set()
        for item in rows:
            estate = item["areaKeys"][0]
            if estate in seen:
                continue
            seen.add(estate)
            item["featured"] = True
            places.append(item)
            if len(seen) >= 2:
                break
    return places


def build_places(units: list[dict], rche_places: list[dict]) -> list[dict]:
    places: dict[str, dict] = {}

    def add(place: dict) -> None:
        key = f"{place['kind']}|{place['district']}|{place['name']}"
        current = places.get(key)
        if current is None:
            places[key] = place
            return
        alias = set(current["aliases"]) | set(place["aliases"])
        keys = set(current["areaKeys"]) | set(place["areaKeys"])
        current["aliases"] = sorted(alias)
        current["areaKeys"] = sorted(keys, key=len, reverse=True)
        current["featured"] = current["featured"] or place["featured"]
        if current["lat"] is None and place.get("lat") is not None:
            current["lat"] = place["lat"]
            current["lng"] = place["lng"]

    for unit in units:
        if unit["type"] != "mssu":
            continue
        base = re.sub(r"\s*[（(].*?[）)]", "", unit["name"]).strip()
        if not unit["district"]:
            continue
        add({
            "id": sid("place", "hospital", base),
            "name": base,
            "aliases": HOSPITAL_ALIASES.get(base, []),
            "kind": "hospital",
            "district": unit["district"],
            "address": unit["address"],
            "phone": "",
            "areaKeys": [base],
            "featured": base in HOSPITAL_ALIASES,
            "lat": None,
            "lng": None,
        })

    for unit in units:
        if unit["type"] not in {"decc", "nec", "ifsc", "hss"}:
            continue
        if not unit["district"]:
            continue
        for keyword in unit["keywords"]:
            if not keyword.endswith(("邨", "苑", "花園")) or len(keyword) < 3:
                continue
            if bad_keyword(keyword):
                continue
            aliases = [ESTATE_EN[keyword]] if keyword in ESTATE_EN else []
            add({
                "id": sid("place", "estate", unit["district"], keyword),
                "name": keyword,
                "aliases": aliases,
                "kind": "estate",
                "district": unit["district"],
                "address": f"{DISTRICT_NAME.get(unit['district'], '')}{keyword}",
                "phone": "",
                "areaKeys": [keyword],
                "featured": keyword in ESTATE_EN,
                "lat": None,
                "lng": None,
            })

    add({
        "id": sid("place", "estate", "e", "太古城"),
        "name": "太古城",
        "aliases": ["Taikoo Shing"],
        "kind": "estate",
        "district": "e",
        "address": "香港東區太古城",
        "phone": "",
        "areaKeys": ["太古城"],
        "featured": True,
        "lat": 22.287585,
        "lng": 114.215207,
    })
    add({
        "id": sid("place", "area", "cw", "堅尼地城"),
        "name": "堅尼地城",
        "aliases": ["Kennedy Town", "堅尼地城卑路乍街"],
        "kind": "area",
        "district": "cw",
        "address": "香港島中西區堅尼地城",
        "phone": "",
        "areaKeys": ["堅尼地城"],
        "featured": True,
        "lat": None,
        "lng": None,
    })
    for place in rche_places:
        add(place)
    return list(places.values())


def load_geo_cache() -> dict:
    if GEO_CACHE_PATH.exists():
        return json.loads(GEO_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_geo_cache(cache: dict) -> None:
    GEO_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def in_hk(lat: float, lng: float) -> bool:
    return 22.08 <= lat <= 22.62 and 113.75 <= lng <= 114.55


def nominatim(query: str, cache: dict) -> dict | None:
    key = "nom:" + query
    if key in cache:
        return cache[key]
    params = urllib.parse.urlencode({
        "format": "jsonv2",
        "limit": "1",
        "viewbox": "113.80,22.60,114.50,22.10",
        "bounded": "1",
        "accept-language": "zh-HK",
        "q": query,
    })
    url = "https://nominatim.openstreetmap.org/search?" + params
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-HK"})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("nominatim error", query, exc)
        time.sleep(2)
        cache[key] = None
        return None
    time.sleep(1.05)
    if not data:
        cache[key] = None
        return None
    item = data[0]
    lat = float(item["lat"])
    lng = float(item["lon"])
    if not in_hk(lat, lng):
        cache[key] = None
        return None
    if item.get("addresstype") in {"country", "state", "province"}:
        cache[key] = None
        return None
    result = {"lat": round(lat, 6), "lng": round(lng, 6), "label": item.get("display_name", ""), "source": "nominatim"}
    cache[key] = result
    return result


def photon(query: str, cache: dict) -> dict | None:
    key = "photon:" + query
    if key in cache:
        return cache[key]
    url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode({
        "q": query,
        "limit": "1",
        "lang": "en",
        "lat": "22.35",
        "lon": "114.15",
    })
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("photon error", query, exc)
        cache[key] = None
        return None
    time.sleep(0.25)
    features = data.get("features") or []
    if not features:
        cache[key] = None
        return None
    lng, lat = features[0]["geometry"]["coordinates"][:2]
    if not in_hk(lat, lng):
        cache[key] = None
        return None
    result = {
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "label": features[0]["properties"].get("name", query),
        "source": "photon",
    }
    cache[key] = result
    return result


def geocode_queries(queries: list[str], cache: dict) -> dict | None:
    seen: list[str] = []
    for query in queries:
        query = squash(query)
        if not query or query in seen or len(query) < 2:
            continue
        seen.append(query)
        if len(seen) > 3:
            break
        hit = nominatim(query, cache)
        if hit:
            return hit
    if seen:
        return photon(seen[0], cache)
    return None


PLACE_PREFIXES = tuple(sorted((
    "香港仔", "鴨脷洲", "香港", "九龍", "新界", "中西區", "東區", "觀塘", "深水埗", "沙田", "柴灣", "北角",
    "筲箕灣", "西灣河", "小西灣", "油塘", "藍田", "九龍灣", "牛頭角", "長沙灣", "石硤尾",
    "美孚", "大圍", "馬鞍山", "火炭", "西營盤", "上環", "中環", "堅尼地城",
), key=len, reverse=True))


def core_place(token: str) -> str:
    changed = True
    while changed and token:
        changed = False
        for prefix in PLACE_PREFIXES:
            if token.startswith(prefix) and len(token) > len(prefix) + 1:
                token = token[len(prefix):]
                changed = True
                break
    return token


def geo_queries_for_unit(unit: dict) -> list[str]:
    district = DISTRICT_NAME.get(unit["district"], "")
    queries: list[str] = []
    if unit["type"] == "mssu":
        base = re.sub(r"\s*[（(].*?[）)]", "", unit["name"]).strip()
        queries.extend([f"{base} 香港", f"{base} {district}"])
    for match in re.finditer(r"([\u4e00-\u9fff]{2,12})(邨|苑|花園|大廈|廣場)", unit["address"]):
        body = re.sub(r"^(?:香港|九龍|新界|號|室|樓)+", "", match.group(1))
        suffix = match.group(2)
        token = body + suffix
        if len(token) >= 3 and not bad_keyword(token):
            queries.append(f"{token} {district}")
        if len(body) > 3:
            tail = body[-3:] + suffix
            if tail != token and not bad_keyword(tail):
                queries.append(f"{tail} {district}")
    street = re.search(r"([\u4e00-\u9fff]{2,4})(街|道|路)", unit["address"])
    if street and not bad_keyword(street.group(1) + street.group(2)):
        queries.append(f"{street.group(1)}{street.group(2)} {district}")
        if len(street.group(1)) > 2:
            short_street = street.group(1)[-2:] + street.group(2)
            if not bad_keyword(short_street):
                queries.append(f"{short_street} {district}")
    deduped: list[str] = []
    for query in queries:
        if query not in deduped:
            deduped.append(query)
    return deduped[:4]


def wants_live_geocode(item: dict) -> bool:
    if item.get("lat") and item.get("lng"):
        return False
    district = item.get("district") or ""
    if item.get("kind"):
        return bool(item.get("featured"))
    return item.get("type") in {"decc", "nec", "ifsc", "hss", "mssu"}


def apply_coordinates(units: list[dict], places: list[dict], do_geocode: bool) -> None:
    cache = load_geo_cache()
    targets = units + places
    live_total = sum(1 for item in targets if do_geocode and wants_live_geocode(item))
    live_index = 0
    for item in targets:
        if item.get("lat") and item.get("lng"):
            item.setdefault("geoSource", item.get("geoSource") or "nominatim")
            continue
        manual = manual_coord(item.get("name", ""), item.get("address", ""), " ".join(item.get("areaKeys", [])))
        if not do_geocode or not wants_live_geocode(item):
            if manual:
                item["lat"], item["lng"] = manual
                item["geoSource"] = "nominatim-manual"
            else:
                item["lat"] = item["lng"] = None
                item["geoSource"] = ""
            continue
        queries = geo_queries_for_unit(item) if "type" in item else [
            f"{item['name']} {DISTRICT_NAME.get(item['district'], '')}",
            item["name"],
            item.get("address", ""),
        ]
        live_index += 1
        print(f"geo {live_index}/{live_total} {item.get('name','')[:28]}")
        hit = geocode_queries(queries, cache)
        if hit:
            item["lat"] = hit["lat"]
            item["lng"] = hit["lng"]
            item["geoSource"] = hit["source"]
        elif manual:
            item["lat"], item["lng"] = manual
            item["geoSource"] = "nominatim-manual"
        else:
            item["lat"] = item["lng"] = None
            item["geoSource"] = ""
        if live_index % 8 == 0:
            save_geo_cache(cache)
    save_geo_cache(cache)


def blank_geo(items: list[dict]) -> None:
    for item in items:
        item.setdefault("lat", None)
        item.setdefault("lng", None)
        item.setdefault("geoSource", "")


def choose_examples(units: list[dict], places: list[dict]) -> list[dict]:
    def hits(query: str, types: set[str], district: str | None = None) -> bool:
        for unit in units:
            if unit["type"] not in types:
                continue
            if district and unit["district"] != district:
                continue
            blob = unit["name"] + unit["serviceArea"] + unit.get("searchText", "") + " ".join(unit["keywords"])
            if query in blob:
                return True
        return False

    examples = []

    def add(example: dict, types: set[str]) -> None:
        district = example.get("district") or None
        if hits(example["query"], types, district if example["mode"] != "hss" else None):
            examples.append(example)
        else:
            print("example miss", example["query"], types)

    add({"id": "home-st", "mode": "assessment", "living": "home", "query": "瀝源邨", "district": "st", "label": "瀝源邨 · 沙田 · 住在家中"}, {"decc", "nec"})
    add({"id": "home-ssp", "mode": "assessment", "living": "home", "query": "美孚新邨", "district": "ssp", "label": "美孚新邨 · 深水埗 · 住在家中"}, {"decc", "nec"})
    add({"id": "home-kt", "mode": "assessment", "living": "home", "query": "啟業邨", "district": "kt", "label": "啟業邨 · 觀塘 · 住在家中"}, {"decc", "nec"})
    add({"id": "home-cw", "mode": "assessment", "living": "home", "query": "堅尼地城", "district": "cw", "label": "堅尼地城 · 中西區 · 住在家中"}, {"decc", "nec"})
    for query, district, label in [
        ("太古城", "e", "太古城 · 東區 · 住在家中"),
        ("漁灣邨", "e", "漁灣邨 · 東區 · 住在家中"),
        ("小西灣邨", "e", "小西灣邨 · 東區 · 住在家中"),
        ("興華邨", "e", "興華邨 · 東區 · 住在家中"),
    ]:
        if hits(query, {"decc", "nec"}, district):
            examples.append({"id": "home-e", "mode": "assessment", "living": "home", "query": query, "district": district, "label": label})
            break
    add({"id": "hosp-pwh", "mode": "assessment", "living": "hospital", "query": "威爾斯親王醫院", "district": "st", "label": "威爾斯親王醫院 · 住在醫院"}, {"mssu"})
    add({"id": "hosp-pyneh", "mode": "assessment", "living": "hospital", "query": "東區尤德夫人那打素醫院", "district": "e", "label": "東區尤德夫人那打素醫院 · 住在醫院"}, {"mssu"})
    add({"id": "hosp-cmc", "mode": "assessment", "living": "hospital", "query": "明愛醫院", "district": "ssp", "label": "明愛醫院 · 住在醫院"}, {"mssu"})
    add({"id": "hosp-uch", "mode": "assessment", "living": "hospital", "query": "基督教聯合醫院", "district": "kt", "label": "基督教聯合醫院 · 住在醫院"}, {"mssu"})
    add({"id": "hosp-twh", "mode": "assessment", "living": "hospital", "query": "東華醫院", "district": "cw", "label": "東華醫院 · 住在醫院"}, {"mssu"})

    rche_added = 0
    for place in places:
        if place["kind"] != "rche" or not place.get("featured"):
            continue
        estate = place["areaKeys"][0]
        if hits(estate, {"ifsc"}, place["district"]):
            examples.append({
                "id": f"rche-{place['district']}-{rche_added}",
                "mode": "assessment",
                "living": "rche",
                "query": place["name"],
                "district": place["district"],
                "label": f"{place['name']} · 住在院舍",
            })
            rche_added += 1
            if rche_added >= 5:
                break

    for query, district in [("太古城", "e"), ("啟業邨", "kt"), ("順安邨", "kt"), ("美孚新邨", "ssp"), ("瀝源邨", "st"), ("堅尼地城", "cw")]:
        if hits(query, {"hss"}, district):
            examples.append({
                "id": f"hss-{district}",
                "mode": "hss",
                "living": "home",
                "query": query,
                "district": district,
                "label": f"{query} · 家居支援服務",
            })
            break
    return examples


def load_previous_coords() -> dict:
    if not OUT.exists():
        return {}
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    saved = {}
    for item in data.get("units", []) + data.get("places", []):
        if item.get("lat") is None or item.get("lng") is None:
            continue
        key = (
            item.get("type") or item.get("kind"),
            item.get("name"),
            item.get("phone") or "",
            item.get("address") or "",
        )
        saved[key] = (item["lat"], item["lng"], item.get("geoSource") or "nominatim")
    return saved


def reuse_coordinates(items: list[dict], saved: dict) -> None:
    for item in items:
        key = (
            item.get("type") or item.get("kind"),
            item.get("name"),
            item.get("phone") or "",
            item.get("address") or "",
        )
        if key not in saved:
            continue
        item["lat"], item["lng"], item["geoSource"] = saved[key]


DISTRICT_ANCHORS = {
    "cw": (22.283, 114.150, 6),
    "e": (22.275, 114.230, 8),
    "wc": (22.278, 114.175, 5),
    "sou": (22.248, 114.160, 9),
    "kt": (22.315, 114.225, 7),
    "ssp": (22.335, 114.155, 6),
    "st": (22.390, 114.200, 12),
    "ytm": (22.312, 114.170, 5),
    "kc": (22.320, 114.190, 5),
    "wts": (22.342, 114.200, 6),
    "sk": (22.310, 114.260, 14),
    "is": (22.270, 113.950, 28),
    "tp": (22.450, 114.170, 14),
    "n": (22.500, 114.140, 14),
    "tm": (22.390, 113.970, 14),
    "yl": (22.450, 114.020, 16),
    "tw": (22.370, 114.120, 8),
    "kwt": (22.360, 114.130, 8),
    "twkw": (22.365, 114.125, 12),
}


def drop_far_coordinates(items: list[dict]) -> None:
    for item in items:
        lat, lng, district = item.get("lat"), item.get("lng"), item.get("district") or ""
        if lat is None or lng is None or district not in DISTRICT_ANCHORS:
            continue
        alat, alng, limit = DISTRICT_ANCHORS[district]
        distance = ((lat - alat) * 111) ** 2 + ((lng - alng) * 102) ** 2
        if distance ** 0.5 > limit:
            print("drop far pin", item.get("name", "")[:24], lat, lng)
            item["lat"] = None
            item["lng"] = None
            item["geoSource"] = ""


def apply_pin_overrides(items: list[dict]) -> None:
    for item in items:
        name = item.get("name") or ""
        if name in PIN_OVERRIDES:
            item["lat"], item["lng"] = PIN_OVERRIDES[name]
            item["geoSource"] = "nominatim"


def dedupe_units(units: list[dict]) -> list[dict]:
    kept: dict[tuple, dict] = {}
    order: list[tuple] = []
    for unit in units:
        key = (unit["type"], unit["name"], unit.get("phone") or "", unit.get("address") or "")
        previous = kept.get(key)
        if previous is None:
            kept[key] = unit
            order.append(key)
            continue
        if len(unit.get("keywords") or []) > len(previous.get("keywords") or []):
            kept[key] = unit
    return [kept[key] for key in order]


def assign_unit_ids(units: list[dict]) -> None:
    seen: set[str] = set()
    for index, unit in enumerate(units):
        unit["id"] = sid(
            unit["type"],
            unit["name"],
            unit.get("address") or "",
            unit.get("phone") or "",
            str(index),
        )
        if unit["id"] in seen:
            raise RuntimeError(f"duplicate unit id {unit['id']} for {unit['name']}")
        seen.add(unit["id"])


def validate_units(units: list[dict]) -> None:
    if any(unit["name"] == "辦事處分處" for unit in units):
        raise RuntimeError("辦事處分處 header row was kept")
    for unit in units:
        if unit["type"] != "mssu":
            continue
        if not unit.get("phone") or not unit.get("address"):
            raise RuntimeError(f"MSSU missing contact: {unit['name']}")
    blank = [unit["name"] for unit in units if unit["type"] == "mssu" and not unit.get("district")]
    if blank:
        print("MSSU still without district:", blank)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geocode", action="store_true", help="Fill coordinates via Nominatim, then Photon")
    args = parser.parse_args()
    previous_coords = load_previous_coords()
    fetch_inputs()
    centres = parse_centres()
    mssu = parse_mssu()
    ifsc = parse_ifsc_catalog()
    hss = parse_hss()
    units = dedupe_units(centres + mssu + ifsc + hss)
    assign_unit_ids(units)
    validate_units(units)
    rche = parse_rche_places(ifsc)
    places = build_places(units, rche)
    reuse_coordinates(units + places, previous_coords)
    apply_coordinates(units, places, args.geocode)
    drop_far_coordinates(units + places)
    apply_pin_overrides(units + places)
    examples = choose_examples(units, places)
    # Mark example targets featured.
    featured_queries = {example["query"] for example in examples}
    for place in places:
        if place["name"] in featured_queries or any(alias in featured_queries for alias in place["aliases"]):
            place["featured"] = True

    def count(kind: str) -> int:
        return sum(1 for unit in units if unit["type"] == kind)

    directory = {
        "title": "搵服務",
        "generatedFrom": "社會福利署公開名冊",
        "disclaimer": "本網站是非官方查詢工具，不是社會福利署、醫院管理局或任何資助機構的官方網站。資料整理自社署公開名單，只供查詢參考，不是福利申請的決定，亦不是法律意見。街號單雙數等服務範圍細節，請向單位或對照來源文件確認。",
        "districts": DISTRICTS,
        "sources": [
            {"id": "csse", "title": "社區支援服務：長者地區中心及長者鄰舍中心名單／服務範圍", "href": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_csse/"},
            {"id": "mss", "title": "醫務社會服務單位名單（社署及醫管局）", "href": f"{SWD}/tc/pubsvc/medical/cat_medical/medicalsoc/"},
            {"id": "ifsc", "title": "綜合家庭服務中心／綜合服務中心服務地域範圍", "href": f"{SWD}/tc/pubsvc/family/cat_family/ifs/ifscbydistrict/index.html"},
            {"id": "ifsc-list", "title": "綜合家庭服務中心地址名單（2026年2月）", "href": f"{SWD}/storage/asset/section/260/tc/IFSC_ISC_address_list_tc_Feb_2026.pdf"},
            {"id": "ccse", "title": "社區照顧服務：家居支援服務範圍", "href": f"{SWD}/tc/pubsvc/elderly/elderly_info/susa/su_ccse/"},
            {"id": "hss", "title": "家居支援服務服務範圍（2026年10月26日）", "href": f"{SWD}/storage/asset/section/734/tc/Service%20Boundary%20of%20HCSST%20of%20HSS_TC%20(26%20October%202026).pdf"},
            {"id": "rche", "title": "提供資助宿位的安老院舍名單（2026年9月30日）", "href": f"{SWD}/storage/asset/section/177/List%20of%20RCHE/4_%20List%20of%20RCHEs%20Providing%20Subsidised%20Places%20for%20the%20Elderly_Q(30_9_2026)_ENG%26TC.pdf"},
        ],
        "coverageNote": "已收錄社會福利署公開名冊上的長者地區中心、長者鄰舍中心、醫務社工單位、綜合家庭服務中心及家居支援服務隊，範圍為全港十八區。這不是逐座樓宇或逐個街號的法律分界，部分單位可能未有地圖座標。",
        "units": units,
        "places": places,
        "examples": examples,
        "counts": {
            "decc": count("decc"),
            "nec": count("nec"),
            "mssu": count("mssu"),
            "ifsc": count("ifsc"),
            "hss": count("hss"),
            "places": len(places),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(directory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(directory["counts"], ensure_ascii=False))
    print("examples", len(examples))
    for example in examples:
        print(" -", example["label"])
    located = sum(1 for unit in units if unit.get("lat"))
    print("units with coordinates", located, "/", len(units))


if __name__ == "__main__":
    main()
