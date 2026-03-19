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

SCRIPT_REV = "2026-03-19-r4"


def _map_api_payload(data: dict, page_num: int) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    if data.get("status_code") != 0:
        return None

    payload = data.get("data") or {}
    certs = payload.get("certificates") or []
    if not certs:
        return None

    mapped = []
    for c in certs:
        specs = c.get("specializations") or []
        spec_oz = ""
        if specs:
            name_obj = specs[0].get("name") or {}
            spec_oz = name_obj.get("oz") or name_obj.get("uz") or name_obj.get("ru") or ""
        mapped.append({
            "number": str(c.get("number", "")),
            "name": (c.get("name") or "").strip(),
            "active": bool(c.get("active", False)),
            "tin": str(c.get("tin", "") or ""),
            "specialization_oz": spec_oz,
            "uuid": c.get("uuid"),
            "page_num": page_num,
        })

    return {
        "current_page": int(payload.get("currentPage", page_num)),
        "all_pages": int(payload.get("totalPages", page_num + 1)),
        "certificates": mapped,
    }


def _fetch_via_test1(page_num: int) -> Optional[dict]:
    try:
        from test1 import fetch_page as api_fetch_page
    except Exception as e:
        print(f"[test.api.test1] import xato: {e}")
        return None

    try:
        data = api_fetch_page(page_num)
        if data and data.get("certificates"):
            print(f"[test.api.test1] OK certs={len(data.get('certificates', []))}")
            return data
    except Exception as e:
        print(f"[test.api.test1] runtime xato: {e}")
    return None


def _fetch_via_requests_compliant(page_num: int) -> Optional[dict]:
    """Compliant API fetch: backoff + diagnostics, no stealth bypass tricks."""
    try:
        import requests
    except ImportError:
        print("[test.api.requests] requests o'rnatilmagan")
        return None

    api_url = "https://api.licenses.uz/v1/register/open_source"
    params_candidates = [
        {"document_id": 4409, "document_type": "LICENSE", "page": page_num, "size": 10},
        {"document_id": 4409, "document_type": "LICENSE", "page": page_num + 1, "size": 10},
    ]

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "uz-UZ,uz;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://license.gov.uz/",
        "Origin": "https://license.gov.uz",
        "User-Agent": "LisbotTest/1.0 (+https://license.gov.uz)",
    })

    delay = 2.0
    for attempt in range(1, 5):
        for params in params_candidates:
            try:
                print(f"[test.api.requests] attempt={attempt} params={params}")
                resp = session.get(api_url, params=params, timeout=30)
                if resp.status_code == 200:
                    mapped = _map_api_payload(resp.json(), page_num)
                    if mapped:
                        print(f"[test.api.requests] OK certs={len(mapped['certificates'])}")
                        return mapped
                    print("[test.api.requests] 200 lekin payload bo'sh/yaroqsiz")
                else:
                    snippet = (resp.text or "")[:180].replace("\n", " ")
                    print(f"[test.api.requests] HTTP={resp.status_code} body={snippet}")
            except Exception as e:
                print(f"[test.api.requests] xato: {e}")

        time.sleep(delay + random.uniform(0.2, 0.7))
        delay *= 1.7

    return None


def _fetch_page_compliant(page_num: int) -> Optional[dict]:
    data = _fetch_via_test1(page_num)
    if data:
        return data
    return _fetch_via_requests_compliant(page_num)


def _fetch_first_item_via_api(page_num: int) -> dict | None:
    """API orqali birinchi yozuvni olish (compliant, resilient)."""
    api_data = _fetch_page_compliant(page_num)
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

    mode = (os.getenv("TEST_MODE", "hybrid") or "hybrid").strip().lower()
    if mode not in {"api", "browser", "hybrid", "api-only"}:
        mode = "api"
    print(f"[test] TEST_MODE={mode}")

    data = None
    if mode in {"api", "hybrid", "api-only"}:
        try:
            print("[test] API yo'li sinovdan o'tkazilmoqda (compliant retry/backoff)...")
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
