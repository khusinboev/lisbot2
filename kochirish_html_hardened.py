"""
kochirish_html_hardened.py — license.gov.uz scraper (hardened)

Yangi modul:
- list ko'rinmaslik sabablarini klassifikatsiya qiladi;
- challenge/interstitial holatlarni aniqlaydi;
- Ubuntu/headless uchun barqarorroq driver flaglar qo'llaydi;
- fallback selectorlar bilan desktop/mobile parse qiladi.
"""

import os
import random
import re
import time
from typing import Callable

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "https://license.gov.uz/registry"
FILTER_PARAMS = "?filter%5Bdocument_id%5D=4409&filter%5Bdocument_type%5D=LICENSE"

current_dir = os.path.dirname(os.path.abspath(__file__))
profile_path = os.getenv("CHROME_PROFILE_DIR") or os.path.join(current_dir, "chrome_profile")
os.makedirs(profile_path, exist_ok=True)

ARTIFACT_DIR = os.path.join(current_dir, "_debug_artifacts")
os.makedirs(ARTIFACT_DIR, exist_ok=True)

_DRIVER = None
_screenshot_callback: Callable[[str, str], None] | None = None
_WARMUP_DONE = False

# Ordered fallback selectors for row discovery.
DESKTOP_ROW_SELECTORS = [
    "table.Table_table__2OuB7 tbody.Table_body__3kRrD tr.Table_row__329lz",
    "table tbody tr.Table_row__329lz",
    "tbody tr[class*='Table_row']",
]

MOBILE_CARD_SELECTORS = [
    "div.RegistryPage_tableMobileWrapper__3oxDb",
    "div[class*='tableMobileWrapper']",
    "div[class*='MobileWrapper']",
]

CHALLENGE_KEYWORDS = [
    "verify you are human",
    "attention required",
    "too many requests",
    "access denied",
]

HARD_CHALLENGE_SELECTORS = [
    "#cf-challenge-running",
    "#challenge-stage",
]

APP_LOADING_SELECTORS = [
    ".Splash_wrapper__2X9p7",
    "[class*='Splash_wrapper']",
    "[class*='spinner']",
    "[class*='Spinner']",
    "[aria-busy='true']",
]


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


