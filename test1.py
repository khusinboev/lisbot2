"""
kochirish2.py — curl_cffi orqali API dan ma'lumot olish

Selenium, Xvfb, undetected-chromedriver — hammasi yo'q.
TLS fingerprint real Chrome kabi ko'rinadi → Cloudflare o'tmaydi.

O'rnatish:
    pip install curl_cffi

Public interfeys kochirish_html.py bilan bir xil:
    fetch_page(page_num)        → dict | None
    fetch_page_list(page_num)   → dict | None
    fetch_new_since(existing_numbers, max_pages) → list[dict]
    set_screenshot_callback(fn) → no-op (mos kelish uchun saqlab qolindi)
"""

import time
import random
import os

from curl_cffi import requests as cffi_requests

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE    = "https://api.licenses.uz/v1/register/open_source"
DOCUMENT_ID = 4409
DOC_TYPE    = "LICENSE"
PAGE_SIZE   = 10
PDF_LANG    = "uz"

# Retry sozlamalari
MAX_RETRIES   = 5
RETRY_DELAY   = 8.0   # birinchi retry oldidan kutish (soniya)
RETRY_BACKOFF = 1.5   # har urinishda delay ko'payish koeffitsienti

# Session — bir marta yaratiladi, cookie va connection saqlanadi
_SESSION: cffi_requests.Session | None = None


# ── Screenshot callback — mos kelish uchun (no-op) ───────────────────────────
_screenshot_callback = None

def set_screenshot_callback(fn):
    """kochirish_html.py bilan mos kelish uchun. Bu yerda hech narsa qilmaydi."""
    global _screenshot_callback
    _screenshot_callback = fn


# ── Session ───────────────────────────────────────────────────────────────────
def _get_session() -> cffi_requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    _SESSION = cffi_requests.Session(impersonate="chrome124")

    # Real Chrome headers
    _SESSION.headers.update({
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "uz-UZ,uz;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         "https://license.gov.uz/",
        "Origin":          "https://license.gov.uz",
        "Connection":      "keep-alive",
        "sec-ch-ua":       '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest":  "empty",
        "Sec-Fetch-Mode":  "cors",
        "Sec-Fetch-Site":  "same-site",
    })

    return _SESSION


# ── Yordamchi ─────────────────────────────────────────────────────────────────
def _normalize_number(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(text))
    except (TypeError, ValueError):
        return text


def _parse_cert(item: dict, page_num: int) -> dict:
    """
    API dagi bitta element → loyiha ichidagi standart format.

    Chiquvchi format (kochirish_html.py bilan bir xil):
    {
        "active":           bool,
        "number":           str,
        "tin":              str,
        "name":             str,
        "specialization_oz": str,
        "uuid":             str | None,
        "page_num":         int,
    }
    """
    # Specialization — birinchisining oz nomini olamiz
    specialization_oz = ""
    specs = item.get("specializations") or []
    if specs:
        name_obj = specs[0].get("name") or {}
        specialization_oz = (
            name_obj.get("oz")
            or name_obj.get("uz")
            or name_obj.get("ru")
            or ""
        )

    return {
        "active":            bool(item.get("active", False)),
        "number":            _normalize_number(item.get("number")),
        "tin":               str(item.get("tin", "") or ""),
        "name":              (item.get("name") or "").strip(),
        "specialization_oz": specialization_oz,
        "uuid":              item.get("uuid"),
        "page_num":          page_num,
    }


