import glob
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime
from google import genai
from google.genai import types
import pandas as pd
from PIL import Image

# -------------------------------------------------------------
# 1. การตั้งค่า
# -------------------------------------------------------------
# อ่าน API key จากไฟล์ key.txt ในโฟลเดอร์เดียวกับโปรแกรม
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.txt")
if not os.path.exists(KEY_FILE):
  print("ไม่พบไฟล์ key.txt ในโฟลเดอร์เดียวกับโปรแกรม")
  input("\nกด Enter เพื่อปิด...")
  sys.exit()
with open(KEY_FILE, encoding="utf-8") as f:
  API_KEY = f.read().strip()
if not API_KEY:
  print("ไฟล์ key.txt ว่างเปล่า กรุณาใส่ API key")
  input("\nกด Enter เพื่อปิด...")
  sys.exit()

MODELS_TO_USE = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
]

MAX_TRIES = 6                       # จำนวนครั้งที่ลองโมเดลเดิมเมื่อคนแน่น
CACHE_DIR = "cache_tiktok"          # โฟลเดอร์เก็บผลที่อ่านแล้ว
HTML_FILE = "tiktok_view.html"

DATE_FIELDS = ["วันสั่งซื้อ", "วันชำระเงิน", "วันจัดส่งสินค้า", "วันที่สำเร็จ_ส่งมอบ"]
TIME_FIELDS = ["เวลาสั่งซื้อ_HHMM", "เวลาชำระเงิน_HHMM", "เวลาจัดส่งสินค้า_HHMM", "เวลาที่สำเร็จ_HHMM"]
MONEY_FIELDS = [
    "ราคารวมค่าสินค้า_ก่อนส่วนลด", "ค่าจัดส่ง", "ส่วนลดค่าจัดส่ง",
    "ส่วนลด_โค้ด_Shopee", "ส่วนลด_ร้านค้า", "ส่วนลดช่องทางการชำระเงิน",
    "การใช้เหรียญ_Shopee", "ส่วนลดอื่นๆ", "ค่าใช้จ่ายอื่นๆ", "ราคารวม_หลังส่วนลด",
]
DISCOUNT_FIELDS = [
    "ส่วนลดค่าจัดส่ง", "ส่วนลด_โค้ด_Shopee", "ส่วนลด_ร้านค้า",
    "ส่วนลดช่องทางการชำระเงิน", "การใช้เหรียญ_Shopee", "ส่วนลดอื่นๆ",
]

# ช่องทางชำระเงินตามฟอร์ม TikTok (ชื่อแรกต้องตรงกับในฟอร์ม)
# คำในลิสต์ที่สองคือชื่อและคำย่อที่อาจพบบนหน้าจอ ใช้จับคู่เท่านั้น
PAYMENT_RULES = [
    ("โอนเงินผ่านตู้ ATM หรือเคาน์เตอร์ธนาคาร", [
        "โอนเงินผ่านตู้ ATM", "ตู้ ATM", "ตู้atm", "ATM", "เคาน์เตอร์ธนาคาร",
        "เคาน์เตอร์", "counter", "bank counter", "โอนผ่านเคาน์เตอร์",
    ]),
    ("ชำระเงินปลายทาง", [
        "ชำระเงินปลายทาง", "ปลายทาง", "เก็บเงินปลายทาง", "Cash on delivery", "COD",
    ]),
    ("ชำระเงินที่ร้านสะดวกซื้อ", [
        "ชำระเงินที่ร้านสะดวกซื้อ", "ร้านสะดวกซื้อ", "เซเว่น", "7-Eleven", "7-11",
        "Convenience store", "CVS", "จ่ายที่เซเว่น", "เคาน์เตอร์ร้านสะดวกซื้อ",
    ]),
    ("บัตรเครดิต/บัตรเดบิต", [
        "บัตรเครดิต", "บัตรเดบิต", "บัตรเครดิต/บัตรเดบิต", "Credit card", "Debit card",
        "Visa", "Mastercard", "มาสเตอร์การ์ด", "JCB", "Amex",
    ]),
    ("อินเทอร์เน็ตแบงก์กิ้ง", [
        "อินเทอร์เน็ตแบงก์กิ้ง", "อินเทอร์เน็ตแบงค์กิ้ง", "Internet banking", "iBanking",
        "i-Banking", "Bualuang iBanking", "บัวหลวง", "Kasikornbank.com", "Kasikorn",
        "กสิกร", "อินเทอร์เน็ต", "SCB Internet", "Krungthai Corporate Online",
    ]),
    ("โมบายแบงก์กิ้ง", [
        "โมบายแบงก์กิ้ง", "โมบายแบงค์กิ้ง", "Mobile banking", "K PLUS", "KPLUS", "K+",
        "SCB EASY", "SCB Easy", "Krungthai NEXT", "กรุงไทย NEXT", "กรุงไทยNEXT",
        "ttb touch", "TTB Touch", "Krungsri", "กรุงศรี", "Mobile app",
    ]),
    ("กระเป๋าเงินอิเล็กทรอนิกส์", [
        "กระเป๋าเงินอิเล็กทรอนิกส์", "กระเป๋าเงินอิเล็กทรอนิกส์ (อี-วอลเล็ต)", "อี-วอลเล็ต",
        "อีวอลเล็ต", "E-wallet", "TrueMoney", "TrueMoney Wallet", "True Money", "ทรูมันนี่",
        "Rabbit LINE Pay", "Rabbit", "LINE Pay", "ลายน์เพย์",
    ]),
    ("แพลตฟอร์มชำระเงินออนไลน์ของบุคคลที่สาม", [
        "แพลตฟอร์มชำระเงินออนไลน์ของบุคคลที่สาม", "Google Pay", "Apple Pay", "Paypal",
        "แพลตฟอร์มชำระเงินออนไลน์",
    ]),
    ("QR พร้อมเพย์", [
        "QR พร้อมเพย์", "พร้อมเพย์", "PromptPay", "QR", "QR code", "Thai QR",
    ]),
    ("ทรู เพย์ เน็กซ์", [
        "ทรู เพย์ เน็กซ์", "ทรู เพย์", "ทรูเพย์", "True Pay Next", "True Pay", "TruePay",
    ]),
    ("TikTok PayLater", [
        "TikTok PayLater", "Tiktok paylater", "PayLater", "Pay Later",
    ]),
    ("Tiktok shop balance", [
        "Tiktok shop balance", "TikTok Shop balance", "Shop balance", "ยอดคงเหลือ TikTok",
    ]),
    ("ซื้อก่อน จ่ายทีหลัง อื่นๆ", [
        "ซื้อก่อน จ่ายทีหลัง", "ซื้อก่อนจ่ายทีหลัง", "ซื้อก่อน", "จ่ายทีหลัง",
    ]),
]
PAYMENT_FORM_NAMES = [name for name, _ in PAYMENT_RULES]

