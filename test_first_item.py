"""
Test script:
- license.gov.uz sahifasiga kiradi
- 1-sahifadan (page=0) birinchi yozuvni oladi
- barcha maydonlarini konsolga JSON formatda print qiladi

Eslatma:
- Chrome session/profile xatosiga tushmaslik uchun har urinishda yangi temp profile ishlatiladi.
"""

import importlib
import json
import os
import sys
import tempfile
import time
import random
from datetime import datetime
from typing import Optional

from selenium.common.exceptions import SessionNotCreatedException

SCRIPT_REV = "2026-03-19-r3"


# ── Inline bot detection bypass strategies ──────────────────────────────────
def _fetch_via_curl_cffi_robust(page_num: int) -> Optional[dict]:
    """curl_cffi with multiple impersonate profiles."""
    try:
        from curl_cffi import requests as cffi_requests

        api_url = "https://api.licenses.uz/v1/register/open_source"
        params = {
            "document_id": 4409,
            "document_type": "LICENSE",
            "page": page_num,
            "size": 10,
        }

        profiles = [("chrome124", "chrome124"), ("chrome120", "chrome120"), ("edge99", "edge99")]
        user_agents = [
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]

        for profile_idx, (profile_name, profile_literal) in enumerate(profiles):
            ua = user_agents[profile_idx % len(user_agents)]
            try:
                print(f"[test.curl_cffi] Urinish {profile_idx + 1}/{len(profiles)}, profile={profile_name}")
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
                            print(f"[test.curl_cffi] OK — {len(certs)} ta yozuv")
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
                    print(f"[test.curl_cffi] HTTP {resp.status_code} — keyingi profile...")
                    time.sleep(random.uniform(3, 6))
                    continue

            except Exception as e:
                print(f"[test.curl_cffi] {profile_name} xato: {e}")
                continue

        return None
    except ImportError:
        print("[test.curl_cffi] curl_cffi o'rnatilmagan")
        return None


def _fetch_via_requests_spoofed(page_num: int) -> Optional[dict]:
    """Requests library with header spoofing."""
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
        }

        print(f"[test.requests] page={page_num}")
        session = requests.Session()
        session.headers.update(headers)

        resp = session.get(api_url, params=params, timeout=20)

        if resp.status_code == 200:
            data = resp.json()
            if data.get("status_code") == 0 and data.get("data"):
                certs = data["data"].get("certificates", [])
                if certs:
                    print(f"[test.requests] OK — {len(certs)} ta yozuv")
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

        print(f"[test.requests] HTTP {resp.status_code}")
        return None

    except ImportError:
        print("[test.requests] requests o'rnatilmagan")
        return None
    except Exception as e:
        print(f"[test.requests] xato: {e}")
        return None


def _fetch_page_robust(page_num: int) -> Optional[dict]:
    """Uchta yo'lni qator bilan sinab."""
    strategies = [
        ("curl_cffi", _fetch_via_curl_cffi_robust),
        ("requests", _fetch_via_requests_spoofed),
    ]

    for name, strategy in strategies:
        print(f"\n[test.robust] {name} urinish qilinmoqda...")
        try:
            result = strategy(page_num)
            if result and result.get("certificates"):
                print(f"[test.robust] ✓ {name} muvaffaqiyatli!")
                return result
        except Exception as e:
            print(f"[test.robust] {name} xato: {e}")
            time.sleep(1)

    print("[test.robust] API yo'llar muvaffaqiyatsiz")
    return None


def _fetch_first_item_via_api(page_num: int) -> dict | None:
    """API orqali birinchi yozuvni olish."""
    try:
        # Agar tashqi modul mavjud bo'lsa, o'shani ishlatamiz.
        from fetch_robust import fetch_page_robust as external_fetch_page_robust

        api_data = external_fetch_page_robust(page_num)
    except Exception:
        # Aks holda inline fallback strategiyalar ishlaydi.
        api_data = _fetch_page_robust(page_num)
    api_certs = api_data.get("certificates", []) if api_data else []
    if not api_data or not api_certs:
        return None

    return {
        "current_page": api_data.get("current_page"),
        "all_pages": api_data.get("all_pages"),
        "certificates_count": len(api_certs),
        "first_item": api_certs[0],
        "source": "api",
    }


