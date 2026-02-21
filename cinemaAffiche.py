import io
import os
import math
import subprocess
import logging
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader


# -----------------------------
# Paths + logging (cross-platform)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
ICONS_DIR = BASE_DIR / "icons"
FONTS_DIR = BASE_DIR / "fonts"   # optional: drop Inter-Regular.ttf here
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
ICONS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(LOGS_DIR / "cinema_affiche.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

APP_TITLE = "Cinema Central — Affiche Generator"

# layout slots by your rules
MAX_TOP = 5
MAX_BOTTOM = 10

# A4 @ 300 DPI
DPI = 300
A4_W_PX = int(8.27 * DPI)   # 2481
A4_H_PX = int(11.69 * DPI)  # 3507

# Layout tuning
TOP_POSTERS_H = int(A4_H_PX * 0.22)

# Big, readable typography => bigger header/rows too
HEADER1_H_PX = 140
HEADER2_H_PX = 190
ROW_H_TARGET = 78
ROW_H_MIN = 54

BOTTOM_MIN_OK = int(A4_H_PX * 0.14)
BOTTOM_TARGET_MULT = 1.55

HEADER_TEXT_Y_BIAS = -2
CELL_TEXT_Y_BIAS = -1

RED_3D = (200, 0, 0)

DUTCH_MONTHS = {
    1: "Jan.", 2: "Feb.", 3: "Mrt.", 4: "Apr.", 5: "Mei", 6: "Jun.",
    7: "Jul.", 8: "Aug.", 9: "Sep.", 10: "Okt.", 11: "Nov.", 12: "Dec."
}
DUTCH_DAYS_SHORT = ["Ma", "Di", "Woe", "Don", "Vrij", "Zat", "Zon"]


def top_cols_for_rows(n_rows: int) -> int:
    return 4 if n_rows <= 12 else 5


def bottom_cols_for_rows(n_rows: int) -> int:
    return 4 if n_rows <= 12 else 5


def _try_font_by_name(name: str, size: int) -> Optional[ImageFont.FreeTypeFont]:
    try:
        return ImageFont.truetype(name, size=size)
    except Exception:
        return None


def _try_font_file(path: Path, size: int) -> Optional[ImageFont.FreeTypeFont]:
    try:
        return ImageFont.truetype(str(path), size=size)
    except Exception:
        return None


def load_modern_font(size: int) -> ImageFont.ImageFont:
    """
    Modern, elegant, no bold:
    - Prefer project fonts in ./fonts (recommended: Inter-Regular.ttf)
    - macOS fallback: SF Pro / Avenir Next / Helvetica Neue
    - cross-platform fallback: DejaVuSans / Arial
    """
    # 1) Project fonts (best: consistent across OS)
    for fn in [
        "Inter-Regular.ttf",
        "Inter.ttf",
        "SourceSans3-Regular.ttf",
        "SourceSansPro-Regular.ttf",
        "NotoSans-Regular.ttf",
        "NotoSans.ttf",
    ]:
        p = FONTS_DIR / fn
        if p.exists():
            f = _try_font_file(p, size)
            if f:
                return f

    # 2) macOS fonts
    for name in [
        "SF Pro Display Regular",
        "SF Pro Text Regular",
        "Avenir Next Regular",
        "Helvetica Neue",
    ]:
        f = _try_font_by_name(name, size)
        if f:
            return f

    # 3) Common fallbacks
    for name in ["DejaVuSans.ttf", "Arial.ttf"]:
        f = _try_font_by_name(name, size)
        if f:
            return f

    return ImageFont.load_default()


@dataclass
class FilmRow:
    name: str = "NAAM"
    duration: str = ""
    version: str = "OV"
    is_3d: bool = False
    good_icons: List[str] = field(default_factory=list)
    cells: List[str] = field(default_factory=lambda: [""] * 14)


@dataclass
class PosterLayout:
    top: List[str] = field(default_factory=lambda: [""] * MAX_TOP)
    bottom: List[str] = field(default_factory=lambda: [""] * MAX_BOTTOM)


@dataclass
class AfficheState:
    start_date: str = ""
    films: List[FilmRow] = field(default_factory=list)
    posters: PosterLayout = field(default_factory=PosterLayout)


def parse_date_iso(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def is_wednesday(d: dt.date) -> bool:
    return d.weekday() == 2


def two_week_dates_from_start(start: dt.date) -> List[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(14)]


def header_text(start: dt.date) -> str:
    end = start + dt.timedelta(days=13)
    return f"Woensdag {start.day} {DUTCH_MONTHS[start.month]} tot Dinsdag {end.day} {DUTCH_MONTHS[end.month]} {end.year}"


def day_col_label(d: dt.date) -> str:
    day = DUTCH_DAYS_SHORT[d.weekday()]
    return f"{day}\n{d.day}\n{DUTCH_MONTHS[d.month]}"


# -----------------------------
# SVG + ImageMagick support for icons
# -----------------------------
def _try_svg_to_png_bytes(svg_path: Path, w: int, h: int) -> Optional[bytes]:
    try:
        import cairosvg
    except Exception:
        return None
    try:
        return cairosvg.svg2png(url=str(svg_path), output_width=w, output_height=h)
    except Exception:
        return None


def rasterize_with_imagemagick_to_png(path: Path, size_px: int) -> Optional[bytes]:
    cmds = [
        ["magick", str(path), "-resize", f"{size_px}x{size_px}", "png:-"],
        ["convert", str(path), "-resize", f"{size_px}x{size_px}", "png:-"],
    ]
    for cmd in cmds:
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return p.stdout
        except Exception:
            continue
    return None


class AfficheRenderer:
    def __init__(self, icons_dir: Path):
        self.icons_dir = icons_dir

        # big, readable, elegant, no bold
        self.font_header = load_modern_font(52)
        self.font_colhdr = load_modern_font(30)
        self.font_colhdr_small = load_modern_font(26)
        self.font_cell = load_modern_font(28)

        self._icons_cache: Dict[str, Image.Image] = {}

    @staticmethod
    def _split_units(total: int, n: int) -> List[int]:
        base = total // n
        arr = [base] * n
        arr[-1] += total - base * n
        return arr

    @staticmethod
    def _draw_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        img = img.convert("RGB")
        sw, sh = img.size
        scale = max(target_w / sw, target_h / sh)
        nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
        resized = img.resize((nw, nh), Image.LANCZOS)
        left = (nw - target_w) // 2
        top = (nh - target_h) // 2
        return resized.crop((left, top, left + target_w, top + target_h))

    def _draw_contain_edge_fill(self, img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """Full poster visible + edge-fill (no blur, no black bars)."""
        img = img.convert("RGB")
        sw, sh = img.size
        scale = min(target_w / sw, target_h / sh)
        nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
        fg = img.resize((nw, nh), Image.LANCZOS)

        bg = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        x_off = (target_w - nw) // 2
        y_off = (target_h - nh) // 2
        bg.paste(fg, (x_off, y_off))

        if nw < target_w:
            left_w = x_off
            right_w = target_w - (x_off + nw)
            if left_w > 0:
                left_strip = fg.crop((0, 0, 1, nh)).resize((left_w, nh), Image.LANCZOS)
                bg.paste(left_strip, (0, y_off))
            if right_w > 0:
                right_strip = fg.crop((nw - 1, 0, nw, nh)).resize((right_w, nh), Image.LANCZOS)
                bg.paste(right_strip, (x_off + nw, y_off))

            if nh < target_h:
                top_h = y_off
                bot_h = target_h - (y_off + nh)
                if top_h > 0:
                    top_band = bg.crop((0, y_off, target_w, y_off + 1)).resize((target_w, top_h), Image.LANCZOS)
                    bg.paste(top_band, (0, 0))
                if bot_h > 0:
                    bot_band = bg.crop((0, y_off + nh - 1, target_w, y_off + nh)).resize((target_w, bot_h), Image.LANCZOS)
                    bg.paste(bot_band, (0, y_off + nh))
        elif nh < target_h:
            top_h = y_off
            bot_h = target_h - (y_off + nh)
            if top_h > 0:
                top_strip = fg.crop((0, 0, nw, 1)).resize((nw, top_h), Image.LANCZOS)
                bg.paste(top_strip, (x_off, 0))
            if bot_h > 0:
                bot_strip = fg.crop((0, nh - 1, nw, nh)).resize((nw, bot_h), Image.LANCZOS)
                bg.paste(bot_strip, (x_off, y_off + nh))

            if x_off > 0:
                left_band = bg.crop((x_off, 0, x_off + 1, target_h)).resize((x_off, target_h), Image.LANCZOS)
                bg.paste(left_band, (0, 0))
            right_w = target_w - (x_off + nw)
            if right_w > 0:
                right_band = bg.crop((x_off + nw - 1, 0, x_off + nw, target_h)).resize((right_w, target_h), Image.LANCZOS)
                bg.paste(right_band, (x_off + nw, 0))

        return bg

    def _draw_poster_best_fit_top(self, img: Image.Image, w: int, h: int) -> Image.Image:
        """
        TOP: contain unless it's too empty -> cover.
        """
        img = img.convert("RGB")
        sw, sh = img.size
        scale_contain = min(w / sw, h / sh)
        nw, nh = max(1, int(sw * scale_contain)), max(1, int(sh * scale_contain))
        empty_ratio = 1.0 - (nw * nh) / float(w * h)
        if empty_ratio > 0.22:
            return self._draw_cover(img, w, h)
        return self._draw_contain_edge_fill(img, w, h)

    @staticmethod
    def _alpha_blit(dst_rgb: Image.Image, src_rgba: Image.Image, x: int, y: int):
        tmp = dst_rgb.convert("RGBA")
        tmp.alpha_composite(src_rgba, (x, y))
        dst_rgb.paste(tmp.convert("RGB"))

    def _load_icon(self, filename: str, size_px: int) -> Optional[Image.Image]:
        if not filename:
            return None
        key = f"{filename}|{size_px}"
        if key in self._icons_cache:
            return self._icons_cache[key]

        path = self.icons_dir / filename
        if not path.exists():
            return None

        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((size_px, size_px), Image.LANCZOS)
            self._icons_cache[key] = img
            return img
        except Exception:
            pass

        if path.suffix.lower() == ".svg":
            png_bytes = _try_svg_to_png_bytes(path, size_px, size_px)
            if png_bytes:
                try:
                    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                    self._icons_cache[key] = img
                    return img
                except Exception:
                    pass

        png_bytes = rasterize_with_imagemagick_to_png(path, size_px)
        if not png_bytes:
            return None
        try:
            img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            self._icons_cache[key] = img
            return img
        except Exception:
            return None

    def render(self, state: AfficheState) -> Image.Image:
        page = Image.new("RGB", (A4_W_PX, A4_H_PX), "white")
        draw = ImageDraw.Draw(page)

        film_rows = max(1, len(state.films))
        top_cols = top_cols_for_rows(film_rows)
        bottom_cols = bottom_cols_for_rows(film_rows)

        top_h = TOP_POSTERS_H
        header1_h = HEADER1_H_PX
        header2_h = HEADER2_H_PX

        bottom_h_target = int(top_h * BOTTOM_TARGET_MULT)

        min_table_h = header1_h + header2_h + film_rows * ROW_H_MIN
        max_bottom_allowed = A4_H_PX - top_h - min_table_h
        bottom_h = BOTTOM_MIN_OK if max_bottom_allowed < BOTTOM_MIN_OK else max(BOTTOM_MIN_OK, min(bottom_h_target, max_bottom_allowed))

        available_for_table = A4_H_PX - top_h - bottom_h
        row_h = min(ROW_H_TARGET, max(ROW_H_MIN, (available_for_table - header1_h - header2_h) // film_rows))

        table_y0 = top_h
        table_h = header1_h + header2_h + film_rows * row_h
        table_y1 = table_y0 + table_h

        bottom_y0 = table_y1
        bottom_h = A4_H_PX - bottom_y0

        # TOP posters (best-fit)
        col_widths = self._split_units(A4_W_PX, top_cols)
        x = 0
        for i in range(top_cols):
            w = col_widths[i]
            p = state.posters.top[i] if i < len(state.posters.top) else ""
            if p and os.path.isfile(p):
                img = Image.open(p)
                page.paste(self._draw_poster_best_fit_top(img, w, top_h), (x, 0))
            else:
                draw.rectangle([x, 0, x + w, top_h], fill=(235, 235, 235))
            x += w

        # TABLE widths
        table_x0, table_x1 = 0, A4_W_PX
        table_w = table_x1 - table_x0

        film_w = int(table_w * 0.20)
        duur_w = int(table_w * 0.05)
        versie_w = int(table_w * 0.08)
        good_w = int(table_w * 0.085)
        day_total = table_w - film_w - duur_w - versie_w - good_w
        day_widths = self._split_units(day_total, 14)

        draw.rectangle([table_x0, table_y0, table_x1, table_y1], outline=(120, 120, 120), width=3)

        try:
            start_date = parse_date_iso(state.start_date) if state.start_date else dt.date.today()
        except Exception:
            start_date = dt.date.today()

        hdr = header_text(start_date)
        if not is_wednesday(start_date):
            hdr += "  (start is geen woensdag)"

        # Header1 black + white
        draw.rectangle([table_x0, table_y0, table_x1, table_y0 + header1_h], fill=(0, 0, 0))
        tw = draw.textlength(hdr, font=self.font_header)
        tx = table_x0 + (table_w - tw) / 2
        ty = table_y0 + (header1_h - self.font_header.size) / 2 + HEADER_TEXT_Y_BIAS
        draw.text((tx, ty), hdr, fill=(255, 255, 255), font=self.font_header)

        def cell_outline(x0, y0, x1, y1):
            draw.rectangle([x0, y0, x1, y1], outline=(210, 210, 210), width=1)

        def draw_center_text(box, text, font, fill=(0, 0, 0), y_bias=0):
            x0, y0, x1, y1 = box
            lines = str(text).split("\n")
            line_h = font.size + 2
            total_h = line_h * len(lines)
            yy = y0 + ((y1 - y0) - total_h) / 2 + y_bias
            for ln in lines:
                ttw = draw.textlength(ln, font=font)
                xx = x0 + ((x1 - x0) - ttw) / 2
                draw.text((xx, yy), ln, fill=fill, font=font)
                yy += line_h

        # Header2
        y_hdr2 = table_y0 + header1_h
        draw.rectangle([table_x0, y_hdr2, table_x1, y_hdr2 + header2_h], fill=(250, 250, 250))

        x = table_x0
        cell_outline(x, y_hdr2, x + film_w, y_hdr2 + header2_h)
        draw_center_text((x, y_hdr2, x + film_w, y_hdr2 + header2_h), "FILM", self.font_colhdr, y_bias=HEADER_TEXT_Y_BIAS)
        x += film_w

        cell_outline(x, y_hdr2, x + duur_w, y_hdr2 + header2_h)
        draw_center_text((x, y_hdr2, x + duur_w, y_hdr2 + header2_h), "DUUR", self.font_colhdr_small, y_bias=HEADER_TEXT_Y_BIAS)
        x += duur_w

        cell_outline(x, y_hdr2, x + versie_w, y_hdr2 + header2_h)
        draw_center_text((x, y_hdr2, x + versie_w, y_hdr2 + header2_h), "VERSIE", self.font_colhdr, y_bias=HEADER_TEXT_Y_BIAS)
        x += versie_w

        cell_outline(x, y_hdr2, x + good_w, y_hdr2 + header2_h)
        draw_center_text((x, y_hdr2, x + good_w, y_hdr2 + header2_h), "GOED\nGEZIEN", self.font_colhdr_small, y_bias=HEADER_TEXT_Y_BIAS)
        x += good_w

        dates = two_week_dates_from_start(start_date)
        for i in range(14):
            w = day_widths[i]
            cell_outline(x, y_hdr2, x + w, y_hdr2 + header2_h)
            draw_center_text((x, y_hdr2, x + w, y_hdr2 + header2_h), day_col_label(dates[i]), self.font_cell, y_bias=HEADER_TEXT_Y_BIAS)
            x += w

        rows_y0 = table_y0 + header1_h + header2_h
        for r in range(film_rows):
            ry0 = rows_y0 + r * row_h
            ry1 = ry0 + row_h
            fill_row = (245, 245, 245) if (r % 2 == 1) else (255, 255, 255)
            draw.rectangle([table_x0, ry0, table_x1, ry1], fill=fill_row)

            film = state.films[r]
            txt_color = RED_3D if film.is_3d else (0, 0, 0)

            x = table_x0

            cell_outline(x, ry0, x + film_w, ry1)
            draw_center_text((x, ry0, x + film_w, ry1), film.name, self.font_cell, fill=txt_color, y_bias=CELL_TEXT_Y_BIAS)
            x += film_w

            cell_outline(x, ry0, x + duur_w, ry1)
            draw_center_text((x, ry0, x + duur_w, ry1), film.duration, self.font_cell, fill=txt_color, y_bias=CELL_TEXT_Y_BIAS)
            x += duur_w

            cell_outline(x, ry0, x + versie_w, ry1)
            vtxt = film.version + (" 3D" if film.is_3d else "")
            draw_center_text((x, ry0, x + versie_w, ry1), vtxt, self.font_cell, fill=txt_color, y_bias=CELL_TEXT_Y_BIAS)
            x += versie_w

            cell_outline(x, ry0, x + good_w, ry1)
            if film.good_icons:
                icon_size = max(20, min(30, row_h - 14))
                ix = x + 4
                iy = ry0 + (row_h - icon_size) // 2
                for icon_fn in film.good_icons[:4]:
                    icon_img = self._load_icon(icon_fn, icon_size)
                    if icon_img:
                        self._alpha_blit(page, icon_img, ix, iy)
                        ix += icon_size + 4
            x += good_w

            for i in range(14):
                w = day_widths[i]
                cell_outline(x, ry0, x + w, ry1)
                t = (film.cells[i] or "").strip()
                if t:
                    draw_center_text((x, ry0, x + w, ry1), t, self.font_cell, fill=txt_color, y_bias=CELL_TEXT_Y_BIAS)
                x += w

        # BOTTOM posters: always full poster visible (no cropping)
        if bottom_h > 0:
            draw.rectangle([0, bottom_y0, A4_W_PX, A4_H_PX], fill=(240, 240, 240))
            slot_hs = self._split_units(bottom_h, 2)
            row1_h, row2_h = slot_hs[0], slot_hs[1]
            col_widths = self._split_units(A4_W_PX, bottom_cols)

            x = 0
            for c in range(bottom_cols):
                w = col_widths[c]
                p = state.posters.bottom[c] if c < len(state.posters.bottom) else ""
                if p and os.path.isfile(p):
                    img = Image.open(p)
                    page.paste(self._draw_contain_edge_fill(img, w, row1_h), (x, bottom_y0))
                x += w

            x = 0
            y2 = bottom_y0 + row1_h
            for c in range(bottom_cols):
                w = col_widths[c]
                idx = bottom_cols + c
                p = state.posters.bottom[idx] if idx < len(state.posters.bottom) else ""
                if p and os.path.isfile(p):
                    img = Image.open(p)
                    page.paste(self._draw_contain_edge_fill(img, w, row2_h), (x, y2))
                x += w

        return page

    def to_pdf_bytes(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        w_pt, h_pt = A4
        c = canvas.Canvas(buf, pagesize=(w_pt, h_pt))

        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_buf.seek(0)

        c.drawImage(ImageReader(img_buf), 0, 0, width=w_pt, height=h_pt,
                    preserveAspectRatio=False, mask="auto")
        c.showPage()
        c.save()
        return buf.getvalue()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x820")

        self.state_obj = AfficheState(
            start_date=dt.date.today().isoformat(),
            films=[FilmRow() for _ in range(12)]
        )
        self.renderer = AfficheRenderer(ICONS_DIR)

        self.icon_files = self._scan_icons()
        self.icon_thumb_cache: Dict[str, ImageTk.PhotoImage] = {}

        self.preview_imgtk = None
        self._preview_after_id = None

        self.current_row_index = 0
        self.is_loading_row = False
        self.last_header_date: Optional[str] = None

        self._root_paned: Optional[ttk.Panedwindow] = None

        self.top_btn_frame = None
        self.bottom_btn_frame = None
        self.top_buttons: List[ttk.Button] = []
        self.bottom_buttons: List[ttk.Button] = []

        self._build_ui()
        self.after(60, self._set_default_split)  # ✅ default "goed"
        self._refresh_film_list()
        self.film_list.selection_set(0)
        self._load_row_into_editor(0)

        self._rebuild_poster_buttons()
        self._schedule_preview()

    # ---- GUI split default
    def _set_default_split(self):
        try:
            if not self._root_paned:
                return
            total = self.winfo_width()
            x = int(total * 0.60)  # 60% editor, 40% preview
            self._root_paned.sashpos(0, x)
        except Exception:
            pass

    def _scan_icons(self) -> List[str]:
        exts = {".png", ".jpg", ".jpeg", ".svg", ".mvg"}
        files = [p.name for p in ICONS_DIR.iterdir() if p.is_file() and p.suffix.lower() in exts]
        files.sort()
        return files

    def _make_icon_thumb(self, filename: str, size: int) -> Optional[ImageTk.PhotoImage]:
        try:
            path = ICONS_DIR / filename
            try:
                img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
            except Exception:
                if path.suffix.lower() == ".svg":
                    png_bytes = _try_svg_to_png_bytes(path, size, size) or rasterize_with_imagemagick_to_png(path, size)
                else:
                    png_bytes = rasterize_with_imagemagick_to_png(path, size)
                if not png_bytes:
                    return None
                img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

            imgtk = ImageTk.PhotoImage(img)
            self.icon_thumb_cache[filename] = imgtk
            return imgtk
        except Exception:
            return None

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._root_paned = ttk.Panedwindow(self, orient="horizontal")
        self._root_paned.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(self._root_paned, padding=8)
        right = ttk.Frame(self._root_paned, padding=8)

        # ✅ preview standaard breder
        self._root_paned.add(left, weight=2)
        self._root_paned.add(right, weight=3)

        ctrl = ttk.Frame(left)
        ctrl.pack(fill="x", pady=(0, 8))

        ttk.Label(ctrl, text="Startdatum (YYYY-MM-DD):").pack(side="left")
        self.start_var = tk.StringVar(value=self.state_obj.start_date)
        self.start_entry = ttk.Entry(ctrl, textvariable=self.start_var, width=12)
        self.start_entry.pack(side="left", padx=6)

        ttk.Button(ctrl, text="↻ Preview", command=self._schedule_preview).pack(side="left", padx=6)
        ttk.Button(ctrl, text="Exporteer PDF…", command=self.export_pdf).pack(side="right")

        posters_frame = ttk.LabelFrame(left, text="Posters", padding=8)
        posters_frame.pack(fill="x", pady=(0, 8))

        self.top_btn_frame = ttk.Frame(posters_frame)
        self.top_btn_frame.pack(fill="x")

        self.bottom_btn_frame = ttk.Frame(posters_frame)
        self.bottom_btn_frame.pack(fill="x", pady=(6, 0))

        mid = ttk.Panedwindow(left, orient="horizontal")
        mid.pack(fill="both", expand=True)

        list_frame = ttk.LabelFrame(mid, text="Films / Rijen", padding=8)
        edit_frame = ttk.LabelFrame(mid, text="Rij bewerken", padding=8)
        mid.add(list_frame, weight=1)
        mid.add(edit_frame, weight=3)

        self.film_list = tk.Listbox(list_frame, height=18, takefocus=0)
        self.film_list.pack(fill="both", expand=True)
        self.film_list.bind("<<ListboxSelect>>", self._on_row_select)

        btns = ttk.Frame(list_frame)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="+ Rij", command=self.add_row).pack(side="left")
        ttk.Button(btns, text="- Rij", command=self.remove_row).pack(side="left", padx=6)

        row1 = ttk.Frame(edit_frame)
        row1.pack(fill="x")

        ttk.Label(row1, text="Film:").pack(side="left", anchor="n")
        name_dur = ttk.Frame(row1)
        name_dur.pack(side="left", padx=6, fill="x", expand=True)

        self.name_var = tk.StringVar()
        ttk.Entry(name_dur, textvariable=self.name_var, width=40).pack(anchor="w")

        dur_row = ttk.Frame(name_dur)
        dur_row.pack(anchor="w", pady=(4, 0))
        ttk.Label(dur_row, text="Duur:").pack(side="left")
        self.duration_var = tk.StringVar()
        ttk.Entry(dur_row, textvariable=self.duration_var, width=10).pack(side="left", padx=(6, 0))

        row2 = ttk.Frame(edit_frame)
        row2.pack(fill="x", pady=(6, 0))

        ttk.Label(row2, text="Versie:").pack(side="left")
        self.version_var = tk.StringVar(value="OV")
        ttk.Combobox(row2, textvariable=self.version_var, values=["OV", "NV"], width=6, state="readonly").pack(side="left", padx=6)
        self.is3d_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="3D (rood)", variable=self.is3d_var).pack(side="left", padx=6)
        ttk.Button(row2, text="Bewaar rij", command=self.save_current_row).pack(side="right")

        icons_box = ttk.LabelFrame(edit_frame, text="Goed gezien (icons)", padding=8)
        icons_box.pack(fill="x", pady=(8, 8))

        self.icon_vars: Dict[str, tk.BooleanVar] = {}
        icons_grid = ttk.Frame(icons_box)
        icons_grid.pack(fill="x")

        if not self.icon_files:
            ttk.Label(icons_grid, text=f"Geen icons gevonden in {ICONS_DIR}").pack(anchor="w")
        else:
            rows = 3
            cols = max(1, math.ceil(len(self.icon_files) / rows))
            for idx, fn in enumerate(self.icon_files):
                var = tk.BooleanVar(value=False)
                self.icon_vars[fn] = var

                r = idx % rows
                c = idx // rows

                frame = ttk.Frame(icons_grid)
                frame.grid(row=r, column=c, sticky="w", padx=8, pady=3)

                thumb = self._make_icon_thumb(fn, 18)
                if thumb:
                    ttk.Label(frame, image=thumb).pack(side="left", padx=(0, 6))
                ttk.Checkbutton(frame, text=os.path.splitext(fn)[0], variable=var,
                                command=self._schedule_preview).pack(side="left")

        # Speeluren: 14 dagen in 2 rijen (7 + 7)
        sched_box = ttk.LabelFrame(edit_frame, text="Speeluren (14 dagen) — 2 rijen (7+7)", padding=8)
        sched_box.pack(fill="both", expand=True)

        self.sched_inner = ttk.Frame(sched_box)
        self.sched_inner.pack(fill="x")

        self.day_labels: List[ttk.Label] = []
        self.cell_vars = [tk.StringVar(value="") for _ in range(14)]
        self.cell_entries: List[ttk.Entry] = []
        self._build_schedule_widgets_once()

        prev_box = ttk.LabelFrame(right, text="Live preview", padding=8)
        prev_box.pack(fill="both", expand=True)
        self.preview_label = ttk.Label(prev_box)
        self.preview_label.pack(fill="both", expand=True)

        for v in [self.start_var, self.name_var, self.duration_var, self.version_var]:
            v.trace_add("write", lambda *_: self._schedule_preview())
        self.is3d_var.trace_add("write", lambda *_: self._schedule_preview())
        for cv in self.cell_vars:
            cv.trace_add("write", lambda *_: self._schedule_preview())

    def _build_schedule_widgets_once(self):
        for i in range(14):
            row_block = 0 if i < 7 else 2
            col = i if i < 7 else (i - 7)

            lbl = ttk.Label(self.sched_inner, text="", justify="center")
            lbl.grid(row=row_block, column=col, padx=6, pady=2)
            self.day_labels.append(lbl)

            e = ttk.Entry(self.sched_inner, textvariable=self.cell_vars[i], width=8)
            e.grid(row=row_block + 1, column=col, padx=6, pady=2)

            def _entry_click(ev, w=e):
                w.focus_set()
                w.selection_range(0, tk.END)
                return "break"

            e.bind("<ButtonPress-1>", _entry_click)
            e.bind("<ButtonRelease-1>", _entry_click)
            e.bind("<FocusIn>", lambda ev, w=e: w.selection_range(0, tk.END))
            self.cell_entries.append(e)

        self._update_day_headers_if_needed(force=True)

    def _update_day_headers_if_needed(self, force=False):
        try:
            d = parse_date_iso(self.start_var.get().strip())
        except Exception:
            d = dt.date.today()

        key = d.isoformat()
        if not force and self.last_header_date == key:
            return
        self.last_header_date = key

        dates = two_week_dates_from_start(d)
        for i, dd in enumerate(dates):
            self.day_labels[i].configure(text=day_col_label(dd))

    def _refresh_film_list(self):
        self.film_list.delete(0, tk.END)
        for i, f in enumerate(self.state_obj.films):
            v = f.version + (" 3D" if f.is_3d else "")
            dur = f.duration.strip()
            dur_show = f" {dur}" if dur else ""
            self.film_list.insert(tk.END, f"{i+1:02d}. {f.name}{dur_show} [{v}]")

    def _rebuild_poster_buttons(self):
        film_rows = max(1, len(self.state_obj.films))
        top_cols = top_cols_for_rows(film_rows)
        bottom_cols = bottom_cols_for_rows(film_rows)

        for child in self.top_btn_frame.winfo_children():
            child.destroy()
        self.top_buttons.clear()

        ttk.Label(self.top_btn_frame, text="Top:").pack(side="left", padx=(0, 8))
        for i in range(top_cols):
            btn = ttk.Button(self.top_btn_frame, text=f"{i+1}", command=lambda k=i: self.import_poster("top", k))
            btn.pack(side="left", padx=2)
            self.top_buttons.append(btn)

        for child in self.bottom_btn_frame.winfo_children():
            child.destroy()
        self.bottom_buttons.clear()

        ttk.Label(self.bottom_btn_frame, text="Bottom:").pack(side="left", padx=(0, 8))
        rowA = ttk.Frame(self.bottom_btn_frame)
        rowB = ttk.Frame(self.bottom_btn_frame)
        rowA.pack(fill="x")
        rowB.pack(fill="x", pady=(4, 0))

        for c in range(bottom_cols):
            idx = c
            btn = ttk.Button(rowA, text=f"R1-{c+1}", command=lambda k=idx: self.import_poster("bottom", k))
            btn.pack(side="left", padx=2)
            self.bottom_buttons.append(btn)

        for c in range(bottom_cols):
            idx = bottom_cols + c
            btn = ttk.Button(rowB, text=f"R2-{c+1}", command=lambda k=idx: self.import_poster("bottom", k))
            btn.pack(side="left", padx=2)
            self.bottom_buttons.append(btn)

    def _save_editor_into_row(self, idx: int):
        if idx < 0 or idx >= len(self.state_obj.films):
            return
        f = self.state_obj.films[idx]
        f.name = self.name_var.get().strip() or "NAAM"
        f.duration = self.duration_var.get().strip()
        f.version = self.version_var.get().strip() or "OV"
        f.is_3d = bool(self.is3d_var.get())
        f.good_icons = [fn for fn, var in self.icon_vars.items() if var.get()]
        f.cells = [cv.get() for cv in self.cell_vars]

    def _load_row_into_editor(self, idx: int):
        if idx < 0 or idx >= len(self.state_obj.films):
            return
        f = self.state_obj.films[idx]
        if len(f.cells) < 14:
            f.cells = (f.cells + [""] * 14)[:14]

        self.is_loading_row = True
        try:
            self.name_var.set(f.name)
            self.duration_var.set(getattr(f, "duration", ""))
            self.version_var.set(f.version)
            self.is3d_var.set(f.is_3d)

            for fn, var in self.icon_vars.items():
                var.set(fn in f.good_icons)

            for i in range(14):
                self.cell_vars[i].set(f.cells[i])
        finally:
            self.is_loading_row = False

    def _on_row_select(self, _event):
        sel = self.film_list.curselection()
        if not sel:
            return
        new_idx = sel[0]
        old_idx = self.current_row_index
        if new_idx == old_idx:
            return

        self._save_editor_into_row(old_idx)

        def do_load():
            self.current_row_index = new_idx
            self._load_row_into_editor(new_idx)
            self._refresh_film_list()
            self._schedule_preview()

        self.after_idle(do_load)

    def save_current_row(self):
        self._save_editor_into_row(self.current_row_index)
        self._refresh_film_list()
        self._schedule_preview()

    def add_row(self):
        self._save_editor_into_row(self.current_row_index)
        self.state_obj.films.append(FilmRow())
        self._refresh_film_list()
        self._rebuild_poster_buttons()

        new_idx = len(self.state_obj.films) - 1
        self.film_list.selection_clear(0, tk.END)
        self.film_list.selection_set(new_idx)
        self.film_list.see(new_idx)

        self.current_row_index = new_idx
        self._load_row_into_editor(new_idx)
        self._schedule_preview()

    def remove_row(self):
        if len(self.state_obj.films) <= 1:
            messagebox.showinfo("Rijen", "Minstens 1 rij is verplicht.")
            return

        self._save_editor_into_row(self.current_row_index)
        idx = self.current_row_index
        del self.state_obj.films[idx]

        new_idx = max(0, idx - 1)
        self._refresh_film_list()
        self._rebuild_poster_buttons()

        self.film_list.selection_clear(0, tk.END)
        self.film_list.selection_set(new_idx)
        self.film_list.see(new_idx)

        self.current_row_index = new_idx
        self._load_row_into_editor(new_idx)
        self._schedule_preview()

    def import_poster(self, where: str, index: int):
        film_rows = max(1, len(self.state_obj.films))
        limit = top_cols_for_rows(film_rows) if where == "top" else bottom_cols_for_rows(film_rows) * 2
        if index < 0 or index >= limit:
            return

        path = filedialog.askopenfilename(
            title="Kies poster",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All", "*.*")]
        )
        if not path:
            return

        if where == "top":
            self.state_obj.posters.top[index] = path
        else:
            self.state_obj.posters.bottom[index] = path
        self._schedule_preview()

    def _schedule_preview(self):
        if self.is_loading_row:
            return
        self._save_editor_into_row(self.current_row_index)
        self._update_day_headers_if_needed()

        try:
            self.state_obj.start_date = parse_date_iso(self.start_var.get().strip()).isoformat()
        except Exception:
            pass

        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(150, self._update_preview)

    def _update_preview(self):
        img = self.renderer.render(self.state_obj)

        avail = self.preview_label.winfo_width()
        if avail < 200:
            avail = 700  # fallback first layout pass
        scale = (avail - 20) / img.size[0]
        prev = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS)

        self.preview_imgtk = ImageTk.PhotoImage(prev)
        self.preview_label.configure(image=self.preview_imgtk)

    def export_pdf(self):
        self._save_editor_into_row(self.current_row_index)
        img = self.renderer.render(self.state_obj)
        pdf_bytes = self.renderer.to_pdf_bytes(img)

        out = filedialog.asksaveasfilename(
            title="Bewaar PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")]
        )
        if not out:
            return
        with open(out, "wb") as f:
            f.write(pdf_bytes)
        messagebox.showinfo("OK", f"PDF opgeslagen:\n{out}")


if __name__ == "__main__":
    App().mainloop()