"""
kochirish_html.py — bitta page uchun ma'lumotni HTML dan yig'ish

API response emas, sahifadagi ko'rinadigan jadval / kartochkalardan o'qiydi.
"""

import os
import time
import random
import re

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "https://license.gov.uz/registry"
FILTER_PARAMS = "?filter%5Bdocument_id%5D=4409&filter%5Bdocument_type%5D=LICENSE"

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


def _env_int(name: str):
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
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1024,768")

    headless = _env_bool("CHROME_HEADLESS", default=_env_bool("IN_DOCKER", default=False))
    if headless:
        options.add_argument("--headless=new")

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


def _youtube_warmup(driver):
    """
    Oldingi kabi warmup — sayt anti-botni biroz aldash uchun.
    """
    try:
        print("[kochirish_html] YouTube warmup...")
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
        print("[kochirish_html] YouTube warmup tugadi")
    except Exception as e:
        print(f"[kochirish_html] YouTube warmup xato: {e}")


# ── Sahifani ochish ───────────────────────────────────────────────────────────
def _open_page(driver, page_num: int) -> bool:
    """
    0-indexed page ochadi (&page=1 dan boshlanadi).
    """
    url = f"{BASE_URL}{FILTER_PARAMS}&page={page_num + 1}"
    print(f"[kochirish_html] URL ochilmoqda: {url}")

    wait = WebDriverWait(driver, 60)

    for attempt in range(3):
        try:
            driver.get(url)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            _human_delay(1.2, 2.0)
            return True
        except Exception as e:
            print(f"[kochirish_html] Sahifa ochishda xato (attempt {attempt + 1}/3): {e}")
            _human_delay(3.0, 5.0)

    return False


# ── HTML dan pagination ma'lumotlari ─────────────────────────────────────────
def _parse_pagination(driver, fallback_page_num: int) -> tuple[int, int]:
    """
    (current_page_0_indexed, total_pages) qaytaradi.
    Agar topilmasa, fallback sifatida (page_num, page_num+1) qaytaradi.
    """
    try:
        # Active page raqami
        active_el = driver.find_element(
            By.CSS_SELECTOR,
            ".Pagination_itemActive___lJca .Pagination_itemActiveLink__1Tcd4",
        )
        current = int(active_el.text.strip()) - 1

        # Barcha raqamli elementlardan max ni olish
        page_els = driver.find_elements(By.CSS_SELECTOR, ".Pagination_item__3BSuR a")
        nums = []
        for el in page_els:
            txt = el.text.strip()
            if txt.isdigit():
                nums.append(int(txt))
        total = max(nums) if nums else (fallback_page_num + 1)
        return current, total
    except Exception:
        return fallback_page_num, fallback_page_num + 1


# ── Listdan qisqa ma'lumotlarni olish (desktop) ──────────────────────────────
def _parse_list_desktop_rows(driver):
    """
    Katta ekran varianti: <table> ichidagi <tr> lar.
    """
    rows = driver.find_elements(By.CSS_SELECTOR, "table.Table_table__2OuB7 tbody.Table_body__3kRrD tr.Table_row__329lz")
    results = []
    for row in rows:
        try:
            tds = row.find_elements(By.CSS_SELECTOR, "td.Table_cell__2s5cE")
            if len(tds) < 6:
                continue

            # Xizmat nomi + kategoriya
            title_cell = tds[0]
            category_el = title_cell.find_element(By.CSS_SELECTOR, ".Table_titleCellCategory__13j94")
            title_el = title_cell.find_element(By.CSS_SELECTOR, ".Table_titleCellValue__2Wjmv")
            specialization_text = title_el.text.strip()

            # Tashkilot + STIR
            org_cell = tds[1]
            org_wrapper = org_cell.find_element(By.CSS_SELECTOR, ".RegistryPage_cellTitle__1__HN")
            tin_span = org_wrapper.find_element(By.TAG_NAME, "span")
            tin_text = tin_span.text.strip()
            name_text = org_wrapper.text.replace(tin_text, "").strip().strip('" ')

            # Hujjat raqami
            number_text = tds[2].text.strip()

            # Faol holati (icon bo'lgani uchun faqat mavjudligini tekshiramiz)
            active = bool(
                tds[5].find_elements(
                    By.CSS_SELECTOR,
                    ".IconLabel_wrapper--success__iBPoQ, .Status_wrapper--success__3eEIw",
                )
            )

            results.append(
                {
                    "active": active,
                    "number": number_text,
                    "tin": tin_text,
                    "name": name_text,
                    "specialization_oz": specialization_text,
                    "uuid": None,  # keyin detal modalidan URL orqali olishga urinib ko'riladi
                    "row_element": row,
                }
            )
        except Exception as e:
            print(f"[kochirish_html] Desktop row parse xato: {e}")
            continue

    return results


