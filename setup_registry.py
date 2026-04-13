"""
旅遊記帳系統 — 用戶管理試算表初始化
執行一次即可，建立用於追蹤所有用戶帳號的試算表
用法：python setup_registry.py
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
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
REGISTRY_HEADERS = ["Email", "姓名", "試算表ID", "建立時間"]


def main():
    print("📊 建立用戶管理試算表")
    print("=" * 40)

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ 找不到憑證檔案：{CREDENTIALS_FILE}")
        return

    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)
        print("✅ Google 驗證成功")
    except Exception as e:
        print(f"❌ 驗證失敗：{e}")
        return

    try:
        spreadsheet = gc.create("🗂️ 旅遊記帳系統 — 用戶清單")
        sheet = spreadsheet.sheet1
        sheet.update_title("用戶清單")
        sheet.append_row(REGISTRY_HEADERS)

        sheet.format("A1:D1", {
            "backgroundColor": {"red": 0.1, "green": 0.35, "blue": 0.2},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER",
        })

        registry_id = spreadsheet.id
        print(f"✅ 用戶管理試算表建立成功！")
        print(f"   ID：{registry_id}")

        # 寫入 .env
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                content = f.read()
            lines = content.splitlines()
            updated = False
            new_lines = []
            for line in lines:
                if line.startswith("REGISTRY_SPREADSHEET_ID="):
                    new_lines.append(f"REGISTRY_SPREADSHEET_ID={registry_id}")
                    updated = True
                else:
                    new_lines.append(line)
            if not updated:
                new_lines.append(f"REGISTRY_SPREADSHEET_ID={registry_id}")
            with open(env_path, "w") as f:
                f.write("\n".join(new_lines) + "\n")
            print("✅ REGISTRY_SPREADSHEET_ID 已寫入 .env")

        print("\n下一步：取得 Google OAuth 憑證")
        print("   python setup_oauth.py")

    except Exception as e:
        print(f"❌ 失敗：{e}")


if __name__ == "__main__":
    main()