# ตารางแปลงเดือนย่อเป็นเลข
THAI_MONTH = {
    "มค": "01", "กพ": "02", "มีค": "03", "เมย": "04", "พค": "05", "มิย": "06",
    "กค": "07", "สค": "08", "กย": "09", "ตค": "10", "พย": "11", "ธค": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# กฎจับคู่ข้อความ -> หมวดหมู่ (ตามฟอร์ม TikTok)
CARRIER_RULES = [
    (["j&t", "j&amp;t", "jt express"], "J&T"),
    (["flash"], "Flash Express"),
    (["kex", "kerry"], "KEX Express"),
    (["best"], "BEST Express"),
    (["thailand post", "ems", "ไปรษณีย์"], "ไปรษณีย์ไทย"),
    (["seller", "ผู้ขาย"], "Seller's Own Fleet"),
]
SHIP_RULES = [
    (["intern", "ระหว่างประเทศ"], "ส่งระหว่างประเทศ"),
    (["same-day", "same day", "วันเดียวกัน"], "ส่งวันเดียวกัน"),
    (["มาตรฐาน", "standard"], "ส่งมาตรฐาน"),
]
SHOP_RULES = [
    (["mall", "มอลล์"], "มอลล์"),
    (["preferred", "top choice", "topchoice", "แนะนำ"], "ร้านแนะนำ"),
]


def to_float(val):
  try:
    return float(str(val).replace(",", "").replace("฿", "").strip())
  except ValueError:
    return 0.0


def clean_number(val):
  num = to_float(val)
  return int(num) if num.is_integer() else num


def norm(text):
  """ทำให้ข้อความเทียบกันง่าย: ตัวพิมพ์เล็ก ไม่มีช่องว่าง ขีด จุด และเครื่องหมาย"""
  return re.sub(r"[\s\-\._/,()\[\]]", "", str(text or "").lower())


def match_payment(text):
  """คืนชื่อช่องทางตามฟอร์ม TikTok ถ้าจับคู่ได้ ไม่งั้นคืน None"""
  t = norm(text)
  if not t:
    return None
  # 1) ตรงกับชื่อในฟอร์มทั้งประโยค
  for form_name in PAYMENT_FORM_NAMES:
    if norm(form_name) == t:
      return form_name
  # 2) มีชื่อหรือคำย่อที่รู้จักอยู่ในข้อความ
  for form_name, keywords in PAYMENT_RULES:
    for kw in keywords:
      if norm(kw) and norm(kw) in t:
        return form_name
  return None


def clean_product_name(name):
  s = str(name or "")
  out = []
  for ch in s:
    cat = unicodedata.category(ch)
    # ตัดอีโมจิและสัญลักษณ์พิเศษ (So, Sk) รวมถึงตัวควบคุมที่มองไม่เห็น
    if cat in ("So", "Sk", "Cf", "Cs", "Co") or ch == "\uFE0F":
      continue
    out.append(ch)
  s = "".join(out)
  # ตัด ... หรือ … ที่ท้ายชื่อ ไม่เดาคำที่หายไป
  s = re.sub(r"\s*(\.{3}|…)\s*$", "", s)
  s = re.sub(r"\s+", " ", s).strip()
  return s or "-"


def parse_tiktok_datetime(raw):
  """แปลง 'วัน เดือนย่อ ค.ศ. เวลา AM/PM' เป็น ('DD-MM-YYYY', 'HHMM')"""
  s = str(raw or "").strip()
  m = re.search(
      r"(\d{1,2})\s*([ก-๙A-Za-z.]+)\s*(\d{4})(?:\s*(\d{1,2}):(\d{2})\s*(AM|PM)?)?",
      s, re.IGNORECASE,
  )
  if not m:
    return "-", "-"
  day, mon_raw, year, hour, minute, ampm = m.groups()
  mon = THAI_MONTH.get(mon_raw.replace(".", "").replace(" ", "").lower())
  if mon is None:
    return "-", "-"
  y = int(year)
  if y > 2500:
    y -= 543
  date_str = f"{int(day):02d}-{mon}-{y}"
  if hour is None:
    return date_str, "-"
  h = int(hour)
  if ampm:
    if ampm.upper() == "PM" and h < 12:
      h += 12
    if ampm.upper() == "AM" and h == 12:
      h = 0
  return date_str, f"{h:02d}{int(minute):02d}"


def natural_sort_key(s):
  return [
      int(text) if text.isdigit() else text.lower()
      for text in re.split(r"(\d+)", s)
  ]


def load_optimized_image(img_path, max_dim=1024):
  with Image.open(img_path) as img:
    img = img.convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80, optimize=True)
    buf.seek(0)
    return Image.open(buf)


# -------------------------------------------------------------
# 2. ค้นหาโฟลเดอร์ออเดอร์
# -------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))

subfolders = sorted(
    [
        os.path.join(current_dir, f)
        for f in os.listdir(current_dir)
        if os.path.isdir(os.path.join(current_dir, f))
    ],
    key=natural_sort_key,
)
order_folders = [
    f for f in subfolders if os.path.basename(f).lower().startswith("order_")
]

active_folders = []
for f in order_folders:
  imgs = (
      glob.glob(os.path.join(f, "*.[jJ][pP][gG]"))
      + glob.glob(os.path.join(f, "*.[pP][nN][gG]"))
      + glob.glob(os.path.join(f, "*.[jJ][pP][eE][gG]"))
  )
  if len(imgs) > 0:
    active_folders.append((f, imgs))

if not active_folders:
  print("ไม่พบรูปภาพในโฟลเดอร์ order_ ใดๆ กรุณาใส่รูปในโฟลเดอร์ก่อนรัน")
  input("\nกด Enter เพื่อปิด...")
  sys.exit()

print("=" * 65)
print(f"ตรวจพบออเดอร์ TikTok พร้อมประมวลผล: {len(active_folders)} ออเดอร์")
print("=" * 65)

