"""
test.py — bitta sahifadan birinchi yozuvni tekshiruvchi smoke-test.

Bu test scraperning asosiy oqimini tekshiradi:
- page=0 uchun fetch_page chaqiradi,
- ro'yxat qaytganini tekshiradi,
- birinchi yozuvni JSON va pprint ko'rinishida chiqaradi.
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

def run_smoke_test():
    print("=" * 80)
    print("🚀 SMOKE TEST BOSHLANDI")
    print("   (fetch_page(0) va birinchi yozuv tekshiruvi)")
    print("=" * 80)

    start_time = time.time()

    # 0-page (birinchi sahifa) ni yig'amiz — loyihadagi to'liq logika
    data = fetch_page(0)

    elapsed = time.time() - start_time

    if data is None:
        print("❌ YIG'ISH MUVAFFASIYATSIZ — sahifadan ma'lumot olinmadi")
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
    print("🎉 TEST TUGADI")
    print("=" * 80)


if __name__ == "__main__":
    # Smoke test uchun defaultlar; .env qiymatlari bo'lsa o'sha ishlaydi.
    os.environ.setdefault("CHROME_HEADLESS", "1")
    os.environ.setdefault("SKIP_WARMUP", "1")

    run_smoke_test()