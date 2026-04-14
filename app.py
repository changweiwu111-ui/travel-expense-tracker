"""
旅遊記帳系統 — Flask 後端（多用戶版 + Email / PIN 登入）
架構：一個主試算表 → 每位用戶一個分頁（tab）
功能：自行註冊 → 個人分頁 → Gemini 辨識收據 → 即時 Dashboard
"""

import os
import json
import base64
import hashlib
import time
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini = genai.GenerativeModel("gemini-1.5-flash")

# Google Sheets 設定
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
MAIN_SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID")        # 所有用戶資料的主試算表
REGISTRY_SPREADSHEET_ID = os.getenv("REGISTRY_SPREADSHEET_ID")  # 用戶帳號清單
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

EXCHANGE_RATES = {
    "TWD": 1.0, "JPY": 0.215, "USD": 32.5, "KRW": 0.024,
    "THB": 0.93, "EUR": 35.5, "HKD": 4.2, "SGD": 24.5,
    "GBP": 41.0, "VND": 0.0013, "AUD": 21.0, "CNY": 4.5,
    "MYR": 7.3, "PHP": 0.57,
}

CATEGORY_EMOJI = {
    "餐廳": "🍜", "超市": "🛒", "藥妝": "💊", "購物": "🛍️",
    "交通": "🚃", "住宿": "🏨", "景點": "🎡", "其他": "📌",
}

HEADERS = [
    "日期", "店名", "原文店名", "金額", "幣別",
    "台幣換算", "類別", "品項", "支付方式", "地區", "旅程", "備註", "建立時間"
]


# ── 認證工具 ───────────────────────────────────────────────

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.strip().encode()).hexdigest()


# ── Google Sheets 工具 ─────────────────────────────────────

def get_gc():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def get_registry_sheet():
    gc = get_gc()
    return gc.open_by_key(REGISTRY_SPREADSHEET_ID).sheet1


def get_main_spreadsheet():
    gc = get_gc()
    return gc.open_by_key(MAIN_SPREADSHEET_ID)


def get_user_by_email(email: str):
    """查找用戶，回傳用戶資訊或 None"""
    registry = get_registry_sheet()
    rows = registry.get_all_values()
    for row in rows[1:]:
        if len(row) >= 4 and row[0] == email:
            return {
                "email": row[0],
                "name": row[1],
                "pin_hash": row[2],
                "sheet_name": row[3],
            }
    return None


def verify_login(email: str, pin: str):
    """驗證 email + PIN，成功回傳用戶資訊"""
    user = get_user_by_email(email)
    if user and user["pin_hash"] == hash_pin(pin):
        return user
    return None


def create_user_tab(name: str) -> str:
    """在主試算表中新增用戶專屬分頁，回傳分頁名稱"""
    spreadsheet = get_main_spreadsheet()
    existing = [ws.title for ws in spreadsheet.worksheets()]

    # 確保分頁名稱不重複
    sheet_name = name[:20]
    base = sheet_name
    i = 2
    while sheet_name in existing:
        sheet_name = f"{base}_{i}"
        i += 1

    sheet = spreadsheet.add_worksheet(title=sheet_name, rows=2000, cols=13)
    sheet.append_row(HEADERS, value_input_option="USER_ENTERED")
    sheet.format("A1:M1", {
        "backgroundColor": {"red": 0.27, "green": 0.28, "blue": 0.44},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "horizontalAlignment": "CENTER",
    })
    return sheet_name


def create_user(email: str, name: str, pin: str):
    """建立新用戶；email 已存在回傳 None，否則回傳分頁名稱"""
    if get_user_by_email(email):
        return None

    sheet_name = create_user_tab(name)

    registry = get_registry_sheet()
    registry.append_row([
        email,
        name,
        hash_pin(pin),
        sheet_name,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    ])
    return sheet_name


def get_user_sheet():
    """取得當前登入用戶的分頁"""
    sheet_name = session.get("sheet_name")
    if not sheet_name:
        return None
    spreadsheet = get_main_spreadsheet()
    return spreadsheet.worksheet(sheet_name)


# ── 登入驗證裝飾器 ─────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ── 收據解析 ───────────────────────────────────────────────

def encode_image(file_bytes):
    return base64.standard_b64encode(file_bytes).decode("utf-8")