# -------------------------------------------------------------
# 3. Prompt: ให้โมเดลอ่านตามที่เห็นในภาพ (คงเดิมเพื่อใช้ cache เดิมได้)
# -------------------------------------------------------------
prompt = """
Extract TikTok Shop order details from the attached screenshots.
Read ONLY what is visible. Copy visible text exactly. Do not guess or classify.
Return JSON only, with exactly these keys:
{
  "ข้อความขนส่ง": "",
  "ข้อความจัดส่ง": "",
  "ข้อความป้ายร้าน": "",
  "ข้อความการชำระเงิน": "",
  "tracking_number": "",
  "หมายเลขคำสั่งซื้อ": "",
  "ชื่อร้านค้า": "",
  "รายการสินค้า": [{"ชื่อสินค้า": "", "รุ่น_ขนาดสินค้า": "", "ราคา": 0, "จำนวนชิ้น": 1}],
  "ราคารวมค่าสินค้า_ก่อนส่วนลด": 0,
  "ค่าจัดส่ง": 0,
  "ส่วนลดค่าจัดส่ง": 0,
  "ส่วนลด_โค้ด_Shopee": 0,
  "ส่วนลด_ร้านค้า": 0,
  "ส่วนลดช่องทางการชำระเงิน": 0,
  "การใช้เหรียญ_Shopee": 0,
  "ส่วนลดอื่นๆ": 0,
  "ค่าใช้จ่ายอื่นๆ": 0,
  "ราคารวม_หลังส่วนลด": 0,
  "วันสั่งซื้อ_ดิบ": "",
  "วันชำระเงิน_ดิบ": "",
  "วันจัดส่ง_ดิบ": "",
  "วันส่งมอบ_ดิบ": ""
}

กฎการอ่านค่า:
1. ข้อความขนส่ง: ชื่อขนส่งตามที่เห็น เช่น J&T Express, Flash Express, KEX Express, BEST Express, ไปรษณีย์ไทย, Seller's Own Fleet, อื่นๆ ระบุ
2. ข้อความจัดส่ง: ข้อความประเภทการจัดส่งตามที่เห็น เช่น การจัดส่งมาตรฐาน, Standard delivery, Standard international delivery, Same-day delivery
3. ข้อความป้ายร้าน: ป้ายที่เห็น เช่น Mall, TopChoice, Preferred ถ้าไม่มีให้ว่าง
4. ข้อความการชำระเงิน: คัดลอกชื่อช่องทางชำระเงินตามที่เห็นบนหน้าจอให้ครบ ถ้าไม่มีให้ว่าง
5. tracking_number: จากแถว หมายเลขการติดตาม หากไม่มีให้ใส่ 9999
6. หมายเลขคำสั่งซื้อ: ตัวเลขจากแถว หมายเลขคำสั่งซื้อ
7. ชื่อร้านค้า: ชื่อร้านที่อยู่ข้างป้ายร้าน
8. รายการสินค้า: แยกทุกชิ้นเป็นรายการ ถ้าชื่อเต็มมองไม่เห็นให้ใส่เท่าที่เห็น
9. ราคา: ใช้ราคาตามบรรทัดสินค้า (ที่แสดงข้างจำนวน x1)
10. ช่องราคา ใส่เฉพาะตัวเลข ไม่มีลูกน้ำและไม่มี ฿ ดังนี้
   - แถว ยอดรวม -> ราคารวมค่าสินค้า_ก่อนส่วนลด
   - แถว การจัดส่ง -> ค่าจัดส่ง
   - แถว คูปองการจัดส่งของ TikTok -> ส่วนลดค่าจัดส่ง
   - แถว คูปอง -> ส่วนลด_โค้ด_Shopee
   - แถว คูปองร้านค้า -> ส่วนลด_ร้านค้า
   - แถว ส่วนลดช่องทางการชำระเงิน -> ส่วนลดช่องทางการชำระเงิน
   - แถว ส่วนลดอื่นๆ -> ส่วนลดอื่นๆ
   - แถว ค่าใช้จ่ายอื่นๆ -> ค่าใช้จ่ายอื่นๆ
   - แถว ทั้งหมด -> ราคารวม_หลังส่วนลด
   - ไม่มีแถวนั้นในภาพ ให้ใส่ 0
11. วันที่และเวลา คัดลอกทั้งบรรทัดตามที่เห็น เช่น "10 พ.ค. 2026 5:19 PM"
   - วันสั่งซื้อ_ดิบ -> แถว วันที่สั่งซื้อ
   - วันชำระเงิน_ดิบ -> แถว เวลาที่ชำระเงิน
   - วันจัดส่ง_ดิบ -> แถว วันที่จัดส่ง
   - วันส่งมอบ_ดิบ -> แถว วันที่ส่งมอบ
   ไม่มีแถวใดให้ใส่ว่าง
"""

PROMPT_HASH = hashlib.md5(prompt.encode("utf-8")).hexdigest()

client = genai.Client(api_key=API_KEY)

fast_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    temperature=0.0,
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)
plain_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    temperature=0.0,
)


# -------------------------------------------------------------
# 4. ความจำชั่วคราว (cache): ตรวจจากเนื้อไฟล์รูป
# -------------------------------------------------------------
def make_signature(img_paths):
  files = []
  for p in sorted(img_paths):
    with open(p, "rb") as f:
      files.append(os.path.basename(p) + ":" + hashlib.md5(f.read()).hexdigest())
  return {"files": files, "prompt": PROMPT_HASH}


def load_cache(path, sig):
  if not os.path.exists(path):
    return None
  try:
    with open(path, encoding="utf-8") as f:
      saved = json.load(f)
    if saved.get("signature") == sig:
      return saved.get("raw")
  except Exception:
    pass
  return None


def save_cache(path, sig, raw):
  with open(path, "w", encoding="utf-8") as f:
    json.dump({"signature": sig, "raw": raw}, f, ensure_ascii=False, indent=2)


# -------------------------------------------------------------
# 5. รูปภาพของออเดอร์ (ใช้แสดงในหน้าเว็บ)
# -------------------------------------------------------------
def image_urls(img_paths):
  urls = []
  for p in sorted(img_paths, key=lambda x: natural_sort_key(os.path.basename(x))):
    rel = os.path.relpath(p, current_dir).replace("\\", "/")
    urls.append(urllib.parse.quote(rel, safe="/"))
  return urls


