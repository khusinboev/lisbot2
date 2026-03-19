"""
main.py — Telegram bot (aiogram 3.x)
"""

import asyncio
import logging
import os
import sqlite3
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramRetryAfter

from yigish import init_db, collect_all, filter_by_specialization, DB_PATH
from dotenv import load_dotenv
load_dotenv()

# Screenshot yuborish uchun loop reference
_main_loop: asyncio.AbstractEventLoop | None = None

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")


def _parse_allowed_users(raw: str) -> set[int]:
    parsed: set[int] = set()
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            parsed.add(int(text))
        except ValueError:
            logging.warning("ALLOWED_USERS ichida noto'g'ri qiymat tashlab yuborildi: %s", text)
    return parsed


ALLOWED_USERS = _parse_allowed_users(os.getenv("ALLOWED_USERS", ""))
SPECIALIZATION_FILTER = (os.getenv("SPECIALIZATION_FILTER", "Олий таълим хизматлари") or "Олий таълим хизматлари").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN .env da berilmagan")

AUTO_CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # 6 soat
PDF_LANGUAGE = "uz"

# “hammasini yuborish” uchun ehtiyotkor pacing
SEND_DELAY_SECONDS = 0.8          # har yuborish orasidagi delay
STATUS_EVERY_N = 10              # har nechta yuborilganda status update qilinsin
SOFT_PAUSE_EVERY_N = 50          # har 50 ta yuborilganda biroz dam
SOFT_PAUSE_SECONDS = 5

# ── Global holat ──────────────────────────────────────────────────────────────
_busy = False  # jarayon ketayaptimi

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ── Klaviatura ────────────────────────────────────────────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 Mavjudlar", callback_data="mavjudlar"),
            InlineKeyboardButton(text="🔴 Tekshirish", callback_data="tekshirish"),
        ]
    ])


# ── DB yordamchilar ───────────────────────────────────────────────────────────
def _db_certificates_count():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM certificates")
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


def _db_max_number():
    """DB dagi eng katta number"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT MAX(CAST(number AS INTEGER)) FROM certificates")
        val = cur.fetchone()[0]
        conn.close()
        return str(val) if val else None
    except Exception:
        return None


def _normalize_certificate_number(value) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return str(int(text))
    except (TypeError, ValueError):
        return text


def _db_existing_numbers() -> set[str]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT number FROM certificates WHERE number IS NOT NULL")
        rows = cur.fetchall()
        conn.close()

        numbers = set()
        for (number,) in rows:
            normalized = _normalize_certificate_number(number)
            if normalized:
                numbers.add(normalized)
        return numbers
    except Exception:
        return set()


def _db_upsert_certificates(certs: list[dict]) -> tuple[int, int]:
    inserted = 0
    skipped = 0

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        for cert in certs:
            file_uuid = cert.get("uuid")
            if not file_uuid:
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO certificates (uuid, number, tin, name, active, specialization, page_num)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    number = excluded.number,
                    tin = excluded.tin,
                    name = excluded.name,
                    active = excluded.active,
                    specialization = excluded.specialization,
                    page_num = excluded.page_num
            """, (
                file_uuid,
                cert.get("number"),
                cert.get("tin"),
                cert.get("name"),
                1 if cert.get("active") else 0,
                cert.get("specialization_oz", ""),
                cert.get("page_num", 0),
            ))
            inserted += 1

        conn.commit()
    finally:
        conn.close()

    return inserted, skipped


def _pdf_url_by_token(file_token: str) -> str:
    return f"https://doc.licenses.uz/v1/certificate/uuid/{file_token}/pdf?language={PDF_LANGUAGE}&download"


def _registry_url_by_number(number: str) -> str:
    return f"https://license.gov.uz/registry?filter%5Bnumber%5D={number}"


def _build_caption(number, name, tin, active, specialization, page_num):
    status_icon = "🟢" if active else "🔴"
    reg_url = _registry_url_by_number(number or "")
    lines = [
        f"{status_icon} <b>Litsenziya</b>",
        f"• <b>Xujjat raqami:</b> {number or ''}",
        f"• <b>Nomi:</b> {name or ''}",
        f"• <b>STIR (TIN):</b> {tin or ''}",
        f"• <b>Faol:</b> {'Ha' if active else 'Yo‘q'}",
        f"• <b>Faoliyat turi:</b> {specialization or ''}",
    ]
    if page_num is not None:
        lines.append(f"• <b>Page:</b> {page_num}")
    lines.append(f"• <b>Registry:</b> {reg_url}")
    return "\n".join(lines)