# ── Listdan qisqa ma'lumotlarni olish (mobile) ───────────────────────────────
def _parse_list_mobile_cards(driver):
    """
    Kichik ekran varianti: .RegistryPage_tableMobileWrapper__3oxDb bloklari.
    """
    cards = driver.find_elements(By.CSS_SELECTOR, ".RegistryPage_tableMobileWrapper__3oxDb")
    results = []

    for card in cards:
        try:
            category_el = card.find_element(By.CSS_SELECTOR, ".RegistryPage_tableMobileTitle__l7DUW")
            specialization_text = category_el.text.strip()

            num_block = card.find_element(By.CSS_SELECTOR, ".RegistryPage_tableMobileNumber__1Z-HB span")
            num_text = num_block.text.strip()
            # Format: "<TIN> \"ORG NAME\" ... <NUMBER>"
            nums = re.findall(r"\d+", num_text)
            tin_text = nums[0] if nums else ""
            number_text = nums[-1] if len(nums) >= 1 else ""

            # Tashkilot nomi: span ichidagi tin va number oralig'idagi matndan chiqarishga urinib ko'ramiz
            name_text = num_text
            if tin_text and number_text and tin_text in name_text and number_text in name_text:
                try:
                    start = name_text.index(tin_text) + len(tin_text)
                    end = name_text.rindex(number_text)
                    name_text = name_text[start:end].strip().strip('" ')
                except ValueError:
                    pass

            desc_el = card.find_element(By.CSS_SELECTOR, ".RegistryPage_tableMobileDescription__3mTbZ")
            specialization_desc = desc_el.text.strip()
            if specialization_desc:
                specialization_text = specialization_desc

            status_el = card.find_element(By.CSS_SELECTOR, ".Status_wrapper__nLMCI")
            active = "active" in status_el.text.strip().lower()

            results.append(
                {
                    "active": active,
                    "number": number_text,
                    "tin": tin_text,
                    "name": name_text,
                    "specialization_oz": specialization_text,
                    "uuid": None,
                    "row_element": card,
                }
            )
        except Exception as e:
            print(f"[kochirish_html] Mobile card parse xato: {e}")
            continue

    return results


# ── Batafsil modalni o'qish ───────────────────────────────────────────────────
def _parse_details_modal(driver) -> dict:
    """
    Ochilgan modal (RegistryView_wrapper__3LW9q) ichidan to'liqroq ma'lumotlarni oladi.
    Faqat kerakli maydonlarni qaytaradi. Topilmasa bo'sh lug'at.
    """
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".RegistryView_wrapper__3LW9q")))

    details = {}

    try:
        # Holati, Hujjat raqami va hokazo
        items = driver.find_elements(By.CSS_SELECTOR, ".Details_item__d8XKD")
        for item in items:
            try:
                title = item.find_element(By.CSS_SELECTOR, ".Details_itemTitle__2kmDz").text.strip()
                value = item.find_element(By.CSS_SELECTOR, ".Details_itemValue__1DlsR").text.strip()
            except Exception:
                continue

            if title == "Holati":
                details["active_text"] = value
            elif title == "Tashkilot nomi":
                details["name"] = value
            elif title == "Litsenziya oluvchi shaxsning STIR raqami":
                details["tin"] = value
            elif title == "Hujjat raqami":
                details["number"] = value

        # Faoliyat turi / kategoriya bosh qismidan
        try:
            cat_el = driver.find_element(By.CSS_SELECTOR, ".RegistryView_title__1khqt")
            details["specialization_oz"] = cat_el.text.strip()
        except Exception:
            pass

        # UUID: URL ichidan olishga urinib ko'ramiz (agar bo'lsa)
        try:
            url = driver.current_url
            # Masalan: .../registry/view/<uuid> format bo'lsa
            m = re.search(r"/([0-9a-fA-F-]{8,})$", url)
            if m:
                details["uuid"] = m.group(1)
        except Exception:
            pass

    except Exception as e:
        print(f"[kochirish_html] Modal parse xato: {e}")

    # Modalni yopish
    try:
        close_btns = driver.find_elements(By.CSS_SELECTOR, ".ModalNav_close__1lmq4")
        if close_btns:
            close_btns[0].click()
        else:
            # fallback: ESC
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(driver).send_keys("\uE00C").perform()  # ESC
        _human_delay(0.3, 0.7)
    except Exception:
        pass

    return details


