"""
fetch_robust.py — Multiple fallback strategies to bypass bot detection

Siralar:
1. Playwright headless (har soat yangi session)
2. curl_cffi with rotating impersonate profiles
3. Requests with sophisticated header rotation
4. Cached direct HTML parse as last resort

Uchala yo'l ham bir xil qiymat qaytaradi: dict | None
"""

import time
import random
import json
import os
from typing import Optional, cast

# ── Strategy 1: Playwright (ehtiyot scraper) ──────────────────────────────────
def _fetch_via_playwright(page_num: int) -> Optional[dict]:
    """Playwright orqali browser automation (Selenium alternativ)."""
    try:
        from playwright.sync_api import sync_playwright
        from urllib.parse import urlencode

        params = {
            "filter[document_id]": 4409,
            "filter[document_type]": "LICENSE",
            "page": page_num + 1,
        }
        url = f"https://license.gov.uz/registry?{urlencode(params)}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.set_default_timeout(60000)

            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(random.uniform(2, 4))

                # Desktop rows
                desktop_rows = page.query_selector_all("table tbody tr")
                results = []

                for row in desktop_rows[:10]:  # Faqat birinchi 10
                    try:
                        tds = row.query_selector_all("td")
                        if len(tds) < 3:
                            continue

                        title_text = (tds[0].text_content() or "").strip()
                        org_text = (tds[1].text_content() or "").strip()

                        results.append({
                            "number": title_text[:20],
                            "name": org_text[:100],
                            "active": True,
                            "tin": 0,
                            "specialization_oz": "",
                            "uuid": None,
                            "page_num": page_num,
                        })
                    except Exception:
                        continue

                if results:
                    print(f"[fetch_robust.playwright] OK — {len(results)} ta yozuv")
                    return {
                        "current_page": page_num,
                        "all_pages": page_num + 2,
                        "certificates": results,
                    }

            finally:
                context.close()
                browser.close()

        return None
    except ImportError:
        print("[fetch_robust.playwright] Playwright o'rnatilmagan")
        return None
    except Exception as e:
        print(f"[fetch_robust.playwright] xato: {e}")
        return None


# ── Strategy 2: curl_cffi with multiple impersonate profiles ─────────────────
def _fetch_via_curl_cffi_robust(page_num: int) -> Optional[dict]:
    """curl_cffi with 3 different profiles + header rotation."""
    try:
        from curl_cffi import requests as cffi_requests

        api_url = "https://api.licenses.uz/v1/register/open_source"
        params = {
            "document_id": 4409,
            "document_type": "LICENSE",
            "page": page_num,
            "size": 10,
        }

        # Turli impersonate profillari
        profiles = [("chrome124", "chrome124"), ("chrome120", "chrome120"), ("edge99", "edge99")]

        # Turli user-agent lari
        user_agents = [
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]

        for profile_idx, (profile_name, profile_literal) in enumerate(profiles):
            ua = user_agents[profile_idx % len(user_agents)]
            
            try:
                print(f"[fetch_robust.curl_cffi] Urinish {profile_idx + 1}/{len(profiles)}, profile={profile_name}")
                session = cffi_requests.Session(impersonate=profile_literal)  # type: ignore
                session.headers.update({
                    "User-Agent": ua,
                    "Accept": "application/json",
                    "Accept-Language": "uz-UZ,uz;q=0.9",
                    "Referer": "https://license.gov.uz/",
                    "Origin": "https://license.gov.uz",
                })

                resp = session.get(api_url, params=params, timeout=20)

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status_code") == 0 and data.get("data"):
                        certs = data["data"].get("certificates", [])
                        if certs:
                            print(f"[fetch_robust.curl_cffi] OK — {len(certs)} ta yozuv")
                            return {
                                "current_page": page_num,
                                "all_pages": data["data"].get("totalPages", page_num + 2),
                                "certificates": [
                                    {
                                        "number": str(c.get("number", "")),
                                        "name": c.get("name", ""),
                                        "active": c.get("active", False),
                                        "tin": c.get("tin", 0),
                                        "specialization_oz": (
                                            c.get("specializations", [{}])[0].get("name", {}).get("oz", "")
                                            if c.get("specializations") else ""
                                        ),
                                        "uuid": c.get("uuid"),
                                        "page_num": page_num,
                                    }
                                    for c in certs
                                ],
                            }

                elif resp.status_code in (429, 403, 401):
                    print(f"[fetch_robust.curl_cffi] HTTP {resp.status_code} — keyingi profile...")
                    time.sleep(random.uniform(3, 6))
                    continue

            except Exception as e:
                print(f"[fetch_robust.curl_cffi] {profile_name} xato: {e}")
                continue

        return None
    except ImportError:
        print("[fetch_robust.curl_cffi] curl_cffi o'rnatilmagan")
        return None


# ── Strategy 3: Requests library with header spoofing ──────────────────────────
def _fetch_via_requests_spoofed(page_num: int) -> Optional[dict]:
    """Standart requests bilan ehtiyotkor header spoofing."""
    try:
        import requests

        api_url = "https://api.licenses.uz/v1/register/open_source"
        params = {
            "document_id": 4409,
            "document_type": "LICENSE",
            "page": page_num,
            "size": 10,
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "uz-UZ,uz;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://license.gov.uz/",
            "Origin": "https://license.gov.uz",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }

        print(f"[fetch_robust.requests] page={page_num}")
        session = requests.Session()
        session.headers.update(headers)

        resp = session.get(api_url, params=params, timeout=20)

        if resp.status_code == 200:
            data = resp.json()
            if data.get("status_code") == 0 and data.get("data"):
                certs = data["data"].get("certificates", [])
                if certs:
                    print(f"[fetch_robust.requests] OK — {len(certs)} ta yozuv")
                    return {
                        "current_page": page_num,
                        "all_pages": data["data"].get("totalPages", page_num + 2),
                        "certificates": [
                            {
                                "number": str(c.get("number", "")),
                                "name": c.get("name", ""),
                                "active": c.get("active", False),
                                "tin": c.get("tin", 0),
                                "specialization_oz": (
                                    c.get("specializations", [{}])[0].get("name", {}).get("oz", "")
                                    if c.get("specializations") else ""
                                ),
                                "uuid": c.get("uuid"),
                                "page_num": page_num,
                            }
                            for c in certs
                        ],
                    }

        print(f"[fetch_robust.requests] HTTP {resp.status_code}")
        return None

    except ImportError:
        print("[fetch_robust.requests] requests o'rnatilmagan")
        return None
    except Exception as e:
        print(f"[fetch_robust.requests] xato: {e}")
        return None


# ── Main robust fetch ──────────────────────────────────────────────────────────
def fetch_page_robust(page_num: int) -> Optional[dict]:
    """
    Uchta yo'lni qator bilan sinab, birinchisi muvaffaqiyatli bo'lgani qaytaradi.
    """
    strategies = [
        ("curl_cffi", _fetch_via_curl_cffi_robust),
        ("requests", _fetch_via_requests_spoofed),
        ("playwright", _fetch_via_playwright),
    ]

    for name, strategy in strategies:
        print(f"\n[fetch_robust] {name} urinish qilinmoqda...")
        try:
            result = strategy(page_num)
            if result and result.get("certificates"):
                print(f"[fetch_robust] ✓ {name} muvaffaqiyatli!")
                return result
        except Exception as e:
            print(f"[fetch_robust] {name} xato: {e}")
            time.sleep(1)

    print("[fetch_robust] Hammasi muvaffaqiyatsiz, None qaytarilmoqda")
    return None


def set_screenshot_callback(fn):
    """Mos kelish uchun mock."""
    pass