def _build_text_fallback(number, name, tin, active, specialization, page_num, reason: str | None = None):
    status_icon = "🟢" if active else "🔴"
    reg_url = _registry_url_by_number(number or "")
    parts = [f"{status_icon} <b>Litsenziya (PDF yuborilmadi)</b>"]
    if reason:
        parts.append(f"❗️ <b>Sabab:</b> {reason}")

    parts.extend([
        f"• <b>Xujjat raqami:</b> {number or ''}",
        f"• <b>Nomi:</b> {name or ''}",
        f"• <b>STIR (TIN):</b> {tin or ''}",
        f"• <b>Faol:</b> {'Ha' if active else 'Yo‘q'}",
        f"• <b>Faoliyat turi:</b> {specialization or ''}",
    ])
    if page_num is not None:
        parts.append(f"• <b>Page:</b> {page_num}")

    parts.append(f"\n🔗 <b>Ko‘rish uchun havola:</b>\n{reg_url}")
    return "\n".join(parts)


def _db_get_filtered_rows(limit: int | None = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    q = """
        SELECT uuid, number, tin, name, active, specialization, page_num, created_at
        FROM filtered_certificates
        WHERE filter_tag = ?
        ORDER BY CAST(number AS INTEGER) DESC
    """
    params = [SPECIALIZATION_FILTER]
    if limit is not None:
        q += " LIMIT ?"
        params.append(limit)

    cur.execute(q, tuple(params))
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Telegram safe send (FloodWait handling) ───────────────────────────────────
async def _safe_send_document(**kwargs):
    """
    TelegramRetryAfter (FloodWait) chiqsa: kutib qayta urinadi.
    """
    while True:
        try:
            return await bot.send_document(**kwargs)
        except TelegramRetryAfter as e:
            await asyncio.sleep(int(e.retry_after) + 1)
        except Exception:
            raise


async def _safe_send_message(**kwargs):
    while True:
        try:
            return await bot.send_message(**kwargs)
        except TelegramRetryAfter as e:
            await asyncio.sleep(int(e.retry_after) + 1)
        except Exception:
            raise


async def _safe_send_photo(chat_id: int, photo_path: str, caption: str):
    """Screenshot faylini Telegram ga yuboradi."""
    try:
        from aiogram.types import FSInputFile
        while True:
            try:
                photo = FSInputFile(photo_path)
                await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode="HTML")
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(int(e.retry_after) + 1)
            except Exception as e:
                print(f"[screenshot] send_photo xato: {e}")
                break
    finally:
        # Faylni yuborilgandan keyin o'chirish
        try:
            if os.path.exists(photo_path):
                os.remove(photo_path)
        except Exception:
            pass


def _make_screenshot_callback(chat_id: int):
    """
    kochirish_html.py ga uzatiladigan screenshot callback.
    Thread-safe: asyncio loop orqali yuboradi.
    """
    def callback(path: str, caption: str):
        if _main_loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                _safe_send_photo(chat_id, path, caption),
                _main_loop
            )
        except Exception as e:
            print(f"[screenshot] callback xato: {e}")
    return callback


