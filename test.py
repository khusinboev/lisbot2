"""
test.py — Loyihani to'liq test qilish (pro daraja anti-bot)

Bu fayl loyihadagi barcha scraping modulini (kochirish_html.py dagi mukammal hardened versiya)
to'liq ishga tushirib, faqat BITTA sahifadan (page 0) ma'lumot yig'adi va
faqat BIRINCHI sertifikatni batafsil print qiladi.

Nima qiladi:
- Driverni pro darajada anti-bot bilan ishga tushiradi (YouTube warmup, human mouse/scroll/typing,
  navigator spoofing, canvas/WebGL fingerprint protection, random delays, binary detection va boshqalar)
- Sahifani ochadi, ro'yxatni kutadi, modalga kirib UUID + to'liq ma'lumotlarni oladi
- Natijani JSON + pprint bilan chiqaradi (copy-paste uchun qulay)

Ishga tushirish:
    python test.py

Hech qanday Telegram, DB yoki boshqa modul kerak emas — toza standalone test.
"""

import os
import time
import json
from pprint import pprint

# Loyihadagi hardened scraper (chuqur anti-bot bilan)
# (agar fayl nomi kochirish_html_hardened.py bo'lsa, shunga o'zgartiring)
from kochirish_html import fetch_page, set_screenshot_callback

# Screenshot callbackni o'chirib qo'yamiz (testda kerak emas)
set_screenshot_callback(None)

def run_pro_test():
    print("=" * 80)
    print("🚀 PRO ANTI-BOT TEST BOSHLANDI")
    print("   (YouTube warmup + human actions + navigator spoof + fingerprint protection)")
    print("=" * 80)

    start_time = time.time()

    # 0-page (birinchi sahifa) ni yig'amiz — loyihadagi to'liq logika
    data = fetch_page(0)

    elapsed = time.time() - start_time

    if data is None:
        print("❌ YIG'ISH MUVAFFASIYATSIZ — 3 urinishdan keyin ham sahifa/API olinmadi")
        return

    certs = data.get("certificates", [])
    total_pages = data.get("all_pages", 0)
    current_page = data.get("current_page", 0)

    print(f"✅ YIG'ISH MUVAFFAQIYATLI!")
    print(f"   • Page: {current_page + 1}/{total_pages}")
    print(f"   • Sertifikatlar soni: {len(certs)}")
    print(f"   • Vaqt: {elapsed:.2f} soniya")
    print("-" * 80)

    if not certs:
        print("⚠️ Sahifada sertifikat topilmadi")
        return

    # FAQAT BIRINCHI SERTIFIKATNI CHIQARAMIZ (foydalanuvchi talabi)
    first_cert = certs[0]

    print("🔍 BIRINCHI SERTIFIKAT (to'liq ma'lumotlar):")
    print("-" * 80)
    pprint(first_cert, sort_dicts=False)

    print("\n📋 JSON format (copy-paste uchun):")
    print(json.dumps(first_cert, ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print("🎉 TEST TUGADI. Loyiha mukammal ishlamoqda!")
    print("=" * 80)


if __name__ == "__main__":
    # Qo'shimcha anti-bot: testdan oldin env sozlamalari
    os.environ.setdefault("CHROME_HEADLESS", "0")      # testda GUI ko'rsatish (anti-bot uchun yaxshiroq)
    os.environ.setdefault("SKIP_WARMUP", "0")          # warmup majburiy

    run_pro_test()