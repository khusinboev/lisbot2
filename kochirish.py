"""
kochirish.py — bitta page uchun ma'lumot olish moduli
"""

import os
import time
import random
import json

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "https://license.gov.uz/registry"
FILTER_PARAMS = "?filter%5Bdocument_id%5D=4409&filter%5Bdocument_type%5D=LICENSE"
API_TARGET = "api.licenses.uz/v1/register/open_source"

current_dir = os.path.dirname(os.path.abspath(__file__))
profile_path = os.getenv("CHROME_PROFILE_DIR") or os.path.join(current_dir, "chrome_profile")
os.makedirs(profile_path, exist_ok=True)

_DRIVER = None


# ── Env helpers ───────────────────────────────────────────────────────────────
def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


# ── Driver ────────────────────────────────────────────────────────────────────
def _is_driver_alive(driver):
    try:
        _ = driver.current_url
        _ = driver.window_handles
        return True
    except Exception:
        return False


def _init_driver():
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    # Docker / server muhitida barqarorroq ishlashi uchun
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=700,700")

    # Default: Docker’da headless, lokalda GUI.
    headless = _env_bool("CHROME_HEADLESS", default=_env_bool("IN_DOCKER", default=False))
    if headless:
        # Chrome 109+ uchun tavsiya etilgan
        options.add_argument("--headless=new")

    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    version_main = _env_int("CHROME_VERSION_MAIN")
    if version_main is not None:
        driver = uc.Chrome(version_main=version_main, options=options)
    else:
        driver = uc.Chrome(options=options)

    driver.set_page_load_timeout(120)
    return driver


def _get_driver():
    global _DRIVER
    if _DRIVER is not None and _is_driver_alive(_DRIVER):
        return _DRIVER
    _DRIVER = _init_driver()
    return _DRIVER


# ── Yordamchi ─────────────────────────────────────────────────────────────────
def _human_delay(a=0.8, b=2.0):
    time.sleep(random.uniform(a, b))


# ── YouTube warmup ────────────────────────────────────────────────────────────
def _youtube_warmup(driver):
    print("[kochirish] YouTube warmup...")
    wait = WebDriverWait(driver, 30)
    driver.get("https://www.youtube.com")
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    box = wait.until(EC.presence_of_element_located((By.NAME, "search_query")))
    box.click()
    _human_delay(0.5, 1.0)
    box.send_keys("python tutorial")
    _human_delay(0.5, 1.0)
    box.send_keys(Keys.ENTER)
    wait.until(EC.presence_of_element_located((By.ID, "contents")))
    _human_delay(1.5, 2.5)
    print("[kochirish] YouTube warmup tugadi")


# ── Sahifani ochish ───────────────────────────────────────────────────────────
def _open_page(driver, page_num):
    """
    Berilgan page raqamini URL orqali ochadi.
    page_num 0-indexed — API ham 0 dan boshlaydi.
    URL da esa &page= 1-indexed bo'lishi mumkin, shuning uchun +1.
    """
    url = f"{BASE_URL}{FILTER_PARAMS}&page={page_num + 1}"
    print(f"[kochirish] URL ochilmoqda: {url}")

    wait = WebDriverWait(driver, 60)

    for attempt in range(3):
        try:
            driver.get(url)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            _human_delay(1.2, 2.0)
            return True
        except Exception as e:
            print(f"[kochirish] Sahifa ochishda xato (attempt {attempt + 1}/3): {e}")
            _human_delay(3.0, 5.0)

    return False


# ── API response ushlash ──────────────────────────────────────────────────────
def _get_api_response(driver, expected_page, timeout=40):
    """
    CDP orqali brauzеr yuborgan API so'rovining response body sini oladi.
    expected_page — API da currentPage shu bo'lishi kerak (0-indexed).
    """
    print(f"[kochirish] API response kutilmoqda (page={expected_page})...")
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            logs = driver.get_log("performance")
        except Exception:
            time.sleep(1.0)
            continue

        for log in logs:
            try:
                msg = json.loads(log["message"])["message"]

                if msg["method"] != "Network.responseReceived":
                    continue

                url = msg["params"]["response"]["url"]

                if API_TARGET not in url:
                    continue
                if "stat" in url or "search" in url:
                    continue

                status = msg["params"]["response"]["status"]
                request_id = msg["params"]["requestId"]

                if status != 200:
                    print(f"[kochirish] API {status} qaytardi — o'tkazildi")
                    continue

                result = driver.execute_cdp_cmd(
                    "Network.getResponseBody",
                    {"requestId": request_id}
                )
                body = result.get("body", "")
                if not body:
                    continue

                data = json.loads(body)
                current_page = data.get("data", {}).get("currentPage", -1)

                # To'g'ri page ekanligini tekshir
                if current_page != expected_page:
                    print(f"[kochirish] Page mismatch: kutilgan={expected_page}, keldi={current_page} — o'tkazildi")
                    continue

                print(f"[kochirish] Response ushlandi: page={current_page}")
                return data

            except Exception:
                continue

        time.sleep(0.5)

    return None