async def _send_one_cert_pdf_or_fallback(chat_id: int, file_token, number, tin, name, active, specialization, page_num):
    """
    PDF yuborishga urinadi; bo'lmasa fallback matn yuboradi.
    FloodWait bo'lsa kutadi.
    """
    url = _pdf_url_by_token(file_token)
    caption = _build_caption(number, name, tin, bool(active), specialization, page_num)

    try:
        await _safe_send_document(
            chat_id=chat_id,
            document=url,
            caption=caption,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        text = _build_text_fallback(
            number=number,
            name=name,
            tin=tin,
            active=bool(active),
            specialization=specialization,
            page_num=page_num,
            reason=str(e)
        )
        try:
            await _safe_send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception:
            pass
        return False


async def _send_filtered_all(chat_id: int, rows, status_msg: Message | None = None, header_text: str | None = None):
    """
    Hammasini yuboradi. Cheklovlarga amal qiladi:
    - FloodWait -> kutib davom etadi
    - har yuborish orasida delay
    - har 50 ta yuborilganda soft pause
    - status yangilanadi
    """
    if header_text:
        try:
            await _safe_send_message(chat_id=chat_id, text=header_text, parse_mode="HTML")
        except Exception:
            pass

    if not rows:
        await _safe_send_message(chat_id=chat_id, text="⚠️ Filter bo‘yicha hech narsa topilmadi.", reply_markup=main_keyboard())
        return

    total = len(rows)
    ok_pdf = 0
    fallback = 0

    started = time.time()

    for idx, (file_token, number, tin, name, active, specialization, page_num, created_at) in enumerate(rows, 1):
        res = await _send_one_cert_pdf_or_fallback(
            chat_id=chat_id,
            file_token=file_token,
            number=number,
            tin=tin,
            name=name,
            active=active,
            specialization=specialization,
            page_num=page_num
        )
        if res:
            ok_pdf += 1
        else:
            fallback += 1

        # pacing
        await asyncio.sleep(SEND_DELAY_SECONDS)

        if idx % SOFT_PAUSE_EVERY_N == 0:
            await asyncio.sleep(SOFT_PAUSE_SECONDS)

        if status_msg and (idx % STATUS_EVERY_N == 0 or idx == total):
            elapsed = int(time.time() - started)
            try:
                await status_msg.edit_text(
                    f"⏳ Yuborilmoqda...\n\n"
                    f"• Jami: <b>{total}</b>\n"
                    f"• Yuborildi: <b>{idx}</b>\n"
                    f"• PDF: <b>{ok_pdf}</b>\n"
                    f"• Filesiz (fallback): <b>{fallback}</b>\n"
                    f"• Vaqt: <b>{elapsed}s</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await _safe_send_message(chat_id=chat_id, text="✅ Hammasi yuborildi.", reply_markup=main_keyboard())


# ── Foydalanuvchi filtri ──────────────────────────────────────────────────────
def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


# ── /start ────────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await message.answer(
        "👋 Litsenziya monitoring boti\n\nQuyidagi tugmalardan birini tanlang:",
        reply_markup=main_keyboard()
    )


# ── Busy holatda kelgan xabarlarni o'chirish ──────────────────────────────────
@dp.message()
async def handle_any_message(message: Message):
    if not is_allowed(message.from_user.id):
        return
    if _busy:
        try:
            await message.delete()
        except Exception:
            pass


# ── MAVJUDLAR ────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "mavjudlar")
async def on_mavjudlar(callback: CallbackQuery):
    global _busy

    if not is_allowed(callback.from_user.id):
        return

    if _busy:
        await callback.answer("⏳ Jarayon ketayapti, kuting...", show_alert=True)
        return

    await callback.answer()

    cert_count = _db_certificates_count()

    # agar DB bo‘sh bo‘lsa - avval collect_all
    status_msg = await callback.message.answer("⏳ Tayyorlanmoqda...")
    _busy = True
    loop = asyncio.get_event_loop()

    async def full_process():
        global _busy
        try:
            if cert_count == 0:
                # yig'ish
                await _update_status(status_msg, "📥 Ma'lumotlar yo‘q. Yig‘ish boshlanyapti...")

                def run_collect():
                    return collect_all(status_callback=None)

                success = await loop.run_in_executor(None, run_collect)
                if not success:
                    await status_msg.edit_text("❌ Yig'ishda xato yuz berdi.", reply_markup=main_keyboard())
                    return

            # filtered ni rebuild (siz so‘raganidek: umumiy bazadan qayta filterlab ko‘chiradi)
            await _update_status(status_msg, f"🔍 '{SPECIALIZATION_FILTER}' bo‘yicha saralanmoqda...")

            def rebuild_filter():
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute("DELETE FROM filtered_certificates WHERE filter_tag = ?", (SPECIALIZATION_FILTER,))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
                return filter_by_specialization(SPECIALIZATION_FILTER, status_callback=None)

            filtered_count = await loop.run_in_executor(None, rebuild_filter)

            # yuborish
            rows = _db_get_filtered_rows(limit=None)

            await status_msg.edit_text(
                f"✅ Filter tayyor.\n\n"
                f"• '{SPECIALIZATION_FILTER}': <b>{filtered_count}</b>\n"
                f"• Yuboriladigan: <b>{len(rows)}</b>\n\n"
                f"📎 Endi hammasi yuboriladi (PDF chiqmasa link bilan)...",
                parse_mode="HTML"
            )

            await _send_filtered_all(
                chat_id=callback.from_user.id,
                rows=rows,
                status_msg=status_msg,
                header_text=None
            )

        finally:
            _busy = False

    asyncio.create_task(full_process())


# ── TEKSHIRISH ────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "tekshirish")
async def on_tekshirish(callback: CallbackQuery):
    global _busy

    if not is_allowed(callback.from_user.id):
        return

    if _busy:
        await callback.answer("⏳ Jarayon ketayapti, kuting...", show_alert=True)
        return

    await callback.answer()

    cert_count = _db_certificates_count()
    if cert_count == 0:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "⚠️ Hali ma'lumot yo'q.\n\nAvval 🟢 <b>Mavjudlar</b> tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
        return

    existing_numbers = _db_existing_numbers()
    if not existing_numbers:
        await callback.message.answer("❌ Bazada taqqoslash uchun hujjat raqami topilmadi.", reply_markup=main_keyboard())
        return

    status_msg = await callback.message.answer(
        f"🔍 Yangi ma'lumotlar tekshirilmoqda...\nBazada mavjud hujjatlar bilan solishtirilmoqda.",
        parse_mode="HTML"
    )
    _busy = True

    loop = asyncio.get_event_loop()

    # Screenshot callback — scraper holatini real-time ko'rsatadi
    from kochirish_html import set_screenshot_callback
    set_screenshot_callback(_make_screenshot_callback(callback.from_user.id))

    async def check_new():
        global _busy
        try:
            await _update_status(status_msg, "🌐 Saytdan yangi ma'lumotlar yuklanmoqda...")
            from kochirish_html import fetch_new_since
            new_certs = await loop.run_in_executor(None, fetch_new_since, existing_numbers)

            if not new_certs:
                await status_msg.edit_text(
                    "✅ Yangi ma'lumot yo'q.\n\nSaytdagi yuqori sahifalarda bazada yo'q hujjat topilmadi.",
                    parse_mode="HTML",
                    reply_markup=main_keyboard()
                )
                return

            # DBga yozish
            await _update_status(status_msg, f"📥 {len(new_certs)} ta yangi yozuv saqlanmoqda...")
            inserted_count, skipped_count = _db_upsert_certificates(new_certs)

            if inserted_count == 0:
                await status_msg.edit_text(
                    "❌ Yangi yozuvlar topildi, lekin hujjat tokeni olinmadi. HTML tuzilmasi yana o'zgargan bo'lishi mumkin.",
                    reply_markup=main_keyboard()
                )
                return

            # filter
            await _update_status(status_msg, "🔍 Saralanmoqda...")
            await loop.run_in_executor(None, filter_by_specialization, SPECIALIZATION_FILTER)

            # yangilarni filtered dan topib yuborish
            new_numbers = []
            for c in new_certs:
                try:
                    new_numbers.append(int(c.get("number")))
                except Exception:
                    continue

            rows = []
            if new_numbers:
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                placeholders = ",".join(["?"] * len(new_numbers))
                cur.execute(f"""
                    SELECT uuid, number, tin, name, active, specialization, page_num, created_at
                    FROM filtered_certificates
                    WHERE filter_tag = ?
                      AND CAST(number AS INTEGER) IN ({placeholders})
                    ORDER BY CAST(number AS INTEGER) DESC
                """, (SPECIALIZATION_FILTER, *new_numbers))
                rows = cur.fetchall()
                conn.close()

            await status_msg.edit_text(
                f"✅ Tekshiruv yakunlandi!\n\n"
                f"🆕 Topildi: <b>{len(new_certs)}</b> ta\n"
                f"💾 Saqlandi: <b>{inserted_count}</b> ta\n"
                f"⚠️ UUID topilmagan: <b>{skipped_count}</b> ta\n"
                f"📎 Endi yangilar yuboriladi (PDF chiqmasa link bilan)...",
                parse_mode="HTML",
                reply_markup=main_keyboard()
            )

            await _send_filtered_all(
                chat_id=callback.from_user.id,
                rows=rows,
                status_msg=status_msg,
                header_text="🆕 <b>Yangi litsenziyalar:</b>"
            )

        except Exception as e:
            await status_msg.edit_text(f"❌ Xatolik: {e}", reply_markup=main_keyboard())
        finally:
            _busy = False

    asyncio.create_task(check_new())


# ── Autocheck loop ────────────────────────────────────────────────────────────
async def _auto_check_loop():
    await asyncio.sleep(10)

    while True:
        try:
            if not ALLOWED_USERS:
                await asyncio.sleep(AUTO_CHECK_INTERVAL_SECONDS)
                continue

            global _busy
            if _busy:
                await asyncio.sleep(60)
                continue

            if _db_certificates_count() == 0:
                await asyncio.sleep(AUTO_CHECK_INTERVAL_SECONDS)
                continue

            existing_numbers = _db_existing_numbers()
            if not existing_numbers:
                await asyncio.sleep(AUTO_CHECK_INTERVAL_SECONDS)
                continue

            _busy = True
            loop = asyncio.get_event_loop()

            from kochirish_html import fetch_new_since
            new_certs = await loop.run_in_executor(None, fetch_new_since, existing_numbers)

            if not new_certs:
                _busy = False
                await asyncio.sleep(AUTO_CHECK_INTERVAL_SECONDS)
                continue

            # DBga yozish
            inserted_count, skipped_count = _db_upsert_certificates(new_certs)
            if inserted_count == 0:
                _busy = False
                await asyncio.sleep(AUTO_CHECK_INTERVAL_SECONDS)
                continue

            # filter
            await loop.run_in_executor(None, filter_by_specialization, SPECIALIZATION_FILTER)

            # yangilarni filtered dan topish
            new_numbers = []
            for c in new_certs:
                try:
                    new_numbers.append(int(c.get("number")))
                except Exception:
                    continue

            rows = []
            if new_numbers:
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                placeholders = ",".join(["?"] * len(new_numbers))
                cur.execute(f"""
                    SELECT uuid, number, tin, name, active, specialization, page_num, created_at
                    FROM filtered_certificates
                    WHERE filter_tag = ?
                      AND CAST(number AS INTEGER) IN ({placeholders})
                    ORDER BY CAST(number AS INTEGER) DESC
                """, (SPECIALIZATION_FILTER, *new_numbers))
                rows = cur.fetchall()
                conn.close()

            # userlarga yuborish
            for uid in ALLOWED_USERS:
                try:
                    await _safe_send_message(
                        chat_id=uid,
                        text=f"🕒 <b>AutoCheck</b>\n🆕 Yangi yozuvlar topildi: <b>{len(new_certs)}</b> ta\n"
                            f"💾 Saqlandi: <b>{inserted_count}</b> ta\n"
                            f"⚠️ UUID topilmagan: <b>{skipped_count}</b> ta\n"
                             f"📎 Yuborilmoqda (PDF chiqmasa link bilan)...",
                        parse_mode="HTML"
                    )
                    await _send_filtered_all(
                        chat_id=uid,
                        rows=rows,
                        status_msg=None,
                        header_text="🆕 <b>AutoCheck: yangi litsenziyalar</b>"
                    )
                except Exception:
                    pass

            _busy = False

        except Exception:
            try:
                _busy = False
            except Exception:
                pass

        await asyncio.sleep(AUTO_CHECK_INTERVAL_SECONDS)


# ── Jonli status yangilash ────────────────────────────────────────────────────
async def _update_status(message: Message, text: str):
    try:
        await message.edit_text(f"⏳ {text}", parse_mode="HTML")
    except Exception:
        pass


# ── Startup ───────────────────────────────────────────────────────────────────
async def on_startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    print("[main] Bot ishga tushmoqda...")
    init_db()
    print("[main] DB tayyor")
    print(f"[main] Ruxsat etilgan userlar: {ALLOWED_USERS}")

    asyncio.create_task(_auto_check_loop())


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())