# ── Asosiy sahifa parse + modal kombinatsiyasi ────────────────────────────────
def _collect_page_data(driver, page_num: int):
    """
    Bitta sahifadagi barcha yozuvlarni:
    - avval listdan qisqa info
    - keyin har biriga kirib modal orqali boyitadi.
    """
    current_page, total_pages = _parse_pagination(driver, page_num)

    # Avval mobile, bo'sh bo'lsa desktop varianti
    entries = _parse_list_mobile_cards(driver)
    if not entries:
        entries = _parse_list_desktop_rows(driver)

    certs = []
    for entry in entries:
        row_el = entry.pop("row_element", None)
        if row_el is None:
            continue

        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row_el)
        except Exception:
            pass

        try:
            row_el.click()
        except Exception as e:
            print(f"[kochirish_html] Row klik xato: {e}")
            continue

        _human_delay(0.8, 1.5)
        details = _parse_details_modal(driver)

        merged = {
            "active": entry.get("active"),
            "number": details.get("number") or entry.get("number"),
            "tin": details.get("tin") or entry.get("tin"),
            "name": details.get("name") or entry.get("name"),
            "specialization_oz": details.get("specialization_oz") or entry.get("specialization_oz"),
            "uuid": details.get("uuid") or entry.get("uuid"),
        }

        active_text = details.get("active_text", "")
        if isinstance(active_text, str) and active_text:
            merged["active"] = "faol" in active_text.lower() or "active" in active_text.lower()

        certs.append(merged)

    return {
        "current_page": current_page,
        "all_pages": total_pages,
        "certificates": certs,
    }


# ── Tashqaridan chaqiriladigan funksiya ───────────────────────────────────────
def fetch_page(page_num: int) -> dict | None:
    """
    Berilgan page raqami uchun ma'lumot oladi (HTML orqali).
    """
    driver = _get_driver()

    if len(driver.window_handles) == 1:
        current_url = driver.current_url
        if "youtube" not in current_url and "license" not in current_url:
            _youtube_warmup(driver)

    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        print(f"[kochirish_html] fetch_page({page_num}) — urinish {attempt + 1}/{MAX_RETRIES}")

        opened = _open_page(driver, page_num)
        if not opened:
            print(f"[kochirish_html] Sahifa ochilmadi — retry")
            _human_delay(5.0, 8.0)
            continue

        try:
            data = _collect_page_data(driver, page_num)
        except Exception as e:
            print(f"[kochirish_html] collect_page_data xato: {e}")
            data = None

        if data is None or not data.get("certificates"):
            print(f"[kochirish_html] {attempt + 1}-urinishda ham olinmadi yoki bo'sh sahifa")
            _human_delay(5.0, 10.0)
            continue

        print(
            f"[kochirish_html] OK — page={data['current_page']}, "
            f"jami={data['all_pages']}, certs={len(data['certificates'])}"
        )
        return data

    print(f"[kochirish_html] {MAX_RETRIES} urinishdan keyin ham olinmadi: page={page_num}")
    return None


def fetch_new_since(last_number: int, max_pages: int = 100) -> list[dict]:
    """
    last_number dan katta number ga ega barcha sertifikatlarni yig‘adi (HTML orqali).
    """
    new_certs = []
    page = 0

    while page < max_pages:
        print(f"[kochirish_html] fetch_new_since: page {page} yuklanmoqda...")
        data = fetch_page(page)
        if data is None:
            break

        certs = data.get("certificates", [])
        if not certs:
            break

        all_smaller_found = False
        for cert in certs:
            try:
                num = int(cert["number"])
            except (ValueError, TypeError, KeyError):
                continue

            if num > last_number:
                new_certs.append(cert)
            else:
                all_smaller_found = True
                break

        if all_smaller_found:
            break

        page += 1

    print(f"[kochirish_html] fetch_new_since: jami {len(new_certs)} ta yangi yozuv topildi")
    return new_certs

