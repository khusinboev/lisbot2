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
from datetime import datetime

from selenium.common.exceptions import SessionNotCreatedException


def _fetch_first_item_via_api(page_num: int) -> dict | None:
    """API (curl_cffi) orqali birinchi yozuvni olish."""
    from test1 import fetch_page as api_fetch_page

    api_data = api_fetch_page(page_num)
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

    mode = (os.getenv("TEST_MODE", "hybrid") or "hybrid").strip().lower()
    if mode not in {"api", "browser", "hybrid"}:
        mode = "hybrid"
    print(f"[test] TEST_MODE={mode}")

    data = None
    if mode in {"api", "hybrid"}:
        try:
            print("[test] API yo'li sinovdan o'tkazilmoqda...")
            data = _fetch_first_item_via_api(0)
            if data:
                print("[test] API yo'li muvaffaqiyatli")
        except Exception as e:
            print(f"[test] API yo'li xato: {e}")

    if data is None and mode in {"browser", "hybrid"}:
        print("[test] Browser yo'li ishga tushmoqda...")
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