# -------------------------------------------------------------
# 6. เรียก AI ให้อ่านรูปของหนึ่งออเดอร์
# -------------------------------------------------------------
def call_model(folder_name, img_paths):
  images = []
  for p in img_paths:
    try:
      images.append(load_optimized_image(p))
    except Exception as e:
      print(f"   ไม่สามารถเปิดไฟล์ {os.path.basename(p)}: {e}")

  if not images:
    return None, "เปิดรูปไม่ได้เลย"

  contents = [prompt] + images
  response = None
  used_model = None
  last_err = ""

  for m in MODELS_TO_USE:
    for attempt in range(MAX_TRIES):
      try:
        response = client.models.generate_content(
            model=m, contents=contents, config=(plain_config if "3.5" in m else fast_config),
        )
        used_model = m
        break
      except Exception as err:
        last_err = str(err)[:150]
        if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
          print(f"   {m} โควตาเต็ม รอ 3 วินาที ({attempt + 1}/{MAX_TRIES})")
          time.sleep(3)
          continue
        if "503" in last_err or "UNAVAILABLE" in last_err:
          print(f"   {m} คนแน่น รอ 2 วินาที ({attempt + 1}/{MAX_TRIES})")
          time.sleep(2)
          continue
        print(f"   {m} ใช้ไม่ได้ สลับไปตัวถัดไป")
        break
    if response is not None:
      break

  if response is None:
    return None, last_err or "ไม่มีการตอบกลับ"

  try:
    text = (response.text or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    raw = json.loads(match.group(0) if match else text)
    return raw, used_model
  except Exception as e:
    return None, f"อ่านคำตอบไม่ได้: {e}"


# -------------------------------------------------------------
# 7. จัดหมวดหมู่ตามกฎ
# -------------------------------------------------------------
def pick(text, rules, default):
  t = str(text or "").lower()
  for keywords, label in rules:
    if any(k in t for k in keywords):
      return label
  return default


def classify(data):
  carrier = pick(data.pop("ข้อความขนส่ง", ""), CARRIER_RULES, "อื่นๆ")
  shipping = pick(data.pop("ข้อความจัดส่ง", ""), SHIP_RULES, "ส่งมาตรฐาน")
  shop = pick(data.pop("ข้อความป้ายร้าน", ""), SHOP_RULES, "ร้านปกติ")

  # ช่องทางชำระเงิน: จับคู่กับฟอร์ม ถ้าไม่ตรงให้แสดงข้อความที่อ่านได้จริง
  raw_pay = str(data.pop("ข้อความการชำระเงิน", "") or "").strip()
  payment = match_payment(raw_pay) or (raw_pay if raw_pay else "-")

  # วันและเวลาสั่งซื้อ / ชำระเงิน / สำเร็จ ตามที่แยกไว้ในข้อ 1-2 และ 4 (ค่าอยู่ใน data แล้ว)
  # วันและเวลาจัดส่ง = วันและเวลาสำเร็จ (ข้อ 3 = ข้อ 4) ทุกออเดอร์ ไม่มีเงื่อนไข
  data["วันจัดส่งสินค้า"] = data.get("วันที่สำเร็จ_ส่งมอบ", "-")
  data["เวลาจัดส่งสินค้า_HHMM"] = data.get("เวลาที่สำเร็จ_HHMM", "-")

  data["แพลตฟอร์ม"] = "Tiktok"
  data["บริษัทขนส่ง"] = carrier
  data["ข้อมูลการจัดส่ง"] = shipping
  data["ประเภทร้านค้า"] = shop
  data["ช่องทางการชำระเงิน"] = payment
  return data


# -------------------------------------------------------------
# 8. ตรวจความถูกต้อง: คืนข้อความเตือน ว่างแปลว่าผ่าน
# -------------------------------------------------------------
DATE_RE = r"^\d{2}-\d{2}-2026$"


def validate(r):
  issues = []

  for k in DATE_FIELDS:
    v = str(r.get(k, "-"))
    if not re.match(DATE_RE, v):
      issues.append(f"{k} ผิดรูปแบบ ({v})")

  for k in TIME_FIELDS:
    v = str(r.get(k, "-"))
    if not re.match(r"^\d{4}$", v):
      issues.append(f"{k} ผิดรูปแบบ ({v})")

  if str(r.get("tracking_number", "")).strip() in ["", "-", "9999"]:
    issues.append("ไม่พบเลข Tracking")

  pay = r.get("ช่องทางการชำระเงิน", "")
  if pay not in PAYMENT_FORM_NAMES:
    issues.append(f"ช่องทางชำระเงินไม่ตรงกับฟอร์ม (อ่านได้: {pay})")

  if r.get("บริษัทขนส่ง") == "อื่นๆ":
    issues.append("ไม่รู้จักบริษัทขนส่ง")

  if not r.get("รายการสินค้า"):
    issues.append("ไม่พบรายการสินค้า")

  total = to_float(r.get("ราคารวม_หลังส่วนลด"))
  if total > 0:
    expected = (
        to_float(r.get("ราคารวมค่าสินค้า_ก่อนส่วนลด"))
        + to_float(r.get("ค่าจัดส่ง"))
        - sum(to_float(r.get(k)) for k in DISCOUNT_FIELDS)
        + to_float(r.get("ค่าใช้จ่ายอื่นๆ"))
    )
    if abs(expected - total) > 1:
      issues.append(
          f"ยอดไม่ตรงกับการคำนวณ (คำนวณได้ {expected:g} อ่านได้ {total:g})"
      )

  return " | ".join(issues)


# -------------------------------------------------------------
# 9. แปลงคำตอบดิบให้เป็นแถวข้อมูลที่พร้อมใช้
# -------------------------------------------------------------
def build_record(raw, folder_name):
  data = dict(raw)

  # วันเวลาสั่งซื้อ / ชำระเงิน / สำเร็จ (ข้อ 3 ไม่ได้อ่านจากภาพ แต่ใช้ค่าของข้อ 4)
  for raw_key, date_key, time_key in [
      ("วันสั่งซื้อ_ดิบ", "วันสั่งซื้อ", "เวลาสั่งซื้อ_HHMM"),
      ("วันชำระเงิน_ดิบ", "วันชำระเงิน", "เวลาชำระเงิน_HHMM"),
      ("วันส่งมอบ_ดิบ", "วันที่สำเร็จ_ส่งมอบ", "เวลาที่สำเร็จ_HHMM"),
  ]:
    d, t = parse_tiktok_datetime(data.get(raw_key))
    data[date_key] = d
    data[time_key] = t

  for k in list(data.keys()):
    if k.endswith("_ดิบ"):
      data.pop(k)

  data = classify(data)

  r = {"โฟลเดอร์": folder_name}

  for k, v in data.items():
    if k == "รายการสินค้า":
      items_list = []
      for item in v or []:
        price = clean_number(item.get("ราคา", 0))
        items_list.append({
            "ชื่อสินค้า": clean_product_name(item.get("ชื่อสินค้า", "-")),
            "รุ่น_ขนาดสินค้า": str(item.get("รุ่น_ขนาดสินค้า", "-")),
            "ราคาเต็ม": price,
            "ราคาที่ลดแล้ว": price,
            "จำนวนชิ้น": clean_number(item.get("จำนวนชิ้น", 1)),
        })
      r["รายการสินค้า"] = items_list
    elif k in MONEY_FIELDS:
      r[k] = clean_number(v)
    else:
      r[k] = v

  r["จำนวนรายการสินค้า_SKU"] = len(r.get("รายการสินค้า", []))
  r["ตรวจสอบ"] = validate(r)
  return r


# -------------------------------------------------------------
# 10. ประมวลผลทีละออเดอร์
# -------------------------------------------------------------
os.makedirs(CACHE_DIR, exist_ok=True)

total = len(active_folders)
results = []
failed = []
reused = 0

for idx, (folder_path, img_paths) in enumerate(active_folders, start=1):
  folder_name = os.path.basename(folder_path)
  print(f"\n[{idx}/{total}] {folder_name} (พบรูป {len(img_paths)} รูป)")

  sig = make_signature(img_paths)
  cache_path = os.path.join(CACHE_DIR, folder_name + ".json")
  raw = load_cache(cache_path, sig)

  if raw is not None:
    reused += 1
    print("   ใช้ผลที่เคยอ่านแล้ว (ไม่เรียก AI)")
  else:
    t0 = time.time()
    raw, info = call_model(folder_name, img_paths)
    if raw is None:
      print(f"   อ่านไม่สำเร็จ: {info}")
      failed.append((folder_name, info))
      continue
    print(f"   อ่านสำเร็จด้วย {info} ใน {time.time() - t0:.1f} วินาที")
    save_cache(cache_path, sig, raw)

  try:
    record = build_record(raw, folder_name)
  except Exception as e:
    print(f"   จัดรูปแบบข้อมูลไม่สำเร็จ: {e}")
    failed.append((folder_name, f"จัดรูปแบบไม่ได้: {e}"))
    continue

  record["รูปภาพ"] = image_urls(img_paths)
  results.append(record)
  print(
      f"   เลขออเดอร์: {record.get('หมายเลขคำสั่งซื้อ')}"
      f" | SKU: {record['จำนวนรายการสินค้า_SKU']}"
  )
  if record["ตรวจสอบ"]:
    print(f"   ⚠ ควรตรวจสอบ: {record['ตรวจสอบ']}")

# -------------------------------------------------------------
# 11. สรุปผล
# -------------------------------------------------------------
print("\n" + "=" * 65)
print(f"สำเร็จ {len(results)} จาก {total} ออเดอร์ (ใช้ผลเดิม {reused} ออเดอร์)")

if failed:
  print("ยังอ่านไม่ได้ (รันใหม่อีกครั้งจะลองเฉพาะรายการนี้):")
  for name, why in failed:
    print(f"   - {name}: {why}")

flagged = [r["โฟลเดอร์"] for r in results if r.get("ตรวจสอบ")]
if flagged:
  print("ควรเปิดตรวจสอบก่อนใช้งาน:", ", ".join(flagged))
print("=" * 65)

if not results:
  print("\nไม่มีข้อมูลถูกบันทึก")
  input("\nกด Enter เพื่อปิด...")
  sys.exit()

# -------------------------------------------------------------
# 12. บันทึกลง Excel (1 แถวต่อ 1 SKU) ชื่อไฟล์ตามเวลา
# -------------------------------------------------------------
excel_rows = []
for r in results:
  items = r.get("รายการสินค้า", [])
  if not items:
    items = [{}]
  for s_idx, itm in enumerate(items, start=1):
    excel_rows.append({
        "โฟลเดอร์": r.get("โฟลเดอร์"),
        "แพลตฟอร์ม": r.get("แพลตฟอร์ม"),
        "บริษัทขนส่ง": r.get("บริษัทขนส่ง"),
        "ข้อมูลการจัดส่ง": r.get("ข้อมูลการจัดส่ง"),
        "tracking_number": r.get("tracking_number"),
        "หมายเลขคำสั่งซื้อ": r.get("หมายเลขคำสั่งซื้อ"),
        "ชื่อร้านค้า": r.get("ชื่อร้านค้า"),
        "ประเภทร้านค้า": r.get("ประเภทร้านค้า"),
        "จำนวนรายการสินค้า_SKU": r.get("จำนวนรายการสินค้า_SKU"),
        "SKU_ลำดับที่": s_idx,
        "ชื่อสินค้า": itm.get("ชื่อสินค้า", "-"),
        "รุ่น_ขนาดสินค้า": itm.get("รุ่น_ขนาดสินค้า", "-"),
        "ราคาเต็ม": itm.get("ราคาเต็ม", 0),
        "ราคาที่ลดแล้ว": itm.get("ราคาที่ลดแล้ว", 0),
        "จำนวนชิ้น": itm.get("จำนวนชิ้น", 1),
        "ราคารวมค่าสินค้า_ก่อนส่วนลด": r.get("ราคารวมค่าสินค้า_ก่อนส่วนลด"),
        "ค่าจัดส่ง": r.get("ค่าจัดส่ง"),
        "ส่วนลดค่าจัดส่ง": r.get("ส่วนลดค่าจัดส่ง"),
        "ส่วนลด_โค้ด_Shopee": r.get("ส่วนลด_โค้ด_Shopee"),
        "ส่วนลด_ร้านค้า": r.get("ส่วนลด_ร้านค้า"),
        "ส่วนลดช่องทางการชำระเงิน": r.get("ส่วนลดช่องทางการชำระเงิน"),
        "การใช้เหรียญ_Shopee": r.get("การใช้เหรียญ_Shopee"),
        "ส่วนลดอื่นๆ": r.get("ส่วนลดอื่นๆ"),
        "ค่าใช้จ่ายอื่นๆ": r.get("ค่าใช้จ่ายอื่นๆ"),
        "ราคารวม_หลังส่วนลด": r.get("ราคารวม_หลังส่วนลด"),
        "ช่องทางการชำระเงิน": r.get("ช่องทางการชำระเงิน"),
        "วันสั่งซื้อ": r.get("วันสั่งซื้อ"),
        "เวลาสั่งซื้อ_HHMM": r.get("เวลาสั่งซื้อ_HHMM"),
        "วันชำระเงิน": r.get("วันชำระเงิน"),
        "เวลาชำระเงิน_HHMM": r.get("เวลาชำระเงิน_HHMM"),
        "วันจัดส่งสินค้า": r.get("วันจัดส่งสินค้า"),
        "เวลาจัดส่งสินค้า_HHMM": r.get("เวลาจัดส่งสินค้า_HHMM"),
        "วันที่สำเร็จ_ส่งมอบ": r.get("วันที่สำเร็จ_ส่งมอบ"),
        "เวลาที่สำเร็จ_HHMM": r.get("เวลาที่สำเร็จ_HHMM"),
        "ตรวจสอบ": r.get("ตรวจสอบ", ""),
    })

df = pd.DataFrame(excel_rows)
# เปลี่ยนหัวคอลัมน์ให้เป็นของ TikTok และตัดคอลัมน์ที่ TikTok ไม่มี
df = df.rename(columns={"ส่วนลด_โค้ด_Shopee": "คูปอง_TikTok"}).drop(columns=["การใช้เหรียญ_Shopee"])

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
excel_file = f"tiktok_result_{stamp}.xlsx"
try:
  df.to_excel(excel_file, index=False)
except PermissionError:
  excel_file = f"tiktok_result_{stamp}_2.xlsx"
  df.to_excel(excel_file, index=False)

print(f"\nบันทึกไฟล์ '{excel_file}' สำเร็จเรียบร้อย!")

# -------------------------------------------------------------
# 13. สร้างหน้าเว็บฟิล์มหนัง HTML (ตามฟอร์ม TikTok + รูปภาพในออเดอร์)
# -------------------------------------------------------------
print("กำลังสร้างหน้าเว็บช่วยกรอกข้อมูล...")

records_json = json.dumps(results, ensure_ascii=False)

html_template = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>ตัวช่วยคัดลอกข้อมูลออเดอร์ TikTok (แบบฟิล์มหนัง)</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 0; }
  
  .filmstrip-container { background: #1e293b; border-bottom: 2px solid #334155; padding: 12px 20px; position: sticky; top: 0; z-index: 100; box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
  .filmstrip-header { display: flex; justify-content: space-between; align-items: center; max-width: 1350px; margin: 0 auto 10px auto; }
  .filmstrip-title { font-size: 16px; font-weight: bold; color: #38bdf8; display: flex; align-items: center; gap: 8px; }
  .stats { font-size: 13px; color: #94a3b8; }
  
  .filmstrip { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; max-width: 1350px; margin: 0 auto; scrollbar-width: thin; scrollbar-color: #475569 #1e293b; }
  .film-frame { flex: 0 0 auto; min-width: 75px; height: 42px; background: #334155; border: 1px solid #475569; border-radius: 6px; display: flex; flex-direction: column; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s; font-size: 12px; }
  .film-frame:hover { background: #475569; border-color: #38bdf8; }
  .film-frame.active { background: #0284c7; border-color: #38bdf8; font-weight: bold; color: white; transform: scale(1.05); }
  .film-frame.done { background: #065f46; border-color: #10b981; color: #a7f3d0; }
  .film-frame.done::after { content: ' ✓'; font-size: 10px; color: #34d399; font-weight: bold; }

  .main-stage { max-width: 1350px; margin: 25px auto; padding: 0 20px 80px 20px; }
  .order-card { background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 25px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
  .card-top { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 15px; margin-bottom: 20px; }
  .card-title { font-size: 20px; font-weight: bold; color: #f1f5f9; }
  .nav-buttons { display: flex; gap: 10px; }
  .nav-btn { background: #334155; color: white; border: 1px solid #475569; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; font-weight: bold; }
  .nav-btn:hover { background: #475569; }

  .gallery-wrap { display: flex; align-items: center; gap: 8px; margin-bottom: 18px; }
  .gallery { display: flex; gap: 10px; overflow-x: auto; flex: 1; scroll-behavior: smooth; padding-bottom: 6px; scrollbar-width: thin; scrollbar-color: #475569 #1e293b; }
  .gallery img { flex: 0 0 31%; width: 31%; height: 260px; object-fit: contain; background: #ffffff; border-radius: 8px; border: 1px solid #334155; cursor: zoom-in; }
  .gal-btn { background: #334155; color: white; border: 1px solid #475569; border-radius: 8px; width: 36px; height: 36px; cursor: pointer; flex-shrink: 0; font-size: 14px; }
  .gal-btn:hover { background: #475569; }
  .gallery-empty { color: #94a3b8; font-size: 13px; margin-bottom: 18px; }

  #lightbox { position: fixed; inset: 0; background: rgba(0,0,0,0.92); display: none; align-items: center; justify-content: center; z-index: 1000; cursor: zoom-out; }
  #lightbox img { max-width: 95vw; max-height: 95vh; object-fit: contain; }

  .warn-box { background: #451a03; border: 1px solid #f59e0b; color: #fde68a; border-radius: 8px; padding: 10px 14px; margin-bottom: 18px; font-size: 13px; }

  .grid-layout { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 15px; margin-bottom: 25px; align-items: start; }
  .section-box { background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 14px; }
  .section-name { font-size: 12px; font-weight: bold; color: #38bdf8; margin-bottom: 12px; padding-bottom: 4px; border-bottom: 1px solid #1e293b; text-transform: uppercase; }
  
  .sku-block { background: #172554; border: 1px solid #1e40af; border-radius: 8px; padding: 10px; margin-top: 10px; }
  .sku-badge { font-size: 11px; font-weight: bold; color: #fbbf24; margin-bottom: 6px; text-transform: uppercase; display: flex; justify-content: space-between; }

  .item-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; gap: 8px; }
  .item-label { color: #94a3b8; font-size: 12px; flex-shrink: 0; }
  
  .copy-target { cursor: pointer; background: #1e293b; border: 1px solid #475569; color: #f8fafc; padding: 5px 10px; border-radius: 6px; font-size: 13px; font-weight: 500; max-width: 165px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; transition: all 0.15s; position: relative; }
  .copy-target:hover { background: #0284c7; border-color: #38bdf8; transform: translateY(-1px); }
  .copy-target:active { transform: scale(0.92); }
  
  .copy-target.copied { border-color: #10b981 !important; color: #34d399 !important; background: #064e3b !important; }
  .copy-target.copied::after { content: ' ✓'; font-size: 10px; font-weight: bold; }

  .highlight-val { color: #f87171 !important; font-weight: bold; font-size: 14px; }
  .total-row { background: #450a0a; padding: 4px 6px; border-radius: 6px; margin-top: 8px; }

  .action-footer { display: flex; justify-content: center; margin-top: 20px; }
  .close-order-btn { background: #10b981; color: white; border: none; border-radius: 10px; padding: 14px 35px; font-size: 16px; font-weight: bold; cursor: pointer; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3); transition: 0.2s; display: flex; align-items: center; gap: 8px; }
  .close-order-btn:hover { background: #059669; transform: scale(1.02); }
  .close-order-btn.is-closed { background: #475569; color: #cbd5e1; box-shadow: none; }

  .toast { position: fixed; bottom: 30px; right: 30px; background: #38bdf8; color: #0f172a; padding: 12px 22px; border-radius: 8px; font-weight: bold; font-size: 14px; display: none; z-index: 999; box-shadow: 0 6px 20px rgba(0,0,0,0.4); }
</style>
</head>
<body>

<div class="filmstrip-container">
  <div class="filmstrip-header">
    <div class="filmstrip-title">🎞️ ฟิล์มม้วนออเดอร์ TikTok (เลือกออเดอร์ที่ต้องการ)</div>
    <div class="stats" id="statsDisplay">กำลังโหลด...</div>
  </div>
  <div class="filmstrip" id="filmstripBar"></div>
</div>

<div class="main-stage">
  <div class="order-card" id="cardContainer"></div>
</div>

<div class="toast" id="toast">คัดลอกเรียบร้อย! ✨</div>

<div id="lightbox" onclick="closeLightbox()">
  <img id="lightboxImg" src="" alt="">
</div>

<script>
const orders = __ORDERS_JSON_DATA__;
let currentIndex = 0;

function keyOf(idx) {
  return 'tiktok_done_' + (orders[idx]['หมายเลขคำสั่งซื้อ'] || orders[idx]['โฟลเดอร์']);
}

function isDone(idx) {
  return localStorage.getItem(keyOf(idx)) === 'true';
}

function renderFilmstrip() {
  const bar = document.getElementById('filmstripBar');
  bar.innerHTML = '';
  let doneCount = 0;

  orders.forEach((ord, i) => {
    const done = isDone(i);
    if (done) doneCount++;
    const frame = document.createElement('div');
    frame.className = `film-frame ${i === currentIndex ? 'active' : ''} ${done ? 'done' : ''}`;
    frame.innerHTML = `<span>#${i+1}${ord['ตรวจสอบ'] ? ' ⚠' : ''}</span><small style="font-size:10px;">${ord['โฟลเดอร์'] || ''}</small>`;
    frame.onclick = () => selectOrder(i);
    bar.appendChild(frame);
  });

  document.getElementById('statsDisplay').innerText = `เสร็จแล้ว ${doneCount} / ${orders.length} ออเดอร์ (กดปุ่ม ◀ / ▶ บนคีย์บอร์ดเพื่อเลื่อนได้)`;
}

function selectOrder(i) {
  currentIndex = i;
  renderFilmstrip();
  renderCard();
}

function nextOrder() {
  if (currentIndex < orders.length - 1) selectOrder(currentIndex + 1);
}

function prevOrder() {
  if (currentIndex > 0) selectOrder(currentIndex - 1);
}

function toggleCloseCurrent() {
  const key = keyOf(currentIndex);
  const currentStatus = isDone(currentIndex);
  if (currentStatus) {
    localStorage.removeItem(key);
  } else {
    localStorage.setItem(key, 'true');
    setTimeout(() => {
      if (currentIndex < orders.length - 1) nextOrder();
    }, 400);
  }
  renderFilmstrip();
  renderCard();
}

function copyTarget(el) {
  const val = el.getAttribute('data-copy');
  if (val === undefined || val === null || val === '' || val === '-') return;

  navigator.clipboard.writeText(val).then(() => {
    const toast = document.getElementById('toast');
    toast.innerText = 'คัดลอก: "' + val + '" แล้ว! ✅';
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 1000);

    el.classList.add('copied');
  });
}

function escapeHtml(text) {
  if (!text && text !== 0) return '-';
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// แถวข้อมูลหนึ่งแถว: ชื่อช่อง + ค่าที่คัดลอกได้
function row(label, val) {
  const v = escapeHtml(val);
  return `<div class="item-row"><span class="item-label">${label}</span><span class="copy-target" data-copy="${v}" onclick="copyTarget(this)">${v}</span></div>`;
}

// แถบรูปภาพของออเดอร์ (เลื่อนดูได้ และคลิกเพื่อขยาย)
function galleryHtml(urls) {
  if (!urls || urls.length === 0) {
    return '<div class="gallery-empty">ไม่มีรูปในโฟลเดอร์นี้</div>';
  }
  const imgs = urls.map((u, i) => `<img src="${u}" alt="รูปที่ ${i + 1}" onclick="openLightbox(this.src)">`).join('');
  return `
    <div class="gallery-wrap">
      <button class="gal-btn" onclick="scrollGallery(-1)">◀</button>
      <div class="gallery" id="gallery">${imgs}</div>
      <button class="gal-btn" onclick="scrollGallery(1)">▶</button>
    </div>`;
}

function scrollGallery(dir) {
  const g = document.getElementById('gallery');
  if (g) g.scrollBy({ left: dir * g.clientWidth * 0.9, behavior: 'smooth' });
}

function openLightbox(src) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightbox').style.display = 'flex';
}

function closeLightbox() {
  document.getElementById('lightbox').style.display = 'none';
}

function renderCard() {
  const d = orders[currentIndex];
  const done = isDone(currentIndex);
  const container = document.getElementById('cardContainer');
  const items = d['รายการสินค้า'] || [];

  // ช่องสินค้า: TikTok มีแค่ "ราคา" อันเดียว (ไม่มีราคาเต็ม/ราคาลดแล้วแยก)
  let skuHtml = '';
  items.forEach((item, k) => {
    skuHtml += `
      <div class="sku-block">
        <div class="sku-badge">
          <span>📦 สินค้า (SKU) ที่ ${k + 1}</span>
          <span>จำนวน: ${escapeHtml(item['จำนวนชิ้น'])} ชิ้น</span>
        </div>
        ${row('ชื่อสินค้า', item['ชื่อสินค้า'])}
        ${row('รุ่น/ขนาด', item['รุ่น_ขนาดสินค้า'])}
        ${row('ราคา', item['ราคาที่ลดแล้ว'])}
        ${row('จำนวนชิ้น', item['จำนวนชิ้น'])}
      </div>
    `;
  });

  const warning = d['ตรวจสอบ']
    ? `<div class="warn-box">⚠ ควรตรวจสอบ: ${escapeHtml(d['ตรวจสอบ'])}</div>`
    : '';

  container.innerHTML = `
    <div class="card-top">
      <div>
        <span class="card-title">ออเดอร์ #${currentIndex + 1} (${escapeHtml(d['โฟลเดอร์'])})</span>
        <span style="margin-left: 10px; font-size:13px; color:#38bdf8;">${escapeHtml(d['แพลตฟอร์ม'])}</span>
      </div>
      <div class="nav-buttons">
        <button class="nav-btn" onclick="prevOrder()" ${currentIndex === 0 ? 'disabled' : ''}>◀ ก่อนหน้า</button>
        <button class="nav-btn" onclick="nextOrder()" ${currentIndex === orders.length - 1 ? 'disabled' : ''}>ถัดไป ▶</button>
      </div>
    </div>

    ${warning}

    ${galleryHtml(d['รูปภาพ'])}

    <div class="grid-layout">
      <!-- 1. จัดส่ง & คำสั่งซื้อ -->
      <div class="section-box">
        <div class="section-name">1. จัดส่ง & คำสั่งซื้อ</div>
        ${row('1. บริษัทขนส่ง', d['บริษัทขนส่ง'])}
        ${row('2. ประเภทส่ง', d['ข้อมูลการจัดส่ง'])}
        ${row('3. Tracking', d['tracking_number'])}
        ${row('4. เลขออเดอร์', d['หมายเลขคำสั่งซื้อ'])}
      </div>

      <!-- 2. ร้านค้า & สินค้า -->
      <div class="section-box">
        <div class="section-name">2. ร้านค้า & สินค้า (${items.length} SKU)</div>
        ${row('ชื่อร้าน', d['ชื่อร้านค้า'])}
        ${row('ประเภทร้าน', d['ประเภทร้านค้า'])}
        ${row('จำนวน SKU', items.length)}
        ${skuHtml}
      </div>

      <!-- 3. ราคา & ส่วนลด (เรียงตามฟอร์ม TikTok) -->
      <div class="section-box">
        <div class="section-name">3. ราคา & ส่วนลด (บาท)</div>
        <div class="item-row total-row">
          <span class="item-label" style="color:#fca5a5; font-weight:bold;">ทั้งหมด (Total)</span>
          <span class="copy-target highlight-val" data-copy="${escapeHtml(d['ราคารวม_หลังส่วนลด'])}" onclick="copyTarget(this)">${escapeHtml(d['ราคารวม_หลังส่วนลด'])}</span>
        </div>
        ${row('ยอดรวม (Subtotal)', d['ราคารวมค่าสินค้า_ก่อนส่วนลด'])}
        ${row('การจัดส่ง (Shipping)', d['ค่าจัดส่ง'])}
        ${row('ส่วนลด คูปอง TikTok Shop', d['ส่วนลด_โค้ด_Shopee'])}
        ${row('คูปองร้านค้า (Seller coupons)', d['ส่วนลด_ร้านค้า'])}
        ${row('คูปองการจัดส่งของ TikTok', d['ส่วนลดค่าจัดส่ง'])}
        ${row('ส่วนลดช่องทางการชำระเงิน', d['ส่วนลดช่องทางการชำระเงิน'])}
        ${row('ส่วนลดอื่นๆ', d['ส่วนลดอื่นๆ'])}
        ${row('ค่าใช้จ่ายอื่นๆ', d['ค่าใช้จ่ายอื่นๆ'])}
      </div>

      <!-- 4. ชำระเงิน & วัน-เวลา (ข้อ 3 = ข้อ 4) -->
      <div class="section-box">
        <div class="section-name">4. ชำระเงิน & วัน-เวลา</div>
        ${row('ช่องทางจ่าย', d['ช่องทางการชำระเงิน'])}
        ${row('1. วันสั่งซื้อ', d['วันสั่งซื้อ'])}
        ${row('เวลาสั่งซื้อ', d['เวลาสั่งซื้อ_HHMM'])}
        ${row('2. วันชำระเงิน', d['วันชำระเงิน'])}
        ${row('เวลาชำระเงิน', d['เวลาชำระเงิน_HHMM'])}
        ${row('3. วันจัดส่ง', d['วันจัดส่งสินค้า'])}
        ${row('เวลาจัดส่ง', d['เวลาจัดส่งสินค้า_HHMM'])}
        ${row('4. วันสำเร็จ', d['วันที่สำเร็จ_ส่งมอบ'])}
        ${row('เวลาสำเร็จ', d['เวลาที่สำเร็จ_HHMM'])}
      </div>
    </div>

    <!-- ปุ่มปิดออเดอร์ -->
    <div class="action-footer">
      <button class="close-order-btn ${done ? 'is-closed' : ''}" onclick="toggleCloseCurrent()">
        ${done ? '↩️ ยกเลิกสถานะปิดออเดอร์ (เปิดใหม่)' : '🔒 ปิดออเดอร์นี้แล้ว (บันทึกว่ากรอกเสร็จสิ้น)'}
      </button>
    </div>
  `;
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowRight') nextOrder();
  if (e.key === 'ArrowLeft') prevOrder();
});

renderFilmstrip();
renderCard();
</script>
</body>
</html>
"""

html_content = html_template.replace("__ORDERS_JSON_DATA__", records_json)

with open(HTML_FILE, "w", encoding="utf-8") as f:
  f.write(html_content)

print(f"สร้างหน้าเว็บสำเร็จ: {HTML_FILE}")
print("กำลังเปิดหน้าเว็บบนเบราว์เซอร์อัตโนมัติ...")
os.system(f"start {HTML_FILE}")