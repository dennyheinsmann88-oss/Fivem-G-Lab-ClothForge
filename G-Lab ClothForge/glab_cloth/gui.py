"""Einfache Oberfläche (tkinter, ist bei Python für Windows dabei)."""

import json
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .builder import _is_own_resource, build, read_group, resource_dlc
from .cli import print_report
from .optimize import DEFAULT_LIMITS, FIVEM_WARN_MIB, KIND_LABELS, optimize_folder, scan_folder
from .preview import PreviewServer

LIMIT_CHOICES = ["512", "1024", "2048", "4096"]

SETTINGS_FILE = Path.home() / ".glab_clothtool.json"
BASE_HELP = (
    "Grundkörper (einmalig): In OpenIV öffnen\n"
    "  x64v.rpf › models › cdimages › streamedpeds_mp.rpf › mp_f_freemode_01.rpf\n"
    "und den Inhalt in einen Ordner exportieren, der „mp_f_freemode_01“ heißt (für Männer mp_m_freemode_01).\n"
    "Diesen Ordner (oder einen Ordner darüber) hier als Grundkörper-Ordner wählen."
)


# Dunkles Farbschema (passend zur 3D-Vorschau)
C = {"bg": "#161618", "panel": "#1f1f22", "field": "#2a2b30", "line": "#3a3a40", "text": "#ececef",
     "muted": "#9a9aa2", "accent": "#6b9cff", "accent_dark": "#3d5f9e", "disabled": "#5c5c63"}


def apply_dark_theme(root):
    root.configure(bg=C["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")  # einziges eingebautes Theme, bei dem sich alle Farben setzen lassen
    style.configure(".", background=C["bg"], foreground=C["text"], fieldbackground=C["field"],
                    bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["line"], troughcolor=C["panel"],
                    selectbackground=C["accent_dark"], selectforeground=C["text"], insertcolor=C["text"],
                    focuscolor=C["accent"], font=("Segoe UI", 10))
    style.configure("TFrame", background=C["bg"])
    style.configure("TLabel", background=C["bg"], foreground=C["text"])
    style.configure("Muted.TLabel", foreground=C["muted"])
    style.configure("TButton", background=C["field"], foreground=C["text"], padding=(10, 5), borderwidth=1)
    style.map("TButton", background=[("disabled", C["panel"]), ("pressed", C["accent_dark"]), ("active", C["line"])],
              foreground=[("disabled", C["disabled"])])
    style.configure("Accent.TButton", background=C["accent_dark"], bordercolor=C["accent"])
    style.map("Accent.TButton", background=[("disabled", C["panel"]), ("pressed", C["accent"]), ("active", C["accent"])])
    style.configure("TEntry", fieldbackground=C["field"], foreground=C["text"], padding=4)
    style.map("TEntry", bordercolor=[("focus", C["accent"])])
    style.configure("TCombobox", fieldbackground=C["field"], background=C["line"], foreground=C["text"],
                    arrowcolor=C["text"], padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", C["field"])], foreground=[("readonly", C["text"])],
              selectbackground=[("readonly", C["field"])], selectforeground=[("readonly", C["text"])],
              background=[("active", C["line"])])
    style.configure("TCheckbutton", background=C["bg"], foreground=C["text"], indicatorbackground=C["field"],
                    indicatorforeground=C["text"])
    style.map("TCheckbutton", background=[("active", C["bg"])], indicatorbackground=[("selected", C["accent_dark"])])
    style.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(8, 8, 8, 0))
    style.configure("TNotebook.Tab", background=C["panel"], foreground=C["muted"], padding=(16, 6), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", C["bg"])], foreground=[("selected", C["text"])],
              expand=[("selected", (1, 1, 1, 0))])
    style.configure("Vertical.TScrollbar", background=C["field"], arrowcolor=C["muted"])
    style.configure("Treeview", background=C["panel"], fieldbackground=C["panel"], foreground=C["text"],
                    rowheight=22, borderwidth=0)
    style.map("Treeview", background=[("selected", C["accent_dark"])])
    style.configure("Treeview.Heading", background=C["field"], foreground=C["muted"], relief="flat")
    style.map("Treeview.Heading", background=[("active", C["line"])])
    # Aufklappliste der Combobox ist ein normales tk-Listbox-Widget
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent_dark"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["text"])


