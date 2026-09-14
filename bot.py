# -*- coding: utf-8 -*-
"""
Owaz Coffee — бот карты лояльности.
Гость получает виртуальную карту с QR-кодом.
Кассир сканирует QR телефоном и начисляет визит.
"""

import os
import io
import sqlite3
import logging
from datetime import datetime

import qrcode
from PIL import Image, ImageDraw, ImageFont

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
import asyncio

logging.basicConfig(level=logging.INFO)

# ---------- НАСТРОЙКИ ----------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Owaz_Coffee_Bot")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
CAFE_NAME = os.environ.get("CAFE_NAME", "OWAZ")

DB_DIR = os.environ.get("DB_DIR", "/data")
if not os.path.isdir(DB_DIR):
    DB_DIR = "."
DB_PATH = os.path.join(DB_DIR, "owaz_loyalty.db")

# Уровни: (минимум визитов, название, скидка %)
LEVELS = [
    (100, "VIP OWAZ", 20),
    (60, "ZAWSEGDATAÝ", 15),
    (30, "HEMIŞELIK MYHMAN", 10),
    (10, "OWAZ DOSTY", 5),
    (0, "MYHMAN", 0),
]


def get_level(visits: int):
    for min_v, name, disc in LEVELS:
        if visits >= min_v:
            return name, disc
    return "MYHMAN", 0


def next_level_info(visits: int):
    """Сколько визитов до следующего уровня."""
    ups = sorted([l for l in LEVELS if l[0] > visits], key=lambda x: x[0])
    if not ups:
        return None
    min_v, name, disc = ups[0]
    return min_v - visits, name, disc


# ---------- БАЗА ДАННЫХ ----------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS guests (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            visits INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            added_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS visits_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_id INTEGER,
            staff_id INTEGER,
            change INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_guest(tg_id):
    conn = db()
    row = conn.execute("SELECT * FROM guests WHERE tg_id=?", (tg_id,)).fetchone()
    conn.close()
    return row


