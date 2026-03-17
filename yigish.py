"""
yigish.py — SQLite baza va ma'lumot yig'ish moduli
"""

import sqlite3
import threading
import os
import time
from datetime import datetime

from kochirish_html import fetch_page

# ── Config ────────────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(current_dir, "licenses.db")

# Bir vaqtda faqat 1ta yig'ish jarayoni
_collect_lock = threading.Lock()
_collect_running = False


# ── 1. Baza va tablelarni tayyorlash ─────────────────────────────────────────
def init_db():
    """
    Baza va tablelar mavjud bo'lmasa yaratadi.
    Mavjud bo'lsa hech narsa qilmaydi.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1-table: barcha sertifikatlar
    cur.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid            TEXT    UNIQUE NOT NULL,
            number          TEXT,
            tin             INTEGER,
            name            TEXT,
            active          INTEGER,           -- 1/0
            specialization  TEXT,              -- name.oz
            page_num        INTEGER,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # 2-table: faoliyat turi bo'yicha saralangan
    cur.execute("""
        CREATE TABLE IF NOT EXISTS filtered_certificates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid            TEXT    UNIQUE NOT NULL,
            number          TEXT,
            tin             INTEGER,
            name            TEXT,
            active          INTEGER,
            specialization  TEXT,
            page_num        INTEGER,
            filter_tag      TEXT,              -- qaysi filter bilan kiritilgan
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()

    print(f"[yigish] DB tayyor: {DB_PATH}")


# ── Yordamchi: upsert ─────────────────────────────────────────────────────────
def _upsert_certificate(cur, cert: dict, page_num: int):
    cur.execute("""
        INSERT INTO certificates (uuid, number, tin, name, active, specialization, page_num)
        VALUES (:uuid, :number, :tin, :name, :active, :specialization, :page_num)
        ON CONFLICT(uuid) DO UPDATE SET
            number         = excluded.number,
            tin            = excluded.tin,
            name           = excluded.name,
            active         = excluded.active,
            specialization = excluded.specialization,
            page_num       = excluded.page_num
    """, {
        "uuid":           cert.get("uuid"),
        "number":         cert.get("number"),
        "tin":            cert.get("tin"),
        "name":           cert.get("name"),
        "active":         1 if cert.get("active") else 0,
        "specialization": cert.get("specialization_oz", ""),
        "page_num":       page_num,
    })


# ── 2. Barcha ma'lumotlarni yig'ish ──────────────────────────────────────────
def collect_all(status_callback=None):
    """
    Barcha pagelardan ma'lumot yig'ib certificates tableiga yozadi.

    Bir vaqtda faqat 1ta jarayon ishlaydi.
    status_callback(msg: str) — jonli holat xabarlari uchun (ixtiyoriy).
    """
    global _collect_running

    # Parallel ishga tushirishni bloklash
    if not _collect_lock.acquire(blocking=False):
        msg = "[yigish] Jarayon allaqachon ketayapti — bekor qilindi"
        print(msg)
        if status_callback:
            status_callback(msg)
        return False

    _collect_running = True

    def _log(msg):
        print(msg)
        if status_callback:
            status_callback(msg)

    try:
        init_db()

        # Birinchi pageni olib totalPages ni bilamiz
        _log("[yigish] Birinchi page tekshirilmoqda...")
        first = fetch_page(0)
        if first is None:
            _log("[yigish] XATO: birinchi page olinmadi")
            return False

        total_pages = first["all_pages"]
        _log(f"[yigish] Jami {total_pages} ta page ({total_pages * 10} yozuv taxminan)")

        # Birinchi pageni yoz
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for cert in first["certificates"]:
            _upsert_certificate(cur, cert, page_num=0)
        conn.commit()
        conn.close()
        _log(f"[yigish] Page 1/{total_pages} — {len(first['certificates'])} ta yozildi")

        # Qolgan pagelar
        for page in range(1, total_pages):
            _log(f"[yigish] Page {page + 1}/{total_pages} yuklanmoqda...")

            data = fetch_page(page)

            if data is None:
                _log(f"[yigish] Page {page + 1} olinmadi — o'tkazildi")
                continue

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            for cert in data["certificates"]:
                _upsert_certificate(cur, cert, page_num=page)
            conn.commit()

            # Jami yozilgan soni
            cur.execute("SELECT COUNT(*) FROM certificates")
            total_written = cur.fetchone()[0]
            conn.close()

            _log(
                f"[yigish] Page {page + 1}/{total_pages} — "
                f"+{len(data['certificates'])} ta | "
                f"DB jami: {total_written}"
            )

            time.sleep(0.3)  # Serverga bosim kamaytirish

        # Yakuniy hisobot
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM certificates")
        final_count = cur.fetchone()[0]
        conn.close()

        _log(f"[yigish] Tugadi. DB da jami: {final_count} ta yozuv")
        return True

    except Exception as e:
        _log(f"[yigish] Kutilmagan xato: {e}")
        return False

    finally:
        _collect_running = False
        _collect_lock.release()


# ── 3. Faoliyat turi bo'yicha filtrlash ──────────────────────────────���───────
def filter_by_specialization(specialization: str, status_callback=None):
    """
    certificates tableidan berilgan faoliyat turi bo'yicha filtrlaydi
    va filtered_certificates tableiga yozadi.

    specialization: qidiriladigan matn (qisman mos ham topiladi)
    """
    def _log(msg):
        print(msg)
        if status_callback:
            status_callback(msg)

    init_db()

    _log(f"[yigish] Filter boshlandi: '{specialization}'")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # certificates tableidan o'qish
    cur.execute("""
        SELECT uuid, number, tin, name, active, specialization, page_num
        FROM certificates
        WHERE specialization LIKE ?
    """, (f"%{specialization}%",))

    rows = cur.fetchall()
    _log(f"[yigish] Topildi: {len(rows)} ta mos yozuv")

    if not rows:
        conn.close()
        _log("[yigish] Mos yozuv topilmadi")
        return 0

    # filtered_certificates ga yozish
    inserted = 0
    for i, row in enumerate(rows, 1):
        uuid, number, tin, name, active, spec, page_num = row
        cur.execute("""
            INSERT INTO filtered_certificates
                (uuid, number, tin, name, active, specialization, page_num, filter_tag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uuid) DO UPDATE SET
                filter_tag = excluded.filter_tag
        """, (uuid, number, tin, name, active, spec, page_num, specialization))
        inserted += 1

        if i % 100 == 0 or i == len(rows):
            _log(f"[yigish] Filter: {i}/{len(rows)} yozildi...")

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM filtered_certificates WHERE filter_tag = ?", (specialization,))
    total_filtered = cur.fetchone()[0]
    conn.close()

    _log(f"[yigish] Filter tugadi. filtered_certificates da '{specialization}': {total_filtered} ta")
    return total_filtered