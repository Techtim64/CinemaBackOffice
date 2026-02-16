import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import date, datetime, timedelta
import calendar
from reportlab.lib import colors


import pandas as pd
from mysql.connector import pooling

# PDF (ReportLab)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader


# =========================
# CONFIG
# =========================
DB_CONFIG = {
    "host": "172.20.18.2",
    "port": 3306,
    "user": "cinema_user",
    "password": "Cinema1919!",
    "database": "cinema_db",
}

POOL = pooling.MySQLConnectionPool(pool_name="cinema_pool", pool_size=5, **DB_CONFIG)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")

DEFAULT_BTW_RATE = 0.0566      # 5,66%
DEFAULT_AUTEURS_RATE = 0.0120  # 1,20% op NETTO

WEEKDAY_LABELS = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
LABEL_TO_WEEKDAY = {lbl: i for i, lbl in enumerate(WEEKDAY_LABELS)}
WEEKDAY_TO_LABEL = {i: lbl for i, lbl in enumerate(WEEKDAY_LABELS)}


# =========================
# Helpers
# =========================
def get_conn():
    return POOL.get_connection()


def extract_variant_parts(variant: str) -> list[str]:
    if pd.isna(variant):
        return []
    s = str(variant).strip()
    for sep in ["·", "•", "|"]:
        if sep in s:
            return [p.strip() for p in s.split(sep) if p.strip()]
    if " - " in s:
        return [p.strip() for p in s.split(" - ") if p.strip()]
    return [s] if s else []


def detect_film_and_zaal(variant: str) -> tuple[str, str]:
    """
    Detecteert film + zaal uit Naam van variant.

    Regels:
    - bevat 'zaal beneden'  -> zaal = '1'
    - bevat 'zaal boven'    -> zaal = '2'
    - film = tweede onderdeel indien aanwezig
    """
    if pd.isna(variant):
        return "", ""

    s = str(variant).strip().lower()

    if "zaal beneden" in s:
        zaal = "1"
    elif "zaal boven" in s:
        zaal = "2"
    else:
        zaal = ""

    parts = extract_variant_parts(variant)
    if len(parts) >= 2:
        film = parts[1]
    elif parts:
        film = parts[0]
    else:
        film = ""

    return film.strip(), zaal


def _money(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _safe_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:160] if len(s) > 160 else s


def _weekday_full_nl(d: date) -> str:
    return WEEKDAY_TO_LABEL[d.weekday()]


def _parse_percent_to_rate(s: str) -> float:
    """
    Input: "5,66" of "5.66" of "5,66%" -> output rate 0.0566
    """
    s = (s or "").strip().replace("%", "").replace(",", ".")
    p = float(s)
    return p / 100.0


# =========================
# DB functions
# =========================
def db_get_setting(key: str) -> str | None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE `key`=%s", (key,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def db_set_setting(key: str, value: str) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def db_get_float_setting(key: str, default: float) -> float:
    v = db_get_setting(key)
    if v is None:
        db_set_setting(key, str(default))
        return default
    try:
        s = str(v).strip().replace(",", ".")
        return float(s)
    except Exception:
        db_set_setting(key, str(default))
        return default


def db_set_float_setting(key: str, value: float) -> None:
    db_set_setting(key, str(value))


def db_get_week_start_weekday() -> int:
    """
    0=Ma ... 6=Zo
    default = 1 (Dinsdag)
    """
    v = db_get_setting("week_start_weekday")
    if v is None:
        db_set_setting("week_start_weekday", "1")
        return 1
    try:
        n = int(v)
        if 0 <= n <= 6:
            return n
    except Exception:
        pass
    db_set_setting("week_start_weekday", "1")
    return 1


def speelweek_range(d: date, week_start_weekday: int) -> tuple[date, date]:
    weekday = d.weekday()
    days_since_start = (weekday - week_start_weekday) % 7
    start = d - timedelta(days=days_since_start)
    end = start + timedelta(days=7)
    return start, end


def db_get_or_create_speelweek(d: date) -> tuple[int, int]:
    week_start = db_get_week_start_weekday()
    start, end = speelweek_range(d, week_start)

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, weeknummer FROM speelweek WHERE start_datum=%s AND eind_datum=%s",
            (start, end),
        )
        row = cur.fetchone()
        if row:
            return int(row[0]), int(row[1])

        week_counter = db_get_setting("week_counter")
        if week_counter is None:
            week_counter = "1"
            db_set_setting("week_counter", "1")
        weeknummer = int(week_counter)

        cur.execute(
            "INSERT INTO speelweek(weeknummer, start_datum, eind_datum) VALUES(%s,%s,%s)",
            (weeknummer, start, end),
        )
        conn.commit()
        speelweek_id = cur.lastrowid

        db_set_setting("week_counter", str(weeknummer + 1))
        return int(speelweek_id), weeknummer
    finally:
        conn.close()


def db_get_film_by_interne_titel(interne_titel: str):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, interne_titel, maccsbox_titel, distributeur, land_herkomst "
            "FROM films WHERE interne_titel=%s",
            (interne_titel,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def db_create_film(interne_titel: str, maccsbox_titel: str, distributeur: str, land_herkomst: str) -> int:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO films(interne_titel, maccsbox_titel, distributeur, land_herkomst) "
            "VALUES(%s,%s,%s,%s)",
            (interne_titel, maccsbox_titel, distributeur, land_herkomst),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def db_get_or_create_zaal(zaal_naam: str) -> int | None:
    zaal_naam = zaal_naam.strip()
    if not zaal_naam:
        return None

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM zalen WHERE naam=%s", (zaal_naam,))
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO zalen(naam) VALUES(%s)", (zaal_naam,))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def db_upsert_daily_sales(
    datum: date,
    speelweek_id: int,
    film_id: int,
    zaal_id: int | None,
    is_3d: bool,
    aantal_volw: int,
    aantal_kind: int,
    bedrag_volw: float,
    bedrag_kind: float,
    totaal_aantal: int,
    totaal_bedrag: float,
    source_file: str | None,
):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO daily_sales(
                datum, speelweek_id, film_id, zaal_id, is_3d,
                aantal_volw, aantal_kind, bedrag_volw, bedrag_kind,
                totaal_aantal, totaal_bedrag, source_file
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                speelweek_id=VALUES(speelweek_id),
                is_3d=VALUES(is_3d),
                aantal_volw=VALUES(aantal_volw),
                aantal_kind=VALUES(aantal_kind),
                bedrag_volw=VALUES(bedrag_volw),
                bedrag_kind=VALUES(bedrag_kind),
                totaal_aantal=VALUES(totaal_aantal),
                totaal_bedrag=VALUES(totaal_bedrag),
                source_file=VALUES(source_file)
            """,
            (
                datum,
                speelweek_id,
                film_id,
                zaal_id,
                1 if is_3d else 0,
                aantal_volw,
                aantal_kind,
                round(bedrag_volw, 2),
                round(bedrag_kind, 2),
                totaal_aantal,
                round(totaal_bedrag, 2),
                source_file,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def db_fetch_history(from_date: date, to_date: date):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              ds.datum,
              sw.weeknummer,
              sw.start_datum,
              sw.eind_datum,
              f.interne_titel,
              z.naam AS zaal,
              ds.is_3d,
              ds.aantal_volw,
              ds.aantal_kind,
              ds.bedrag_volw,
              ds.bedrag_kind,
              ds.totaal_aantal,
              ds.totaal_bedrag
            FROM daily_sales ds
            JOIN films f ON f.id = ds.film_id
            JOIN speelweek sw ON sw.id = ds.speelweek_id
            LEFT JOIN zalen z ON z.id = ds.zaal_id
            WHERE ds.datum BETWEEN %s AND %s
            ORDER BY ds.datum ASC, z.naam ASC, f.interne_titel ASC
            """,
            (from_date, to_date),
        )
        return cur.fetchall()
    finally:
        conn.close()