def create_guest(tg_id, name):
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO guests (tg_id, name, visits, created_at) VALUES (?,?,0,?)",
        (tg_id, name, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def set_phone(tg_id, phone):
    conn = db()
    conn.execute("UPDATE guests SET phone=? WHERE tg_id=?", (phone, tg_id))
    conn.commit()
    conn.close()


def change_visits(guest_id, staff_id, delta):
    conn = db()
    conn.execute(
        "UPDATE guests SET visits = MAX(0, visits + ?) WHERE tg_id=?", (delta, guest_id)
    )
    conn.execute(
        "INSERT INTO visits_log (guest_id, staff_id, change, created_at) VALUES (?,?,?,?)",
        (guest_id, staff_id, delta, datetime.now().isoformat()),
    )
    conn.commit()
    row = conn.execute("SELECT visits FROM guests WHERE tg_id=?", (guest_id,)).fetchone()
    conn.close()
    return row["visits"] if row else 0


def is_staff(tg_id):
    if tg_id == ADMIN_ID:
        return True
    conn = db()
    row = conn.execute("SELECT 1 FROM staff WHERE tg_id=?", (tg_id,)).fetchone()
    conn.close()
    return row is not None


def add_staff(tg_id, name):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO staff (tg_id, name, added_at) VALUES (?,?,?)",
        (tg_id, name, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def remove_staff(tg_id):
    conn = db()
    conn.execute("DELETE FROM staff WHERE tg_id=?", (tg_id,))
    conn.commit()
    conn.close()


def stats():
    conn = db()
    total = conn.execute("SELECT COUNT(*) c FROM guests").fetchone()["c"]
    visits = conn.execute("SELECT COALESCE(SUM(visits),0) s FROM guests").fetchone()["s"]
    today = datetime.now().strftime("%Y-%m-%d")
    today_v = conn.execute(
        "SELECT COUNT(*) c FROM visits_log WHERE change>0 AND created_at LIKE ?",
        (today + "%",),
    ).fetchone()["c"]
    conn.close()
    return total, visits, today_v


# ---------- КАРТИНКА КАРТЫ ----------

def load_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_card(card_id, name, visits):
    """Рисует карту лояльности как картинку."""
    level, discount = get_level(visits)

    W, H = 900, 1300
    bg = (28, 26, 24)
    card_bg = (245, 242, 236)
    accent = (176, 141, 87)

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    # Заголовок кофейни
    f_logo = load_font(64, bold=True)
    d.text((W // 2, 70), CAFE_NAME, font=f_logo, fill=card_bg, anchor="mt")
    f_sub = load_font(24)
    d.text((W // 2, 150), "C O F F E E", font=f_sub, fill=accent, anchor="mt")

    # Белая карточка
    cx, cy, cw, ch = 70, 220, W - 140, 820
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=40, fill=card_bg)

    # Верхняя полоса уровня
    d.rounded_rectangle([cx, cy + 90, cx + cw, cy + 260], radius=0, fill=accent)
    f_level = load_font(42, bold=True)
    d.text((cx + cw // 2, cy + 175), level, font=f_level, fill=card_bg, anchor="mm")

    # Визиты сверху справа
    f_small = load_font(22)
    f_num = load_font(40, bold=True)
    d.text((cx + cw - 40, cy + 25), "WIZITLER / ВИЗИТЫ", font=f_small, fill=(120, 115, 105), anchor="rt")
    d.text((cx + cw - 40, cy + 55), str(visits), font=f_num, fill=(40, 38, 35), anchor="rt")

    # Скидка и имя
    d.text((cx + 40, cy + 300), "ARZANLAŞYK / СКИДКА", font=f_small, fill=(120, 115, 105))
    d.text((cx + 40, cy + 335), f"{discount}%", font=f_num, fill=(40, 38, 35))

    d.text((cx + cw - 40, cy + 300), "KART EÝESI / ГОСТЬ", font=f_small, fill=(120, 115, 105), anchor="rt")
    f_name = load_font(32, bold=True)
    d.text((cx + cw - 40, cy + 335), name[:20], font=f_name, fill=(40, 38, 35), anchor="rt")

    # QR-код
    qr = qrcode.QRCode(box_size=10, border=1)
    qr.add_data(f"https://t.me/{BOT_USERNAME}?start=g{card_id}")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_size = 330
    qr_img = qr_img.resize((qr_size, qr_size))
    img.paste(qr_img, (cx + (cw - qr_size) // 2, cy + 430))

    f_card = load_font(20)
    d.text((cx + cw // 2, cy + 780), f"№ {card_id}", font=f_card,
           fill=(120, 115, 105), anchor="mm")

    # Подсказка про следующий уровень
    nxt = next_level_info(visits)
    f_hint = load_font(26)
    if nxt:
        need, nname, ndisc = nxt
        hint = f"Ýene {need} wizit → {nname} ({ndisc}%)"
        hint2 = f"Ещё {need} визитов до уровня {nname} — скидка {ndisc}%"
    else:
        hint = "Iň ýokary dereje!"
        hint2 = "Максимальный уровень достигнут!"
    d.text((W // 2, cy + ch + 50), hint, font=f_hint, fill=accent, anchor="mt")
    d.text((W // 2, cy + ch + 95), hint2, font=f_hint, fill=(170, 165, 155), anchor="mt")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def render_card(tg_id, name, visits):
    return make_card(tg_id, name, visits)


# ---------- КЛАВИАТУРЫ ----------

def guest_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💳 Meniň kartym / Моя карта")],
            [KeyboardButton(text="ℹ️ Şertler / Условия")],
        ],
        resize_keyboard=True,
    )


def staff_panel_kb(guest_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Wizit goş / Начислить визит",
                                  callback_data=f"add:{guest_id}")],
            [InlineKeyboardButton(text="➖ Ýalňyşlyk / Отменить визит",
                                  callback_data=f"sub:{guest_id}")],
        ]
    )


# ---------- БОТ ----------

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    args = message.text.split(maxsplit=1)
    payload = args[1].strip() if len(args) > 1 else ""

    # Кассир отсканировал QR гостя
    if payload.startswith("g") and payload[1:].isdigit():
        guest_id = int(payload[1:])
        if is_staff(message.from_user.id) and guest_id != message.from_user.id:
            g = get_guest(guest_id)
            if not g:
                await message.answer("Myhman tapylmady / Гость не найден.")
                return
            level, disc = get_level(g["visits"])
            await message.answer(
                f"👤 <b>{g['name']}</b>\n"
                f"Wizitler / Визиты: <b>{g['visits']}</b>\n"
                f"Dereje / Уровень: <b>{level}</b>\n"
                f"Arzanlaşyk / Скидка: <b>{disc}%</b>",
                parse_mode="HTML",
                reply_markup=staff_panel_kb(guest_id),
            )
            return

    # Обычный гость
    name = message.from_user.full_name or "Myhman"
    create_guest(message.from_user.id, name)
    await message.answer(
        f"Salam, {name}! 👋\n\n"
        f"{CAFE_NAME} kofehanasynyň wepalylyk kartyna hoş geldiňiz.\n"
        f"Добро пожаловать в клуб гостей {CAFE_NAME}!\n\n"
        "Her gezek gelendeǹizde kassira QR kodyňyzy görkeziň — "
        "wizit ýazylar we arzanlaşyk ýygnalar.\n"
        "Показывайте QR-код кассиру при каждом визите — "
        "визиты копятся, скидка растёт.",
        reply_markup=guest_kb(),
    )
    await send_card(message.from_user.id, message)


async def send_card(tg_id, message: Message):
    g = get_guest(tg_id)
    if not g:
        create_guest(tg_id, message.from_user.full_name or "Myhman")
        g = get_guest(tg_id)
    png = render_card(tg_id, g["name"], g["visits"])
    await message.answer_photo(
        BufferedInputFile(png, filename="card.png"),
        caption="👆 QR kody kassira görkeziň / Покажите QR-код кассиру",
    )


@dp.message(F.text.contains("Моя карта") | F.text.contains("kartym"))
async def my_card(message: Message):
    await send_card(message.from_user.id, message)


@dp.message(F.text.contains("Условия") | F.text.contains("Şertler"))
async def rules(message: Message):
    text = f"<b>{CAFE_NAME} — wepalylyk kartasy / карта лояльности</b>\n\n"
    for min_v, name, disc in sorted(LEVELS, key=lambda x: x[0]):
        if disc == 0:
            text += f"• <b>{name}</b> — {min_v}+ wizit / визитов — ýygnaýarsyňyz\n"
        else:
            text += f"• <b>{name}</b> — {min_v}+ wizit / визитов — <b>{disc}%</b>\n"
    text += ("\nBir gezek gelmek = 1 wizit.\nОдин визит = 1 отметка.\n"
             "Arzanlaşyk awtomatiki işleýär.\nСкидка применяется автоматически.")
    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data.startswith("add:"))
async def cb_add(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Rugsat ýok / Нет доступа", show_alert=True)
        return
    guest_id = int(call.data.split(":")[1])
    old = get_guest(guest_id)
    old_level, _ = get_level(old["visits"])
    new_visits = change_visits(guest_id, call.from_user.id, +1)
    level, disc = get_level(new_visits)

    await call.message.edit_text(
        f"✅ Wizit ýazyldy / Визит начислен\n\n"
        f"👤 <b>{old['name']}</b>\n"
        f"Wizitler / Визиты: <b>{new_visits}</b>\n"
        f"Dereje / Уровень: <b>{level}</b>\n"
        f"Arzanlaşyk / Скидка: <b>{disc}%</b>",
        parse_mode="HTML",
        reply_markup=staff_panel_kb(guest_id),
    )
    await call.answer("Wizit +1")

    # Уведомляем гостя
    try:
        if level != old_level:
            await bot.send_message(
                guest_id,
                f"🎉 Gutlaýarys! Täze dereje: <b>{level}</b>\n"
                f"Поздравляем! Новый уровень: <b>{level}</b> — скидка <b>{disc}%</b>",
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                guest_id,
                f"✅ Wizit ýazyldy / Визит засчитан.\n"
                f"Jemi / Всего: <b>{new_visits}</b> · Arzanlaşyk / Скидка: <b>{disc}%</b>",
                parse_mode="HTML",
            )
    except Exception as e:
        logging.warning(f"Не смог уведомить гостя: {e}")


@dp.callback_query(F.data.startswith("sub:"))
async def cb_sub(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Rugsat ýok / Нет доступа", show_alert=True)
        return
    guest_id = int(call.data.split(":")[1])
    g = get_guest(guest_id)
    new_visits = change_visits(guest_id, call.from_user.id, -1)
    level, disc = get_level(new_visits)
    await call.message.edit_text(
        f"↩️ Wizit yzyna alyndy / Визит отменён\n\n"
        f"👤 <b>{g['name']}</b>\n"
        f"Wizitler / Визиты: <b>{new_visits}</b>\n"
        f"Dereje / Уровень: <b>{level}</b> · {disc}%",
        parse_mode="HTML",
        reply_markup=staff_panel_kb(guest_id),
    )
    await call.answer("Wizit -1")


# ---------- АДМИН ----------

@dp.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Siziň ID / Ваш ID: <code>{message.from_user.id}</code>",
                         parse_mode="HTML")


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    total, visits, today_v = stats()
    conn = db()
    staff_rows = conn.execute("SELECT * FROM staff").fetchall()
    conn.close()
    slist = "\n".join([f"• {s['name']} — <code>{s['tg_id']}</code>" for s in staff_rows]) or "— нет —"
    await message.answer(
        f"<b>Панель администратора</b>\n\n"
        f"Гостей всего: <b>{total}</b>\n"
        f"Визитов всего: <b>{visits}</b>\n"
        f"Визитов сегодня: <b>{today_v}</b>\n\n"
        f"<b>Кассиры:</b>\n{slist}\n\n"
        f"Команды:\n"
        f"<code>/addstaff ID Имя</code> — добавить кассира\n"
        f"<code>/delstaff ID</code> — убрать кассира\n"
        f"<code>/id</code> — узнать свой Telegram ID",
        parse_mode="HTML",
    )


@dp.message(Command("addstaff"))
async def cmd_addstaff(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Формат: /addstaff 123456789 Ислам")
        return
    name = parts[2] if len(parts) > 2 else "Kassir"
    add_staff(int(parts[1]), name)
    await message.answer(f"✅ Кассир {name} добавлен.")


@dp.message(Command("delstaff"))
async def cmd_delstaff(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Формат: /delstaff 123456789")
        return
    remove_staff(int(parts[1]))
    await message.answer("✅ Кассир удалён.")


async def main():
    init_db()
    logging.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
