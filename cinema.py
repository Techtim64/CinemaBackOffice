import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import pandas as pd


def extract_second_part(variant: str) -> str:
    if pd.isna(variant):
        return ""

    s = str(variant).strip()
    for sep in ["·", "•", "|"]:
        if sep in s:
            parts = [p.strip() for p in s.split(sep)]
            return parts[1] if len(parts) >= 2 else parts[0]

    if " - " in s:
        parts = [p.strip() for p in s.split(" - ")]
        return parts[1] if len(parts) >= 2 else parts[0]

    return s


class SumUpFilmApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SumUp Filmrapport")
        self.root.geometry("1200x600")

        self.unit_prices = {}  # per rij: {"volw": prijs, "kind": prijs}

        # Laatst aangeklikte cel (voor copy)
        self._active_item = None
        self._active_col_index = None
        self._active_value = None

        self._build_ui()
        self._bind_copy_shortcuts()

    # -----------------------------
    # UI
    # -----------------------------
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Button(top, text="CSV openen", command=self.open_csv).pack(side="left")
        ttk.Button(top, text="Exporteren", command=self.export_csv).pack(side="left", padx=8)

        self.status = tk.StringVar(value="Geen bestand geladen.")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=20)

        mid = ttk.Frame(self.root, padding=10)
        mid.pack(fill="both", expand=True)

        self.columns = (
            "Film",
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
            self.tree.column(col, width=150, anchor="center")

        self.tree.column("Film", width=300, anchor="w")
        self.tree.column("3D", width=60)

        self.tree.pack(fill="both", expand=True)

        # Bewerk aantal bij dubbelklik
        self.tree.bind("<Double-1>", self._start_edit)

        # Cel/rij selectie bij linksklik (ook voor Ctrl+C)
        self.tree.bind("<Button-1>", self._on_left_click, add=True)

        # Rechtermuisklik contextmenu (Windows/Linux)
        self.tree.bind("<Button-3>", self._on_right_click, add=True)

        # macOS: sommige trackpads geven Button-2 voor “right click”
        self.tree.bind("<Button-2>", self._on_right_click, add=True)

        # macOS: Control+Click = rechtermuisklik
        self.tree.bind("<Control-Button-1>", self._on_right_click, add=True)

        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(fill="x")

        self.total_label = tk.StringVar(value="Totaal tickets: 0 | Totaal bedrag: 0,00")
        ttk.Label(bottom, textvariable=self.total_label).pack(anchor="w")

        # Contextmenu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Kopieer", command=self.copy_active_cell_to_clipboard)

    def _bind_copy_shortcuts(self):
        # Ctrl+C (Windows/Linux)
        self.root.bind_all("<Control-c>", lambda e: self.copy_active_cell_to_clipboard())
        self.root.bind_all("<Control-C>", lambda e: self.copy_active_cell_to_clipboard())
        # Cmd+C (macOS)
        self.root.bind_all("<Command-c>", lambda e: self.copy_active_cell_to_clipboard())
        self.root.bind_all("<Command-C>", lambda e: self.copy_active_cell_to_clipboard())

    # -----------------------------
    # Klik handlers voor copy
    # -----------------------------
    def _on_left_click(self, event):
        """Onthoud de cel waar je op klikt (voor Ctrl/Cmd+C)."""
        self._set_active_cell_from_event(event)

    def _on_right_click(self, event):
        """Toon contextmenu op numerieke cellen."""
        self._set_active_cell_from_event(event)
        if self._active_value is None:
            return
        # Alleen numerieke kolommen (niet Film / 3D)
        col_name = self.columns[self._active_col_index]
        if col_name in ["Film", "3D"]:
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
        col = self.tree.identify_column(event.x)  # '#1', '#2', ...
        if not item or not col:
            self._active_item = None
            self._active_col_index = None
            self._active_value = None
            return

        col_index = int(col.replace("#", "")) - 1
        values = self.tree.item(item, "values")

        # Zet ook rijselectie zodat “kopieer rij” werkt
        self.tree.focus(item)
        self.tree.selection_set(item)

        self._active_item = item
        self._active_col_index = col_index
        try:
            self._active_value = values[col_index]
        except Exception:
            self._active_value = None

    def copy_active_cell_to_clipboard(self):
        """
        Kopieert:
        - als er een actieve cel is: die waarde
        - anders: de geselecteerde rij als tab-gescheiden tekst
        """
        text = None

        if self._active_item is not None and self._active_col_index is not None:
            # Kopieer actieve cel
            col_name = self.columns[self._active_col_index]
            if col_name not in ["Film", "3D"] and self._active_value is not None:
                text = str(self._active_value)

        if text is None:
            # Fallback: kopieer hele rij
            sel = self.tree.selection()
            if sel:
                vals = self.tree.item(sel[0], "values")
                text = "\t".join(str(v) for v in vals)

        if not text:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()  # meteen beschikbaar
        # kleine feedback in status
        self.status.set("Gekopieerd naar klembord.")

    # -----------------------------
    # CSV INLADEN
    # -----------------------------
    def open_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV bestanden", "*.csv")])
        if not path:
            return

        df = pd.read_csv(path)
        df = df[df["Categorie"].astype(str).str.lower() == "film"].copy()

        df["Film"] = df["Naam van variant"].apply(extract_second_part)
        df["Aantal"] = pd.to_numeric(df["Aantal"], errors="coerce").fillna(0)
        df["Bedrag"] = pd.to_numeric(df["Bedrag"], errors="coerce").fillna(0)

        name = df["Naam van artikel"].astype(str)
        df["IsKind"] = name.str.contains("kind", case=False, na=False)
        df["Is3D"] = name.str.contains("3d", case=False, na=False)

        df["AantalVolw"] = df["Aantal"].where(~df["IsKind"], 0)
        df["AantalKind"] = df["Aantal"].where(df["IsKind"], 0)
        df["BedragVolw"] = df["Bedrag"].where(~df["IsKind"], 0)
        df["BedragKind"] = df["Bedrag"].where(df["IsKind"], 0)

        summary = (
            df.groupby("Film", as_index=False)
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

        self.tree.delete(*self.tree.get_children())
        self.unit_prices.clear()

        for _, row in summary.iterrows():
            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    row["Film"],
                    "✅" if row["Is3D"] else "",
                    int(row["AantalVolw"]),
                    int(row["AantalKind"]),
                    f"{row['BedragVolw']:.2f}",
                    f"{row['BedragKind']:.2f}",
                    int(row["TotaalAantal"]),
                    f"{row['TotaalBedrag']:.2f}",
                ),
            )

            volw_price = (row["BedragVolw"] / row["AantalVolw"]) if row["AantalVolw"] > 0 else None
            kind_price = (row["BedragKind"] / row["AantalKind"]) if row["AantalKind"] > 0 else None

            self.unit_prices[item_id] = {"volw": volw_price, "kind": kind_price}

        self.status.set(f"Geladen: {os.path.basename(path)}")
        self._update_totals()

    # -----------------------------
    # Bewerken aantal
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
            index_aantal = 2
            index_bedrag = 4
            unit_key = "volw"
        else:
            index_aantal = 3
            index_bedrag = 5
            unit_key = "kind"

        unit = self.unit_prices[item][unit_key]

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

        totaal_aantal = int(values[2]) + int(values[3])
        totaal_bedrag = float(values[4]) + float(values[5])

        values[6] = totaal_aantal
        values[7] = f"{totaal_bedrag:.2f}"

        self.tree.item(item, values=values)

        entry.destroy()
        self.root.focus_set()
        self._update_totals()

    # -----------------------------
    # Totalen
    # -----------------------------
    def _update_totals(self):
        totaal_aantal = 0
        totaal_bedrag = 0.0

        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            totaal_aantal += int(vals[6])
            totaal_bedrag += float(vals[7])

        self.total_label.set(
            f"Totaal tickets: {totaal_aantal} | Totaal bedrag: {totaal_bedrag:.2f}".replace(".", ",")
        )

    # -----------------------------
    # Export
    # -----------------------------
    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if not path:
            return

        rows = []
        for item in self.tree.get_children():
            rows.append(dict(zip(self.columns, self.tree.item(item, "values"))))

        pd.DataFrame(rows).to_csv(path, index=False)
        messagebox.showinfo("Export", "CSV succesvol opgeslagen.")


def main():
    root = tk.Tk()
    app = SumUpFilmApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
