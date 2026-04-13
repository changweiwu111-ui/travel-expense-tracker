"""
旅遊記帳系統 — Notion 資料庫初始化腳本
執行一次即可建立所需的 Notion 資料庫
用法：python setup_notion.py
"""

import os
import json
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()

notion = Client(auth=os.getenv("NOTION_API_KEY"))


def find_parent_page():
    """搜尋工作區中可用的父頁面"""
    results = notion.search(filter={"property": "object", "value": "page"}, page_size=5)
    pages = results.get("results", [])
    if not pages:
        raise Exception("找不到可用的父頁面，請在 Notion 中手動建立一個頁面後再執行。")
    return pages[0]["id"]


def create_database(parent_page_id):
    """建立旅遊記帳資料庫"""
    db = notion.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        icon={"type": "emoji", "emoji": "✈️"},
        title=[{"type": "text", "text": {"content": "旅遊記帳"}}],
        properties={
            "店名": {"title": {}},
            "原文店名": {"rich_text": {}},
            "日期": {"date": {}},
            "金額": {"number": {"format": "number"}},
            "幣別": {
                "select": {
                    "options": [
                        {"name": "JPY", "color": "red"},
                        {"name": "TWD", "color": "green"},
                        {"name": "USD", "color": "blue"},
                        {"name": "KRW", "color": "yellow"},
                        {"name": "THB", "color": "orange"},
                        {"name": "EUR", "color": "purple"},
                        {"name": "HKD", "color": "pink"},
                        {"name": "SGD", "color": "brown"},
                        {"name": "GBP", "color": "gray"},
                        {"name": "VND", "color": "default"},
                    ]
                }
            },
            "台幣換算": {"number": {"format": "number"}},
            "類別": {
                "select": {
                    "options": [
                        {"name": "餐廳", "color": "red"},
                        {"name": "超市", "color": "orange"},
                        {"name": "藥妝", "color": "pink"},
                        {"name": "購物", "color": "purple"},
                        {"name": "交通", "color": "blue"},
                        {"name": "住宿", "color": "green"},
                        {"name": "景點", "color": "yellow"},
                        {"name": "其他", "color": "gray"},
                    ]
                }
            },
            "品項": {"rich_text": {}},
            "支付方式": {
                "select": {
                    "options": [
                        {"name": "現金", "color": "green"},
                        {"name": "信用卡", "color": "blue"},
                        {"name": "IC卡", "color": "orange"},
                        {"name": "行動支付", "color": "purple"},
                    ]
                }
            },
            "地區": {"rich_text": {}},
            "旅程": {"rich_text": {}},
            "備註": {"rich_text": {}},
        },
    )
    return db["id"]


def main():
    print("🛫 旅遊記帳系統 — Notion 資料庫初始化")
    print("=" * 40)

    notion_key = os.getenv("NOTION_API_KEY")
    if not notion_key:
        print("❌ 找不到 NOTION_API_KEY，請先複製 .env.example 為 .env 並填入金鑰")
        return

    print("✅ Notion API 金鑰已載入")
    print("🔍 搜尋可用父頁面...")

    try:
        parent_id = find_parent_page()
        print(f"✅ 找到父頁面：{parent_id}")
    except Exception as e:
        print(f"❌ {e}")
        return

    print("📦 建立旅遊記帳資料庫...")
    try:
        db_id = create_database(parent_id)
        print(f"✅ 資料庫建立成功！")
        print(f"\n📋 資料庫 ID：{db_id}")
        print(f"\n👇 請將以下內容加入你的 .env 檔案：")
        print(f"NOTION_DATABASE_ID={db_id}")

        # 自動寫入 .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                content = f.read()
            if "NOTION_DATABASE_ID=" in content:
                lines = content.splitlines()
                new_lines = [
                    f"NOTION_DATABASE_ID={db_id}" if l.startswith("NOTION_DATABASE_ID=") else l
                    for l in lines
                ]
                with open(env_path, "w") as f:
                    f.write("\n".join(new_lines))
            else:
                with open(env_path, "a") as f:
                    f.write(f"\nNOTION_DATABASE_ID={db_id}\n")
            print(f"\n✅ 已自動寫入 .env 檔案！")
        print("\n🎉 初始化完成，可以執行 python app.py 啟動系統")
    except Exception as e:
        print(f"❌ 建立資料庫失敗：{e}")


if __name__ == "__main__":
    main()
