import io
import os
import subprocess
import logging
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageFilter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader


# -----------------------------
# Paths + logging (cross-platform)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
ICONS_DIR = BASE_DIR / "icons"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
ICONS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    filename=str(LOGS_DIR / "cinema_affiche.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

APP_TITLE = "Cinema Central — Affiche Generator"
MAX_TOP = 5
MAX_BOTTOM = 10

# A4 at 300 DPI
DPI = 300
A4_W_PX = int(8.27 * DPI)   # 2481
A4_H_PX = int(11.69 * DPI)  # 3507

# Layout
TOP_POSTERS_H = int(A4_H_PX * 0.18)

# Table style constants
HEADER1_H_PX = 110   # black bar
HEADER2_H_PX = 120   # column headers row
ROW_H_TARGET = 36    # nice compact row height
ROW_H_MIN = 28       # minimum if too many rows

# Bottom strip rules
BOTTOM_MIN_OK = int(A4_H_PX * 0.16)  # keep 2-row posters visible
BOTTOM_DEFAULT = int(A4_H_PX * 0.20)

DUTCH_MONTHS = {
    1: "Jan.", 2: "Feb.", 3: "Mrt.", 4: "Apr.", 5: "Mei", 6: "Jun.",
    7: "Jul.", 8: "Aug.", 9: "Sep.", 10: "Okt.", 11: "Nov.", 12: "Dec."
}
DUTCH_DAYS_SHORT = ["Ma", "Di", "Woe", "Don", "Vrij", "Zat", "Zon"]


def _load_font(size: int, bold=False):
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    ]
    for f in candidates:
        try:
            return ImageFont.truetype(f, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


@dataclass
class FilmRow:
    name: str = "NAAM"
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
# SVG support (optional)
# -----------------------------
def _try_svg_to_png_bytes(svg_path: Path, w: int, h: int) -> Optional[bytes]:
    try:
        import cairosvg  # pip install cairosvg
    except Exception:
        return None
    try:
        return cairosvg.svg2png(url=str(svg_path), output_width=w, output_height=h)
    except Exception as e:
        logging.exception(f"cairosvg failed on {svg_path}: {e}")
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

        # Fonts
        self.font_header = _load_font(30, bold=True)     # white text on black bar
        self.font_colhdr = _load_font(16, bold=True)     # uniform header2
        self.font_cell = _load_font(14, bold=False)      # cell text

        self._icons_cache: Dict[str, Image.Image] = {}

    @staticmethod
    def _split_width(total_w: int, n: int) -> List[int]:
        base = total_w // n
        widths = [base] * n
        widths[-1] += total_w - base * n
        return widths

    @staticmethod
    def _draw_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        src_w, src_h = img.size
        scale = max(target_w / src_w, target_h / src_h)
        new_w, new_h = int(src_w * scale), int(src_h * scale)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        return resized.crop((left, top, left + target_w, top + target_h))

    @staticmethod
    def _draw_contain(img: Image.Image, target_w: int, target_h: int, bg=(240, 240, 240)) -> Image.Image:
        src_w, src_h = img.size
        scale = min(target_w / src_w, target_h / src_h)
        new_w, new_h = int(src_w * scale), int(src_h * scale)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        canvas_img = Image.new("RGB", (target_w, target_h), bg)
        x = (target_w - new_w) // 2
        y = (target_h - new_h) // 2
        canvas_img.paste(resized, (x, y))
        return canvas_img

    @staticmethod
    def _draw_contain_with_blur_bg(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        # background: cover + blur
        bg = AfficheRenderer._draw_cover(img, target_w, target_h).filter(ImageFilter.GaussianBlur(radius=18))
        # foreground: contain (with black bg), then alpha composite on bg
        fg = AfficheRenderer._draw_contain(img, target_w, target_h, bg=(0, 0, 0)).convert("RGBA")
        bg_rgba = bg.convert("RGBA")
        bg_rgba.alpha_composite(fg, (0, 0))
        return bg_rgba.convert("RGB")

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

        # Try Pillow
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((size_px, size_px), Image.LANCZOS)
            self._icons_cache[key] = img
            return img
        except Exception:
            pass

        # SVG via cairosvg
        if path.suffix.lower() == ".svg":
            png_bytes = _try_svg_to_png_bytes(path, size_px, size_px)
            if png_bytes:
                try:
                    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                    self._icons_cache[key] = img
                    return img
                except Exception:
                    pass

        # ImageMagick fallback
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

        # -------------------------
        # Dynamic layout (NO big whitespace):
        # table grows with rows, bottom follows directly.
        # -------------------------
        top_h = TOP_POSTERS_H
        header1_h = HEADER1_H_PX
        header2_h = HEADER2_H_PX

        row_h = ROW_H_TARGET
        table_y0 = top_h
        table_h_needed = header1_h + header2_h + film_rows * row_h
        table_y1 = table_y0 + table_h_needed

        bottom_y0 = table_y1
        bottom_h = A4_H_PX - bottom_y0

        if bottom_h < BOTTOM_MIN_OK:
            space_for_table = A4_H_PX - BOTTOM_MIN_OK - top_h
            max_rows_height = space_for_table - header1_h - header2_h
            row_h = max(ROW_H_MIN, max_rows_height // film_rows)
            table_h_needed = header1_h + header2_h + film_rows * row_h
            table_y1 = table_y0 + table_h_needed
            bottom_y0 = table_y1
            bottom_h = A4_H_PX - bottom_y0
            if bottom_h < 0:
                bottom_h = 0

        # -------------------------
        # Top posters (cover)
        # -------------------------
        top_widths = self._split_width(A4_W_PX, MAX_TOP)
        x = 0
        for i, w in enumerate(top_widths):
            p = state.posters.top[i]
            if p and os.path.isfile(p):
                try:
                    img = Image.open(p).convert("RGB")
                    page.paste(self._draw_cover(img, w, top_h), (x, 0))
                except Exception:
                    draw.rectangle([x, 0, x + w, top_h], fill=(220, 220, 220))
            else:
                draw.rectangle([x, 0, x + w, top_h], fill=(235, 235, 235))
            x += w

        # -------------------------
        # Table (full width, 14 days)
        # -------------------------
        table_x0, table_x1 = 0, A4_W_PX
        table_w = table_x1 - table_x0

        film_w = int(table_w * 0.22)
        versie_w = int(table_w * 0.08)
        good_w = int(table_w * 0.11)
        day_total = table_w - film_w - versie_w - good_w
        day_widths = self._split_width(day_total, 14)

        # outer border
        draw.rectangle([table_x0, table_y0, table_x1, table_y1], outline=(120, 120, 120), width=3)

        # date parsing
        try:
            start_date = parse_date_iso(state.start_date) if state.start_date else dt.date.today()
        except Exception:
            start_date = dt.date.today()

        # HEADER 1: black bar + white text
        hdr = header_text(start_date)
        if not is_wednesday(start_date):
            hdr += "  (start is geen woensdag)"

        draw.rectangle([table_x0, table_y0, table_x1, table_y0 + header1_h], fill=(0, 0, 0))
        tw = draw.textlength(hdr, font=self.font_header)
        tx = table_x0 + (table_w - tw) / 2
        ty = table_y0 + (header1_h - self.font_header.size) / 2
        draw.text((tx, ty), hdr, fill=(255, 255, 255), font=self.font_header)

        # helper functions
        def cell_outline(x0, y0, x1, y1):
            draw.rectangle([x0, y0, x1, y1], outline=(210, 210, 210), width=1)

        def draw_center_text(box, text, font, fill=(0, 0, 0)):
            x0, y0, x1, y1 = box
            lines = str(text).split("\n")
            line_h = font.size + 1
            total_h = line_h * len(lines)
            yy = y0 + ((y1 - y0) - total_h) / 2
            for ln in lines:
                ttw = draw.textlength(ln, font=font)
                xx = x0 + ((x1 - x0) - ttw) / 2
                draw.text((xx, yy), ln, fill=fill, font=font)
                yy += line_h

        # HEADER 2 uniform
        y_hdr2 = table_y0 + header1_h
        draw.rectangle([table_x0, y_hdr2, table_x1, y_hdr2 + header2_h], fill=(250, 250, 250))

        x = table_x0
        box = (x, y_hdr2, x + film_w, y_hdr2 + header2_h)
        cell_outline(*box); draw_center_text(box, "FILM", self.font_colhdr)
        x += film_w

        box = (x, y_hdr2, x + versie_w, y_hdr2 + header2_h)
        cell_outline(*box); draw_center_text(box, "VERSIE", self.font_colhdr)
        x += versie_w

        box = (x, y_hdr2, x + good_w, y_hdr2 + header2_h)
        cell_outline(*box); draw_center_text(box, "GOED\nGEZIEN", self.font_colhdr)
        x += good_w

        dates = two_week_dates_from_start(start_date)
        for i in range(14):
            w = day_widths[i]
            box = (x, y_hdr2, x + w, y_hdr2 + header2_h)
            cell_outline(*box)
            draw_center_text(box, day_col_label(dates[i]), self.font_cell)
            x += w

        # FILM ROWS
        rows_y0 = table_y0 + header1_h + header2_h
        for r in range(film_rows):
            ry0 = rows_y0 + r * row_h
            ry1 = ry0 + row_h
            fill = (245, 245, 245) if (r % 2 == 1) else (255, 255, 255)
            draw.rectangle([table_x0, ry0, table_x1, ry1], fill=fill)

            film = state.films[r]
            x = table_x0

            # film cell
            cell_outline(x, ry0, x + film_w, ry1)
            draw_center_text((x, ry0, x + film_w, ry1), film.name, self.font_cell)
            x += film_w

            # version cell
            cell_outline(x, ry0, x + versie_w, ry1)
            vtxt = film.version + (" 3D" if film.is_3d else "")
            vcol = (200, 0, 0) if film.is_3d else (0, 0, 0)
            draw_center_text((x, ry0, x + versie_w, ry1), vtxt, self.font_cell, fill=vcol)
            x += versie_w

            # good icons cell
            cell_outline(x, ry0, x + good_w, ry1)
            if film.good_icons:
                icon_size = max(18, min(24, row_h - 8))
                ix = x + 6
                iy = ry0 + (row_h - icon_size) // 2
                for icon_fn in film.good_icons[:6]:
                    icon_img = self._load_icon(icon_fn, icon_size)
                    if icon_img:
                        self._alpha_blit(page, icon_img, ix, iy)
                        ix += icon_size + 4
            x += good_w

            # 14 day cells
            for i in range(14):
                w = day_widths[i]
                cell_outline(x, ry0, x + w, ry1)
                t = (film.cells[i] or "").strip()
                if t:
                    draw_center_text((x, ry0, x + w, ry1), t, self.font_cell)
                x += w

        # -------------------------
        # Bottom posters (2x5) — follow table directly
        # -------------------------
        if bottom_h > 0:
            slot_h = bottom_h // 2
            col_widths = self._split_width(A4_W_PX, 5)  # fixed widths for both rows
            draw.rectangle([0, bottom_y0, A4_W_PX, A4_H_PX], fill=(240, 240, 240))

            posters_to_show = min(MAX_BOTTOM, film_rows)  # match films count

            for j in range(MAX_BOTTOM):
                row = j // 5
                col = j % 5
                x0 = sum(col_widths[:col])
                w = col_widths[col]
                y0b = bottom_y0 + row * slot_h
                h = slot_h

                if j < posters_to_show:
                    p = state.posters.bottom[j]
                    if p and os.path.isfile(p):
                        try:
                            img = Image.open(p).convert("RGB")
                            # city-ready: contain with blurred background
                            page.paste(self._draw_contain_with_blur_bg(img, w, h), (x0, y0b))
                        except Exception:
                            draw.rectangle([x0, y0b, x0 + w, y0b + h], fill=(220, 220, 220))
                    else:
                        draw.rectangle([x0, y0b, x0 + w, y0b + h], fill=(240, 240, 240))
                else:
                    draw.rectangle([x0, y0b, x0 + w, y0b + h], fill=(240, 240, 240))

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
            films=[FilmRow() for _ in range(8)]
        )
        self.renderer = AfficheRenderer(ICONS_DIR)

        self.icon_files = self._scan_icons()
        self.icon_thumb_cache: Dict[str, ImageTk.PhotoImage] = {}
        self.preview_imgtk = None
        self._preview_after_id = None

        self.current_row_index = 0
        self.is_loading_row = False
        self.last_header_date: Optional[str] = None

        self._build_ui()
        self._refresh_film_list()
        self.film_list.selection_set(0)
        self._load_row_into_editor(0)
        self._schedule_preview()

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

        root = ttk.Panedwindow(self, orient="horizontal")
        root.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(root, padding=8)
        right = ttk.Frame(root, padding=8)
        root.add(left, weight=3)
        root.add(right, weight=2)

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

        top_row = ttk.Frame(posters_frame)
        top_row.pack(fill="x")
        ttk.Label(top_row, text="Top:").pack(side="left", padx=(0, 8))
        for i in range(MAX_TOP):
            ttk.Button(top_row, text=f"Top {i+1}", command=lambda k=i: self.import_poster("top", k)).pack(side="left", padx=2)

        bot_row = ttk.Frame(posters_frame)
        bot_row.pack(fill="x", pady=(6, 0))
        ttk.Label(bot_row, text="Bottom:").pack(side="left", padx=(0, 8))
        for i in range(MAX_BOTTOM):
            label = f"R1-{i+1}" if i < 5 else f"R2-{i-4}"
            ttk.Button(bot_row, text=label, command=lambda k=i: self.import_poster("bottom", k)).pack(side="left", padx=2)

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
        ttk.Label(row1, text="Film:").pack(side="left")
        self.name_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.name_var, width=40).pack(side="left", padx=6)

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
            cols = 6
            for idx, fn in enumerate(self.icon_files):
                var = tk.BooleanVar(value=False)
                self.icon_vars[fn] = var

                frame = ttk.Frame(icons_grid)
                frame.grid(row=idx // cols, column=idx % cols, sticky="w", padx=8, pady=4)

                thumb = self._make_icon_thumb(fn, 18)
                if thumb:
                    ttk.Label(frame, image=thumb).pack(side="left", padx=(0, 6))
                ttk.Checkbutton(frame, text=os.path.splitext(fn)[0], variable=var,
                                command=self._schedule_preview).pack(side="left")

        sched_box = ttk.LabelFrame(edit_frame, text="Speeluren (14 dagen)", padding=8)
        sched_box.pack(fill="both", expand=True)

        self.sched_canvas = tk.Canvas(sched_box, highlightthickness=0, takefocus=0)
        self.sched_canvas.pack(side="left", fill="both", expand=True)
        sb_y = ttk.Scrollbar(sched_box, orient="vertical", command=self.sched_canvas.yview)
        sb_y.pack(side="right", fill="y")
        self.sched_canvas.configure(yscrollcommand=sb_y.set)

        self.sched_inner = ttk.Frame(self.sched_canvas)
        self.sched_canvas.create_window((0, 0), window=self.sched_inner, anchor="nw")
        self.sched_inner.bind("<Configure>", lambda e: self.sched_canvas.configure(scrollregion=self.sched_canvas.bbox("all")))

        self.day_labels: List[ttk.Label] = []
        self.cell_vars = [tk.StringVar(value="") for _ in range(14)]
        self.cell_entries: List[ttk.Entry] = []
        self._build_schedule_widgets_once()

        prev_box = ttk.LabelFrame(right, text="Live preview", padding=8)
        prev_box.pack(fill="both", expand=True)

        self.preview_label = ttk.Label(prev_box)
        self.preview_label.pack(fill="both", expand=True)

        for v in [self.start_var, self.name_var, self.version_var]:
            v.trace_add("write", lambda *_: self._schedule_preview())
        self.is3d_var.trace_add("write", lambda *_: self._schedule_preview())
        for cv in self.cell_vars:
            cv.trace_add("write", lambda *_: self._schedule_preview())

    def _build_schedule_widgets_once(self):
        # compact editor
        for i in range(14):
            lbl = ttk.Label(self.sched_inner, text="", justify="center")
            lbl.grid(row=0, column=i, padx=3, pady=2)
            self.day_labels.append(lbl)

            e = ttk.Entry(self.sched_inner, textvariable=self.cell_vars[i], width=7)
            e.grid(row=1, column=i, padx=3, pady=2)

            # macOS: single click focus
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
            self.film_list.insert(tk.END, f"{i+1:02d}. {f.name} [{v}]")

    def _save_editor_into_row(self, idx: int):
        if idx < 0 or idx >= len(self.state_obj.films):
            return
        f = self.state_obj.films[idx]
        f.name = self.name_var.get().strip() or "NAAM"
        f.version = self.version_var.get().strip() or "OV"
        f.is_3d = bool(self.is3d_var.get())
        f.good_icons = [fn for fn, var in self.icon_vars.items() if var.get()]
        f.cells = [cv.get() for cv in self.cell_vars]

    def _load_row_into_editor(self, idx: int):
        if idx < 0 or idx >= len(self.state_obj.films):
            return
        f = self.state_obj.films[idx]

        self.is_loading_row = True
        try:
            self.name_var.set(f.name)
            self.version_var.set(f.version)
            self.is3d_var.set(f.is_3d)

            for fn, var in self.icon_vars.items():
                var.set(fn in f.good_icons)

            for i in range(14):
                self.cell_vars[i].set(f.cells[i] if i < len(f.cells) else "")
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

        self.film_list.selection_clear(0, tk.END)
        self.film_list.selection_set(new_idx)
        self.film_list.see(new_idx)

        self.current_row_index = new_idx
        self._load_row_into_editor(new_idx)
        self._schedule_preview()

    def import_poster(self, where: str, index: int):
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
        self._preview_after_id = self.after(200, self._update_preview)

    def _update_preview(self):
        try:
            img = self.renderer.render(self.state_obj)
            max_w = 560
            scale = max_w / img.size[0]
            prev = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS)
            self.preview_imgtk = ImageTk.PhotoImage(prev)
            self.preview_label.configure(image=self.preview_imgtk)
        except Exception as e:
            logging.exception(f"Preview error: {e}")
            messagebox.showerror("Preview fout", str(e))

    def export_pdf(self):
        self._save_editor_into_row(self.current_row_index)
        try:
            img = self.renderer.render(self.state_obj)
            pdf_bytes = self.renderer.to_pdf_bytes(img)
        except Exception as e:
            logging.exception(f"Export error: {e}")
            messagebox.showerror("Export fout", str(e))
            return

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