def parse_receipt(image_data: str, media_type: str, retries: int = 3) -> dict:
    today = date.today().strftime("%Y-%m-%d")
    prompt = f"""你是專業旅遊記帳助手。請分析這張收據或發票圖片，提取資訊並以 JSON 格式回傳。

支援語言：日文、英文、繁體中文、簡體中文、韓文、泰文、越南文、法文、德文、義大利文、西班牙文等。

請回傳以下 JSON（只回傳 JSON，不要其他文字）：
{{
  "store_name_original": "原文店名",
  "store_name_zh": "店名翻譯成繁體中文",
  "date": "消費日期 YYYY-MM-DD（若無法辨識填 {today}）",
  "total_amount": 總金額數字,
  "currency": "幣別代碼（JPY/USD/TWD/KRW/THB/EUR/HKD/SGD/GBP/VND/AUD/CNY/MYR/PHP）",
  "items": ["品項1", "品項2"],
  "category": "類別（餐廳/超市/藥妝/購物/交通/住宿/景點/其他）",
  "payment_method": "支付方式（現金/信用卡/IC卡/行動支付）",
  "region": "消費地區或城市",
  "notes": "其他備註"
}}"""

    image_part = {"mime_type": media_type, "data": base64.b64decode(image_data)}

    last_error = None
    for attempt in range(retries):
        try:
            response = gemini.generate_content([prompt, image_part])
            result_text = response.text.strip()

            if result_text.startswith("```"):
                parts = result_text.split("```")
                for part in parts:
                    if part.startswith("json"):
                        result_text = part[4:].strip()
                        break
                    elif "{" in part:
                        result_text = part.strip()
                        break

            return json.loads(result_text)
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                wait = 10 * (attempt + 1)
                time.sleep(wait)
            else:
                raise

    raise last_error


def to_twd(amount: float, currency: str) -> int:
    return round(amount * EXCHANGE_RATES.get(currency.upper(), 1.0))


