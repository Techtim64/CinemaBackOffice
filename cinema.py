import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import date, datetime, timedelta

import pandas as pd
from mysql.connector import pooling

import calendar



# =========================
# CONFIG - vul dit in
# =========================
DB_CONFIG = {
    "host": "172.20.18.2",
    "port": 3306,
    "user": "cinema_user",
    "password": "Cinema1919!",
    "database": "cinema_db",
}

POOL = pooling.MySQLConnectionPool(pool_name="cinema_pool", pool_size=5, **DB_CONFIG)


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


ZAAL_RE = re.compile(r"\bzaal\s*\d+\b", re.IGNORECASE)


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

    # Zaal mapping
    if "zaal beneden" in s:
        zaal = "1"
    elif "zaal boven" in s:
        zaal = "2"
    else:
        zaal = ""

    # Film extractie (zoals je eerder deed: tweede deel)
    parts = extract_variant_parts(variant)
    if len(parts) >= 2:
        film = parts[1]
    elif parts:
        film = parts[0]
    else:
        film = ""

    return film.strip(), zaal



WEEKDAY_LABELS = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
LABEL_TO_WEEKDAY = {lbl: i for i, lbl in enumerate(WEEKDAY_LABELS)}
WEEKDAY_TO_LABEL = {i: lbl for i, lbl in enumerate(WEEKDAY_LABELS)}


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
# Calendar Picker (modal)
# =========================
class DatePickerDialog(tk.Toplevel):
    """
    Cross-platform calendar popup (no tkcalendar).
    - Month/year navigation
    - Grid of day buttons
    - Selected day: black background, white text, visible border
    - Returns a Python `date` in .selected
    """
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

        # --- layout ---
        outer = tk.Frame(self, padx=12, pady=12, bg="white")
        outer.pack(fill="both", expand=True)

        # Header: prev / month-year / next
        hdr = tk.Frame(outer, bg="white")
        hdr.pack(fill="x")

        self.btn_prev = tk.Button(hdr, text="◀", width=3, command=self._prev_month)
        self.btn_prev.pack(side="left")

        self.lbl_title = tk.Label(hdr, text="", bg="white", fg="black", font=("Arial", 14, "bold"))
        self.lbl_title.pack(side="left", expand=True, fill="x", padx=8)

        self.btn_next = tk.Button(hdr, text="▶", width=3, command=self._next_month)
        self.btn_next.pack(side="right")

        # Weekday labels
        wdays = tk.Frame(outer, bg="white")
        wdays.pack(fill="x", pady=(10, 4))

        # Start on Monday (like your app)
        self._weekday_names = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
        for i, name in enumerate(self._weekday_names):
            tk.Label(wdays, text=name, width=4, bg="white", fg="black", font=("Arial", 11, "bold")).grid(row=0, column=i)

        # Grid for days
        self.grid_frame = tk.Frame(outer, bg="white")
        self.grid_frame.pack()

        # Buttons row
        btns = tk.Frame(outer, bg="white")
        btns.pack(fill="x", pady=(10, 0))
        tk.Button(btns, text="Annuleren", command=self._cancel).pack(side="right")
        tk.Button(btns, text="OK", command=self._ok).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Return>", lambda e: self._ok())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        # Render month
        self._render_month()

        # Center popup
        self.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        w = self.winfo_width()
        h = self.winfo_height()
        self.geometry(f"+{px + (pw - w)//2}+{py + (ph - h)//2}")

    @property
    def selected(self):
        return self._selected

    # ---------- navigation ----------
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

    # ---------- rendering ----------
    def _render_month(self):
        # Title
        month_name = calendar.month_name[self._view_month]
        self.lbl_title.config(text=f"{month_name} {self._view_year}")

        # Clear old grid
        for child in self.grid_frame.winfo_children():
            child.destroy()

        cal = calendar.Calendar(firstweekday=0)  # 0 = Monday
        weeks = cal.monthdayscalendar(self._view_year, self._view_month)

        # Ensure 6 rows for stable size
        while len(weeks) < 6:
            weeks.append([0, 0, 0, 0, 0, 0, 0])

        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                if day == 0:
                    # empty cell
                    lbl = tk.Label(self.grid_frame, text=" ", width=4, height=2, bg="white")
                    lbl.grid(row=r, column=c, padx=2, pady=2)
                    continue

                d = date(self._view_year, self._view_month, day)
                is_selected = (d == self._sel_date)

                # Selected style: black bg, white fg, visible border
                if is_selected:
                    bg, fg = "red", "black"
                    bd, relief, hl = 4, "solid", 1
                else:
                    bg, fg = "white", "black"
                    bd, relief, hl = 1, "solid", 0

                btn = tk.Button(
                    self.grid_frame,
                    text=str(day),
                    width=4,
                    height=2,
                    bg=bg,
                    fg=fg,
                    activebackground="black",
                    activeforeground="white",
                    bd=bd,
                    relief=relief,
                    highlightthickness=hl,
                    highlightbackground="red",
                    command=lambda dd=d: self._set_selected(dd),
                )
                btn.grid(row=r, column=c, padx=2, pady=2)

    def _set_selected(self, d: date):
        self._sel_date = d
        # If user clicks a day in another month view (not possible here), you'd adjust view.
        self._render_month()

    # ---------- actions ----------
    def _ok(self):
        self._selected = self._sel_date
        self.destroy()

    def _cancel(self):
        self._selected = None
        self.destroy()



class DateField(ttk.Frame):
    """Readonly field + calendar popup button."""
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
# UI App
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

        # Import pane shows only what you want
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

        # ✅ import date = typed input (like before), NO calendar
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

        self.status.set(
            f"Geladen + opgeslagen: {os.path.basename(path)} | Datum: {d.isoformat()} | Speelweek: {weeknummer}"
        )
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

        # columns: 0 Film, 1 Zaal, 2 3D, 3 av, 4 ak, 5 bv, 6 bk, 7 ta, 8 tb
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
    # History tab (calendar popup fields)
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
        for c in self.hist_cols:
            self.hist_tree.heading(c, text=c)
            if c == "Film":
                self.hist_tree.column(c, width=320, anchor="w")
            elif c == "Zaal":
                self.hist_tree.column(c, width=110, anchor="center")
            elif c == "3D":
                self.hist_tree.column(c, width=60, anchor="center")
            else:
                self.hist_tree.column(c, width=130, anchor="center")

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
        df = pd.DataFrame(self._history_cache)
        df.to_csv(path, index=False)
        messagebox.showinfo("Export", "Historiek CSV opgeslagen.")

    # -----------------------------
    # Settings tab
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

        ttk.Button(frm, text="Opslaan", command=self.save_settings).grid(row=2, column=1, sticky="w", pady=(12, 6))

        self.settings_status = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.settings_status).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        frm.columnconfigure(2, weight=1)

    def _load_settings_into_ui(self):
        ws = db_get_week_start_weekday()
        self.weekday_var.set(WEEKDAY_TO_LABEL.get(ws, "Dinsdag"))
        wc = db_get_setting("week_counter") or "1"
        self.week_counter_var.set(str(wc))

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

        self.settings_status.set("Instellingen opgeslagen.")
        self.status.set("Instellingen opgeslagen.")


def main():
    root = tk.Tk()
    app = SumUpFilmApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
