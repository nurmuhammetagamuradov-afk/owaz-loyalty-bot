# -*- coding: utf-8 -*-
"""Отрисовка карты лояльности Owaz."""

import io
import os
from PIL import Image, ImageDraw, ImageFilter

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

BG_TOP = (18, 17, 16)
BG_BOTTOM = (38, 33, 28)
CARD = (247, 244, 238)
GOLD = (186, 149, 92)
GOLD_SOFT = (212, 184, 136)
INK = (34, 32, 29)
MUTED = (132, 126, 116)


def _font(size, bold=False):
    from PIL import ImageFont
    names = (["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold
             else ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf"])
    for n in names:
        for base in (FONT_DIR, os.path.dirname(os.path.abspath(__file__)),
                     "/usr/share/fonts/truetype/dejavu", "."):
            p = os.path.join(base, n)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
    return ImageFont.load_default()


def _gradient(w, h):
    grad = Image.new("RGB", (1, h))
    d = ImageDraw.Draw(grad)
    for y in range(h):
        t = y / max(1, h - 1)
        d.point((0, y), fill=(
            int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
        ))
    return grad.resize((w, h))


def _shadow(img, box, radius, blur=26, alpha=120):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(box, radius=radius, fill=(0, 0, 0, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    img.paste(Image.alpha_composite(img.convert("RGBA"), sh).convert("RGB"), (0, 0))


def render(card_id, name, visits, level, discount, next_info,
           cafe_name="OWAZ", qr_image=None):
    W, H = 940, 1500
    img = _gradient(W, H)
    d = ImageDraw.Draw(img)

    # --- Шапка ---
    f_logo = _font(70, bold=True)
    d.text((W // 2, 78), cafe_name, font=f_logo, fill=CARD, anchor="mt")
    f_sub = _font(22)
    d.text((W // 2, 166), "C  O  F  F  E  E", font=f_sub, fill=GOLD, anchor="mt")
    d.line([(W // 2 - 190, 152), (W // 2 - 80, 152)], fill=GOLD, width=1)
    d.line([(W // 2 + 80, 152), (W // 2 + 190, 152)], fill=GOLD, width=1)

    # --- Карточка ---
    cx, cy = 58, 250
    cw, ch = W - 116, 1080
    _shadow(img, [cx, cy + 16, cx + cw, cy + ch], 46)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=46, fill=CARD)

    # Полоса уровня
    bar_h = 132
    band = Image.new("RGB", (cw, bar_h), GOLD)
    bd = ImageDraw.Draw(band)
    for i in range(cw):
        t = i / cw
        bd.line([(i, 0), (i, bar_h)], fill=(
            int(GOLD[0] + (GOLD_SOFT[0] - GOLD[0]) * t),
            int(GOLD[1] + (GOLD_SOFT[1] - GOLD[1]) * t),
            int(GOLD[2] + (GOLD_SOFT[2] - GOLD[2]) * t),
        ))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw, ch], radius=46, fill=255)
    img.paste(band, (cx, cy + 96), mask.crop((0, 96, cw, 96 + bar_h)))
    d = ImageDraw.Draw(img)

    f_level = _font(40, bold=True)
    d.text((cx + cw // 2, cy + 96 + bar_h // 2), level, font=f_level,
           fill=(255, 253, 248), anchor="mm")

    # Имя гостя сверху
    f_cap = _font(20)
    f_name = _font(30, bold=True)
    d.text((cx + 44, cy + 30), "KART EÝESI / ГОСТЬ", font=f_cap, fill=MUTED)
    d.text((cx + 44, cy + 56), name[:22], font=f_name, fill=INK)

    # Показатели
    row_y = cy + 96 + bar_h + 44
    f_big = _font(52, bold=True)
    d.text((cx + 44, row_y), "WIZITLER / ВИЗИТЫ", font=f_cap, fill=MUTED)
    d.text((cx + 44, row_y + 28), str(visits), font=f_big, fill=INK)

    d.text((cx + cw - 44, row_y), "ARZANLAŞYK / СКИДКА", font=f_cap, fill=MUTED, anchor="rt")
    d.text((cx + cw - 44, row_y + 28), f"{discount}%", font=f_big, fill=GOLD, anchor="rt")

    d.line([(cx + 44, row_y + 108), (cx + cw - 44, row_y + 108)], fill=(226, 221, 211), width=2)

    # --- QR ---
    qr_panel = 560
    qx = cx + (cw - qr_panel) // 2
    qy = row_y + 140
    d.rounded_rectangle([qx, qy, qx + qr_panel, qy + qr_panel], radius=26, fill=(255, 255, 255))
    if qr_image is not None:
        q = qr_image.convert("RGB").resize((qr_panel - 44, qr_panel - 44), Image.NEAREST)
        img.paste(q, (qx + 22, qy + 22))
    d = ImageDraw.Draw(img)

    # Уголки-рамка
    corner, th = 44, 5
    for ox, oy, dx, dy in ((qx - 14, qy - 14, 1, 1), (qx + qr_panel + 14, qy - 14, -1, 1),
                           (qx - 14, qy + qr_panel + 14, 1, -1),
                           (qx + qr_panel + 14, qy + qr_panel + 14, -1, -1)):
        d.line([(ox, oy), (ox + corner * dx, oy)], fill=GOLD, width=th)
        d.line([(ox, oy), (ox, oy + corner * dy)], fill=GOLD, width=th)

    f_num = _font(22)
    d.text((cx + cw // 2, qy + qr_panel + 52), f"№ {card_id}", font=f_num,
           fill=MUTED, anchor="mm")

    # --- Прогресс к следующему уровню ---
    py = cy + ch + 58
    f_hint = _font(26)
    f_hint_s = _font(23)
    if next_info:
        need, nname, ndisc, done, total = next_info
        pw = cw - 40
        px = (W - pw) // 2
        d.rounded_rectangle([px, py, px + pw, py + 14], radius=7, fill=(58, 52, 46))
        filled = int(pw * min(1.0, done / max(1, total)))
        if filled > 14:
            d.rounded_rectangle([px, py, px + filled, py + 14], radius=7, fill=GOLD)
        d.text((W // 2, py + 40), f"Ýene {need} wizit → {nname} · {ndisc}%",
               font=f_hint, fill=GOLD_SOFT, anchor="mt")
        d.text((W // 2, py + 78), f"Ещё {need} визитов до уровня «{nname}» — скидка {ndisc}%",
               font=f_hint_s, fill=(150, 144, 133), anchor="mt")
    else:
        d.text((W // 2, py + 20), "Iň ýokary dereje / Максимальный уровень",
               font=f_hint, fill=GOLD_SOFT, anchor="mt")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