def dark_title_bar(root):
    """Windows 10/11: dunkle Titelleiste (sonst bleibt sie weiß). Auf anderen Systemen ohne Wirkung."""
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / alte Win10-Builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


def _dark_tk(widget):
    widget.configure(bg=C["field"], fg=C["text"], selectbackground=C["accent_dark"], selectforeground=C["text"],
                     highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["accent"],
                     relief="flat", borderwidth=0)


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass

GENDERS = {"Automatisch erkennen": None, "Männlich": "m", "Weiblich": "f"}
REPLACE_TAG = "[Ersetzen] "


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        apply_dark_theme(self)
        dark_title_bar(self)
        self.title("G_Lab ClothTool – FiveM Addon-Kleidung")
        self.geometry("820x640")
        self.minsize(640, 480)
        self.messages = queue.Queue()
        self.settings = load_settings()
        self.preview = PreviewServer()

        pad = {"padx": 6, "pady": 4}
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True)
        frm = ttk.Frame(tabs, padding=10)
        tabs.add(frm, text="Resource bauen")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Eingabe-Ordner (Packs):").grid(row=0, column=0, sticky="nw", **pad)
        self.inputs = tk.Listbox(frm, height=5, selectmode="extended")
        _dark_tk(self.inputs)
        self.inputs.grid(row=0, column=1, sticky="nsew", **pad)
        btns = ttk.Frame(frm)
        btns.grid(row=0, column=2, sticky="n", **pad)
        ttk.Button(btns, text="Ordner hinzufügen …", command=self.add_input).pack(fill="x")
        ttk.Button(btns, text="Als Ersatz erzwingen …", command=self.add_replace_input).pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Entfernen", command=self.remove_input).pack(fill="x", pady=4)

        ttk.Label(frm, text="Ausgabe-Ordner:").grid(row=1, column=0, sticky="w", **pad)
        self.output = tk.StringVar(value=self.settings.get("output", ""))
        ttk.Entry(frm, textvariable=self.output).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Wählen …", command=self.pick_output).grid(row=1, column=2, sticky="ew", **pad)

        ttk.Label(frm, text="Resource-Name:").grid(row=2, column=0, sticky="w", **pad)
        self.name = tk.StringVar(value="glab_clothes")
        ttk.Entry(frm, textvariable=self.name).grid(row=2, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="DLC-Name (leer = wie Resource):").grid(row=3, column=0, sticky="w", **pad)
        self.dlc = tk.StringVar()
        ttk.Entry(frm, textvariable=self.dlc).grid(row=3, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="Geschlecht:").grid(row=4, column=0, sticky="w", **pad)
        self.gender = tk.StringVar(value=next(iter(GENDERS)))
        ttk.Combobox(frm, textvariable=self.gender, values=list(GENDERS), state="readonly").grid(
            row=4, column=1, sticky="w", **pad)

        opts = ttk.Frame(frm)
        opts.grid(row=5, column=1, columnspan=2, sticky="w", **pad)
        self.append = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=False)
        self.keep_unknown = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="An bestehende Resource anhängen", variable=self.append).pack(side="left")
        ttk.Checkbutton(opts, text="Probelauf (nichts schreiben)", variable=self.dry_run).pack(side="left", padx=12)
        opts2 = ttk.Frame(frm)
        opts2.grid(row=6, column=1, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(opts2, text="Nicht erkannte Dateien unverändert übernehmen (Ersatzdateien)",
                        variable=self.keep_unknown).pack(anchor="w")
        self.optimize = tk.BooleanVar(value=self.settings.get("optimize", True))
        self.optimize_label = tk.StringVar()
        ttk.Checkbutton(opts2, textvariable=self.optimize_label, variable=self.optimize).pack(anchor="w", pady=(6, 0))
        self.split = tk.BooleanVar(value=self.settings.get("split", False))
        ttk.Checkbutton(opts2, text="Nach Kategorie aufteilen (eigene Resource für Oberteile, Hosen, Haare …)",
                        variable=self.split).pack(anchor="w", pady=(6, 0))

        self.run_btn = ttk.Button(frm, text="Resource bauen", command=self.start, style="Accent.TButton")
        self.run_btn.grid(row=7, column=1, sticky="w", **pad)

        self.log = tk.Text(frm, height=18, wrap="none", state="disabled", font=("Consolas", 9))
        _dark_tk(self.log)
        self.log.configure(bg=C["panel"], insertbackground=C["text"], padx=8, pady=6)
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(8, weight=1)

        saved = self.settings.get("limits", {})
        self.limits = {k: tk.StringVar(value=str(saved.get(k, v))) for k, v in DEFAULT_LIMITS.items()}
        for var in self.limits.values():
            var.trace_add("write", lambda *_: self.update_optimize_label())
        self.update_optimize_label()

        self.build_preview_tab(tabs, pad)
        self.build_optimize_tab(tabs, pad)
        self.after(100, self.poll)

    def current_limits(self):
        return {k: int(v.get()) for k, v in self.limits.items()}

    def update_optimize_label(self):
        sizes = sorted(set(self.current_limits().values()))
        size = "/".join(str(x) for x in sizes)
        self.optimize_label.set(f"Texturen verkleinern (max. {size} px – einstellbar im Tab „Optimieren“)")

    def build_optimize_tab(self, tabs, pad):
        frm = ttk.Frame(tabs, padding=10)
        tabs.add(frm, text="Optimieren")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Resource / Ordner:").grid(row=0, column=0, sticky="w", **pad)
        self.opt_folder = tk.StringVar(value=self.settings.get("opt_folder", self.settings.get("preview_resource", "")))
        ttk.Entry(frm, textvariable=self.opt_folder).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Wählen …", command=lambda: self.pick_dir(self.opt_folder, "Resource wählen")
                   ).grid(row=0, column=2, sticky="ew", **pad)

        limits = ttk.Frame(frm)
        limits.grid(row=1, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(frm, text="Maximale Größe:").grid(row=1, column=0, sticky="w", **pad)
        for kind, var in self.limits.items():
            ttk.Label(limits, text=KIND_LABELS[kind]).pack(side="left", padx=(0, 4))
            ttk.Combobox(limits, textvariable=var, values=LIMIT_CHOICES, width=6, state="readonly").pack(
                side="left", padx=(0, 14))

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        self.check_btn = ttk.Button(btns, text="Prüfen", command=lambda: self.run_optimize(False))
        self.check_btn.pack(side="left")
        self.shrink_btn = ttk.Button(btns, text="Jetzt verkleinern", style="Accent.TButton",
                                     command=lambda: self.run_optimize(True))
        self.shrink_btn.pack(side="left", padx=8)
        self.fix_btn = ttk.Button(btns, text="Defekte durch Platzhalter ersetzen", command=self.fix_defects,
                                  state="disabled")
        self.fix_btn.pack(side="left")

        self.opt_summary = tk.StringVar(value=f"FiveM warnt ab {FIVEM_WARN_MIB} MiB Grafikspeicher pro Datei. "
                                              "„Prüfen“ zeigt, welche Dateien betroffen sind.")
        ttk.Label(frm, textvariable=self.opt_summary, wraplength=760, justify="left").grid(
            row=3, column=0, columnspan=3, sticky="w", **pad)

        cols = ("size", "after", "texture")
        tree = ttk.Treeview(frm, columns=cols, show="tree headings", height=14)
        tree.heading("#0", text="Datei")
        tree.heading("size", text="Speicher")
        tree.heading("after", text="Nachher")
        tree.heading("texture", text="Größte Textur")
        tree.column("#0", width=330)
        tree.column("size", width=80, anchor="e")
        tree.column("after", width=80, anchor="e")
        tree.column("texture", width=240)
        tree.tag_configure("red", foreground="#ff6b5e")
        tree.tag_configure("defect", foreground="#ffffff", background="#7a2620")
        tree.tag_configure("yellow", foreground="#e3c255")
        tree.tag_configure("green", foreground="#4cc183")
        tree.grid(row=4, column=0, columnspan=3, sticky="nsew", **pad)
        scroll = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        scroll.grid(row=4, column=3, sticky="ns", pady=4)
        tree.configure(yscrollcommand=scroll.set)
        frm.rowconfigure(4, weight=1)
        self.opt_tree = tree

    def run_optimize(self, apply):
        folder = self.opt_folder.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("ClothTool", "Bitte eine Resource bzw. einen Ordner wählen.")
            return
        if apply and not messagebox.askyesno(
                "ClothTool", "Zu große Texturen jetzt verkleinern?\n\nDie Originale werden vorher nach "
                f"„_original\\{Path(folder).name}“ neben dem Ordner gesichert. Danach die Resource neu starten."):
            return
        self.settings.update(opt_folder=folder, limits=self.current_limits())
        save_settings(self.settings)
        self.check_btn.config(state="disabled")
        self.shrink_btn.config(state="disabled")
        self.opt_summary.set("Wird geprüft …" if not apply else "Wird verkleinert …")
        threading.Thread(target=self.optimize_work, args=(folder, self.current_limits(), apply), daemon=True).start()

    def fix_defects(self):
        folder = Path(self.opt_folder.get().strip())
        group = read_group(folder)
        name, dlc, split = (group["name"], group["dlc"], True) if group else (folder.name, resource_dlc(folder), False)
        if not dlc or not messagebox.askyesno(
                "ClothTool", "Defekte Teile durch Platzhalter ersetzen?\n\nDie IDs der anderen Teile bleiben gleich, "
                "defekte Ersatz-Dateien werden entfernt. Die Resource wird dafür neu gebaut. Danach neu starten."):
            return
        self.fix_btn.config(state="disabled")
        self.opt_summary.set("Defekte werden ersetzt …")
        limits = self.current_limits()

        def work():
            try:
                report = build([], folder.parent, name, dlc, append=True, split=split, log=lambda m: None)
                fixed = sum("DEFEKT" in w for w in report.warnings)
                text = (f"Fehler: {report.errors[0]} " if report.errors else f"{fixed} defekte Dateien ersetzt/entfernt. "
                        "Resource neu starten. ")
                self.messages.put(("optimize", str(folder), scan_folder(folder, limits), text))
            except Exception as exc:  # Fehler anzeigen statt abstürzen
                self.messages.put(("optimize", str(folder), [], f"Fehler: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def optimize_work(self, folder, limits, apply):
        try:
            text = ""
            if apply:
                changed, before, after, backup = optimize_folder(folder, limits, log=lambda m: None)
                text = (f"{changed} Dateien verkleinert: {before / 1048576:.0f} → {after / 1048576:.0f} MiB. "
                        + (f"Originale in {backup}. " if backup else "") + "Resource neu starten. ")
            rows = scan_folder(folder, limits)
            self.messages.put(("optimize", folder, rows, text))
        except Exception as exc:  # Fehler anzeigen statt abstürzen
            self.messages.put(("optimize", folder, [], f"Fehler: {exc}"))

    def show_optimize(self, folder, rows, text):
        tree = self.opt_tree
        tree.delete(*tree.get_children())
        mib = 1048576
        limit = FIVEM_WARN_MIB * mib
        rows = sorted(rows, key=lambda r: (not r.defects, -(r.info.physical if r.info else 0)))
        for r in rows:
            name = r.path.name.split("^")[-1] if "^" in r.path.name else r.path.name
            name = f"{r.path.parent.name}/{name}"
            if r.defects:
                tree.insert("", "end", text=name, values=("DEFEKT", "–", r.defects[0]), tags=("defect",))
                continue
            if r.info is None:
                tree.insert("", "end", text=name, values=("–", "–", f"nicht lesbar: {r.error}"), tags=("yellow",))
                continue
            size = r.info.physical
            tag = "red" if size > limit else "yellow" if size > limit / 2 else "green"
            largest = r.info.largest.label if r.info.largest else "keine Texturen"
            after = f"{r.estimate / mib:.1f} MiB" if r.estimate < size else "–"
            tree.insert("", "end", text=name, values=(f"{size / mib:.1f} MiB", after, largest), tags=(tag,))
        total = sum(r.info.physical for r in rows if r.info)
        est = sum(r.estimate for r in rows if r.info)
        over = sum(1 for r in rows if r.info and r.info.physical > limit)
        over_after = sum(1 for r in rows if r.info and r.estimate > limit)
        defects = sum(1 for r in rows if r.defects)
        own = read_group(folder) or (_is_own_resource(Path(folder)) and resource_dlc(folder))
        self.fix_btn.config(state="normal" if defects and own else "disabled")
        if defects:
            text += (f"⚠ {defects} DEFEKTE Datei{'en' if defects > 1 else ''} – FiveM würde daran abstürzen. "
                     + ("„Defekte durch Platzhalter ersetzen“ behebt das, ohne IDs zu verschieben. " if own else
                        "Diese Dateien entfernen oder neu exportieren. "))
        self.opt_summary.set(f"{text}{len(rows)} Dateien, {total / mib:.0f} MiB Grafikspeicher, {over} über "
                             f"{FIVEM_WARN_MIB} MiB. Mit diesen Einstellungen: ca. {est / mib:.0f} MiB"
                             f"{f', {over_after} bleiben über {FIVEM_WARN_MIB} MiB' if over_after else ''}.")
        self.check_btn.config(state="normal")
        self.shrink_btn.config(state="normal")

    def build_preview_tab(self, tabs, pad):
        frm = ttk.Frame(tabs, padding=10)
        tabs.add(frm, text="3D-Vorschau")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Fertige Resource:").grid(row=0, column=0, sticky="w", **pad)
        self.preview_resource = tk.StringVar(value=self.settings.get("preview_resource", ""))
        ttk.Entry(frm, textvariable=self.preview_resource).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Wählen …", command=lambda: self.pick_dir(self.preview_resource, "Fertige Resource wählen")
                   ).grid(row=0, column=2, sticky="ew", **pad)

        ttk.Label(frm, text="Grundkörper-Ordner:").grid(row=1, column=0, sticky="w", **pad)
        self.preview_base = tk.StringVar(value=self.settings.get("preview_base", ""))
        ttk.Entry(frm, textvariable=self.preview_base).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Wählen …", command=lambda: self.pick_dir(self.preview_base, "Grundkörper-Ordner wählen")
                   ).grid(row=1, column=2, sticky="ew", **pad)

        ttk.Label(frm, text="Geschlecht Grundkörper:").grid(row=2, column=0, sticky="w", **pad)
        self.preview_gender = tk.StringVar(value=self.settings.get("preview_gender", next(iter(GENDERS))))
        ttk.Combobox(frm, textvariable=self.preview_gender, values=list(GENDERS), state="readonly").grid(
            row=2, column=1, sticky="w", **pad)

        ttk.Button(frm, text="3D-Vorschau im Browser öffnen", command=self.open_preview, style="Accent.TButton").grid(
            row=3, column=1, sticky="w", **pad)
        self.preview_status = tk.StringVar(value="Die Vorschau öffnet sich im Browser (drehen: linke Maustaste, "
                                                 "zoomen: Mausrad, verschieben: rechte Maustaste).")
        ttk.Label(frm, textvariable=self.preview_status, wraplength=700, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(frm, text=BASE_HELP, justify="left", style="Muted.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", padx=6, pady=(16, 4))

    def pick_dir(self, var, title):
        path = filedialog.askdirectory(title=title)
        if path:
            var.set(path)

    def open_preview(self):
        resource, base = self.preview_resource.get().strip(), self.preview_base.get().strip()
        if not resource and not base:
            messagebox.showwarning("ClothTool", "Bitte eine fertige Resource und/oder einen Grundkörper-Ordner wählen.")
            return
        for path in (resource, base):
            if path and not Path(path).is_dir():
                messagebox.showwarning("ClothTool", f"Ordner nicht gefunden:\n{path}")
                return
        self.settings.update(preview_resource=resource, preview_base=base, preview_gender=self.preview_gender.get())
        save_settings(self.settings)
        self.preview.set_folders(resource or None, base or None, GENDERS[self.preview_gender.get()])
        url = self.preview.start()
        count = len(self.preview.items)
        self.preview_status.set(f"{count} Teile gefunden – Vorschau läuft unter {url} "
                                "(nach Änderungen einfach erneut auf den Knopf klicken)")
        webbrowser.open(url)

    def add_input(self):
        path = filedialog.askdirectory(title="Ordner wählen – wird komplett durchsucht (auch .zip/.oiv)")
        if path:
            self.inputs.insert("end", path)

    def add_replace_input(self):
        path = filedialog.askdirectory(title="Ordner mit Dateien, die Original-GTA-Kleidung ersetzen")
        if path:
            self.inputs.insert("end", REPLACE_TAG + path)

    def remove_input(self):
        for i in reversed(self.inputs.curselection()):
            self.inputs.delete(i)

    def pick_output(self):
        path = filedialog.askdirectory(title="Ausgabe-Ordner wählen (z.B. resources)")
        if path:
            self.output.set(path)

    def write(self, text):
        self.messages.put(text)

    def poll(self):
        while not self.messages.empty():
            msg = self.messages.get()
            if msg is None:
                self.run_btn.config(state="normal")
                continue
            if isinstance(msg, tuple) and msg[0] == "optimize":
                self.show_optimize(*msg[1:])
                continue
            if isinstance(msg, tuple):  # ("built", ausgabe, resource) aus dem Arbeits-Thread
                _, output, resource = msg
                self.preview_resource.set(resource)
                self.opt_folder.set(resource)
                self.settings.update(output=output, preview_resource=resource)
                save_settings(self.settings)
                continue
            self.log.config(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.after(100, self.poll)

    def start(self):
        entries = list(self.inputs.get(0, "end"))
        inputs = [e for e in entries if not e.startswith(REPLACE_TAG)]
        replace_inputs = [e[len(REPLACE_TAG):] for e in entries if e.startswith(REPLACE_TAG)]
        if not entries and not self.append.get():
            messagebox.showwarning("ClothTool", "Bitte mindestens einen Eingabe-Ordner hinzufügen.")
            return
        if not self.output.get():
            messagebox.showwarning("ClothTool", "Bitte einen Ausgabe-Ordner wählen.")
            return
        name = self.name.get().strip()
        dlc = self.dlc.get().strip() or name.lower().replace("-", "_")
        self.settings.update(optimize=self.optimize.get(), limits=self.current_limits(), split=self.split.get())
        save_settings(self.settings)
        args = (inputs, self.output.get(), name, dlc, GENDERS[self.gender.get()], self.append.get(), self.dry_run.get(),
                self.keep_unknown.get(), replace_inputs, self.current_limits() if self.optimize.get() else None,
                self.split.get())

        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.run_btn.config(state="disabled")
        threading.Thread(target=self.work, args=args, daemon=True).start()

    def work(self, inputs, output, name, dlc, gender, append, dry_run, keep_unknown, replace_inputs, optimize, split):
        try:
            self.write("Suche Dateien …")
            report = build(inputs, output, name, dlc, gender, append, dry_run, log=self.write,
                           keep_unknown=keep_unknown, replace_inputs=replace_inputs, optimize=optimize, split=split)
            print_report(report, log=self.write)
            if dry_run and not report.errors:
                self.write("\n(Probelauf – es wurde nichts geschrieben)")
            if report.output:
                self.messages.put(("built", output, str(report.output)))
                self.write("Im Tab „3D-Vorschau“ kannst du dir die Teile jetzt ansehen.")
        except Exception as exc:  # Fehler im Log anzeigen statt das Fenster abstürzen zu lassen
            self.write(f"FEHLER: {exc}")
        finally:
            self.messages.put(None)


def run_gui():
    App().mainloop()
