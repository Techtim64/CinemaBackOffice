import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path


# -----------------------------
# Pas deze namen aan indien nodig
# -----------------------------
AFFICHES_SCRIPT = "cinemaAffiche.py"
BORDERELLEN_SCRIPT = "cinema.py"


class MainMenu(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cinema BackOffice — Main Menu")
        self.geometry("520x260")
        self.resizable(False, False)

        self.base_dir = Path(__file__).resolve().parent
        self.processes: list[subprocess.Popen] = []

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
            "Tip: elk venster opent als apart programma.\n"
            "Sluit je dit menu, dan kan je kiezen om alles te sluiten."
        )
        ttk.Label(outer, text=info).pack(anchor="w")

        self.status = tk.StringVar(value="Klaar.")
        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(12, 0))

        outer.columnconfigure(0, weight=1)

    def _script_path(self, filename: str) -> Path:
        return (self.base_dir / filename).resolve()

    def _run_script(self, script_filename: str, title: str):
        script_path = self._script_path(script_filename)
        if not script_path.exists():
            messagebox.showerror(
                "Bestand niet gevonden",
                f"Kan {title} niet openen.\n\nBestand ontbreekt:\n{script_path}",
            )
            return

        try:
            # Start as separate process using same python executable
            p = subprocess.Popen(
                [sys.executable, str(script_path)],
                cwd=str(self.base_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.processes.append(p)
            self.status.set(f"Gestart: {title}")
        except Exception as e:
            messagebox.showerror("Fout", f"Kon {title} niet starten:\n\n{e}")

    def open_affiches(self):
        self._run_script(AFFICHES_SCRIPT, "Affiches")

    def open_borderellen(self):
        self._run_script(BORDERELLEN_SCRIPT, "Borderellen")

    def _cleanup_process_list(self):
        # verwijder processen die al afgesloten zijn
        alive = []
        for p in self.processes:
            if p.poll() is None:
                alive.append(p)
        self.processes = alive

    def _on_close(self):
        self._cleanup_process_list()

        if self.processes:
            ans = messagebox.askyesnocancel(
                "Afsluiten",
                "Er zijn nog vensters open (Affiches/Borderellen).\n\n"
                "Ja = alles sluiten\n"
                "Nee = menu sluiten maar vensters laten open\n"
                "Annuleren = niet afsluiten",
            )
            if ans is None:
                return  # cancel
            if ans is True:
                # terminate all child processes
                for p in self.processes:
                    try:
                        p.terminate()
                    except Exception:
                        pass
        self.destroy()


if __name__ == "__main__":
    MainMenu().mainloop()