# =========================
# PDF: DB queries
# =========================
def db_fetch_borderel_combos(from_date: date, to_date: date):
    """
    Unieke combos binnen range (speelweek + film + zaal).
    """
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT DISTINCT
              ds.speelweek_id,
              sw.weeknummer,
              sw.start_datum,
              sw.eind_datum,
              ds.film_id,
              f.interne_titel,
              f.maccsbox_titel,
              f.distributeur,
              f.land_herkomst,
              COALESCE(z.naam, '') AS zaal
            FROM daily_sales ds
            JOIN speelweek sw ON sw.id = ds.speelweek_id
            JOIN films f ON f.id = ds.film_id
            LEFT JOIN zalen z ON z.id = ds.zaal_id
            WHERE ds.datum BETWEEN %s AND %s
            ORDER BY sw.start_datum ASC, zaal ASC, f.interne_titel ASC
            """,
            (from_date, to_date),
        )
        return cur.fetchall()
    finally:
        conn.close()


def db_fetch_week_sales_for_film_zaal(speelweek_id: int, film_id: int, zaal_naam: str):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              ds.datum,
              ds.aantal_volw, ds.aantal_kind,
              ds.bedrag_volw, ds.bedrag_kind,
              ds.is_3d,
              sw.weeknummer, sw.start_datum, sw.eind_datum,
              f.interne_titel, f.maccsbox_titel, f.distributeur, f.land_herkomst,
              COALESCE(z.naam, '') AS zaal
            FROM daily_sales ds
            JOIN speelweek sw ON sw.id = ds.speelweek_id
            JOIN films f ON f.id = ds.film_id
            LEFT JOIN zalen z ON z.id = ds.zaal_id
            WHERE ds.speelweek_id = %s
              AND ds.film_id = %s
              AND COALESCE(z.naam, '') = %s
            ORDER BY ds.datum ASC
            """,
            (speelweek_id, film_id, zaal_naam or ""),
        )
        return cur.fetchall()
    finally:
        conn.close()


# =========================================================
# PDF helper: "GEBRUIKTE TICKETS" tabel van scratch (jouw screenshot)
# =========================================================
def draw_used_tickets_table_bo1(
    c,
    *,
    x_mm: float,
    y_mm: float,
    w_mm: float,
    volw_qty: int,
    kind_qty: int,
    volw_price: float,
    kind_price: float,
    volw_amt: float,
    kind_amt: float,
    tickets_total: int,
    gross_total: float,
    outer_lw: float = 1.8,
    inner_lw: float = 1.4,
):
    def mmx(v): return v * mm
    def X(v): return mmx(x_mm + v)
    def Y(v): return mmx(y_mm + v)

    def money(v: float) -> str:
        return f"{v:.2f}".replace(".", ",")

    def rect(x, y, w, h, lw):
        c.setLineWidth(lw)
        c.rect(X(x), Y(y), mmx(w), mmx(h), stroke=1, fill=0)

    def hline(x1, x2, y, lw):
        c.setLineWidth(lw)
        c.line(X(x1), Y(y), X(x2), Y(y))

    def vline(x, y1, y2, lw):
        c.setLineWidth(lw)
        c.line(X(x), Y(y1), X(x), Y(y2))

    def text_left(x, y, s, font="Helvetica", size=10):
        c.setFont(font, size)
        c.drawString(X(x), Y(y), s)

    def text_center(x, y, s, font="Helvetica", size=10):
        c.setFont(font, size)
        c.drawCentredString(X(x), Y(y), s)

    def text_right(x, y, s, font="Helvetica", size=10):
        c.setFont(font, size)
        c.drawRightString(X(x), Y(y), s)

    # --- SMALLER table (was 18/20/9/9 => now tighter) ---
    h_header = 14.0
    h_body = 16.0
    h_footer1 = 7.5
    h_footer2 = 7.5
    h_total = h_header + h_body + h_footer1 + h_footer2

    # columns unchanged
    w_left = w_mm * 0.58
    w_mid = w_mm * 0.20
    w_right = w_mm - w_left - w_mid
    w_left_label = w_left * 0.68

    pad_r = 1.5  # slightly tighter

    # frame
    rect(0, 0, w_mm, h_total, outer_lw)

    # horizontal lines
    y_footer2_top = h_footer2
    y_footer1_top = h_footer2 + h_footer1
    y_body_top = h_footer2 + h_footer1 + h_body

    hline(0, w_mm, y_footer2_top, inner_lw)
    hline(0, w_mm, y_footer1_top, inner_lw)
    hline(0, w_mm, y_body_top, inner_lw)

    # vertical lines
    vline(w_left, 0, h_total, inner_lw)
    vline(w_left + w_mid, 0, h_total, inner_lw)
    vline(w_left_label, h_footer2, h_footer2 + h_footer1, inner_lw)

    # --- HEADER (smaller fonts) ---
    header_y0 = y_body_top
    text_center(w_left / 2, header_y0 + 9.5, "Aantal", font="Helvetica", size=9)
    text_center(w_left / 2, header_y0 + 3.2, "toeschouwers", font="Helvetica", size=9)

    text_center(w_left + w_mid / 2, header_y0 + 6.3, "Prijs", font="Helvetica-Bold", size=9)

    text_center(w_left + w_mid + w_right / 2, header_y0 + 9.5, "Bruto ontvangst", font="Helvetica", size=9)
    text_center(w_left + w_mid + w_right / 2, header_y0 + 3.2, "BTW inbegrepen", font="Helvetica", size=9)

    # --- BODY (smaller fonts + reposition) ---
    row1_y = y_footer1_top + 10.0
    row2_y = y_footer1_top + 3.5

    text_right(w_left - pad_r, row1_y, str(int(volw_qty)), font="Helvetica", size=9)
    text_right(w_left - pad_r, row2_y, str(int(kind_qty)), font="Helvetica", size=9)

    text_right(w_left + w_mid - pad_r, row1_y, money(volw_price), font="Helvetica", size=9)
    text_right(w_left + w_mid - pad_r, row2_y, money(kind_price), font="Helvetica", size=9)

    text_right(w_mm - pad_r, row1_y, money(volw_amt), font="Helvetica", size=9)
    text_right(w_mm - pad_r, row2_y, money(kind_amt), font="Helvetica", size=9)

    # --- FOOTER1 (smaller fonts) ---
    f1_y = h_footer2
    text_left(2.0, f1_y + 2.2, "toeschouwers", font="Helvetica-Bold", size=9)
    text_right(w_left - pad_r, f1_y + 2.4, str(int(tickets_total)), font="Helvetica", size=9)
    text_center(w_left + w_mid / 2, f1_y + 2.4, "Totaal", font="Helvetica", size=9)
    text_right(w_mm - pad_r, f1_y + 2.4, money(gross_total), font="Helvetica", size=9)

    # --- FOOTER2 ---
    text_center(w_left + w_mid / 2, 2.2, "Kosteloos", font="Helvetica", size=9)


