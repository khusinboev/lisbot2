"""
Compliant test script for first item retrieval.

Goals:
- Use the public API path without stealth/evasion behavior.
- Provide deterministic retry/backoff for transient failures.
- Print a clear diagnostic summary when blocked or unavailable.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any


def _sleep_backoff(attempt: int) -> None:
    # 1, 2, 4, 8, 12 seconds (capped)
    delay = min(12, 2 ** max(0, attempt - 1))
    time.sleep(delay)


def _try_fetch_first_item(page_num: int, max_attempts: int = 5) -> dict[str, Any] | None:
    """Try API retrieval with bounded retries and explicit diagnostics."""
    from test1 import fetch_page

    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        started = time.time()
        try:
            data = fetch_page(page_num)
            elapsed = round(time.time() - started, 2)

            if not data:
                last_error = "empty_response"
                print(f"[compliant] attempt={attempt}/{max_attempts} elapsed={elapsed}s result=empty")
                _sleep_backoff(attempt)
                continue

            certs = data.get("certificates") or []
            if not certs:
                last_error = "no_certificates"
                print(f"[compliant] attempt={attempt}/{max_attempts} elapsed={elapsed}s result=no_certificates")
                _sleep_backoff(attempt)
                continue

            print(f"[compliant] attempt={attempt}/{max_attempts} elapsed={elapsed}s result=ok certs={len(certs)}")
            return {
                "current_page": data.get("current_page"),
                "all_pages": data.get("all_pages"),
                "certificates_count": len(certs),
                "first_item": certs[0],
                "source": "official_api",
            }
        except Exception as e:
            elapsed = round(time.time() - started, 2)
            last_error = str(e)
            print(f"[compliant] attempt={attempt}/{max_attempts} elapsed={elapsed}s error={e}")
            _sleep_backoff(attempt)

    if last_error:
        print(f"[compliant] final_status=failed reason={last_error}")
    return None


def main() -> int:
    print(f"[{datetime.now().isoformat()}] Compliant test boshlandi")

    page_num = int((os.getenv("TEST_PAGE", "0") or "0").strip())
    max_attempts = int((os.getenv("TEST_MAX_ATTEMPTS", "5") or "5").strip())

    result = _try_fetch_first_item(page_num=page_num, max_attempts=max_attempts)
    if not result:
        print("[compliant] Xato: birinchi yozuv olinmadi")
        return 1

    print("\n=== PAGE META ===")
    print(
        json.dumps(
            {
                "current_page": result.get("current_page"),
                "all_pages": result.get("all_pages"),
                "certificates_count": result.get("certificates_count"),
                "source": result.get("source"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n=== FIRST ITEM (FULL) ===")
    print(json.dumps(result.get("first_item", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
