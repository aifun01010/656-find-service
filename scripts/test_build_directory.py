#!/usr/bin/env python3
"""Parser checks for elderly-centre rows that share a name."""

from __future__ import annotations

import unittest

import build_directory as build


def sheet(*data_rows: list[str]) -> list[list[str]]:
    header = ["Agency", "Centre", "Type of Centre", "Address", "Tel", "Service Area"]
    skipped = ["機構", "中心", "中心類別", "地址", "電話", "服務範圍"]
    return [header, skipped, *data_rows]


def row(name: str, address: str, area: str, *, kind: str = "nec", phone: str = "2476 6036", operator: str = "測試機構") -> list[str]:
    type_cell = "District Elderly Community Centre\n長者地區中心" if kind == "decc" else "Neighbourhood Elderly Centre\n長者鄰舍中心"
    return [operator, name, type_cell, address, phone, area]


class CentreRowMergeTests(unittest.TestCase):
    def test_repeated_name_keeps_every_service_area_block(self) -> None:
        address = "新界元朗水邊圍邨盈水樓地下"
        rows = sheet(
            row("明愛元朗長者社區中心", address, "元朗市區\n天水圍區\n十八鄉郊區\nYuen Long Urban Area", kind="decc", phone="2479 7383"),
            ["", "", "", "", "", ""],
            row("明愛元朗長者社區中心", address, "屏山鄉郊區\nPing Shan Rural Area", kind="decc", phone="2479 7383"),
        )
        units = build.units_from_centre_table(rows, "yl", filename="YL.xlsx")
        self.assertEqual(len(units), 1)
        area = units[0]["serviceArea"]
        self.assertIn("元朗市區", area)
        self.assertIn("天水圍區", area)
        self.assertIn("十八鄉郊區", area)
        self.assertIn("屏山鄉郊區", area)
        self.assertIn("Yuen Long Urban Area", units[0]["searchText"])
        self.assertIn("Ping Shan Rural Area", units[0]["searchText"])
        self.assertEqual(units[0]["type"], "decc")

    def test_continued_area_is_merged_when_the_mark_is_only_in_the_area(self) -> None:
        address = "新界元朗朗屏邨賀屏樓平台"
        rows = sheet(
            row("田家炳長者鄰舍中心", address, "元朗市區\n公共屋邨：朗屏邨\nYuen Long Urban Area"),
            row("田家炳長者鄰舍中心", address, "元朗市區 (續)\n安樂路：永興大廈"),
            row("元朗大會堂陳應祥紀念老人中心", "新界元朗體育路四號一樓", "元朗市區\n大型屋苑：御豪山莊"),
            row("元朗大會堂陳應祥紀念老人中心", "新界元朗體育路四號一樓", "元朗市區 (續)\n馬田路一帶：基業大樓\n錦綉花園"),
        )
        units = build.units_from_centre_table(rows, "yl")
        self.assertEqual([unit["name"] for unit in units], ["田家炳長者鄰舍中心", "元朗大會堂陳應祥紀念老人中心"])
        tin = units[0]["serviceArea"]
        self.assertIn("朗屏邨", tin)
        self.assertIn("安樂路", tin)
        chan = units[1]["serviceArea"]
        self.assertIn("御豪山莊", chan)
        self.assertIn("馬田路", chan)
        self.assertIn("錦綉花園", chan)

    def test_same_name_with_a_different_address_stays_a_second_unit(self) -> None:
        shared = "新界元朗鳳翔路五號偉發大廈地下 6-11號；新界元朗西菁街富達廣場"
        other = "新界元朗鳳翔路五號偉發大廈地下 6-11號；新界元朗鳳翔路五號偉發大廈地下 1及21號"
        rows = sheet(
            row("王東源夫人長者地區中心", shared, "元朗市區\n朗善邨", kind="decc"),
            row("王東源夫人長者地區中心", shared, "十八鄉鄉郊區\n新田鄉鄉郊區", kind="decc"),
            row("王東源夫人長者地區中心", other, "錦田鄉鄉郊區\n八鄉鄉郊區", kind="decc"),
        )
        units = build.units_from_centre_table(rows, "yl")
        self.assertEqual(len(units), 2)
        urban = next(unit for unit in units if "西菁街" in unit["address"])
        kam_tin = next(unit for unit in units if "1及21號" in unit["address"])
        self.assertIn("元朗市區", urban["serviceArea"])
        self.assertIn("十八鄉鄉郊區", urban["serviceArea"])
        self.assertIn("新田鄉", urban["serviceArea"])
        self.assertNotIn("錦田鄉鄉郊區", urban["serviceArea"])
        self.assertIn("錦田鄉鄉郊區", kam_tin["serviceArea"])
        self.assertIn("八鄉鄉郊區", kam_tin["serviceArea"])
        self.assertNotIn("十八鄉鄉郊區", kam_tin["serviceArea"])

    def test_continuation_mark_in_the_centre_name_still_appends(self) -> None:
        address = "新界元朗體育路四號一樓"
        rows = sheet(
            row("元朗大會堂陳應祥紀念老人中心", address, "元朗市區\n御豪山莊"),
            row("元朗大會堂陳應祥紀念老人中心（續）", address, "馬田路一帶：基業大樓"),
            row("Cont'd", "", "English only block"),
        )
        units = build.units_from_centre_table(rows, "yl")
        self.assertEqual(len(units), 1)
        self.assertIn("御豪山莊", units[0]["serviceArea"])
        self.assertIn("馬田路", units[0]["serviceArea"])
        self.assertIn("English only block", units[0]["searchText"])

    def test_workbook_characters_are_kept(self) -> None:
        rows = sheet(
            row(
                "Rhythm Garden Lutheran Centre for the Elderly\n路德會采頤長者中心",
                "九龍新蒲崗采頤花園十二座地下",
                "Rhythm Garden, Kai Chuen Court\n采頤花園、啟鑽苑",
            )
        )
        units = build.units_from_centre_table(rows, "wtssk")
        self.assertEqual(units[0]["name"], "路德會采頤長者中心")
        self.assertIn("采頤花園", units[0]["address"])
        self.assertIn("采頤花園", units[0]["serviceArea"])
        self.assertNotIn("彩頤", units[0]["name"])
        self.assertNotIn("彩頤", units[0]["serviceArea"])

    def test_short_estate_names_stay_in_keywords_when_the_area_is_long(self) -> None:
        digits = "零一二三四五六七八九"
        long_names = []
        for i in range(130):
            spelled = "".join(digits[int(ch)] for ch in f"{i:03d}")
            long_names.append(f"測試名稱{spelled}花園")
        text = "\n".join(long_names + ["朗善邨", "鳳庭苑", "華麗苑"])
        keywords = build.keywords_from_text(text, keep_places=True)
        self.assertIn("朗善邨", keywords)
        self.assertIn("鳳庭苑", keywords)
        self.assertIn("華麗苑", keywords)
        self.assertNotIn("朗善邨", build.keywords_from_text(text))


if __name__ == "__main__":
    unittest.main()