# =========================
# PDF: BO1 layout (zonder ticketnummers)
# =========================
def generate_borderel_bo1_pdf(output_path: str, week_rows: list[dict], btw_rate: float, auteurs_rate: float):
    if not week_rows:
        raise ValueError("Geen data voor deze (speelweek + film + zaal).")

    meta = week_rows[0]
    film_title = (meta.get("maccsbox_titel") or meta.get("interne_titel") or "").strip()
    distributeur = (meta.get("distributeur") or "").strip()
    land = (meta.get("land_herkomst") or "").strip()
    weeknr = int(meta.get("weeknummer") or 0)
    week_start = meta.get("start_datum")
    zaal = (meta.get("zaal") or "").strip()

    if isinstance(week_start, str):
        week_start_d = datetime.strptime(week_start, "%Y-%m-%d").date()
    else:
        week_start_d = week_start

    rows_by_date = {r["datum"]: r for r in week_rows}

    volw_qty = sum(int(r.get("aantal_volw") or 0) for r in week_rows)
    kind_qty = sum(int(r.get("aantal_kind") or 0) for r in week_rows)
    volw_amt = sum(float(r.get("bedrag_volw") or 0.0) for r in week_rows)
    kind_amt = sum(float(r.get("bedrag_kind") or 0.0) for r in week_rows)

    gross_total = volw_amt + kind_amt
    tickets_total = volw_qty + kind_qty

    btw_total = gross_total * btw_rate
    netto_total = gross_total - btw_total
    auteurs_total = netto_total * auteurs_rate
    verschil = netto_total - auteurs_total

    volw_price = (volw_amt / volw_qty) if volw_qty else 0.0
    kind_price = (kind_amt / kind_qty) if kind_qty else 0.0

    def mmx(x): return x * mm
    def mmy(y): return y * mm

    c = canvas.Canvas(output_path, pagesize=A4)
    W, H = A4

    def rect(x, y, w, h, lw=1):
        c.setLineWidth(lw)
        c.rect(mmx(x), mmy(y), mmx(w), mmx(h), stroke=1, fill=0)

    def hline(x1, x2, y, lw=1):
        c.setLineWidth(lw)
        c.line(mmx(x1), mmy(y), mmx(x2), mmy(y))

    def vline(x, y1, y2, lw=1):
        c.setLineWidth(lw)
        c.line(mmx(x), mmy(y1), mmx(x), mmy(y2))

    def text(x, y, s, font="Helvetica", size=9):
        c.setFont(font, size)
        c.drawString(mmx(x), mmy(y), s)

    def textr(x, y, s, font="Helvetica", size=9):
        c.setFont(font, size)
        c.drawRightString(mmx(x), mmy(y), s)

    def textc(x, y, s, font="Helvetica", size=9):
        c.setFont(font, size)
        c.drawCentredString(mmx(x), mmy(y), s)

    def textc_multiline(x_center_mm, y_top_mm, lines, font="Helvetica-Bold", size=8, leading_mm=3.2):
        c.setFont(font, size)
        y = y_top_mm
        for ln in lines:
            c.drawCentredString(mmx(x_center_mm), mmy(y), ln)
            y -= leading_mm

    def fit_left(x_mm, y_mm, text_str, max_width_mm, font="Helvetica-Bold", max_size=12, min_size=7):
        s = (text_str or "").strip()
        size = max_size
        while size > min_size:
            if c.stringWidth(s, font, size) <= mmx(max_width_mm):
                break
            size -= 1
        c.setFont(font, size)
        c.drawString(mmx(x_mm), mmy(y_mm), s)

    def wrap_lines(text_str: str, font: str, size: int, max_width_mm: float, max_lines: int = 2) -> list[str]:
        s = (text_str or "").strip()
        if not s:
            return [""]
        words = s.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if c.stringWidth(test, font, size) <= mmx(max_width_mm):
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
                if len(lines) >= max_lines:
                    break
        if len(lines) < max_lines and cur:
            lines.append(cur)

        used_words = " ".join(lines).split()
        if len(used_words) < len(words):
            last = lines[-1]
            ell = "..."
            while c.stringWidth(last + ell, font, size) > mmx(max_width_mm) and len(last) > 1:
                last = last[:-1].rstrip()
            lines[-1] = (last + ell).rstrip()

        return lines[:max_lines]

    # =========================
    # GRID CONSTANTS
    # =========================
    PAD_X = 2.0
    PAD_Y = 2.2
    LW_OUT = 1.3
    LW_IN = 1.0
    LW_THIN = 0.7

    left = 18
    right = 210 - 18
    top = 297 - 14
    bottom = 20

    # ===== Header =====
    if os.path.exists(LOGO_PATH):
        try:
            img = ImageReader(LOGO_PATH)
            c.drawImage(img, mmx(left), mmy(top - 26), width=mmx(60), height=mmx(22), mask="auto")
        except Exception:
            pass

    HEADER_C = 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(mmx(left + HEADER_C), mmy(top - 5), "BORDEREL VAN ONTVANGSTEN")
    c.setFont("Helvetica", 9)
    c.drawString(mmx(left + HEADER_C), mmy(top - 11), "Lavendelstraat, 25  9400 NINOVE")
    c.drawString(mmx(left + HEADER_C), mmy(top - 16), "Tel/Fax : 054/33.10.96  *  054/34.37.57")
    c.setFont("Helvetica", 9)
    c.drawString(mmx(left + HEADER_C), mmy(top - 21), "RPR : BE.0.436.658.564")

    # --- FLUO achter enkel "NR Repertorium ..." (1 lijn blijft 1 lijn) ---
    prefix = "facturen@cinemacentral.be --- "
    rep_part = f"Repertorium {week_start_d.year} : {weeknr}"
    x_rep = mmx(left + HEADER_C)
    y_rep = mmy(top - 26)
    prefix_w = c.stringWidth(prefix, "Helvetica", 9)
    rep_w = c.stringWidth(rep_part, "Helvetica", 9)
    c.setFillColor(colors.HexColor("#FFF200"))  # fluo geel
    c.rect(x_rep + prefix_w - 6, y_rep - 1.5, rep_w + 20, 9 + 3, stroke=0, fill=1)
    c.setFillColor(colors.black)
    # ---------------------------------------------------------------

    c.drawString(mmx(left + HEADER_C), mmy(top - 26), f"facturen@cinemacentral.be - NR Repertorium {week_start_d.year}: {weeknr}")
    c.drawString(mmx(left + HEADER_C), mmy(top - 31), "www.cinemacentral.be")

    zaal_txt = f"ZAAL {zaal}".strip()
    c.setFont("Helvetica-Bold", 11)

    xZ = mmx(left)
    yZ = mmy(top - 38)

    # tekst
    c.setFillColor(colors.black)
    c.drawString(xZ, yZ, zaal_txt)

    # cirkel/ovaal rond de tekst
    wZ = c.stringWidth(zaal_txt, "Helvetica-Bold", 11)
    padX, padY = 6, 4  # punten (niet mm)
    c.setLineWidth(1.4)
    c.setStrokeColor(colors.black)
    c.ellipse(xZ - padX, yZ - padY, xZ + wZ + padX, yZ + 11 + padY)

    week_txt = f"Week {week_start_d.strftime('%d %b').lower()} tot {(week_start_d + timedelta(days=6)).strftime('%d %b %Y').lower()}"
    xW = mmx(left + 35)
    yW = mmy(top - 38)

    # fluo blok achter week_txt
    c.setFont("Helvetica-Bold", 11)  # of "Helvetica", 11 als je het niet vet wil
    wW = c.stringWidth(week_txt, "Helvetica-Bold", 11)
    c.setFillColor(colors.HexColor("#FFF200"))
    c.rect(xW - 3, yW - 2.5, wW + 6, 11 + 5, stroke=0, fill=1)
    c.setFillColor(colors.black)

    # tekst erboven
    c.drawString(xW, yW, week_txt)


    # ===== Film header =====
    FILMBOX_DROP_MM = -30.0
    film_x = left
    film_w = right - left
    film_h = 22
    film_y = top - 92 - FILMBOX_DROP_MM
    rect(film_x, film_y, film_w, film_h, lw=LW_OUT)

    col_title = 100
    col_nat = 25
    col_dist = film_w - col_title - col_nat

    vline(film_x + col_title, film_y, film_y + film_h, lw=LW_IN)
    vline(film_x + col_title + col_nat, film_y, film_y + film_h, lw=LW_IN)

    header_h = 6.2
    hline(film_x, film_x + film_w, film_y + film_h - header_h, lw=LW_IN)

    textc(film_x + col_title/2, film_y + film_h - 4.7, "TITEL VAN DE FILM EN VAN DE BIJFILM", font="Helvetica-Bold", size=8)
    textc(film_x + col_title + col_nat/2, film_y + film_h - 4.7, "NATIONALITEIT", font="Helvetica-Bold", size=8)
    textc(film_x + col_title + col_nat + col_dist/2, film_y + film_h - 4.7, "DISTRIBUTEUR", font="Helvetica-Bold", size=8)

    content_base = film_y + PAD_Y + 3.8
    fit_left(film_x + PAD_X, content_base, film_title.upper(), col_title - 2*PAD_X, font="Helvetica-Bold", max_size=18, min_size=10)
    fit_left(film_x + col_title + PAD_X, content_base, land, col_nat - 2*PAD_X, font="Helvetica-Bold", max_size=12, min_size=8)

    dist_font = "Helvetica-Bold"
    dist_size = 10
    while dist_size >= 7:
        lines = wrap_lines(distributeur, dist_font, dist_size, col_dist - 2*PAD_X, max_lines=2)
        if all(c.stringWidth(ln, dist_font, dist_size) <= mmx(col_dist - 2*PAD_X) for ln in lines):
            break
        dist_size -= 1

    dist_x = film_x + col_title + col_nat + PAD_X
    c.setFont(dist_font, dist_size)
    if len(lines) == 1:
        c.drawString(mmx(dist_x), mmy(content_base), lines[0])
    else:
        content_h = film_h - header_h
        mid = film_y + (content_h / 2.0)
        c.drawString(mmx(dist_x), mmy(mid + 2.3), lines[0])
        c.drawString(mmx(dist_x), mmy(mid - 1.7), lines[1])

    # ===== Linker tabellen =====
    tbl_x = left
    tbl_w = 120

    # ---- Tickets table ----
    gt_x = tbl_x
    gt_w = tbl_w
    gt_y = film_y - 47.5
    draw_used_tickets_table_bo1(
        c,
        x_mm=gt_x,
        y_mm=gt_y,
        w_mm=gt_w,
        volw_qty=volw_qty,
        kind_qty=kind_qty,
        volw_price=volw_price,
        kind_price=kind_price,
        volw_amt=volw_amt,
        kind_amt=kind_amt,
        tickets_total=tickets_total,
        gross_total=gross_total,
        outer_lw=2.2,
        inner_lw=1.8,
    )

    # ---- Voorstelling table ----
    TABLES_DROP_MM = 15.0
    vt_x = tbl_x
    vt_w = tbl_w
    vt_h = 130
    vt_y = bottom + 35 - TABLES_DROP_MM

    rect(vt_x, vt_y, vt_w, vt_h, lw=LW_OUT)

    v0, v1, v2, v3 = 28, 18, 20, 22
    v4 = vt_w - (v0 + v1 + v2 + v3)

    # FIX lijnen: binnenlijnen niet door bovenste header
    header1_h = 16
    header2_h = 8
    y_header1_bottom = vt_y + vt_h - header1_h
    y_header2_bottom = y_header1_bottom - header2_h

    vline(vt_x + v0, vt_y, vt_y + vt_h, lw=LW_IN)
    vline(vt_x + v0 + v1 + v2, vt_y, vt_y + vt_h, lw=LW_IN)
    vline(vt_x + v0 + v1, vt_y, y_header1_bottom, lw=LW_IN)
    vline(vt_x + v0 + v1 + v2 + v3, vt_y, y_header1_bottom, lw=LW_IN)

    hline(vt_x, vt_x + vt_w, y_header1_bottom, lw=LW_IN)
    hline(vt_x, vt_x + vt_w, y_header2_bottom, lw=LW_THIN)

    textc(vt_x + v0/2, vt_y + vt_h - 7.2, "Voorstelling", font="Helvetica-Bold", size=8)
    textc_multiline(vt_x + v0 + (v1+v2)/2, vt_y + vt_h - 6.0, ["Betalende", "toeschouwers"], font="Helvetica-Bold", size=7, leading_mm=3.0)
    textc_multiline(vt_x + v0 + v1 + v2 + (v3+v4)/2, vt_y + vt_h - 6.0, ["Bruto", "ontvangst"], font="Helvetica-Bold", size=7, leading_mm=3.0)

    textc(vt_x + v0 + v1/2, vt_y + vt_h - 21, "Aantal", font="Helvetica-Bold", size=7)
    textc(vt_x + v0 + v1 + v2/2, vt_y + vt_h - 21, "Prijs", font="Helvetica-Bold", size=7)
    textc(vt_x + v0 + v1 + v2 + v3/2, vt_y + vt_h - 21, "Opstelsom", font="Helvetica-Bold", size=7)
    textc(vt_x + v0 + v1 + v2 + v3 + v4/2, vt_y + vt_h - 21, "Som", font="Helvetica-Bold", size=7)

    # >>> FIX: kleinere rijhoogte zodat 7 dagen + subtotaal + totaal binnen vt_h passen
    row_h = 12

    y = vt_y + vt_h - 24
    for i in range(7):
        d = week_start_d + timedelta(days=i)
        r = rows_by_date.get(d)
        av = int(r.get("aantal_volw") or 0) if r else 0
        ak = int(r.get("aantal_kind") or 0) if r else 0
        gv = float(r.get("bedrag_volw") or 0.0) if r else 0.0
        gk = float(r.get("bedrag_kind") or 0.0) if r else 0.0
        day_total = gv + gk

        y -= row_h
        hline(vt_x, vt_x + vt_w, y, lw=0.6)

        text(vt_x + PAD_X, y + 7.2, _weekday_full_nl(d), size=8)

        textr(vt_x + v0 + v1 - PAD_X, y + 8.5, str(av), size=8)
        textr(vt_x + v0 + v1 + v2 - PAD_X, y + 8.5, _money(volw_price), size=8)
        textr(vt_x + v0 + v1 + v2 + v3 - PAD_X, y + 8.5, _money(gv), size=8)

        textr(vt_x + v0 + v1 - PAD_X, y + 3.0, str(ak), size=8)
        textr(vt_x + v0 + v1 + v2 - PAD_X, y + 3.0, _money(kind_price), size=8)
        textr(vt_x + v0 + v1 + v2 + v3 - PAD_X, y + 3.0, _money(gk), size=8)

        textr(vt_x + vt_w - PAD_X, y + 3.0, _money(day_total), size=8)

    # -------- SUBTOTAAL (totalen per kolom: volw + kind) --------
    y -= row_h
    hline(vt_x, vt_x + vt_w, y, lw=LW_THIN)

    text(vt_x + PAD_X, y + 7.2, "Subtotaal", font="Helvetica-Bold", size=8)

    # Aantal (volw boven / kind onder)
    textr(vt_x + v0 + v1 - PAD_X, y + 8.5, str(int(volw_qty)), font="Helvetica-Bold", size=8)
    textr(vt_x + v0 + v1 - PAD_X, y + 3.0, str(int(kind_qty)), font="Helvetica-Bold", size=8)

    # Prijs (toon eenheidsprijs ook bij subtotaal)
    textr(vt_x + v0 + v1 + v2 - PAD_X, y + 8.5, _money(volw_price), font="Helvetica-Bold", size=8)
    textr(vt_x + v0 + v1 + v2 - PAD_X, y + 3.0, _money(kind_price), font="Helvetica-Bold", size=8)


    # Opstelsom (volw boven / kind onder)
    textr(vt_x + v0 + v1 + v2 + v3 - PAD_X, y + 8.5, _money(volw_amt), font="Helvetica-Bold", size=8)
    textr(vt_x + v0 + v1 + v2 + v3 - PAD_X, y + 3.0, _money(kind_amt), font="Helvetica-Bold", size=8)

    # Som (totaal bedrag)
    textr(vt_x + vt_w - PAD_X, y + 3.0, _money(gross_total), font="Helvetica-Bold", size=8)

    # -------- TOTAAL (binnen kader) --------
    y -= row_h
    hline(vt_x, vt_x + vt_w, y, lw=LW_IN)

    text(vt_x + PAD_X, y + 5.3, "TOTAAL", font="Helvetica-Bold", size=9)
    textr(vt_x + vt_w - PAD_X, y + 5.3, _money(gross_total), font="Helvetica-Bold", size=9)

    # ===== Rechterkant berekeningentabel =====
    rb_x = vt_x + vt_w + 12
    rb_w = right - rb_x
    rb_y = vt_y
    rb_h = vt_h

    rect(rb_x, rb_y, rb_w, rb_h, lw=LW_OUT)
    label_w = rb_w * 0.62
    vline(rb_x + label_w, rb_y, rb_y + rb_h, lw=LW_IN)

    rows = [
        ("Bruto-Ontvangst.", _money(gross_total), "Helvetica", 9),
        (f"BTW {btw_rate*100:.2f} %".replace(".", ","), _money(btw_total), "Helvetica", 9),
        ("Netto-Ontvangst", _money(netto_total), "Helvetica-Bold", 8),
        ("Auteursrechten", _money(auteurs_total), "Helvetica", 9),
        ("Verschil", _money(verschil), "Helvetica-Bold", 10),
    ]

    row_h2 = rb_h / len(rows)
    yrow = rb_y + rb_h
    for i, (lbl, val, fnt, fsz) in enumerate(rows):
        yrow -= row_h2
        if i > 0:
            hline(rb_x, rb_x + rb_w, yrow, lw=LW_THIN)

        ty = yrow + (row_h2 / 2) - 2.2
        text(rb_x + PAD_X, ty, lbl, font=fnt, size=fsz)
        textr(rb_x + rb_w - PAD_X, ty, val, font=fnt, size=fsz)

    # ===== Onderlijn =====
    BOTTOMLINE=10
    text(left, bottom + BOTTOMLINE, "Te NINOVE", size=9)
    text(left + 22, bottom + BOTTOMLINE, week_start_d.strftime("%d %b %Y").lower(), size=9)
    text(left + 70, bottom + BOTTOMLINE, "Oprecht en volledig verklaard", size=9)
    textr(right, bottom + BOTTOMLINE, "Handtekening,", size=9)

    c.save()


