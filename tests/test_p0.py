import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from openpyxl import Workbook

from tradeflow.compose import compose_system_prompt
from tradeflow.registry import get_spec
from web import database, store
from web.import_service import (ads_chat_analysis, ads_overview, competitor_rows, detect_report_type,
                                parse_upload, save_import, suggest_mapping)


class TestImportParsing(unittest.TestCase):
    def test_csv_header_detection_and_mapping(self):
        content = ("Amazon report,,,\nCampaign Name,Customer Search Term,Impressions,Clicks,Spend,7 Day Total Sales\n"
                   "Kitchen,kitchen mat,1000,20,12.5,50\n").encode()
        columns, rows = parse_upload("ads.csv", content)
        mapping = suggest_mapping(columns)
        self.assertEqual(mapping["Campaign Name"], "campaign")
        self.assertEqual(mapping["Customer Search Term"], "search_term")
        self.assertEqual(len(rows), 1)
        self.assertEqual(detect_report_type(mapping), "ads_search_terms")

    def test_multisheet_xlsx(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["说明", None])
        ws.append(["SKU", "Stock"])
        ws.append(["A-1", 12])
        buf = io.BytesIO()
        wb.save(buf)
        columns, rows = parse_upload("inventory.xlsx", buf.getvalue())
        self.assertEqual(columns, ["SKU", "Stock"])
        self.assertEqual(rows[0]["SKU"], "A-1")

    def test_xlsx_with_broken_dimension_declaration(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["广告活动名称", "客户搜索词", "展示量", "点击量", "花费", "7天总销售额"])
        ws.append(["Campaign", "silicone mat", 100, 5, 10, 40])
        original = io.BytesIO()
        wb.save(original)

        broken = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original.getvalue())) as source, zipfile.ZipFile(broken, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "xl/worksheets/sheet1.xml":
                    data = data.replace(b'<dimension ref="A1:F2"/>', b'<dimension ref="A1:A1"/>')
                target.writestr(info, data)

        columns, rows = parse_upload("amazon-export.xlsx", broken.getvalue())
        self.assertEqual(len(columns), 6)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["客户搜索词"], "silicone mat")


class TestTenantPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "test.db"
        database.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_opportunities_are_store_scoped(self):
        with database.connect() as db:
            db.execute("INSERT INTO stores(id,user_id,name,marketplace) VALUES('second','default','Second','US')")
        store.add_opp({"key": "x", "name": "One"}, "default", "default")
        self.assertEqual(len(store.list_opps("default", "default")), 1)
        self.assertEqual(store.list_opps("default", "second"), [])

    def test_import_is_durable_and_drives_ads_overview(self):
        mapping = {"Campaign Name": "campaign", "Clicks": "clicks", "Impressions": "impressions",
                   "Spend": "spend", "Sales": "sales", "Orders": "orders",
                   "Customer Search Term": "search_term"}
        rows = [{"Campaign Name": "C1", "Clicks": 10, "Impressions": 100, "Spend": 20,
                 "Sales": 80, "Orders": 2, "Customer Search Term": "mat"}]
        saved = save_import("default", "default", "ads.xlsx", list(mapping), rows, mapping)
        self.assertEqual(saved["row_count"], 1)
        result = ads_overview("default", "default")
        self.assertEqual(result["source"], "imported_report")
        self.assertEqual(result["items"][0]["acos"], 0.25)

    def test_imported_ads_can_be_analyzed_from_chat(self):
        mapping = {"Campaign Name": "campaign", "Clicks": "clicks", "Impressions": "impressions",
                   "Spend": "spend", "Sales": "sales", "Orders": "orders",
                   "Customer Search Term": "search_term"}
        rows = [
            {"Campaign Name": "C1", "Clicks": 12, "Impressions": 100, "Spend": 15,
             "Sales": 0, "Orders": 0, "Customer Search Term": "bad term"},
            {"Campaign Name": "C2", "Clicks": 8, "Impressions": 100, "Spend": 8,
             "Sales": 100, "Orders": 3, "Customer Search Term": "good term"},
        ]
        save_import("default", "default", "ads.xlsx", list(mapping), rows, mapping)
        reply = ads_chat_analysis("default", "default")
        self.assertIsNotNone(reply)
        self.assertIn("已读取你导入的广告搜索词报表", reply)
        self.assertIn("bad term", reply)
        self.assertIn("good term", reply)

    def test_competitor_import_can_drive_offline_flow(self):
        mapping = {"ASIN": "asin", "Title": "title", "Price": "price", "Rating": "rating"}
        rows = [{"ASIN": "B001", "Title": "Silicone Mat", "Price": 19.99, "Rating": 4.6}]
        saved = save_import("default", "default", "competitors.xlsx", list(mapping), rows, mapping)
        self.assertEqual(saved["report_type"], "competitors")
        self.assertEqual(competitor_rows("default", "default")[0]["asin"], "B001")


class TestPromptAndTools(unittest.TestCase):
    def test_base_prompt_has_p0_guardrails(self):
        prompt = compose_system_prompt("listing")
        self.assertIn("数据不足", prompt)
        self.assertIn("compliance_gate", prompt)
        self.assertIn("不得使用示例或 Mock 数据冒充真实结果", prompt)

    def test_market_agents_have_real_query_tools(self):
        for name in ("listing", "teardown", "market", "selection"):
            tools = {t.name for t in get_spec(name).tools}
            self.assertIn("search_products", tools)


if __name__ == "__main__":
    unittest.main()