def save_to_sheet(data: dict, trip_name: str) -> None:
    sheet = get_user_sheet()
    twd = to_twd(data.get("total_amount", 0), data.get("currency", "TWD"))
    items_text = "、".join(data.get("items", [])) if data.get("items") else ""
    date_str = data.get("date", date.today().strftime("%Y-%m-%d"))

    row = [
        date_str,
        data.get("store_name_zh", "未知店家"),
        data.get("store_name_original", ""),
        data.get("total_amount", 0),
        data.get("currency", "TWD"),
        twd,
        data.get("category", "其他"),
        items_text,
        data.get("payment_method", "現金"),
        data.get("region", ""),
        trip_name,
        data.get("notes", ""),
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")


def get_all_records() -> list:
    sheet = get_user_sheet()
    if not sheet:
        return []
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return []
    records = []
    for row in rows[1:]:
        if len(row) < 13:
            row += [""] * (13 - len(row))
        try:
            records.append({
                "date": row[0],
                "store_name": row[1],
                "store_name_original": row[2],
                "amount": float(row[3]) if row[3] else 0,
                "currency": row[4] or "TWD",
                "twd_amount": float(row[5]) if row[5] else 0,
                "category": row[6] or "其他",
                "items": row[7],
                "payment_method": row[8] or "現金",
                "region": row[9],
                "trip": row[10],
                "notes": row[11],
            })
        except Exception:
            continue
    return records


def get_stats(trip_name: str = "") -> dict:
    records = get_all_records()
    if trip_name:
        records = [r for r in records if trip_name in r.get("trip", "")]

    today_str = date.today().strftime("%Y-%m-%d")
    total_twd = sum(r["twd_amount"] for r in records)
    today_twd = sum(r["twd_amount"] for r in records if r["date"] == today_str)

    by_category, by_day, by_payment = {}, {}, {}
    for r in records:
        by_category[r["category"]] = by_category.get(r["category"], 0) + r["twd_amount"]
        if r["date"]:
            by_day[r["date"]] = by_day.get(r["date"], 0) + r["twd_amount"]
        by_payment[r["payment_method"]] = by_payment.get(r["payment_method"], 0) + r["twd_amount"]

    top10 = sorted(records, key=lambda x: x["twd_amount"], reverse=True)[:10]

    return {
        "total_twd": total_twd,
        "today_twd": today_twd,
        "count": len(records),
        "records": records[:30],
        "by_category": by_category,
        "by_day": dict(sorted(by_day.items())),
        "by_payment": by_payment,
        "top10": top10,
        "category_emoji": CATEGORY_EMOJI,
    }


def get_trips() -> list:
    records = get_all_records()
    trips = set(r["trip"] for r in records if r.get("trip"))
    return sorted(list(trips))


# ── Routes ────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        action = request.form.get("action", "login")

        if action == "login":
            email = request.form.get("email", "").strip().lower()
            pin = request.form.get("pin", "").strip()
            user = verify_login(email, pin)
            if user:
                session["user"] = {"email": user["email"], "name": user["name"], "picture": ""}
                session["sheet_name"] = user["sheet_name"]
                session.permanent = True
                return redirect(url_for("index"))
            return render_template("login.html", error="Email 或密碼錯誤", tab="login", email=email)

        elif action == "register":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            pin = request.form.get("pin", "").strip()
            pin2 = request.form.get("pin2", "").strip()

            if not name or not email or not pin:
                return render_template("login.html", error="請填寫所有欄位", tab="register",
                                       name=name, email=email)
            if pin != pin2:
                return render_template("login.html", error="兩次密碼不一致", tab="register",
                                       name=name, email=email)
            if len(pin) < 4:
                return render_template("login.html", error="密碼至少 4 位數", tab="register",
                                       name=name, email=email)

            sheet_name = create_user(email, name, pin)
            if sheet_name is None:
                return render_template("login.html", error="此 Email 已註冊，請直接登入",
                                       tab="login", email=email)

            session["user"] = {"email": email, "name": name, "picture": ""}
            session["sheet_name"] = sheet_name
            session.permanent = True
            return redirect(url_for("index"))

    return render_template("login.html", tab="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    try:
        trips = get_trips()
        stats = get_stats()
    except Exception:
        trips = []
        stats = {"total_twd": 0, "today_twd": 0, "count": 0, "records": []}
    return render_template("index.html", trips=trips, stats=stats, user=session.get("user"))


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    if "receipt" not in request.files:
        return jsonify({"error": "沒有上傳檔案"}), 400

    file = request.files["receipt"]
    trip_name = request.form.get("trip_name", "我的旅遊").strip() or "我的旅遊"

    if not file.filename:
        return jsonify({"error": "未選擇檔案"}), 400

    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    media_types = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/jpeg")

    try:
        file_bytes = file.read()
        image_data = encode_image(file_bytes)
        parsed = parse_receipt(image_data, media_type)
        save_to_sheet(parsed, trip_name)
        twd = to_twd(parsed.get("total_amount", 0), parsed.get("currency", "TWD"))

        return jsonify({
            "success": True,
            "store_name": parsed.get("store_name_zh", ""),
            "store_name_original": parsed.get("store_name_original", ""),
            "amount": parsed.get("total_amount", 0),
            "currency": parsed.get("currency", "TWD"),
            "twd_amount": twd,
            "category": parsed.get("category", "其他"),
            "date": parsed.get("date", ""),
            "items": parsed.get("items", []),
            "region": parsed.get("region", ""),
            "payment_method": parsed.get("payment_method", "現金"),
            "sheets_url": f"https://docs.google.com/spreadsheets/d/{MAIN_SPREADSHEET_ID}",
        })
    except json.JSONDecodeError:
        return jsonify({"error": "AI 無法解析此收據，請確認圖片清晰度"}), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
@login_required
def api_stats():
    trip = request.args.get("trip", "")
    try:
        return jsonify(get_stats(trip))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trips")
@login_required
def api_trips():
    try:
        return jsonify(get_trips())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/add", methods=["POST"])
@login_required
def add_manual():
    data = request.get_json()
    if not data:
        return jsonify({"error": "無資料"}), 400

    trip_name = (data.get("trip_name") or "我的旅遊").strip()
    amount_raw = data.get("amount", 0)
    try:
        amount = float(amount_raw)
    except (ValueError, TypeError):
        return jsonify({"error": "金額格式錯誤"}), 400

    currency = (data.get("currency") or "TWD").upper()
    twd = to_twd(amount, currency)

    record = {
        "store_name_zh": (data.get("store_name") or "未知店家").strip(),
        "store_name_original": (data.get("store_name_original") or "").strip(),
        "date": data.get("date") or date.today().strftime("%Y-%m-%d"),
        "total_amount": amount,
        "currency": currency,
        "items": [i.strip() for i in (data.get("items") or "").split("、") if i.strip()],
        "category": data.get("category") or "其他",
        "payment_method": data.get("payment_method") or "現金",
        "region": (data.get("region") or "").strip(),
        "notes": (data.get("notes") or "").strip(),
    }

    try:
        save_to_sheet(record, trip_name)
        return jsonify({
            "success": True,
            "store_name": record["store_name_zh"],
            "amount": amount,
            "currency": currency,
            "twd_amount": twd,
            "category": record["category"],
            "sheets_url": f"https://docs.google.com/spreadsheets/d/{MAIN_SPREADSHEET_ID}",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    missing = []
    if not os.getenv("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if not os.getenv("SPREADSHEET_ID"):
        missing.append("SPREADSHEET_ID")
    if not os.getenv("REGISTRY_SPREADSHEET_ID"):
        missing.append("REGISTRY_SPREADSHEET_ID")
    if not os.path.exists(CREDENTIALS_FILE):
        missing.append("credentials.json")

    if missing:
        print(f"⚠️  缺少設定：{', '.join(missing)}")
    else:
        print("✅ 設定載入完成")
        print("🌐 啟動伺服器：http://localhost:5001")

    app.run(debug=True, port=5001, host="0.0.0.0")
