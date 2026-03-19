"""Robust data fetch for license.gov.uz/api.licenses.uz with deep diagnostics."""

import json
import random
import time
from typing import Optional

API_BASE = "https://api.licenses.uz/v1/register/open_source"
REGISTRY_URL = "https://license.gov.uz/registry?filter%5Bdocument_id%5D=4409&filter%5Bdocument_type%5D=LICENSE&page=1"


def _candidate_params(page_num: int) -> list[dict]:
    # Serverlarda ba'zan page 0-based/1-based tafovuti bo'ladi, ikkalasini ham sinaymiz.
    return [
        {"document_id": 4409, "document_type": "LICENSE", "page": page_num, "size": 10},
        {"document_id": 4409, "document_type": "LICENSE", "page": page_num + 1, "size": 10},
        {"document_id": "4409", "document_type": "LICENSE", "page": page_num, "size": "10"},
        {"document_id": "4409", "document_type": "LICENSE", "page": page_num + 1, "size": "10"},
    ]


def _map_payload(data: dict, page_num: int) -> Optional[dict]:
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
        spec_name = ""
        if specs:
            spec = specs[0].get("name") or {}
            spec_name = spec.get("oz") or spec.get("uz") or spec.get("ru") or ""
        mapped.append({
            "number": str(c.get("number", "")),
            "name": (c.get("name") or "").strip(),
            "active": bool(c.get("active", False)),
            "tin": str(c.get("tin", "") or ""),
            "specialization_oz": spec_name,
            "uuid": c.get("uuid"),
            "page_num": page_num,
        })

    return {
        "current_page": int(payload.get("currentPage", page_num)),
        "all_pages": int(payload.get("totalPages", page_num + 1)),
        "certificates": mapped,
    }


def _fetch_via_curl_cffi_robust(page_num: int) -> Optional[dict]:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("[fetch_robust.curl_cffi] curl_cffi o'rnatilmagan")
        return None

    profiles = ["chrome124", "chrome120", "edge101", "safari17_0"]
    for profile in profiles:
        for params in _candidate_params(page_num):
            try:
                print(f"[fetch_robust.curl_cffi] profile={profile} params={params}")
                session = cffi_requests.Session(impersonate=profile)  # type: ignore[arg-type]
                session.headers.update({
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "uz-UZ,uz;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": "https://license.gov.uz/",
                    "Origin": "https://license.gov.uz",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-site",
                })
                resp = session.get(API_BASE, params=params, timeout=30)
                if resp.status_code == 200:
                    try:
                        mapped = _map_payload(resp.json(), page_num)
                    except Exception as e:
                        print(f"[fetch_robust.curl_cffi] JSON parse xato: {e}")
                        mapped = None
                    if mapped:
                        print(f"[fetch_robust.curl_cffi] OK certs={len(mapped['certificates'])}")
                        return mapped
                    print("[fetch_robust.curl_cffi] 200 qaytdi, lekin payload bo'sh/yaroqsiz")
                else:
                    snippet = (resp.text or "")[:180].replace("\n", " ")
                    print(f"[fetch_robust.curl_cffi] HTTP {resp.status_code} body={snippet}")
            except Exception as e:
                print(f"[fetch_robust.curl_cffi] xato: {e}")
                time.sleep(random.uniform(1.0, 2.5))

    return None


def _fetch_via_requests_spoofed(page_num: int) -> Optional[dict]:
    try:
        import requests
    except ImportError:
        print("[fetch_robust.requests] requests o'rnatilmagan")
        return None

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "uz-UZ,uz;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://license.gov.uz/",
        "Origin": "https://license.gov.uz",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Cache-Control": "no-cache",
    })

    for params in _candidate_params(page_num):
        try:
            print(f"[fetch_robust.requests] params={params}")
            resp = session.get(API_BASE, params=params, timeout=30)
            if resp.status_code == 200:
                mapped = _map_payload(resp.json(), page_num)
                if mapped:
                    print(f"[fetch_robust.requests] OK certs={len(mapped['certificates'])}")
                    return mapped
                print("[fetch_robust.requests] 200 qaytdi, lekin payload yaroqsiz")
            else:
                snippet = (resp.text or "")[:180].replace("\n", " ")
                print(f"[fetch_robust.requests] HTTP {resp.status_code} body={snippet}")
        except Exception as e:
            print(f"[fetch_robust.requests] xato: {e}")

    return None


def _fetch_via_playwright(page_num: int) -> Optional[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[fetch_robust.playwright] Playwright o'rnatilmagan")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.set_default_timeout(35000)

            # networkidle serverlarda osilib qolishi mumkin; domcontentloaded + qo'shimcha kutish.
            page.goto(REGISTRY_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            for params in _candidate_params(page_num):
                try:
                    print(f"[fetch_robust.playwright] browser-context API params={params}")
                    result = page.evaluate(
                        """
                        async ({ url, params }) => {
                            const q = new URLSearchParams(params).toString();
                            const res = await fetch(`${url}?${q}`, {
                                method: 'GET',
                                headers: {
                                    'accept': 'application/json, text/plain, */*',
                                    'x-requested-with': 'XMLHttpRequest'
                                },
                                credentials: 'include'
                            });
                            const text = await res.text();
                            let data = null;
                            try { data = JSON.parse(text); } catch {}
                            return { status: res.status, text: text.slice(0, 300), data };
                        }
                        """,
                        {"url": API_BASE, "params": params},
                    )

                    status = int(result.get("status", 0))
                    if status == 200 and result.get("data"):
                        mapped = _map_payload(result["data"], page_num)
                        if mapped:
                            print(f"[fetch_robust.playwright] OK certs={len(mapped['certificates'])}")
                            context.close()
                            browser.close()
                            return mapped
                        print("[fetch_robust.playwright] 200, lekin payload yaroqsiz")
                    else:
                        snippet = (result.get("text") or "")[:180].replace("\n", " ")
                        print(f"[fetch_robust.playwright] HTTP {status} body={snippet}")
                except Exception as e:
                    print(f"[fetch_robust.playwright] fetch xato: {e}")

            context.close()
            browser.close()
    except Exception as e:
        print(f"[fetch_robust.playwright] xato: {e}")

    return None


def fetch_page_robust(page_num: int) -> Optional[dict]:
    strategies = [
        ("curl_cffi", _fetch_via_curl_cffi_robust),
        ("playwright", _fetch_via_playwright),
        ("requests", _fetch_via_requests_spoofed),
    ]

    for name, strategy in strategies:
        print(f"\n[fetch_robust] {name} urinish qilinmoqda...")
        try:
            result = strategy(page_num)
            if result and result.get("certificates"):
                print(f"[fetch_robust] OK via {name}")
                return result
        except Exception as e:
            print(f"[fetch_robust] {name} strategy xato: {e}")
            time.sleep(1)

    print("[fetch_robust] Hammasi muvaffaqiyatsiz, None qaytarilmoqda")
    return None


def set_screenshot_callback(fn):
    _ = fn
