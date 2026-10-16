"""개발용: 앱 아이콘 / 시작 화면 / 탭 아이콘 PNG 생성.

Pillow 가 필요하며 앱 실행·APK 에는 필요 없다. 생성된 assets/*.png 만 앱에 포함된다.
    python tools/make_assets.py
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
FONT_BOLD = os.path.join(ROOT, "fonts", "Pretendard-Bold.otf")
SS = 4  # 슈퍼샘플링 배율 (크게 그린 뒤 축소해 안티앨리어싱)

PRIMARY = (49, 130, 246)
BG = (242, 244, 246)
TEXT = (25, 31, 40)
SUB = (107, 118, 132)
BALLS = [((251, 196, 0), "7"), ((255, 114, 114), "23"), ((176, 216, 64), "45")]


def font(size):
    return ImageFont.truetype(FONT_BOLD, int(size))


def canvas(w, h, fill=(0, 0, 0, 0)):
    img = Image.new("RGBA", (w * SS, h * SS), fill)
    return img, ImageDraw.Draw(img, "RGBA")


def finish(img, w, h, name):
    img.resize((w, h), Image.LANCZOS).save(os.path.join(OUT, name))
    print("wrote", name)


def draw_ball(d, cx, cy, r, color, text, ring=(255, 255, 255, 255)):
    d.ellipse((cx - r, cy - r + r * 0.08, cx + r, cy + r + r * 0.08), fill=(0, 0, 0, 45))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (255,), outline=ring,
              width=max(1, int(r * 0.09)))
    d.text((cx, cy + r * 0.02), text, font=font(r * 0.8), fill="white", anchor="mm")


def draw_ball_cluster(d, cx, cy, size):
    r = size * 0.2
    spots = [(cx, cy - size * 0.14), (cx - size * 0.16, cy + size * 0.12),
             (cx + size * 0.16, cy + size * 0.12)]
    for (x, y), (color, text) in zip(spots, BALLS):
        draw_ball(d, x, y, r, color, text)


def make_icon(size=512):
    img, d = canvas(size, size)
    S = size * SS
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=S * 0.22, fill=PRIMARY + (255,))
    draw_ball_cluster(d, S / 2, S / 2, S)
    finish(img, size, size, "icon.png")


def make_presplash(size=1024):
    img, d = canvas(size, size, BG + (255,))
    S = size * SS
    draw_ball_cluster(d, S / 2, S * 0.40, S * 0.62)
    d.text((S / 2, S * 0.74), "로또 6/45", font=font(S * 0.085), fill=TEXT, anchor="mm")
    d.text((S / 2, S * 0.83), "오프라인 번호 추천", font=font(S * 0.042), fill=SUB, anchor="mm")
    finish(img, size, size, "presplash.png")


def make_tab_icons(size=96):
    # 흰색으로 그리고 Kivy Image.color 로 활성/비활성 색을 입힌다
    white = (255, 255, 255, 255)
    S = size * SS

    img, d = canvas(size, size)
    r = S * 0.17
    for x, y in [(S * 0.5, S * 0.3), (S * 0.29, S * 0.68), (S * 0.71, S * 0.68)]:
        d.ellipse((x - r, y - r, x + r, y + r), fill=white)
    finish(img, size, size, "tab_recommend.png")

    img, d = canvas(size, size)
    w = int(S * 0.085)
    d.rounded_rectangle((S * 0.18, S * 0.1, S * 0.82, S * 0.9), radius=S * 0.12,
                        outline=white, width=w)
    for y in (0.34, 0.5, 0.66):
        d.rounded_rectangle((S * 0.33, S * y - w / 2, S * 0.67, S * y + w / 2),
                            radius=w / 2, fill=white)
    finish(img, size, size, "tab_manage.png")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    make_icon()
    make_presplash()
    make_tab_icons()