def _detect_chrome_binary() -> str | None:
    import shutil
    import sys

    env_path = os.getenv("CHROME_BINARY", "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        candidates = [
            "/opt/google/chrome/google-chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path

    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        found = shutil.which(name)
        if found:
            return found

    return None


def _detect_firefox_binary() -> str | None:
    import shutil
    import sys

    env_path = os.getenv("FIREFOX_BINARY", "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Firefox.app/Contents/MacOS/firefox",
        ]
    else:
        candidates = [
            "/usr/bin/firefox",
            "/snap/bin/firefox",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path

    found = shutil.which("firefox")
    return found


def _is_driver_alive(driver):
    try:
        _ = driver.current_url
        _ = driver.window_handles
        return True
    except Exception:
        return False


def _warmup_mode() -> str:
    raw = (os.getenv("WARMUP_MODE", "adaptive") or "adaptive").strip().lower()
    if raw in {"never", "off", "disable", "0", "no"}:
        return "never"
    if raw in {"always", "on", "1", "yes"}:
        return "always"
    return "adaptive"


def _init_firefox_driver():
    options = FirefoxOptions()

    # Firefox profile path (fallback: existing profile path envs).
    ff_profile = os.getenv("FIREFOX_PROFILE_DIR") or os.getenv("CHROME_PROFILE_DIR") or profile_path
    os.makedirs(ff_profile, exist_ok=True)
    options.set_preference("profile", ff_profile)

    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)
    options.set_preference("media.peerconnection.enabled", False)

    headless = _env_bool("FIREFOX_HEADLESS", default=_env_bool("CHROME_HEADLESS", default=_env_bool("IN_DOCKER", default=False)))
    if headless:
        options.add_argument("-headless")

    firefox_binary = _detect_firefox_binary()
    if firefox_binary:
        options.binary_location = firefox_binary
        print(f"[hardened.driver] Firefox: {firefox_binary}")
    else:
        print("[hardened.driver] Firefox path topilmadi, Selenium Manager ishlatiladi")

    driver = webdriver.Firefox(options=options)
    driver.set_page_load_timeout(120)
    driver.set_window_size(900, 900)
    return driver


def _init_driver():
    browser = (os.getenv("SCRAPER_BROWSER", "chrome") or "chrome").strip().lower()
    if browser == "firefox":
        try:
            return _init_firefox_driver()
        except Exception as e:
            print(f"[hardened.driver] Firefox init xato, Chrome fallback: {e}")

    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=900,900")

    # Ubuntu/container-friendly runtime flags.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    chrome_binary = _detect_chrome_binary()
    if chrome_binary:
        options.binary_location = chrome_binary
        print(f"[hardened.driver] Chrome: {chrome_binary}")
    else:
        print("[hardened.driver] Chrome path topilmadi, auto-detect ishlatiladi")

    # Docker yoki server muhiti uchun headless default.
    headless = _env_bool("CHROME_HEADLESS", default=_env_bool("IN_DOCKER", default=False))
    if headless:
        options.add_argument("--headless=new")

    version_main = _env_int("CHROME_VERSION_MAIN")
    if version_main is not None:
        driver = uc.Chrome(version_main=version_main, options=options)
    else:
        driver = uc.Chrome(options=options)

    driver.set_page_load_timeout(120)

    # Fingerprint signalini kamaytirish uchun baseline JS overrides.
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['uz-UZ', 'uz', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """,
    })
    return driver


def _get_driver():
    global _DRIVER, _WARMUP_DONE
    if _DRIVER is not None and _is_driver_alive(_DRIVER):
        return _DRIVER

    _DRIVER = _init_driver()
    _WARMUP_DONE = False

    mode = _warmup_mode()
    if not _env_bool("SKIP_WARMUP", default=False) and mode == "always":
        _WARMUP_DONE = _warmup(_DRIVER)

    return _DRIVER


def _take_artifacts(driver, label: str) -> tuple[str | None, str | None]:
    """Skrinshot + qisqa HTML snapshot saqlaydi."""
    ts = int(time.time())
    shot_path = os.path.join(ARTIFACT_DIR, f"{label}_{ts}.png")
    html_path = os.path.join(ARTIFACT_DIR, f"{label}_{ts}.html")

    saved_shot = None
    saved_html = None

    try:
        driver.save_screenshot(shot_path)
        saved_shot = shot_path
    except Exception:
        pass

    try:
        source = driver.page_source or ""
        with open(html_path, "w", encoding="utf-8") as f:
            # Juda katta bo'lsa ham tahlil uchun birinchi qismini saqlaymiz.
            f.write(source[:300000])
        saved_html = html_path
    except Exception:
        pass

    return saved_shot, saved_html


def set_screenshot_callback(fn):
    global _screenshot_callback
    _screenshot_callback = fn


def _emit_screenshot(driver, label: str, caption: str):
    if _screenshot_callback is None:
        return
    shot_path, _ = _take_artifacts(driver, label)
    if shot_path:
        try:
            _screenshot_callback(shot_path, caption)
        except Exception as e:
            print(f"[hardened.screenshot] callback xato: {e}")


def _count_rows(driver) -> tuple[int, int]:
    desktop = 0
    mobile = 0
    for selector in DESKTOP_ROW_SELECTORS:
        try:
            desktop = len(driver.find_elements(By.CSS_SELECTOR, selector))
            if desktop:
                break
        except Exception:
            continue
    for selector in MOBILE_CARD_SELECTORS:
        try:
            mobile = len(driver.find_elements(By.CSS_SELECTOR, selector))
            if mobile:
                break
        except Exception:
            continue
    return desktop, mobile


def _looks_like_challenge(driver) -> bool:
    source = ""
    body_text = ""
    title_text = ""

    try:
        source = (driver.page_source or "").lower()
    except Exception:
        source = ""

    try:
        body_text = (driver.execute_script("return document.body ? document.body.innerText : ''") or "").lower()
    except Exception:
        body_text = ""

    try:
        title_text = (driver.title or "").lower()
    except Exception:
        title_text = ""

    # Cloudflare challenge page signatures.
    if "just a moment" in title_text or "cf-chl" in source:
        return True

    for selector in HARD_CHALLENGE_SELECTORS:
        try:
            if driver.find_elements(By.CSS_SELECTOR, selector):
                return True
        except Exception:
            continue

    return any(keyword in body_text for keyword in CHALLENGE_KEYWORDS)


def _app_is_loading(driver) -> bool:
    for selector in APP_LOADING_SELECTORS:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            if els:
                return True
        except Exception:
            continue
    return False


def _wait_for_app_bootstrap(driver, timeout=35) -> tuple[bool, str]:
    """SPA sahifasi to'liq yuklanishini kutadi (splash yo'qolishi + DOM ready)."""
    deadline = time.time() + timeout
    last_reason = "app_loading"

    while time.time() < deadline:
        try:
            ready_state = driver.execute_script("return document.readyState")
        except Exception:
            ready_state = None

        if ready_state != "complete":
            last_reason = "dom_not_ready"
            time.sleep(0.7)
            continue

        if _app_is_loading(driver):
            last_reason = "app_loading"
            time.sleep(0.9)
            continue

        # App shell yuklangandan keyin sahifada asosiy konteynerlardan biri ko'rinishi kerak.
        try:
            anchors = driver.find_elements(
                By.CSS_SELECTOR,
                "#root, .RegistryPage_wrapper__6Jx5V, [class*='RegistryPage_'], .Pagination_wrapper__x6M1d, [class*='Pagination_']",
            )
            if anchors:
                return True, "app_ready"
        except Exception:
            pass

        last_reason = "app_shell_not_ready"
        time.sleep(0.7)

    return False, last_reason


def _detect_page_state(driver) -> dict:
    desktop_rows, mobile_rows = _count_rows(driver)
    total_rows = desktop_rows + mobile_rows

    state = {
        "rows": total_rows,
        "desktop_rows": desktop_rows,
        "mobile_rows": mobile_rows,
        "challenge": False,
        "empty_marker": False,
        "reason": "unknown",
    }

    if total_rows > 0:
        state["reason"] = "ok"
        return state

    challenge = _looks_like_challenge(driver)
    state["challenge"] = challenge
    if challenge:
        state["reason"] = "blocked_or_challenge"
        return state

    if _app_is_loading(driver):
        state["reason"] = "app_loading"
        return state

    # Empty-state markerlar (saytning bo'sh holati yoki placeholderlari).
    empty_selectors = [
        "[class*='empty']",
        "[class*='Empty']",
        "[class*='notFound']",
        "[class*='placeholder']",
    ]
    for selector in empty_selectors:
        try:
            if driver.find_elements(By.CSS_SELECTOR, selector):
                state["empty_marker"] = True
                state["reason"] = "selector_mismatch_or_empty_state"
                return state
        except Exception:
            continue

    state["reason"] = "timeout_no_rows"
    return state


def _wait_for_rows(driver, timeout=45) -> tuple[bool, str, dict]:
    deadline = time.time() + timeout
    last_reason = "timeout_no_rows"
    last_state = {"rows": 0}

    while time.time() < deadline:
        try:
            state = _detect_page_state(driver)
            last_state = state
            last_reason = state.get("reason", "timeout_no_rows")
            if state.get("rows", 0) > 0:
                return True, "ok", state
            if state.get("challenge") and state.get("reason") == "blocked_or_challenge":
                # Faqat kuchli challenge signallari bo'lsa erta to'xtaymiz.
                return False, "blocked_or_challenge", state
        except Exception as e:
            last_reason = "network_or_dom_error"
            last_state = {"rows": 0, "error": str(e)}
        time.sleep(1.0)

    return False, last_reason, last_state


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


def _human_scroll(driver):
    try:
        for _ in range(random.randint(2, 4)):
            scroll_y = random.randint(200, 450)
            driver.execute_script(f"window.scrollBy(0, {scroll_y});")
            time.sleep(random.uniform(0.3, 0.8))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.2, 0.5))
    except Exception:
        pass


def _human_mouse_move(driver):
    try:
        action = ActionChains(driver)
        for _ in range(random.randint(2, 4)):
            x = random.randint(20, 200)
            y = random.randint(20, 160)
            action.move_by_offset(x, y)
            time.sleep(random.uniform(0.1, 0.2))
        action.perform()
    except Exception:
        pass


def _type_humanlike(element, text: str):
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(0.04, 0.16))


def _warmup(driver) -> bool:
    if _env_bool("SKIP_WARMUP", default=False):
        return True

    try:
        wait = WebDriverWait(driver, 25)
        driver.execute_script("window.location.href = arguments[0];", "https://www.youtube.com")
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        _human_delay(1.0, 2.0)

        for consent_sel in [
            "button[aria-label*='Accept']",
            "button[aria-label*='agree']",
            ".eom-buttons button:first-child",
        ]:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, consent_sel)
                btn.click()
                _human_delay(0.6, 1.2)
                break
            except Exception:
                continue

        box = wait.until(EC.presence_of_element_located((By.NAME, "search_query")))
        ActionChains(driver).move_to_element(box).click().perform()

        query = random.choice(["uzbekistan", "news today", "python tutorial"])
        _type_humanlike(box, query)
        _human_delay(0.5, 1.0)
        box.send_keys(Keys.ENTER)

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-video-renderer, ytd-rich-item-renderer")))
        except Exception:
            wait.until(EC.presence_of_element_located((By.ID, "contents")))

        _human_mouse_move(driver)
        _human_scroll(driver)
        return True
    except Exception as e:
        print(f"[hardened.warmup] xato: {e}")
        return False


def _open_page(driver, page_num: int) -> tuple[bool, str]:
    global _WARMUP_DONE

    url = f"{BASE_URL}{FILTER_PARAMS}&page={page_num + 1}"
    print(f"[hardened] URL ochilmoqda: {url}")

    # Exponential backoff + jitter.
    retry_wait = [3.0, 8.0, 20.0]
    last_reason = "timeout_no_rows"
    warmup_mode = _warmup_mode()
    can_adaptive_warmup = warmup_mode == "adaptive" and not _env_bool("SKIP_WARMUP", default=False)

    boot_timeout = _env_int("APP_BOOT_TIMEOUT_SECONDS") or 40
    row_timeout = _env_int("ROW_WAIT_TIMEOUT_SECONDS") or 65

    for attempt in range(3):
        try:
            driver.get(url)
        except Exception as e:
            print(f"[hardened] driver.get xato (attempt {attempt + 1}/3): {e}")

        boot_ok, boot_reason = _wait_for_app_bootstrap(driver, timeout=boot_timeout)
        if not boot_ok:
            last_reason = boot_reason
            label = f"boot_fail_p{page_num}_try{attempt + 1}_{boot_reason}"
            shot_path, html_path = _take_artifacts(driver, label)
            print(f"[hardened] app bootstrap fail: reason={boot_reason}")
            if shot_path:
                print(f"[hardened] screenshot: {shot_path}")
            if html_path:
                print(f"[hardened] html snapshot: {html_path}")

            if attempt < 2:
                sleep_for = retry_wait[attempt] + random.uniform(0.5, 1.5)
                time.sleep(sleep_for)
                try:
                    driver.refresh()
                except Exception:
                    pass
            continue

        ok, reason, state = _wait_for_rows(driver, timeout=row_timeout)
        last_reason = reason
        if ok:
            _human_delay(0.6, 1.2)
            _emit_screenshot(
                driver,
                f"ok_p{page_num}_try{attempt + 1}",
                f"✅ Page {page_num + 1} yuklandi (attempt {attempt + 1}/3)",
            )
            return True, "ok"

        if reason == "blocked_or_challenge" and can_adaptive_warmup and not _WARMUP_DONE:
            print("[hardened] blocked/challenge ko'rindi, adaptive warmup ishga tushdi...")
            _WARMUP_DONE = _warmup(driver)
            print(f"[hardened] adaptive warmup natijasi: {_WARMUP_DONE}")
            # Warmupdan keyin keyingi urinishda shu page qayta ochiladi.
            continue

        label = f"fail_p{page_num}_try{attempt + 1}_{reason}"
        shot_path, html_path = _take_artifacts(driver, label)
        print(
            f"[hardened] page wait fail: reason={reason} rows={state.get('rows')} "
            f"desktop={state.get('desktop_rows')} mobile={state.get('mobile_rows')}"
        )
        if shot_path:
            print(f"[hardened] screenshot: {shot_path}")
        if html_path:
            print(f"[hardened] html snapshot: {html_path}")

        _emit_screenshot(
            driver,
            f"retry_p{page_num}_try{attempt + 1}",
            f"⚠️ Page {page_num + 1}: {reason}. Qayta urinish...",
        )

        if attempt < 2:
            sleep_for = retry_wait[attempt] + random.uniform(0.5, 1.5)
            time.sleep(sleep_for)
            try:
                driver.refresh()
            except Exception:
                pass

    return False, last_reason


def _parse_pagination(driver, fallback_page_num: int) -> tuple[int, int]:
    try:
        active_el = driver.find_element(
            By.CSS_SELECTOR,
            ".Pagination_itemActive___lJca .Pagination_itemActiveLink__1Tcd4",
        )
        current = int(active_el.text.strip()) - 1

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


def _parse_list_desktop_rows(driver):
    rows = []
    for selector in DESKTOP_ROW_SELECTORS:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, selector)
            if rows:
                break
        except Exception:
            continue

    results = []
    for row in rows:
        try:
            tds = row.find_elements(By.CSS_SELECTOR, "td.Table_cell__2s5cE, td")
            if len(tds) < 3:
                continue

            title_cell = tds[0]
            specialization_text = ""
            try:
                title_el = title_cell.find_element(By.CSS_SELECTOR, ".Table_titleCellValue__2Wjmv")
                specialization_text = title_el.text.strip()
            except Exception:
                specialization_text = title_cell.text.strip()

            org_cell = tds[1]
            name_text = org_cell.text.strip()
            tin_text = ""
            try:
                span = org_cell.find_element(By.TAG_NAME, "span")
                tin_text = span.text.strip()
                name_text = org_cell.text.replace(tin_text, "").strip().strip('" ')
            except Exception:
                pass

            number_text = tds[2].text.strip()
            active = False
            if len(tds) >= 6:
                active = bool(
                    tds[5].find_elements(
                        By.CSS_SELECTOR,
                        ".IconLabel_wrapper--success__iBPoQ, .Status_wrapper--success__3eEIw, [class*='success']",
                    )
                )

            results.append({
                "active": active,
                "number": number_text,
                "tin": tin_text,
                "name": name_text,
                "specialization_oz": specialization_text,
                "uuid": None,
                "layout": "desktop",
            })
        except Exception:
            continue

    return results


def _parse_list_mobile_cards(driver):
    cards = []
    for selector in MOBILE_CARD_SELECTORS:
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, selector)
            if cards:
                break
        except Exception:
            continue

    results = []
    for card in cards:
        try:
            specialization_text = ""
            for sel in [
                ".RegistryPage_tableMobileTitle__l7DUW",
                ".RegistryPage_tableMobileDescription__3mTbZ",
                "[class*='tableMobileTitle']",
                "[class*='tableMobileDescription']",
            ]:
                try:
                    txt = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                    if txt:
                        specialization_text = txt
                        break
                except Exception:
                    continue

            num_text = card.text.strip()
            nums = re.findall(r"\d+", num_text)
            tin_text = nums[0] if nums else ""
            number_text = nums[-1] if nums else ""

            name_text = num_text
            if tin_text and number_text and tin_text in name_text and number_text in name_text:
                try:
                    start = name_text.index(tin_text) + len(tin_text)
                    end = name_text.rindex(number_text)
                    name_text = name_text[start:end].strip().strip('" ')
                except ValueError:
                    pass

            active = "faol" in num_text.lower() or "active" in num_text.lower()

            results.append({
                "active": active,
                "number": number_text,
                "tin": tin_text,
                "name": name_text,
                "specialization_oz": specialization_text,
                "uuid": None,
                "layout": "mobile",
            })
        except Exception:
            continue

    return results


def _open_details_modal(driver, row_el, layout: str | None) -> bool:
    candidates = [row_el]

    if layout == "desktop":
        try:
            action = row_el.find_element(By.CSS_SELECTOR, ".Table_actionCell__2NMKA, .Table_action__3OpEV, [class*='action']")
            candidates.insert(0, action)
        except Exception:
            pass

    for candidate in candidates:
        if not _click_element(driver, candidate):
            continue

        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".RegistryView_wrapper__3LW9q, [class*='RegistryView_wrapper']"))
            )
            return True
        except Exception:
            continue

    return False


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

        # Tab aktiv bo'lgandan keyin kontent ready bo'lishini kutamiz.
        link = WebDriverWait(driver, 12).until(
            EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                ".RegistryView_wrapper__3LW9q a[href*='doc.licenses.uz'][href*='/uuid/'], [class*='RegistryView_wrapper'] a[href*='/uuid/']",
            ))
        )

        href = link.get_attribute("href") or ""
        uuid = _extract_uuid_from_href(href)
        if uuid:
            return uuid

        page_source = driver.page_source
        return _extract_uuid_from_href(page_source)
    except Exception:
        try:
            return _extract_uuid_from_href(driver.page_source)
        except Exception:
            return None


def _parse_details_modal(driver) -> dict:
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".RegistryView_wrapper__3LW9q, [class*='RegistryView_wrapper']")))

    details = {}
    try:
        items = driver.find_elements(By.CSS_SELECTOR, ".Details_item__d8XKD, [class*='Details_item']")
        for item in items:
            try:
                title = item.find_element(By.CSS_SELECTOR, ".Details_itemTitle__2kmDz, [class*='itemTitle']").text.strip()
                value = item.find_element(By.CSS_SELECTOR, ".Details_itemValue__1DlsR, [class*='itemValue']").text.strip()
            except Exception:
                continue

            if title == "Holati":
                details["active_text"] = value
            elif "Tashkilot" in title:
                details["name"] = value
            elif "STIR" in title:
                details["tin"] = value
            elif "Hujjat raqami" in title:
                details["number"] = value

        try:
            cat_el = driver.find_element(By.CSS_SELECTOR, ".RegistryView_title__1khqt, [class*='RegistryView_title']")
            details["specialization_oz"] = cat_el.text.strip()
        except Exception:
            pass

        uuid = _open_document_tab_and_get_uuid(driver)
        if uuid:
            details["uuid"] = uuid
    except Exception as e:
        print(f"[hardened] modal parse xato: {e}")

    # Close modal safely.
    try:
        close_btns = driver.find_elements(By.CSS_SELECTOR, ".ModalNav_close__1lmq4, [class*='close']")
        if close_btns:
            close_btns[0].click()
        else:
            ActionChains(driver).send_keys("\uE00C").perform()
        _human_delay(0.25, 0.6)
    except Exception:
        pass

    return details


def _collect_page_data(driver, page_num: int, target_numbers: set[str] | None = None):
    current_page, total_pages = _parse_pagination(driver, page_num)

    entries = []
    layout = None
    for _ in range(3):
        entries = _parse_list_mobile_cards(driver)
        if entries:
            layout = "mobile"
            break

        entries = _parse_list_desktop_rows(driver)
        if entries:
            layout = "desktop"
            break

        _human_delay(0.8, 1.6)

    certs = []
    normalized_targets = {_normalize_number(value) for value in target_numbers} if target_numbers is not None else None

    for entry in entries:
        number = _normalize_number(entry.get("number"))
        if not number:
            continue
        if normalized_targets is not None and number not in normalized_targets:
            continue

        # Har iteratsiyada row elementini qayta topib stale elementni kamaytiramiz.
        row_el = None
        try:
            if layout == "mobile":
                cards = _parse_matching_cards(driver, number)
                row_el = cards[0] if cards else None
            else:
                rows = _parse_matching_rows(driver, number)
                row_el = rows[0] if rows else None
        except Exception:
            row_el = None

        if row_el is None:
            continue
        if not _open_details_modal(driver, row_el, layout):
            continue

        _human_delay(0.6, 1.2)
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


def _parse_matching_cards(driver, number: str):
    cards = []
    for selector in MOBILE_CARD_SELECTORS:
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, selector)
            if cards:
                break
        except Exception:
            continue
    matches = []
    for card in cards:
        try:
            if number in card.text:
                matches.append(card)
        except Exception:
            continue
    return matches


def _parse_matching_rows(driver, number: str):
    rows = []
    for selector in DESKTOP_ROW_SELECTORS:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, selector)
            if rows:
                break
        except Exception:
            continue

    matches = []
    for row in rows:
        try:
            tds = row.find_elements(By.CSS_SELECTOR, "td.Table_cell__2s5cE, td")
            if len(tds) < 3:
                continue
            if _normalize_number(tds[2].text.strip()) == number:
                matches.append(row)
        except Exception:
            continue
    return matches


def _collect_page_list(driver, page_num: int) -> dict:
    current_page, total_pages = _parse_pagination(driver, page_num)

    entries = []
    for _ in range(3):
        entries = _parse_list_mobile_cards(driver)
        if not entries:
            entries = _parse_list_desktop_rows(driver)
        if entries:
            break
        _human_delay(0.8, 1.6)

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
    driver = _get_driver()

    for attempt in range(3):
        print(f"[hardened] fetch_page_list({page_num}) attempt {attempt + 1}/3")
        opened, reason = _open_page(driver, page_num)
        if not opened:
            print(f"[hardened] list page ochilmadi: {reason}")
            _human_delay(4.0, 8.0)
            continue

        try:
            data = _collect_page_list(driver, page_num)
        except Exception as e:
            print(f"[hardened] collect_page_list xato: {e}")
            data = None

        if data is None or not data.get("certificates"):
            _human_delay(4.0, 8.0)
            continue

        print(
            f"[hardened] OK(list) page={data['current_page']} "
            f"all={data['all_pages']} certs={len(data['certificates'])}"
        )
        return data

    return None


def fetch_page(page_num: int) -> dict | None:
    driver = _get_driver()

    for attempt in range(3):
        print(f"[hardened] fetch_page({page_num}) attempt {attempt + 1}/3")

        opened, reason = _open_page(driver, page_num)
        if not opened:
            print(f"[hardened] page ochilmadi: {reason}")
            _human_delay(4.0, 8.0)
            continue

        try:
            data = _collect_page_data(driver, page_num)
        except Exception as e:
            print(f"[hardened] collect_page_data xato: {e}")
            data = None

        if data is None or not data.get("certificates"):
            print(f"[hardened] page bo'sh yoki cert yo'q: {page_num}")
            _human_delay(4.0, 8.0)
            continue

        print(
            f"[hardened] OK page={data['current_page']} "
            f"all={data['all_pages']} certs={len(data['certificates'])}"
        )
        return data

    return None


def fetch_new_since(existing_numbers: set[str], max_pages: int = 100) -> list[dict]:
    new_certs = []
    pending_pages: list[tuple[int, list[str]]] = []
    queued_numbers: set[str] = set()
    page = 0

    while page < max_pages:
        print(f"[hardened] fetch_new_since page={page}")

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
        opened, reason = _open_page(driver, page_num)
        if not opened:
            print(f"[hardened] detail page ochilmadi: {page_num}, reason={reason}")
            continue

        try:
            detailed_page = _collect_page_data(driver, page_num, target_numbers=set(page_numbers))
        except Exception as e:
            print(f"[hardened] collect_page_data(new_only) xato: {e}")
            detailed_page = None

        if detailed_page and detailed_page.get("certificates"):
            new_certs.extend(detailed_page["certificates"])

    print(f"[hardened] fetch_new_since: {len(new_certs)} ta yangi yozuv")
    return new_certs