# ── Ma'lumotlarni parse qilish ────────────────────────────────────────────────
def _parse_data(raw_data):
    """
    Raw API javobidan kerakli maydonlarni ajratib oladi.
    """
    data_block = raw_data.get("data", {})
    certificates = data_block.get("certificates", [])
    total_pages = data_block.get("totalPages", 0)
    current_page = data_block.get("currentPage", 0)

    parsed_certs = []
    for cert in certificates:
        # specializations.name.oz — birinchi specializationdan olish
        specializations = cert.get("specializations", [])
        spec_name_oz = ""
        if specializations:
            spec_name_oz = specializations[0].get("name", {}).get("oz", "") or ""

        parsed_certs.append({
            "active": cert.get("active"),
            "number": cert.get("number"),
            "tin": cert.get("tin"),
            "name": cert.get("name"),
            "specialization_oz": spec_name_oz,
            "uuid": cert.get("uuid"),
        })

    return {
        "current_page": current_page,
        "all_pages": total_pages,
        "certificates": parsed_certs,
    }


# ── Asosiy funksiya (tashqaridan chaqiriladi) ─────────────────────────────────
def fetch_page(page_num: int) -> dict | None:
    """
    Berilgan page raqami uchun ma'lumot oladi.

    Parametr:
        page_num (int): 0-indexed page raqami (0 = birinchi sahifa)

    Qaytaradi:
        {
            "current_page": int,
            "all_pages": int,
            "certificates": [
                {
                    "active": bool,
                    "number": str,
                    "tin": int,
                    "name": str,
                    "specialization_oz": str,
                    "uuid": str,
                },
                ...  # 10 ta
            ]
        }
        yoki None — muvaffaqiyatsiz bo'lsa
    """
    driver = _get_driver()

    # Birinchi marta chaqirilganda YouTube warmup
    # (profil yangi bo'lsa yoki driver yangi yaratilgan bo'lsa)
    if len(driver.window_handles) == 1:
        current_url = driver.current_url
        if "youtube" not in current_url and "license" not in current_url:
            _youtube_warmup(driver)

    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        print(f"[kochirish] fetch_page({page_num}) — urinish {attempt + 1}/{MAX_RETRIES}")

        opened = _open_page(driver, page_num)
        if not opened:
            print(f"[kochirish] Sahifa ochilmadi — retry")
            _human_delay(5.0, 8.0)
            continue

        raw_data = _get_api_response(driver, expected_page=page_num, timeout=40)

        if raw_data is None:
            print(f"[kochirish] API response kelmadi — refresh qilinmoqda...")
            try:
                driver.refresh()
                _human_delay(4.0, 6.0)
            except Exception:
                pass
            raw_data = _get_api_response(driver, expected_page=page_num, timeout=30)

        if raw_data is None:
            print(f"[kochirish] {attempt + 1}-urinishda ham olinmadi")
            _human_delay(5.0, 10.0)
            continue

        result = _parse_data(raw_data)
        print(f"[kochirish] OK — page={result['current_page']}, jami={result['all_pages']}, certs={len(result['certificates'])}")
        return result

    print(f"[kochirish] {MAX_RETRIES} urinishdan keyin ham olinmadi: page={page_num}")
    return None


def fetch_new_since(existing_numbers: set[str], max_pages: int = 100) -> list[dict]:
    """
    API ro'yxatidagi hujjat raqamlarini bazadagi mavjud raqamlar bilan solishtiradi.
    Birinchi marta bazada mavjud raqam uchragan page'gacha bo'lgan yo'q yozuvlarni qaytaradi.
    """
    new_certs = []
    page = 0

    while page < max_pages:
        print(f"[kochirish] fetch_new_since: page {page} yuklanmoqda...")
        data = fetch_page(page)
        if data is None:
            break

        certs = data.get("certificates", [])
        if not certs:
            break

        page_has_existing = False
        for cert in certs:
            number = cert.get("number")
            if number is None:
                continue

            try:
                normalized = str(int(str(number).strip()))
            except (TypeError, ValueError):
                normalized = str(number).strip()

            if not normalized:
                continue

            if normalized in existing_numbers:
                page_has_existing = True
                continue

            new_certs.append(cert)

        if page_has_existing:
            break

        page += 1

    print(f"[kochirish] fetch_new_since: jami {len(new_certs)} ta yangi yozuv topildi")
    return new_certs