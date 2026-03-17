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
from selenium.webdriver.common.action_chains import ActionChains
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
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # Real monitor o'lchamiga o'xshash — 1366x768 eng keng tarqalgan
    options.add_argument("--window-size=1366,768")

    # Bot izlarini yashirish
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-browser-side-navigation")

    # Real user-agent (Ubuntu Chrome 136)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    )

    # Tilni o'rnatish — serverda default en-US bo'lishi mumkin
    options.add_argument("--lang=uz-UZ,uz;q=0.9,en-US;q=0.8,en;q=0.7")

    # Xvfb bilan render xatoliklarini oldini olish
    options.add_argument("--disable-software-rasterizer")

    # Chrome path
    options.binary_location = "/opt/google/chrome/google-chrome"

    headless = _env_bool("CHROME_HEADLESS", default=_env_bool("IN_DOCKER", default=False))
    if headless:
        options.add_argument("--headless=new")

    version_main = _env_int("CHROME_VERSION_MAIN")
    if version_main is not None:
        driver = uc.Chrome(version_main=version_main, options=options)
    else:
        driver = uc.Chrome(options=options)

    driver.set_page_load_timeout(120)

    # WebDriver belgisini JS darajasida o'chirish
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['uz-UZ', 'uz', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """
    })

    return driver


def _get_driver():
    global _DRIVER
    if _DRIVER is not None and _is_driver_alive(_DRIVER):
        return _DRIVER
    _DRIVER = _init_driver()
    _warmup(_DRIVER)   # yangi driver ochilganda bir marta warmup
    return _DRIVER


# ── Yordamchi ─────────────────────────────────────────────────────────────────
def _human_delay(a=0.8, b=2.0):
    time.sleep(random.uniform(a, b))


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


def _extract_uuid_from_href(href: str | None) -> str | None:
    if not href:
        return None

    match = re.search(r"/uuid/([^/?]+)/pdf", href)
    if match:
        return match.group(1)

    match = re.search(r"/uuid/([^/?]+)", href)
    if match:
        return match.group(1)

    return None


def _is_document_tab_text(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    keywords = ["hujjat", "ҳужжат", "документ", "document"]
    return any(keyword in normalized for keyword in keywords)


def _open_document_tab_and_get_uuid(driver) -> str | None:
    try:
        tabs = driver.find_elements(By.CSS_SELECTOR, "[class*='RegistryView_tabItem']")
        document_tab = None
        for tab in tabs:
            try:
                if _is_document_tab_text(tab.text):
                    document_tab = tab
                    break
            except Exception:
                continue

        if document_tab is None:
            return None

        if "RegistryView_tabItemActive" not in (document_tab.get_attribute("class") or ""):
            if not _click_element(driver, document_tab):
                return None

        WebDriverWait(driver, 10).until(
            lambda d: "RegistryView_tabItemActive" in (document_tab.get_attribute("class") or "")
        )

        link = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                ".RegistryView_wrapper__3LW9q a[href*='doc.licenses.uz'][href*='/uuid/'][href*='/pdf']",
            ))
        )

        href = link.get_attribute("href") or ""
        uuid = _extract_uuid_from_href(href)
        if uuid:
            return uuid

        try:
            page_source = driver.page_source
            return _extract_uuid_from_href(page_source)
        except Exception:
            return None
    except Exception:
        try:
            page_source = driver.page_source
            return _extract_uuid_from_href(page_source)
        except Exception:
            return None


def _click_element(driver, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    except Exception:
        pass

    click_attempts = [
        lambda: element.click(),
        lambda: driver.execute_script("arguments[0].click();", element),
        lambda: ActionChains(driver).move_to_element(element).click().perform(),
    ]

    for attempt in click_attempts:
        try:
            attempt()
            return True
        except Exception:
            continue

    return False


def _open_details_modal(driver, row_el, layout: str | None) -> bool:
    candidates = [row_el]

    if layout == "desktop":
        try:
            action = row_el.find_element(By.CSS_SELECTOR, ".Table_actionCell__2NMKA, .Table_action__3OpEV")
            candidates.insert(0, action)
        except Exception:
            pass

    for candidate in candidates:
        if not _click_element(driver, candidate):
            continue

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".RegistryView_wrapper__3LW9q"))
            )
            return True
        except Exception:
            continue

    return False


# Warmup uchun saytlar zanjiri: biri ishlamasa keyingisi uriniladi
_WARMUP_SITES = [
    # (url, CSS selector, qidiruv so'z)
    ("https://www.wikipedia.org", "#searchInput",    "O'zbekiston"),
    ("https://www.google.com",    "input[name='q']", "python tutorial"),
    ("https://duckduckgo.com",    "input[name='q']", "python tutorial"),
]


def _human_scroll(driver):
    """Sahifada inson kabi scroll qiladi."""
    try:
        for _ in range(random.randint(2, 4)):
            scroll_y = random.randint(200, 500)
            driver.execute_script(f"window.scrollBy(0, {scroll_y});")
            time.sleep(random.uniform(0.3, 0.7))
        # Qaytib yuqoriga
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.2, 0.5))
    except Exception:
        pass


def _human_mouse_move(driver):
    """Sahifada inson kabi mouse harakati."""
    try:
        action = ActionChains(driver)
        # Ekranda bir necha nuqtaga siljitish
        for _ in range(random.randint(3, 6)):
            x = random.randint(100, 900)
            y = random.randint(100, 500)
            action.move_by_offset(x, y)
            time.sleep(random.uniform(0.1, 0.3))
        action.perform()
    except Exception:
        pass


def _warmup(driver) -> bool:
    """
    Cloudflare bot-detection'ni aldash uchun oddiy saytlarda qisqa faoliyat ko'rsatadi.

    Zanjir: Wikipedia → Google → DuckDuckGo
    Har bir saytda: sahifaga kirish + qidirish + scroll + mouse harakat.
    Biri xato bersa keyingisiga o'tadi.
    Hammasi ishlamasa ham bot o'lmaydi.

    SKIP_WARMUP=true bo'lsa butunlay o'tkazib yuboradi.
    """
    if _env_bool("SKIP_WARMUP", default=False):
        print("[warmup] SKIP_WARMUP=true — o'tkazildi")
        return True

    for url, selector, query in _WARMUP_SITES:
        try:
            print(f"[warmup] {url} urinilmoqda...")
            wait = WebDriverWait(driver, 25)

            driver.get(url)
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            _human_delay(0.8, 1.5)

            # Scroll — sahifa yuklangach biroz o'qigan kabi
            _human_scroll(driver)

            # Search box topib yozish
            box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))

            # Mouse harakati — to'g'ri bosmasdan avval
            _human_mouse_move(driver)
            _human_delay(0.3, 0.6)

            box.click()
            _human_delay(0.4, 0.8)

            # Harfma-harf yozish — bot emas, odam kabi
            for ch in query:
                box.send_keys(ch)
                time.sleep(random.uniform(0.05, 0.15))

            _human_delay(0.5, 1.0)
            box.send_keys(Keys.ENTER)
            _human_delay(2.0, 3.5)

            # Natijalar sahifasida ham scroll
            _human_scroll(driver)
            _human_delay(1.0, 2.0)

            print(f"[warmup] OK: {url}")
            return True

        except Exception as e:
            print(f"[warmup] {url} ishlamadi: {e} — keyingisi sinab ko'riladi...")
            continue

    print("[warmup] Hamma warmup saytlari ishlamadi — shunga qaramay davom etilmoqda")
    return False


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
            # DOM to'liq yuklanishini kutish
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

            # Ro'yxat elementlari (desktop jadval yoki mobile kartochkalar) paydo bo'lishini
            # kutamiz — bu qism aynan siz so'ragan "to'liq yuklanguncha kutish".
            try:
                wait_list = WebDriverWait(driver, 40)
                wait_list.until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "table.Table_table__2OuB7 tbody.Table_body__3kRrD tr.Table_row__329lz, "
                            ".RegistryPage_tableMobileWrapper__3oxDb",
                        )
                    )
                )
            except Exception:
                # Agar ro'yxat elementlari 40s ichida chiqmasa, bu urinishni muvaffaqiyatsiz
                # deb hisoblaymiz va qayta urinib ko'ramiz.
                raise

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
    rows = driver.find_elements(
        By.CSS_SELECTOR,
        "table.Table_table__2OuB7 tbody.Table_body__3kRrD tr.Table_row__329lz",
    )
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

            results.append({
                "active": active,
                "number": number_text,
                "tin": tin_text,
                "name": name_text,
                "specialization_oz": specialization_text,
                "uuid": None,  # keyin detal modalidan URL orqali olishga urinib ko'riladi
                "layout": "desktop",
            })
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

            results.append({
                "active": active,
                "number": number_text,
                "tin": tin_text,
                "name": name_text,
                "specialization_oz": specialization_text,
                "uuid": None,
                "layout": "mobile",
            })
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

        # UUID: faqat "Hujjat" tabidagi PDF havolasidan olinadi
        try:
            uuid = _open_document_tab_and_get_uuid(driver)
            if uuid:
                details["uuid"] = uuid
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
            ActionChains(driver).send_keys("\uE00C").perform()  # ESC
        _human_delay(0.3, 0.7)
    except Exception:
        pass

    return details


# ── Asosiy sahifa parse + modal kombinatsiyasi ────────────────────────────────
def _collect_page_data(driver, page_num: int, target_numbers: set[str] | None = None):
    """
    Bitta sahifadagi barcha yozuvlarni:
    - avval listdan qisqa info
    - keyin har biriga kirib modal orqali boyitadi.
    """
    current_page, total_pages = _parse_pagination(driver, page_num)

    # Avval mobile, bo'sh bo'lsa desktop varianti.
    # Ba'zan JS sekin ishlashi mumkin, shuning uchun bir necha marta
    # (kichik delay bilan) qayta urinib ko'ramiz.
    entries: list[dict] = []
    layout: str | None = None
    for _ in range(3):
        entries = _parse_list_mobile_cards(driver)
        if entries:
            layout = "mobile"
            break

        entries = _parse_list_desktop_rows(driver)
        if entries:
            layout = "desktop"
            break

        _human_delay(1.0, 2.0)

    certs: list[dict] = []
    normalized_targets = {_normalize_number(value) for value in target_numbers} if target_numbers is not None else None
    for entry in entries:
        number = _normalize_number(entry.get("number"))
        if not number:
            continue
        if normalized_targets is not None and number not in normalized_targets:
            continue

        # Har safar DOMdan yangi element izlaymiz — shunda oldingi modal
        # ochilib-yopilgandan keyingi stale element muammosidan qochamiz.
        row_el = None
        try:
            if layout == "mobile":
                cards = driver.find_elements(By.CSS_SELECTOR, ".RegistryPage_tableMobileWrapper__3oxDb")
                for card in cards:
                    try:
                        if number in card.text:
                            row_el = card
                            break
                    except Exception:
                        continue
            else:
                rows = driver.find_elements(
                    By.CSS_SELECTOR,
                    "table.Table_table__2OuB7 tbody.Table_body__3kRrD tr.Table_row__329lz",
                )
                for row in rows:
                    try:
                        tds = row.find_elements(By.CSS_SELECTOR, "td.Table_cell__2s5cE")
                        if len(tds) < 3:
                            continue
                        if tds[2].text.strip() == number:
                            row_el = row
                            break
                    except Exception:
                        continue
        except Exception as e:
            print(f"[kochirish_html] Row qidirishda xato: {e}")
            continue

        if row_el is None:
            print(f"[kochirish_html] Row topilmadi (number={number})")
            continue

        if not _open_details_modal(driver, row_el, layout):
            print(f"[kochirish_html] Modal ochilmadi (number={number})")
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
            "page_num": page_num,
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


def _collect_page_list(driver, page_num: int) -> dict:
    """
    Bitta sahifadagi ro'yxatdan (modalga kirmasdan) minimal ma'lumotlarni oladi.
    """
    current_page, total_pages = _parse_pagination(driver, page_num)

    entries: list[dict] = []
    for _ in range(3):
        entries = _parse_list_mobile_cards(driver)
        if not entries:
            entries = _parse_list_desktop_rows(driver)
        if entries:
            break
        _human_delay(1.0, 2.0)

    # ro'yxat mode'ida row_element saqlamaymiz
    minimal = []
    for e in entries:
        minimal.append({
            "active": e.get("active"),
            "number": e.get("number"),
            "tin": e.get("tin"),
            "name": e.get("name"),
            "specialization_oz": e.get("specialization_oz"),
            "uuid": None,
        })

    return {
        "current_page": current_page,
        "all_pages": total_pages,
        "certificates": minimal,
    }


def fetch_page_list(page_num: int) -> dict | None:
    """
    Berilgan page ro'yxatini oladi (modal ochmasdan).
    """
    driver = _get_driver()  # warmup _get_driver ichida, alohida tekshiruv shart emas

    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        print(f"[kochirish_html] fetch_page_list({page_num}) — urinish {attempt + 1}/{MAX_RETRIES}")

        opened = _open_page(driver, page_num)
        if not opened:
            print("[kochirish_html] Sahifa ochilmadi — retry")
            _human_delay(5.0, 8.0)
            continue

        try:
            data = _collect_page_list(driver, page_num)
        except Exception as e:
            print(f"[kochirish_html] collect_page_list xato: {e}")
            data = None

        if data is None or not data.get("certificates"):
            print(f"[kochirish_html] {attempt + 1}-urinishda ham ro'yxat olinmadi yoki bo'sh")
            _human_delay(5.0, 10.0)
            continue

        print(
            f"[kochirish_html] OK(list) — page={data['current_page']}, "
            f"jami={data['all_pages']}, certs={len(data['certificates'])}"
        )
        return data

    print(f"[kochirish_html] {MAX_RETRIES} urinishdan keyin ham list olinmadi: page={page_num}")
    return None


# ── Tashqaridan chaqiriladigan funksiya ───────────────────────────────────────
def fetch_page(page_num: int) -> dict | None:
    """
    Berilgan page raqami uchun ma'lumot oladi (HTML orqali).
    """
    driver = _get_driver()  # warmup _get_driver ichida, alohida tekshiruv shart emas

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


def fetch_new_since(existing_numbers: set[str], max_pages: int = 100) -> list[dict]:
    """
    Ro'yxatdagi hujjat raqamlarini bazadagi mavjud raqamlar bilan solishtiradi.

    Page ichida birorta bazada mavjud raqam topilmaguncha keyingi page'ga o'tadi
    va topilmagan raqamlarni vaqtincha yig'ib boradi. Birinchi marta bazada bor
    raqam uchragan page'ga yetgach, shu paytgacha yig'ilgan yo'q raqamlar uchun
    batafsil ma'lumotlarni modal orqali olib qaytaradi.
    """
    new_certs = []
    pending_pages: list[tuple[int, list[str]]] = []
    queued_numbers: set[str] = set()
    page = 0

    while page < max_pages:
        print(f"[kochirish_html] fetch_new_since: page {page} yuklanmoqda...")

        list_data = fetch_page_list(page)
        if list_data is None:
            break

        listed = list_data.get("certificates", [])
        if not listed:
            break

        page_missing_numbers: list[str] = []
        page_has_existing = False

        for cert in listed:
            normalized_number = _normalize_number(cert.get("number"))
            if not normalized_number:
                continue

            if normalized_number in existing_numbers:
                page_has_existing = True
                continue

            if normalized_number in queued_numbers:
                continue

            queued_numbers.add(normalized_number)
            page_missing_numbers.append(normalized_number)

        if page_missing_numbers:
            pending_pages.append((page, page_missing_numbers))

        if page_has_existing:
            break

        page += 1

    for page_num, page_numbers in pending_pages:
        driver = _get_driver()
        opened = _open_page(driver, page_num)
        if not opened:
            print(f"[kochirish_html] Detail uchun page ochilmadi: {page_num}")
            continue

        try:
            detailed_page = _collect_page_data(driver, page_num, target_numbers=set(page_numbers))
        except Exception as e:
            print(f"[kochirish_html] collect_page_data(new_only) xato: {e}")
            detailed_page = None

        if detailed_page and detailed_page.get("certificates"):
            new_certs.extend(detailed_page["certificates"])

    print(f"[kochirish_html] fetch_new_since: jami {len(new_certs)} ta yangi yozuv topildi")
    return new_certs