# =========================
# Calendar Picker (modal) – JOUW EXACTE KALENDER
# =========================
class DatePickerDialog(tk.Toplevel):
    def __init__(self, parent, title: str, initial: date):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._selected: date | None = None
        self._view_year = initial.year
        self._view_month = initial.month
        self._sel_date = initial

        outer = tk.Frame(self, padx=12, pady=12, bg="white")
        outer.pack(fill="both", expand=True)

        hdr = tk.Frame(outer, bg="white")
        hdr.pack(fill="x")

        tk.Button(hdr, text="◀", width=3, command=self._prev_month).pack(side="left")
        self.lbl_title = tk.Label(hdr, text="", bg="white", fg="black", font=("Arial", 14, "bold"))
        self.lbl_title.pack(side="left", expand=True, fill="x", padx=8)
        tk.Button(hdr, text="▶", width=3, command=self._next_month).pack(side="right")

        wdays = tk.Frame(outer, bg="white")
        wdays.pack(fill="x", pady=(10, 4))
        for i, name in enumerate(["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]):
            tk.Label(wdays, text=name, width=4, bg="white", fg="black", font=("Arial", 11, "bold")).grid(
                row=0, column=i
            )

        self.grid_frame = tk.Frame(outer, bg="white")
        self.grid_frame.pack()

        btns = tk.Frame(outer, bg="white")
        btns.pack(fill="x", pady=(10, 0))
        tk.Button(btns, text="Annuleren", command=self._cancel).pack(side="right")
        tk.Button(btns, text="OK", command=self._ok).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Return>", lambda e: self._ok())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._render_month()

        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w)//2}+{py + (ph - h)//2}")

    @property
    def selected(self):
        return self._selected

    def _prev_month(self):
        if self._view_month == 1:
            self._view_month = 12
            self._view_year -= 1
        else:
            self._view_month -= 1
        self._render_month()

    def _next_month(self):
        if self._view_month == 12:
            self._view_month = 1
            self._view_year += 1
        else:
            self._view_month += 1
        self._render_month()

    def _render_month(self):
        self.lbl_title.config(text=f"{calendar.month_name[self._view_month]} {self._view_year}")

        for child in self.grid_frame.winfo_children():
            child.destroy()

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdayscalendar(self._view_year, self._view_month)
        while len(weeks) < 6:
            weeks.append([0, 0, 0, 0, 0, 0, 0])

        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                if day == 0:
                    tk.Label(self.grid_frame, text=" ", width=4, height=2, bg="white").grid(
                        row=r, column=c, padx=2, pady=2
                    )
                    continue

                d = date(self._view_year, self._view_month, day)
                is_selected = (d == self._sel_date)
                bg = "red" if is_selected else "white"
                fg = "black"

                btn = tk.Button(
                    self.grid_frame,
                    text=str(day),
                    width=4,
                    height=2,
                    bg=bg,
                    fg=fg,
                    bd=2 if is_selected else 1,
                    relief="solid",
                    command=lambda dd=d: self._set_selected(dd),
                )
                btn.grid(row=r, column=c, padx=2, pady=2)

    def _set_selected(self, d: date):
        self._sel_date = d
        self._render_month()

    def _ok(self):
        self._selected = self._sel_date
        self.destroy()

    def _cancel(self):
        self._selected = None
        self.destroy()


class DateField(ttk.Frame):
    def __init__(self, parent, label: str, initial: date):
        super().__init__(parent)
        self.var = tk.StringVar(value=initial.strftime("%Y-%m-%d"))

        ttk.Label(self, text=label).pack(side="left")
        self.entry = ttk.Entry(self, textvariable=self.var, width=12, state="readonly")
        self.entry.pack(side="left", padx=(6, 6))
        ttk.Button(self, text="📅", width=3, command=self.pick).pack(side="left")

    def pick(self):
        current = datetime.strptime(self.var.get(), "%Y-%m-%d").date()
        dlg = DatePickerDialog(self.winfo_toplevel(), "Kies datum", current)
        self.wait_window(dlg)
        if dlg.selected:
            self.var.set(dlg.selected.strftime("%Y-%m-%d"))

    def get_date(self) -> date:
        return datetime.strptime(self.var.get(), "%Y-%m-%d").date()

    def set_date(self, d: date):
        self.var.set(d.strftime("%Y-%m-%d"))


# =========================
# UI App (jouw volledige project)
# =========================
class SumUpFilmApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Cinema BackOffice – SumUp Filmrapport")
        self.root.geometry("1400x860")

        self.unit_prices = {}
        self._active_item = None
        self._active_col_index = None
        self._active_value = None

        self._build_ui()
        self._bind_copy_shortcuts()
        self._load_settings_into_ui()

    def _build_ui(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True)

        self.tab_import = ttk.Frame(self.nb, padding=10)
        self.tab_history = ttk.Frame(self.nb, padding=10)
        self.tab_settings = ttk.Frame(self.nb, padding=10)

        self.nb.add(self.tab_import, text="Import (CSV)")
        self.nb.add(self.tab_history, text="Historiek")
        self.nb.add(self.tab_settings, text="Instellingen")

        self._build_import_tab()
        self._build_history_tab()
        self._build_settings_tab()

    # -----------------------------
    # Import tab
    # -----------------------------
    def _build_import_tab(self):
        top = ttk.Frame(self.tab_import)
        top.pack(fill="x")

        ttk.Button(top, text="CSV openen & opslaan in DB", command=self.open_csv).pack(side="left")
        ttk.Button(top, text="Exporteren (huidige tabel)", command=self.export_csv).pack(side="left", padx=8)

        self.status = tk.StringVar(value="Klaar.")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=20)

        mid = ttk.Frame(self.tab_import)
        mid.pack(fill="both", expand=True, pady=(10, 0))

        self.columns = (
            "Film",
            "Zaal",
            "3D",
            "Aantal volwassenen",
            "Aantal kinderen",
            "Bedrag volwassenen",
            "Bedrag kinderen",
            "Totaal aantal",
            "Totaal bedrag",
        )

        self.tree = ttk.Treeview(mid, columns=self.columns, show="headings", selectmode="browse")
        for col in self.columns:
            self.tree.heading(col, text=col)
            if col == "Film":
                self.tree.column(col, width=320, anchor="w")
            elif col == "Zaal":
                self.tree.column(col, width=110, anchor="center")
            elif col == "3D":
                self.tree.column(col, width=60, anchor="center")
            else:
                self.tree.column(col, width=150, anchor="center")

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._start_edit)
        self.tree.bind("<Button-1>", self._on_left_click, add=True)
        self.tree.bind("<Button-3>", self._on_right_click, add=True)
        self.tree.bind("<Button-2>", self._on_right_click, add=True)
        self.tree.bind("<Control-Button-1>", self._on_right_click, add=True)

        bottom = ttk.Frame(self.tab_import)
        bottom.pack(fill="x", pady=(10, 0))

        self.total_label = tk.StringVar(value="Totaal tickets: 0 | Totaal bedrag: 0,00")
        ttk.Label(bottom, textvariable=self.total_label).pack(anchor="w")

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Kopieer", command=self.copy_active_cell_to_clipboard)

    def _bind_copy_shortcuts(self):
        self.root.bind_all("<Control-c>", lambda e: self.copy_active_cell_to_clipboard())
        self.root.bind_all("<Control-C>", lambda e: self.copy_active_cell_to_clipboard())
        self.root.bind_all("<Command-c>", lambda e: self.copy_active_cell_to_clipboard())
        self.root.bind_all("<Command-C>", lambda e: self.copy_active_cell_to_clipboard())

    def _on_left_click(self, event):
        self._set_active_cell_from_event(event)

    def _on_right_click(self, event):
        self._set_active_cell_from_event(event)
        if self._active_value is None:
            return
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _set_active_cell_from_event(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            self._active_item = None
            self._active_col_index = None
            self._active_value = None
            return

        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or not col:
            self._active_item = None
            self._active_col_index = None
            self._active_value = None
            return

        col_index = int(col.replace("#", "")) - 1
        values = self.tree.item(item, "values")

        self.tree.focus(item)
        self.tree.selection_set(item)

        self._active_item = item
        self._active_col_index = col_index
        self._active_value = values[col_index] if col_index < len(values) else None

    def copy_active_cell_to_clipboard(self):
        text = None
        if self._active_item is not None and self._active_col_index is not None:
            if self._active_value is not None:
                text = str(self._active_value)

        if not text:
            sel = self.tree.selection()
            if sel:
                vals = self.tree.item(sel[0], "values")
                text = "\t".join(str(v) for v in vals)

        if not text:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.status.set("Gekopieerd naar klembord.")

    # -----------------------------
    # CSV import + DB save
    # -----------------------------
    def open_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV bestanden", "*.csv")])
        if not path:
            return

        default_d = date.today().strftime("%Y-%m-%d")
        d_str = simpledialog.askstring(
            "Datum kiezen",
            "Voor welke datum is deze CSV? (YYYY-MM-DD)",
            initialvalue=default_d,
            parent=self.root,
        )
        if not d_str:
            return
        try:
            d = datetime.strptime(d_str.strip(), "%Y-%m-%d").date()
        except Exception:
            messagebox.showerror("Fout", "Ongeldige datum. Gebruik formaat YYYY-MM-DD.")
            return

        try:
            df = pd.read_csv(path)
        except Exception as e:
            messagebox.showerror("Fout", f"CSV kon niet gelezen worden:\n\n{e}")
            return

        df = df[df["Categorie"].astype(str).str.lower() == "film"].copy()

        film_zaal = df["Naam van variant"].apply(detect_film_and_zaal)
        df["Film"] = film_zaal.apply(lambda x: x[0])
        df["Zaal"] = film_zaal.apply(lambda x: x[1])

        df["Aantal"] = pd.to_numeric(df.get("Aantal", 0), errors="coerce").fillna(0)
        df["Bedrag"] = pd.to_numeric(df.get("Bedrag", 0), errors="coerce").fillna(0)

        name = df["Naam van artikel"].astype(str)
        df["IsKind"] = name.str.contains("kind", case=False, na=False)
        df["Is3D"] = name.str.contains("3d", case=False, na=False)

        df["AantalVolw"] = df["Aantal"].where(~df["IsKind"], 0)
        df["AantalKind"] = df["Aantal"].where(df["IsKind"], 0)
        df["BedragVolw"] = df["Bedrag"].where(~df["IsKind"], 0)
        df["BedragKind"] = df["Bedrag"].where(df["IsKind"], 0)

        summary = (
            df.groupby(["Film", "Zaal"], as_index=False)
            .agg(
                AantalVolw=("AantalVolw", "sum"),
                AantalKind=("AantalKind", "sum"),
                BedragVolw=("BedragVolw", "sum"),
                BedragKind=("BedragKind", "sum"),
                Is3D=("Is3D", "any"),
            )
        )
        summary["TotaalAantal"] = summary["AantalVolw"] + summary["AantalKind"]
        summary["TotaalBedrag"] = summary["BedragVolw"] + summary["BedragKind"]

        try:
            speelweek_id, weeknummer = db_get_or_create_speelweek(d)
        except Exception as e:
            messagebox.showerror("DB fout", f"Kon speelweek niet ophalen/aanmaken:\n\n{e}")
            return

        self.tree.delete(*self.tree.get_children())
        self.unit_prices.clear()

        for _, row in summary.iterrows():
            film_titel = str(row["Film"]).strip()
            zaal = str(row["Zaal"]).strip() if str(row["Zaal"]).strip() else ""
            if not film_titel:
                continue

            film = db_get_film_by_interne_titel(film_titel)
            if not film:
                maccs = simpledialog.askstring(
                    "Nieuwe film",
                    f"Maccsbox filmtitel voor:\n{film_titel}",
                    initialvalue=film_titel,
                    parent=self.root,
                )
                if not maccs:
                    continue

                distr = simpledialog.askstring("Nieuwe film", f"Distributeur voor:\n{film_titel}", parent=self.root)
                if distr is None:
                    continue

                land = simpledialog.askstring("Nieuwe film", f"Land van herkomst voor:\n{film_titel}", parent=self.root)
                if land is None:
                    continue

                try:
                    film_id = db_create_film(film_titel, maccs.strip(), distr.strip(), land.strip())
                    film = {"id": film_id}
                except Exception as e:
                    messagebox.showerror("DB fout", f"Kon film niet opslaan:\n\n{e}")
                    continue

            film_id = int(film["id"])

            if not zaal:
                zaal = (simpledialog.askstring("Zaal ontbreekt", f"Welke zaal voor:\n{film_titel} ?", parent=self.root) or "").strip()

            zaal_id = db_get_or_create_zaal(zaal) if zaal else None

            aantal_volw = int(row["AantalVolw"])
            aantal_kind = int(row["AantalKind"])
            bedrag_volw = float(row["BedragVolw"])
            bedrag_kind = float(row["BedragKind"])
            totaal_aantal = int(row["TotaalAantal"])
            totaal_bedrag = float(row["TotaalBedrag"])
            is_3d = bool(row["Is3D"])

            try:
                db_upsert_daily_sales(
                    datum=d,
                    speelweek_id=speelweek_id,
                    film_id=film_id,
                    zaal_id=zaal_id,
                    is_3d=is_3d,
                    aantal_volw=aantal_volw,
                    aantal_kind=aantal_kind,
                    bedrag_volw=bedrag_volw,
                    bedrag_kind=bedrag_kind,
                    totaal_aantal=totaal_aantal,
                    totaal_bedrag=totaal_bedrag,
                    source_file=os.path.basename(path),
                )
            except Exception as e:
                messagebox.showerror("DB fout", f"Kon daily_sales niet opslaan voor {film_titel} ({zaal}):\n\n{e}")
                continue

            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    film_titel,
                    zaal,
                    "✅" if is_3d else "",
                    int(aantal_volw),
                    int(aantal_kind),
                    f"{bedrag_volw:.2f}",
                    f"{bedrag_kind:.2f}",
                    int(totaal_aantal),
                    f"{totaal_bedrag:.2f}",
                ),
            )

            volw_price = (bedrag_volw / aantal_volw) if aantal_volw > 0 else None
            kind_price = (bedrag_kind / aantal_kind) if aantal_kind > 0 else None
            self.unit_prices[item_id] = {"volw": volw_price, "kind": kind_price}

        self.status.set(f"Geladen + opgeslagen: {os.path.basename(path)} | Datum: {d.isoformat()} | Speelweek: {weeknummer}")
        self._update_totals()

        self.hist_from.set_date(d)
        self.hist_to.set_date(d)
        self.refresh_history()

    # -----------------------------
    # Edit aantal (UI only)
    # -----------------------------
    def _start_edit(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        col_index = int(col.replace("#", "")) - 1
        col_name = self.columns[col_index]

        if col_name not in ["Aantal volwassenen", "Aantal kinderen"]:
            return

        x, y, w, h = self.tree.bbox(item, col)
        value = self.tree.item(item, "values")[col_index]

        entry = ttk.Entry(self.tree)
        entry.insert(0, value)
        entry.select_range(0, tk.END)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus()

        entry.bind("<Return>", lambda e: self._finish_edit(entry, item, col_name))
        entry.bind("<Escape>", lambda e: entry.destroy())
        entry.bind("<FocusOut>", lambda e: self._finish_edit(entry, item, col_name))

    def _finish_edit(self, entry, item, col_name):
        try:
            new_aantal = int(entry.get())
            if new_aantal < 0:
                raise ValueError()
        except Exception:
            entry.destroy()
            return

        values = list(self.tree.item(item, "values"))

        if col_name == "Aantal volwassenen":
            index_aantal = 3
            index_bedrag = 5
            unit_key = "volw"
        else:
            index_aantal = 4
            index_bedrag = 6
            unit_key = "kind"

        unit = self.unit_prices.get(item, {}).get(unit_key)

        if unit is None and new_aantal > 0:
            price = simpledialog.askfloat(
                "Eenheidsprijs nodig",
                f"Geef eenheidsprijs voor {values[0]}",
                parent=self.root,
            )
            if price is None:
                entry.destroy()
                return
            unit = float(price)
            self.unit_prices[item][unit_key] = unit

        new_bedrag = (unit * new_aantal) if unit else 0.0
        values[index_aantal] = new_aantal
        values[index_bedrag] = f"{new_bedrag:.2f}"

        totaal_aantal = int(values[3]) + int(values[4])
        totaal_bedrag = float(values[5]) + float(values[6])
        values[7] = totaal_aantal
        values[8] = f"{totaal_bedrag:.2f}"

        self.tree.item(item, values=values)
        entry.destroy()
        self.root.focus_set()
        self._update_totals()

    def _update_totals(self):
        totaal_aantal = 0
        totaal_bedrag = 0.0
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            totaal_aantal += int(vals[7])
            totaal_bedrag += float(vals[8])

        self.total_label.set(
            f"Totaal tickets: {totaal_aantal} | Totaal bedrag: {totaal_bedrag:.2f}".replace(".", ",")
        )

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if not path:
            return
        rows = []
        for item in self.tree.get_children():
            rows.append(dict(zip(self.columns, self.tree.item(item, "values"))))
        pd.DataFrame(rows).to_csv(path, index=False)
        messagebox.showinfo("Export", "CSV succesvol opgeslagen.")

    # -----------------------------
    # Historiek tab + PDF export (met jouw kalender)
    # -----------------------------
    def _build_history_tab(self):
        top = ttk.Frame(self.tab_history)
        top.pack(fill="x")

        self.hist_from = DateField(top, "Van:", date.today() - timedelta(days=7))
        self.hist_from.pack(side="left", padx=(0, 18))

        self.hist_to = DateField(top, "Tot:", date.today())
        self.hist_to.pack(side="left", padx=(0, 18))

        ttk.Button(top, text="Vernieuwen", command=self.refresh_history).pack(side="left")
        ttk.Button(top, text="Export historiek (CSV)", command=self.export_history_csv).pack(side="left", padx=8)
        ttk.Button(top, text="Export PDF's (BO1)", command=self.export_borderels_pdf_bo1).pack(side="left", padx=8)

        self.hist_status = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.hist_status).pack(side="left", padx=20)

        mid = ttk.Frame(self.tab_history)
        mid.pack(fill="both", expand=True, pady=(10, 0))

        self.hist_cols = (
            "Datum",
            "Speelweek",
            "Week start",
            "Week eind",
            "Film",
            "Zaal",
            "3D",
            "Volw",
            "Kind",
            "Bedrag volw",
            "Bedrag kind",
            "Totaal",
            "Totaal bedrag",
        )

        self.hist_tree = ttk.Treeview(mid, columns=self.hist_cols, show="headings")
        for ccol in self.hist_cols:
            self.hist_tree.heading(ccol, text=ccol)
            if ccol == "Film":
                self.hist_tree.column(ccol, width=320, anchor="w")
            elif ccol == "Zaal":
                self.hist_tree.column(ccol, width=110, anchor="center")
            elif ccol == "3D":
                self.hist_tree.column(ccol, width=60, anchor="center")
            else:
                self.hist_tree.column(ccol, width=130, anchor="center")

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=vsb.set)

        self.hist_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._history_cache = []

    def refresh_history(self):
        f = self.hist_from.get_date()
        t = self.hist_to.get_date()
        if t < f:
            messagebox.showerror("Fout", "‘Tot’ mag niet vóór ‘Van’ liggen.")
            return

        try:
            rows = db_fetch_history(f, t)
        except Exception as e:
            messagebox.showerror("DB fout", f"Kon historiek niet ophalen:\n\n{e}")
            return

        self._history_cache = rows
        self.hist_tree.delete(*self.hist_tree.get_children())

        for r in rows:
            self.hist_tree.insert(
                "",
                "end",
                values=(
                    str(r["datum"]),
                    str(r["weeknummer"]),
                    str(r["start_datum"]),
                    str(r["eind_datum"]),
                    r["interne_titel"],
                    r["zaal"] or "",
                    "✅" if int(r["is_3d"]) == 1 else "",
                    int(r["aantal_volw"]),
                    int(r["aantal_kind"]),
                    f"{float(r['bedrag_volw']):.2f}",
                    f"{float(r['bedrag_kind']):.2f}",
                    int(r["totaal_aantal"]),
                    f"{float(r['totaal_bedrag']):.2f}",
                ),
            )

        self.hist_status.set(f"{len(rows)} records")

    def export_history_csv(self):
        if not self._history_cache:
            messagebox.showinfo("Info", "Geen historiek data om te exporteren.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if not path:
            return
        pd.DataFrame(self._history_cache).to_csv(path, index=False)
        messagebox.showinfo("Export", "Historiek CSV opgeslagen.")

    def export_borderels_pdf_bo1(self):
        f = self.hist_from.get_date()
        t = self.hist_to.get_date()
        if t < f:
            messagebox.showerror("Fout", "‘Tot’ mag niet vóór ‘Van’ liggen.")
            return

        folder = filedialog.askdirectory(title="Kies map voor PDF export")
        if not folder:
            return

        btw_rate = db_get_float_setting("btw_rate", DEFAULT_BTW_RATE)
        auteurs_rate = db_get_float_setting("auteurs_rate", DEFAULT_AUTEURS_RATE)

        try:
            combos = db_fetch_borderel_combos(f, t)
        except Exception as e:
            messagebox.showerror("DB fout", f"Kon PDF export data niet ophalen:\n\n{e}")
            return

        if not combos:
            messagebox.showinfo("Info", "Geen records in deze periode om PDF’s te genereren.")
            return

        ok = 0
        fail = 0
        errors = []

        for c_ in combos:
            speelweek_id = int(c_["speelweek_id"])
            film_id = int(c_["film_id"])
            zaal_naam = (c_.get("zaal") or "").strip()

            try:
                week_rows = db_fetch_week_sales_for_film_zaal(speelweek_id, film_id, zaal_naam)
                if not week_rows:
                    continue
                weeknr_ = int(c_.get("weeknummer") or 0)
                distributeur_ = (c_.get("distributeur") or "").strip()
                film_title_ = (c_.get("maccsbox_titel") or c_.get("interne_titel") or "FILM").strip()

                fname = f"BO {weeknr_} {_safe_filename(distributeur_)} {_safe_filename(film_title_)}.pdf"
                out_path = os.path.join(folder, fname)

                

                generate_borderel_bo1_pdf(out_path, week_rows, btw_rate=btw_rate, auteurs_rate=auteurs_rate)
                ok += 1
            except Exception as e:
                fail += 1
                errors.append(f"{c_.get('interne_titel')} ({zaal_naam}) week {c_.get('weeknummer')}: {e}")

        if fail == 0:
            messagebox.showinfo("Klaar", f"{ok} PDF('s) gegenereerd in:\n{folder}")
        else:
            msg = f"{ok} gelukt, {fail} mislukt.\n\nMap:\n{folder}\n\nEerste fouten:\n- " + "\n- ".join(errors[:6])
            messagebox.showwarning("Klaar (met fouten)", msg)

    # -----------------------------
    # Instellingen tab
    # -----------------------------
    def _build_settings_tab(self):
        frm = ttk.Frame(self.tab_settings)
        frm.pack(fill="x", pady=10)

        ttk.Label(frm, text="Speelweek startdag:").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        self.weekday_var = tk.StringVar(value="Dinsdag")
        self.weekday_combo = ttk.Combobox(
            frm, textvariable=self.weekday_var, values=WEEKDAY_LABELS, state="readonly", width=18
        )
        self.weekday_combo.grid(row=0, column=1, sticky="w", pady=6)

        ttk.Label(frm, text="Week teller (volgende nieuwe speelweek):").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=6
        )
        self.week_counter_var = tk.StringVar(value="1")
        ttk.Entry(frm, textvariable=self.week_counter_var, width=10).grid(row=1, column=1, sticky="w", pady=6)

        ttk.Label(frm, text="BTW % (bv 5,66):").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=6)
        self.btw_percent_var = tk.StringVar(value="5,66")
        ttk.Entry(frm, textvariable=self.btw_percent_var, width=10).grid(row=2, column=1, sticky="w", pady=6)

        ttk.Label(frm, text="Auteursrechten % op NETTO (bv 1,20):").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=6)
        self.auteurs_percent_var = tk.StringVar(value="1,20")
        ttk.Entry(frm, textvariable=self.auteurs_percent_var, width=10).grid(row=3, column=1, sticky="w", pady=6)

        ttk.Button(frm, text="Opslaan", command=self.save_settings).grid(row=4, column=1, sticky="w", pady=(12, 6))

        self.settings_status = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.settings_status).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

        frm.columnconfigure(2, weight=1)

    def _load_settings_into_ui(self):
        ws = db_get_week_start_weekday()
        self.weekday_var.set(WEEKDAY_TO_LABEL.get(ws, "Dinsdag"))

        wc = db_get_setting("week_counter") or "1"
        self.week_counter_var.set(str(wc))

        btw = db_get_float_setting("btw_rate", DEFAULT_BTW_RATE) * 100.0
        aut = db_get_float_setting("auteurs_rate", DEFAULT_AUTEURS_RATE) * 100.0
        self.btw_percent_var.set(f"{btw:.2f}".replace(".", ","))
        self.auteurs_percent_var.set(f"{aut:.2f}".replace(".", ","))

    def save_settings(self):
        lbl = self.weekday_var.get()
        ws = LABEL_TO_WEEKDAY.get(lbl, 1)
        db_set_setting("week_start_weekday", str(ws))

        try:
            wc = int(self.week_counter_var.get().strip())
            if wc < 1:
                raise ValueError()
        except Exception:
            messagebox.showerror("Fout", "Week teller moet een positief getal zijn (>= 1).")
            return
        db_set_setting("week_counter", str(wc))

        try:
            btw_rate = _parse_percent_to_rate(self.btw_percent_var.get())
            aut_rate = _parse_percent_to_rate(self.auteurs_percent_var.get())
            if btw_rate < 0 or aut_rate < 0:
                raise ValueError()
        except Exception:
            messagebox.showerror("Fout", "BTW% en Auteurs% moeten geldige getallen zijn (bv 5,66 en 1,20).")
            return

        db_set_float_setting("btw_rate", btw_rate)
        db_set_float_setting("auteurs_rate", aut_rate)

        self.settings_status.set("Instellingen opgeslagen.")
        self.status.set("Instellingen opgeslagen.")


def main():
    root = tk.Tk()
    app = SumUpFilmApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
