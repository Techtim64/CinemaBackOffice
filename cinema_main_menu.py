import tkinter as tk
from tkinter import ttk, messagebox

# Importeer de open_window functies uit je 2 modules
# (zorg dat deze bestanden in dezelfde map staan als dit main_menu bestand)
from cinema_affiche import open_window as open_affiche_window
from cinema_borderel import open_window as open_borderel_window


class MainMenu(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cinema BackOffice — Main Menu")
        self.geometry("520x260")
        self.resizable(False, False)

        # optioneel: onthoud windows zodat we ze kunnen hergebruiken / focussen
        self.affiche_win = None
        self.borderel_win = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Cinema BackOffice",
            font=("TkDefaultFont", 18),
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(
            outer,
            text="Kies een module:",
        ).pack(anchor="w", pady=(0, 14))

        btns = ttk.Frame(outer)
        btns.pack(fill="x")

        ttk.Button(
            btns,
            text="1. Affiches",
            command=self.open_affiches,
            width=22,
        ).grid(row=0, column=0, padx=(0, 10), pady=6, sticky="w")

        ttk.Button(
            btns,
            text="2. Borderellen",
            command=self.open_borderellen,
            width=22,
        ).grid(row=0, column=1, pady=6, sticky="w")

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

    def open_affiches(self):
        # hergebruik bestaand venster als het nog open is
        if self.affiche_win is not None and self.affiche_win.winfo_exists():
            self._bring_to_front(self.affiche_win)
            self.status.set("Affiches: venster actief.")
            return

        try:
            self.affiche_win = open_affiche_window(self)
            self.affiche_win.protocol("WM_DELETE_WINDOW", self.affiche_win.destroy)
            self.status.set("Affiches geopend.")
        except Exception as e:
            messagebox.showerror("Fout", f"Kon Affiches niet openen:\n\n{e}")

    def open_borderellen(self):
        if self.borderel_win is not None and self.borderel_win.winfo_exists():
            self._bring_to_front(self.borderel_win)
            self.status.set("Borderellen: venster actief.")
            return

        try:
            self.borderel_win = open_borderel_window(self)
            self.borderel_win.protocol("WM_DELETE_WINDOW", self.borderel_win.destroy)
            self.status.set("Borderellen geopend.")
        except Exception as e:
            messagebox.showerror("Fout", f"Kon Borderellen niet openen:\n\n{e}")

    def _on_close(self):
        # Sluit alles netjes
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