# ── Asosiy API so'rovi ────────────────────────────────────────────────────────
def _fetch_api(page_num: int) -> dict | None:
    """
    Bitta page uchun API ga so'rov yuboradi.
    Muvaffaqiyatli bo'lsa raw JSON dict qaytaradi.
    Xato bo'lsa None qaytaradi.
    """
    session = _get_session()
    params = {
        "document_id":   DOCUMENT_ID,
        "document_type": DOC_TYPE,
        "page":          page_num,
        "size":          PAGE_SIZE,
    }

    delay = RETRY_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[kochirish2] API so'rov: page={page_num}, urinish={attempt}/{MAX_RETRIES}")
            resp = session.get(API_BASE, params=params, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                # Javob tuzilmasi tekshiruvi
                if (
                    isinstance(data, dict)
                    and data.get("status_code") == 0
                    and isinstance(data.get("data"), dict)
                ):
                    return data["data"]

                print(f"[kochirish2] Kutilmagan javob tuzilmasi: {str(data)[:200]}")
                return None

            elif resp.status_code in (429, 503, 502, 504):
                # Rate limit yoki server muammosi — qayta urinish
                print(f"[kochirish2] HTTP {resp.status_code} — {delay:.0f}s kutilmoqda...")
                time.sleep(delay)
                delay *= RETRY_BACKOFF
                continue

            elif resp.status_code in (401, 403):
                print(f"[kochirish2] HTTP {resp.status_code} — Cloudflare blok. "
                      f"Session yangilanmoqda...")
                # Session ni yangilab qayta urinish
                global _SESSION
                _SESSION = None
                session = _get_session()
                time.sleep(delay)
                delay *= RETRY_BACKOFF
                continue

            else:
                print(f"[kochirish2] HTTP {resp.status_code} — xato")
                return None

        except Exception as e:
            print(f"[kochirish2] So'rov xatosi (urinish {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(delay)
                delay *= RETRY_BACKOFF
            continue

    print(f"[kochirish2] {MAX_RETRIES} urinishdan keyin ham olinmadi: page={page_num}")
    return None


# ── Public interfeys ──────────────────────────────────────────────────────────
def fetch_page(page_num: int) -> dict | None:
    """
    Berilgan page raqami uchun to'liq ma'lumot oladi.
    kochirish_html.py::fetch_page() bilan bir xil interfeys.
    """
    raw = _fetch_api(page_num)
    if raw is None:
        return None

    certs_raw = raw.get("certificates") or []
    if not certs_raw:
        print(f"[kochirish2] Page {page_num} — bo'sh ro'yxat")
        return None

    total_pages  = int(raw.get("totalPages",  page_num + 1))
    current_page = int(raw.get("currentPage", page_num))

    certificates = [_parse_cert(item, page_num) for item in certs_raw]

    print(
        f"[kochirish2] OK — page={current_page}, "
        f"jami={total_pages}, certs={len(certificates)}"
    )

    return {
        "current_page": current_page,
        "all_pages":    total_pages,
        "certificates": certificates,
    }


def fetch_page_list(page_num: int) -> dict | None:
    """
    fetch_page() bilan bir xil — API da modal yo'q, farq yo'q.
    kochirish_html.py::fetch_page_list() bilan bir xil interfeys.
    """
    return fetch_page(page_num)


def fetch_new_since(existing_numbers: set[str], max_pages: int = 100) -> list[dict]:
    """
    Saytdagi eng yangi yozuvlarni tekshiradi.
    Bazada mavjud raqam birinchi marta uchragunga qadar oldingi pagelarni ko'radi.

    kochirish_html.py::fetch_new_since() bilan bir xil interfeys va mantiq.
    """
    new_certs: list[dict] = []
    page = 0

    while page < max_pages:
        print(f"[kochirish2] fetch_new_since: page {page} tekshirilmoqda...")

        data = fetch_page(page)
        if data is None:
            print(f"[kochirish2] Page {page} olinmadi — to'xtaldi")
            break

        certs = data.get("certificates", [])
        if not certs:
            break

        found_existing = False
        for cert in certs:
            normalized = _normalize_number(cert.get("number"))
            if not normalized:
                continue

            if normalized in existing_numbers:
                found_existing = True
                # Bu raqam bazada bor — yangilarni yig'ish to'xtatiladi
                continue

            # Yangi yozuv — qo'shiladi
            if normalized not in {_normalize_number(c.get("number")) for c in new_certs}:
                new_certs.append(cert)

        if found_existing:
            print(f"[kochirish2] Page {page} da mavjud raqam topildi — to'xtaldi")
            break

        # Oxirgi page bo'lsa ham to'xtatamiz
        if page >= data.get("all_pages", 1) - 1:
            break

        page += 1
        # Serverga bosim bermaslik uchun kichik delay
        time.sleep(random.uniform(0.5, 1.2))

    print(f"[kochirish2] fetch_new_since: jami {len(new_certs)} ta yangi yozuv")
    return new_certs


# ── Test ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== kochirish2.py test ===\n")

    print("--- fetch_page(0) ---")
    result = fetch_page(0)
    if result:
        print(f"Jami pages: {result['all_pages']}")
        print(f"Sertifikatlar soni: {len(result['certificates'])}")
        print("\nBirinchi sertifikat:")
        first = result["certificates"][0]
        for k, v in first.items():
            print(f"  {k}: {v}")
    else:
        print("XATO: natija olinmadi")

    print("\n--- fetch_new_since({1000000}) ---")
    new = fetch_new_since({str(1000000)}, max_pages=2)
    print(f"Yangi: {len(new)} ta")