def _fetch_first_item_with_fresh_profile(page_num: int) -> dict | None:
    """Har urinishda yangi Chrome profile bilan faqat birinchi elementni oladi."""
    max_attempts = 2
    last_error = None

    for attempt in range(1, max_attempts + 1):
        temp_profile = tempfile.mkdtemp(prefix="lisbot_test_profile_")
        os.environ["CHROME_PROFILE_DIR"] = temp_profile
        os.environ.setdefault("SKIP_WARMUP", "1")
        os.environ.setdefault("APP_BOOT_TIMEOUT_SECONDS", "35")
        os.environ.setdefault("ROW_WAIT_TIMEOUT_SECONDS", "70")
        os.environ.setdefault("LATE_LIST_GRACE_SECONDS", "20")
        os.environ.setdefault("SAME_ATTEMPT_LOADING_GRACE_SECONDS", "30")

        print(f"[test] attempt {attempt}/{max_attempts} | profile: {temp_profile}")

        try:
            import kochirish_html_hardened as kh
            importlib.reload(kh)

            driver = kh._get_driver()

            url = f"{kh.BASE_URL}{kh.FILTER_PARAMS}&page={page_num + 1}"
            print(f"[test] URL ochilmoqda: {url}")
            driver.get(url)

            boot_ok, boot_reason = kh._wait_for_app_bootstrap(driver, timeout=90)
            if not boot_ok:
                print(f"[test] app bootstrap fail: {boot_reason}")
                continue

            # Bu testda challenge classificationni chetlab o'tamiz.
            # Spinner yo'qolib, ro'yxat elementlari chiqquncha kutamiz.
            # Agar uzoq vaqt chiqmasa, periodic refresh bilan recovery qilamiz.
            rows_ok = False
            wait_deadline = time.time() + 50
            next_recover_at = time.time() + 12
            while time.time() < wait_deadline:
                desktop_rows, mobile_rows = kh._count_rows(driver)
                total_rows = desktop_rows + mobile_rows
                if total_rows > 0:
                    rows_ok = True
                    print(f"[test] rows topildi: desktop={desktop_rows}, mobile={mobile_rows}")
                    break

                if time.time() >= next_recover_at:
                    print("[test] recovery: refresh + qayta ochish")
                    try:
                        driver.refresh()
                    except Exception:
                        pass
                    try:
                        driver.get(url)
                    except Exception:
                        pass
                    next_recover_at = time.time() + 12

                if kh._app_is_loading(driver):
                    print("[test] app loading... kutilyapti")
                else:
                    print("[test] row hali ko'rinmadi... kutilyapti")

                time.sleep(2)

            if not rows_ok:
                shot_path, html_path = kh._take_artifacts(driver, f"test_no_rows_p{page_num}")
                print("[test] row topilmadi (timeout)")
                try:
                    ready = driver.execute_script("return document.readyState")
                    print(f"[test] readyState: {ready}")
                except Exception:
                    pass
                try:
                    print(f"[test] title: {driver.title}")
                    print(f"[test] current_url: {driver.current_url}")
                except Exception:
                    pass
                if shot_path:
                    print(f"[test] screenshot: {shot_path}")
                if html_path:
                    print(f"[test] html: {html_path}")

                # DOM bo'sh qolsa API fallback (curl_cffi) orqali birinchi yozuvni olamiz.
                try:
                    print("[test] API fallback ishga tushdi (test1.fetch_page)")
                    api_payload = _fetch_first_item_via_api(page_num)
                    if api_payload:
                        api_payload["source"] = "api_fallback"
                        return api_payload
                except Exception as fallback_err:
                    print(f"[test] API fallback xato: {fallback_err}")

                continue

            list_data = kh._collect_page_list(driver, page_num)
            certs = list_data.get("certificates", []) if list_data else []
            if not certs:
                print("[test] list bo'sh qaytdi")
                continue

            first = certs[0]
            number = kh._normalize_number(first.get("number"))

            # Faqat birinchi elementni detail bilan boyitamiz.
            enriched = dict(first)
            if number:
                try:
                    detailed = kh._collect_page_data(driver, page_num, target_numbers={number})
                    detailed_certs = detailed.get("certificates", []) if detailed else []
                    if detailed_certs:
                        enriched_detail = detailed_certs[0]
                        for key in ["active", "number", "tin", "name", "specialization_oz", "uuid", "page_num"]:
                            val = enriched_detail.get(key)
                            if val is not None and val != "":
                                enriched[key] = val
                    else:
                        print("[test] detail topilmadi, list ma'lumotlari qaytarildi")
                except Exception as detail_err:
                    print(f"[test] detail olishda xato, list fallback ishlatildi: {detail_err}")

            return {
                "current_page": list_data.get("current_page"),
                "all_pages": list_data.get("all_pages"),
                "certificates_count": len(certs),
                "first_item": enriched,
                "source": "html_dom",
            }
        except SessionNotCreatedException as e:
            last_error = e
            print(f"[test] SessionNotCreatedException: {e}")
            print("[test] Chrome qayta urinish qilinmoqda...")
        except KeyboardInterrupt as e:
            last_error = e
            print("[test] Jarayon foydalanuvchi tomonidan to'xtatildi (KeyboardInterrupt)")
            break
        except Exception as e:
            last_error = e
            print(f"[test] Kutilmagan xato: {e}")

            # Runtime xatoda API fallbackga urinib ko'ramiz.
            try:
                print("[test] Kutilmagan xatodan keyin API fallback ishga tushdi")
                api_payload = _fetch_first_item_via_api(page_num)
                if api_payload:
                    api_payload["source"] = "api_fallback_after_error"
                    return api_payload
            except Exception as fallback_err:
                print(f"[test] API fallback ham xato: {fallback_err}")

            break
        finally:
            try:
                import kochirish_html_hardened as kh
                drv = getattr(kh, "_DRIVER", None)
                if drv is not None:
                    drv.quit()
            except Exception:
                pass

    if last_error is not None:
        raise last_error

    return None


