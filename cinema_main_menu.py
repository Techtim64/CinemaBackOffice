import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from cinema_affiche import open_window as open_affiche_window
from cinema_borderel import open_window as open_borderel_window


def resource_path(*parts) -> Path:
    """
    Dev + PyInstaller path resolver.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base, *parts)
    return Path(__file__).resolve().parent.joinpath(*parts)


# Windows logo Helper
def set_window_icon(win):
    """
    Sets window/taskbar icon for Tk windows.
    - Windows: uses .ico via iconbitmap
    - Fallback: uses PNG via iconphoto
    Works in dev + PyInstaller (onedir/onefile).
    """
    # Windows: prefer .ico
    try:
        ico_path = resource_path("assets", "CinemaCentral.ico")
        if sys.platform.startswith("win") and ico_path.exists():
            try:
                win.iconbitmap(str(ico_path))
                return
            except Exception:
                pass
    except Exception:
        pass

    # Fallback: PNG (cross-platform)
    try:
        png_path = resource_path("assets", "CinemaCentral_1024.png")
        if png_path.exists():
            img = tk.PhotoImage(file=str(png_path))
            win.iconphoto(True, img)
            win._app_icon_ref = img  # keep reference
    except Exception:
        pass


def _mysql_config_from_env():
    return {
        "host": os.environ.get("MYSQL_HOST", "172.20.18.2"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "cinema_user"),
        "password": os.environ.get("MYSQL_PASSWORD", "Cinema1919!"),
        "database": os.environ.get("MYSQL_DATABASE", "cinema_db"),
    }


def _check_mysql_connection(timeout_sec: int = 3) -> tuple[bool, str]:
    """
    Returns: (ok, error_message)
    """
    try:
        import mysql.connector  # mysql-connector-python
    except Exception as e:
        return False, f"MySQL driver ontbreekt (mysql-connector-python).\n\nDetails:\n{e}"

    cfg = _mysql_config_from_env()
    try:
        cn = mysql.connector.connect(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            connection_timeout=timeout_sec,
        )
        try:
            cur = cn.cursor()
            cur.execute("SELECT 1;")
            cur.fetchone()
        finally:
            cn.close()
        return True, ""
    except Exception as e:
        msg = (
            "Kan geen verbinding maken met de Cinema-database.\n\n"
            f"Server: {cfg['host']}:{cfg['port']}\n"
            f"Database: {cfg['database']}\n\n"
            "Mogelijke oorzaken:\n"
            "• Je zit extern: zet je VPN aan en probeer opnieuw.\n"
            "• De database/server is tijdelijk niet bereikbaar.\n"
            "• Je netwerk/credentials kloppen niet.\n\n"
            "Als het probleem blijft aanhouden: contacteer de systeembeheerder.\n\n"
            f"Technische details:\n{e}"
        )
        return False, msg


class MainMenu(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cinema BackOffice — Main Menu")
        self.geometry("520x260")
        self.resizable(False, False)

        self.affiche_win = None
        self.borderel_win = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ✅ set window icon (prevents the “feather” icon on Windows)
        set_window_icon(self)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Cinema BackOffice", font=("TkDefaultFont", 18)).pack(anchor="w", pady=(0, 6))
        ttk.Label(outer, text="Kies een module:").pack(anchor="w", pady=(0, 14))

        btns = ttk.Frame(outer)
        btns.pack(fill="x")

        ttk.Button(btns, text="1. Affiches", command=self.open_affiches, width=22).grid(
            row=0, column=0, padx=(0, 10), pady=6, sticky="w"
        )
        ttk.Button(btns, text="2. Borderellen", command=self.open_borderellen, width=22).grid(
            row=0, column=1, pady=6, sticky="w"
        )

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=14)

        info = (
            "Tip: elk venster opent in dezelfde app.\n"
            "Sluit je dit menu, dan sluit alles."
        )
        ttk.Label(outer, text=info).pack(anchor="w")

        self.status = tk.StringVar(value="Klaar.")
        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(12, 0))

        outer.columnconfigure(0, weight=1)

    def _bring_to_front(self, win: tk.Toplevel):
        try:
            win.deiconify()
            win.lift()
            win.focus_force()
        except Exception:
            pass

    def _ensure_db_or_show_error(self) -> bool:
        ok, err = _check_mysql_connection(timeout_sec=3)
        if not ok:
            messagebox.showerror("Database niet bereikbaar", err, parent=self)
            self.status.set("Database niet bereikbaar. (VPN?)")
            return False
        return True

    def open_affiches(self):
        if not self._ensure_db_or_show_error():
            return

        if self.affiche_win is not None and self.affiche_win.winfo_exists():
            self._bring_to_front(self.affiche_win)
            self.status.set("Affiches: venster actief.")
            return

        try:
            self.affiche_win = open_affiche_window(self)
            # ✅ icon on child window too (if affiche.open_window doesn't do it)
            try:
                set_window_icon(self.affiche_win)
            except Exception:
                pass
            self.status.set("Affiches geopend.")
        except Exception as e:
            messagebox.showerror("Fout", f"Kon Affiches niet openen:\n\n{e}", parent=self)

    def open_borderellen(self):
        if not self._ensure_db_or_show_error():
            return

        if self.borderel_win is not None and self.borderel_win.winfo_exists():
            self._bring_to_front(self.borderel_win)
            self.status.set("Borderellen: venster actief.")
            return

        try:
            self.borderel_win = open_borderel_window(self)
            # ✅ icon on child window too (this fixes the “feather” if borderel forgets it)
            try:
                set_window_icon(self.borderel_win)
            except Exception:
                pass
            self.status.set("Borderellen geopend.")
        except Exception as e:
            messagebox.showerror("Fout", f"Kon Borderellen niet openen:\n\n{e}", parent=self)

    def _on_close(self):
        # Sluit alle open vensters
        try:
            if self.affiche_win is not None and self.affiche_win.winfo_exists():
                self.affiche_win.destroy()
        except Exception:
            pass

        try:
            if self.borderel_win is not None and self.borderel_win.winfo_exists():
                self.borderel_win.destroy()
        except Exception:
            pass

        self.destroy()


if __name__ == "__main__":
    MainMenu().mainloop()