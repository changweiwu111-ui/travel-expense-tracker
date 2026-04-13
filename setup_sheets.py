"""
旅遊記帳系統 — Google Sheets 初始化腳本
執行一次即可建立試算表並設定欄位標題
用法：python setup_sheets.py
"""

import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "日期", "店名", "原文店名", "金額", "幣別",
    "台幣換算", "類別", "品項", "支付方式", "地區", "旅程", "備註", "建立時間"
]

CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")


def main():
    print("📊 旅遊記帳系統 — Google Sheets 初始化")
    print("=" * 40)

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ 找不到憑證檔案：{CREDENTIALS_FILE}")
        print("請依照啟動說明.md 取得 credentials.json 後再執行")
        return

    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)
        print("✅ Google 驗證成功")
    except Exception as e:
        print(f"❌ 驗證失敗：{e}")
        return

    print("📝 建立旅遊記帳試算表...")
    try:
        spreadsheet = gc.create("✈️ 旅遊記帳")
        sheet = spreadsheet.sheet1
        sheet.update_title("記帳明細")

        # 寫入標題列
        sheet.append_row(HEADERS)

        # 格式化標題列
        sheet.format("A1:M1", {
            "backgroundColor": {"red": 0.27, "green": 0.28, "blue": 0.44},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER",
        })

        # 凍結第一列
        spreadsheet.batch_update({
            "requests": [{"updateSheetProperties": {
                "properties": {"sheetId": sheet.id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"
            }}]
        })

        # 設定欄位寬度
        spreadsheet.batch_update({
            "requests": [{"updateDimensionProperties": {
                "range": {"sheetId": sheet.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 13},
                "properties": {"pixelSize": 120},
                "fields": "pixelSize"
            }}]
        })

        spreadsheet_id = spreadsheet.id
        spreadsheet_url = spreadsheet.url

        print(f"✅ 試算表建立成功！")
        print(f"\n🔗 試算表網址：{spreadsheet_url}")
        print(f"\n📋 Spreadsheet ID：{spreadsheet_id}")

        # 自動寫入 .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                content = f.read()
            lines = content.splitlines()
            updated = False
            new_lines = []
            for line in lines:
                if line.startswith("SPREADSHEET_ID="):
                    new_lines.append(f"SPREADSHEET_ID={spreadsheet_id}")
                    updated = True
                else:
                    new_lines.append(line)
            if not updated:
                new_lines.append(f"SPREADSHEET_ID={spreadsheet_id}")
            with open(env_path, "w") as f:
                f.write("\n".join(new_lines))
            print("✅ 已自動寫入 .env 檔案！")

        print(f"\n⚠️  重要：請將試算表分享給你的 Service Account Email")
        print(f"    （Email 在 credentials.json 裡的 client_email 欄位）")
        print(f"\n🎉 完成！執行 python app.py 啟動系統")

    except Exception as e:
        print(f"❌ 建立試算表失敗：{e}")


if __name__ == "__main__":
    main()