def main() -> int:
    print(f"[{datetime.now().isoformat()}] Test boshlandi...")
    print("[test] page=0 ochilib, birinchi element olinmoqda")
    print(f"[test] rev={SCRIPT_REV}")

    mode = (os.getenv("TEST_MODE", "api") or "api").strip().lower()
    if mode not in {"api", "browser", "hybrid", "api-only"}:
        mode = "api"
    print(f"[test] TEST_MODE={mode}")

    data = None
    if mode in {"api", "hybrid", "api-only"}:
        try:
            print("[test] API yo'li sinovdan o'tkazilmoqda (curl_cffi + requests + playwright)...")
            data = _fetch_first_item_via_api(0)
            if data:
                print("[test] API yo'li muvaffaqiyatli!")
        except Exception as e:
            print(f"[test] API yo'li xato: {e}")

    if data is None and mode == "api-only":
        print("[test] api-only rejimida API muvaffaqiyatsiz, natijasiz qaytish")
        return 1

    if data is None and mode in {"browser", "hybrid"}:
        print("[test] Browser yo'li ishga tushmoqda (fallback)...")
        data = _fetch_first_item_with_fresh_profile(0)

    if data is None:
        print("[test] Xato: sahifadan ma'lumot olinmadi")
        return 1

    print("\n=== PAGE META ===")
    print(json.dumps({
        "current_page": data.get("current_page"),
        "all_pages": data.get("all_pages"),
        "certificates_count": data.get("certificates_count"),
    }, ensure_ascii=False, indent=2))

    print("\n=== FIRST ITEM (FULL) ===")
    print(json.dumps(data.get("first_item", {}), ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
