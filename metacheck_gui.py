"""MüCOS Manuscript Checker desktop app - pick a manuscript, run GROBID + metacheck, view report.

Double-click this file (or the packaged ManuscriptChecker.exe) to launch. Requires the
Python deps in requirements.txt (or a PyInstaller build) plus R + the metacheck
package, and LibreOffice if you convert DOCX/HTML.
"""

import os
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, scrolledtext, ttk

import config
import pipeline

# --- MüCOS dark palette (from the MüCOS logo) --------------------------
# logo colors: primary teal #009dd1, slate #434553, light cyan #9ed7ea,
# off-white #e6e2e2
BG = "#232331"
PANEL = "#2f2f3d"
PANEL2 = "#3a3a4a"
BORDER = "#4a4a5e"
TEXT = "#e6e2e2"
MUTED = "#9a9ab5"
ACCENT = "#009dd1"
ACCENT_HOVER = "#2fb2dd"
LOG_BG = "#1a1a24"
LOG_TEXT = "#d8d8e4"
SELECT_BG = "#3a4a56"
SELECT_FG = "#e6e2e2"

FONT = "Segoe UI"
FONT_BOLD = "Segoe UI semibold"

DESKTOP_APP_VERSION = config.DESKTOP_APP_VERSION


def _bg_of(widget):
    """Background colour a (ttk or tk) parent widget is drawn with."""
    try:
        if isinstance(widget, ttk.Widget):
            st = widget.cget("style") or widget.winfo_class()
            c = ttk.Style().lookup(st, "background")
            if c:
                return c
        return widget.cget("bg")
    except tk.TclError:
        return BG


class ModernButton(tk.Canvas):
    """Flat, rounded Windows-11-style button drawn on a canvas.

    Drop-in for ttk.Button as used here: ``text``, ``style``, ``command`` and
    ``state`` can be set at creation and changed later via ``config``.
    """
    # style -> (fill, text, hover, pressed, disabled_fill, disabled_text, font, padx, pady)
    LOOK = {
        "Accent.TButton": (ACCENT, "#ffffff", ACCENT_HOVER, "#0083b0", "#2a3a44",
                           "#7d8d96", (FONT_BOLD, 10), 18, 9),
        "Ghost.TButton": (PANEL2, TEXT, "#46465c", "#3a3a56", "#26262f", MUTED,
                          (FONT, 9), 14, 8),
        "Tab.TButton": (PANEL2, MUTED, "#46465c", "#3a3a56", "#26262f", MUTED,
                        (FONT_BOLD, 10), 18, 9),
        "TabActive.TButton": (ACCENT, "#06222e", ACCENT_HOVER, "#0083b0", ACCENT,
                              "#06222e", (FONT_BOLD, 10), 18, 9),
        "Small.TButton": (PANEL2, TEXT, "#46465c", "#3a3a56", "#26262f", MUTED,
                          (FONT, 8), 10, 3),
    }
    RADIUS = 8

    def __init__(self, parent, text="", style="Ghost.TButton", command=None,
                 state="normal", **kw):
        super().__init__(parent, highlightthickness=0, bd=0,
                         bg=_bg_of(parent), cursor="hand2", takefocus=1)
        self._text, self._style, self._command = text, style, command
        self._state = state
        self._hover = self._down = False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<space>", lambda e: self._invoke())
        self.bind("<Return>", lambda e: self._invoke())
        self._redraw()

    def _set(self, hover=None, down=None):
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        self._redraw()

    def _release(self, event):
        was = self._down
        self._set(down=False)
        if was and self._state != "disabled" and \
                0 <= event.x <= self.winfo_width() and \
                0 <= event.y <= self.winfo_height():
            self._invoke()

    def _invoke(self):
        if self._state != "disabled" and self._command:
            self._command()

    def _redraw(self):
        look = self.LOOK.get(self._style, self.LOOK["Ghost.TButton"])
        fill, fg, hov, prs, dfill, dfg, font, px, py = look
        disabled = self._state == "disabled"
        col = dfill if disabled else prs if self._down else hov if self._hover else fill
        fnt = tkfont.Font(family=font[0], size=font[1])
        w = fnt.measure(self._text) + 2 * px
        h = fnt.metrics("linespace") + 2 * py
        self.delete("all")
        self.configure(width=w, height=h, cursor="arrow" if disabled else "hand2")
        r = min(self.RADIUS, h // 2)
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h,
               0, h - r, 0, r, 0, 0]
        self.create_polygon(pts, smooth=True, fill=col, outline=col)
        self.create_text(w / 2, h / 2, text=self._text, fill=dfg if disabled else fg,
                         font=font)

    def config(self, cnf=None, **kw):
        redraw = False
        for k in ("text", "style", "command", "state"):
            if k in kw:
                setattr(self, "_" + k, kw.pop(k))
                redraw = True
        if redraw:
            self._redraw()
        if kw or cnf:
            super().configure(cnf, **kw)

    configure = config


class EngineCard(tk.Frame):
    """Clickable logo tile; a highlighted frame marks a selected engine.

    ``variable`` is a ``tk.BooleanVar`` so multiple engines can be selected at
    once; clicking a card toggles it.
    """

    def __init__(self, parent, value, caption, image, variable, command=None):
        super().__init__(parent, bg=PANEL, highlightthickness=3,
                         highlightbackground=BORDER, highlightcolor=BORDER,
                         cursor="hand2")
        self.value, self.variable, self.command = value, variable, command
        self.img = tk.Label(self, image=image, bg=PANEL, bd=0)
        self.img.pack(padx=10, pady=(8, 2))
        self.cap = tk.Label(self, text=caption, bg=PANEL, fg=MUTED,
                            font=(FONT_BOLD, 9))
        self.cap.pack(padx=10, pady=(0, 8))
        for w in (self, self.img, self.cap):
            w.bind("<Button-1>", self._pick)
        variable.trace_add("write", lambda *a: self.refresh())
        self.refresh()

    def _pick(self, _e=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def refresh(self):
        sel = bool(self.variable.get())
        self.configure(highlightbackground=ACCENT if sel else BORDER,
                       highlightcolor=ACCENT if sel else BORDER)
        self.cap.configure(fg=TEXT if sel else MUTED)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MüCOS Manuscript Checker")
        self.geometry("980x840")
        self.minsize(600, 480)
        self.configure(bg=BG)
        self.manuscript = None
        self.grobid_by_label = {s["id"]: s["url"] for s in config.PUBLIC_GROBID_SERVERS}
        self.report_path = None
        self.xml_path = None
        self.pdf_path = None
        self.outdir = None
        self.engine_vars = {e: tk.BooleanVar(value=(e == "chetameck"))
                            for e in pipeline.ENGINES}
        try:
            from chetameck.catalog import all_modules
            self.all_chetameck_modules = all_modules(include_online=True)
        except Exception:  # noqa: BLE001
            self.all_chetameck_modules = []
        self.selected_modules = list(self.all_chetameck_modules)
        self.plag_files = []
        self.plag_lib = tk.StringVar(value=self._load_setting("library_dir"))
        self.plag_passages = tk.IntVar(value=120)
        self.plag_seed = tk.StringVar(value="")
        self.plag_skip_used = tk.BooleanVar(value=False)
        self.plag_mailto = tk.StringVar(value=self._load_setting("mailto"))

        self._style()
        self._icon()
        self._build()
        self._refresh_status()
        self.after(2500, self._startup_update_check)

    # ------------------------------------------------------------- styling
    def _style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT,
                        font=(FONT, 10), bordercolor=BORDER, focuscolor=BG)
        style.configure("TFrame", background=PANEL)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=TEXT, font=(FONT, 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT,
                        font=(FONT, 10))
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED,
                        font=(FONT, 9))
        style.configure("Title.TLabel", background=PANEL, foreground=TEXT,
                        font=(FONT_BOLD, 16))
        style.configure("Sub.TLabel", background=PANEL, foreground=MUTED,
                        font=(FONT, 9))

        style.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER)
        style.map("TEntry", bordercolor=[("focus", ACCENT)])

        style.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                        foreground=TEXT, bordercolor=BORDER, arrowcolor=TEXT)
        style.map("TCombobox",
                  fieldbackground=[("readonly", PANEL2)],
                  foreground=[("readonly", TEXT)],
                  bordercolor=[("focus", ACCENT)])

        style.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                        font=(FONT, 10))
        style.map("TCheckbutton",
                  background=[("active", PANEL), ("disabled", PANEL)],
                  foreground=[("active", TEXT), ("disabled", MUTED)])

        style.configure("TRadiobutton", background=BG, foreground=TEXT,
                        font=(FONT, 10))
        style.map("TRadiobutton",
                  background=[("active", BG), ("disabled", BG)],
                  foreground=[("active", TEXT), ("disabled", MUTED)])

        style.configure("TButton", background=PANEL2, foreground=TEXT,
                        font=(FONT, 9), borderwidth=0, padding=(12, 7),
                        lightcolor=PANEL2, darkcolor=PANEL2, bordercolor=BORDER)
        style.map("TButton",
                  background=[("pressed", "#3a3a56"), ("active", "#3a3a56"),
                              ("disabled", "#26262f")],
                  foreground=[("active", TEXT), ("disabled", MUTED)],
                  lightcolor=[("active", "#3a3a56"), ("pressed", "#3a3a56")],
                  darkcolor=[("active", "#3a3a56"), ("pressed", "#3a3a56")])

        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=(FONT_BOLD, 10), borderwidth=0, padding=(14, 8),
                        lightcolor=ACCENT, darkcolor=ACCENT, bordercolor=ACCENT)
        style.map("Accent.TButton",
                  background=[("pressed", "#0083b0"), ("active", ACCENT_HOVER),
                              ("disabled", "#3a4a3c")],
                  foreground=[("disabled", "#9aa39b")],
                  lightcolor=[("active", ACCENT_HOVER), ("pressed", "#0083b0")],
                  darkcolor=[("active", ACCENT_HOVER), ("pressed", "#0083b0")])

        style.configure("Ghost.TButton", background=PANEL2, foreground=TEXT,
                        font=(FONT, 9), borderwidth=0, padding=(12, 7),
                        lightcolor=PANEL2, darkcolor=PANEL2, bordercolor=BORDER)
        style.map("Ghost.TButton",
                  background=[("pressed", "#3a3a56"), ("active", "#3a3a56"),
                              ("disabled", "#26262f")],
                  foreground=[("active", TEXT), ("disabled", MUTED)],
                  lightcolor=[("active", "#3a3a56"), ("pressed", "#3a3a56")],
                  darkcolor=[("active", "#3a3a56"), ("pressed", "#3a3a56")])

        style.configure("Tab.TButton", background=PANEL2, foreground=MUTED,
                        font=(FONT_BOLD, 10), borderwidth=0, padding=(18, 9),
                        lightcolor=PANEL2, darkcolor=PANEL2, bordercolor=BORDER)
        style.map("Tab.TButton",
                  background=[("active", "#3a3a56")],
                  foreground=[("active", TEXT)],
                  lightcolor=[("active", "#3a3a56")],
                  darkcolor=[("active", "#3a3a56")])

        style.configure("TabActive.TButton", background=ACCENT, foreground="#06222e",
                        font=(FONT_BOLD, 10), borderwidth=0, padding=(18, 9),
                        lightcolor=ACCENT, darkcolor=ACCENT, bordercolor=ACCENT)
        style.map("TabActive.TButton",
                  background=[("active", ACCENT_HOVER)],
                  lightcolor=[("active", ACCENT_HOVER)],
                  darkcolor=[("active", ACCENT_HOVER)])

        style.configure("TSeparator", background=BORDER)
        style.configure("TCheckbutton", indicatorbackground=PANEL2,
                        indicatorforeground="#ffffff", indicatormargin=(0, 0, 6, 0))
        style.map("TCheckbutton",
                  indicatorbackground=[("selected", ACCENT), ("active", "#46465c")])
        style.map("TSpinbox", fieldbackground=[("!disabled", PANEL2)],
                  foreground=[("!disabled", TEXT)])
        style.configure("TSpinbox", fieldbackground=PANEL2, foreground=TEXT,
                        background=PANEL2, arrowcolor=TEXT, bordercolor=BORDER,
                        insertcolor=TEXT)
        style.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG,
                        bordercolor=BG, arrowcolor=MUTED, relief="flat",
                        arrowsize=12)
        style.map("Vertical.TScrollbar", background=[("active", "#46465c")])

    def _icon(self):
        try:
            ico = config.BASE_DIR / "muecos.ico"
            if not ico.exists():
                ico = config.BASE_DIR / "metacheck.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except tk.TclError:
            pass

    # -------------------------------------------------------------- layout
    def _build(self):
        # header: logo + title (with version) on the left, tabs on the right
        header = ttk.Frame(self, style="Panel.TFrame")
        header.pack(fill="x")
        logo_path = config.BASE_DIR / "muecos_small.png"
        if not logo_path.exists():
            logo_path = config.BASE_DIR / "metacheck_logo_small.png"
        if logo_path.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(logo_path))
                ttk.Label(header, image=self.logo_img, background=PANEL).pack(
                    side="left", padx=(16, 10), pady=12)
            except tk.TclError:
                pass
        ttl = ttk.Frame(header, style="Panel.TFrame")
        ttl.pack(side="left", pady=12)
        ttk.Label(ttl, text=f"MüCOS Manuscript Checker v{DESKTOP_APP_VERSION}",
                  style="Title.TLabel").pack(anchor="w")
        self._title_frame = ttl

        # spacer to push the tabs to the right
        spacer = ttk.Frame(header, style="Panel.TFrame")
        spacer.pack(side="left", fill="x", expand=True)
        self._header_spacer = spacer

        tabbar = ttk.Frame(header, style="Panel.TFrame")
        tabbar.pack(side="right", padx=16, pady=12)
        self._tab_btns = {}
        for name in ("Manuscript", "Checks", "About"):
            b = ModernButton(tabbar, text=name, style="Tab.TButton",
                           command=lambda n=name: self._show_tab(n))
            b.pack(side="left", padx=(0, 8))
            self._tab_btns[name] = b

        self._panels = {}
        for name in ("Manuscript", "Checks", "About"):
            self._panels[name] = ttk.Frame(self, style="Panel.TFrame")

        self._build_run(self._panels["Manuscript"])
        self._build_checks(self._panels["Checks"])
        self._build_about(self._panels["About"])
        self._show_tab("Manuscript")

        # keep the tab buttons visible: hide the header title when the window
        # is too narrow to fit it alongside the tabs.
        self.bind("<Configure>", self._on_header_resize)

    def _on_header_resize(self, event=None):
        """Hide/show the header title based on the window width.

        The three tab buttons are always kept visible; if the window is too
        narrow to show the "MüCOS Manuscript Checker v…" title as well, the
        title is hidden instead.
        """
        if not hasattr(self, "_title_frame"):
            return
        width = self.winfo_width()
        # below this width the title no longer fits next to the tabs
        breakpoint = 720
        if width < breakpoint:
            if self._title_frame.winfo_manager():
                self._title_frame.pack_forget()
        else:
            if not self._title_frame.winfo_manager():
                self._title_frame.pack(side="left", pady=12,
                                       before=self._header_spacer)

    def _show_tab(self, name):
        for n, p in self._panels.items():
            if n == name:
                p.pack(fill="both", expand=True, padx=14, pady=12)
                self._tab_btns[n].config(style="TabActive.TButton")
            else:
                p.pack_forget()
                self._tab_btns[n].config(style="Tab.TButton")

    def _build_run(self, panel):
        # manuscript
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Manuscript", width=13).pack(side="left")
        self.man_entry = ttk.Entry(row)
        self.man_entry.pack(side="left", fill="x", expand=True, padx=6)
        ModernButton(row, text="Browse…", style="Ghost.TButton",
                   command=self.browse).pack(side="left")

        # grobid
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="GROBID server", width=13).pack(side="left")
        self.grobid_box = ttk.Combobox(row, state="readonly",
                                       values=list(self.grobid_by_label.keys()))
        # default to TUE (first entry)
        self.grobid_box.current(0)
        self.grobid_box.pack(side="left", fill="x", expand=True, padx=6)
        ModernButton(row, text="Refresh", style="Ghost.TButton",
                   command=self._refresh_status).pack(side="left")

        # custom url
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Custom URL", width=13).pack(side="left")
        self.custom_entry = ttk.Entry(row)
        self.custom_entry.pack(side="left", fill="x", expand=True, padx=6)

        # run + status row
        run_row = ttk.Frame(panel)
        run_row.pack(fill="x", pady=(0, 6))
        self.run_btn = ModernButton(run_row, text="Run check",
                                  style="Accent.TButton", command=self.run)
        self.run_btn.pack(side="left")
        self.rerun_btn = ModernButton(run_row, text="Run again with new phrases",
                                      style="Ghost.TButton",
                                      command=self.run_again_new_phrases)
        self.status_lbl = ttk.Label(run_row, style="Muted.TLabel", text="")
        self.status_lbl.pack(side="left", padx=10)

        # version row + update button
        ver_row = ttk.Frame(panel)
        ver_row.pack(fill="x", pady=(0, 8))
        self.ver_lbl = ttk.Label(ver_row, style="Muted.TLabel", text="metacheck pkg: …")
        self.ver_lbl.pack(side="left")
        ModernButton(ver_row, text="Update metacheck", style="Ghost.TButton",
                   command=self.update_metacheck).pack(side="left", padx=8)

        ttk.Separator(panel).pack(fill="x", pady=(0, 8))

        # result buttons - pack at the bottom so they stay visible
        rrow = ttk.Frame(panel)
        rrow.pack(fill="x", side="bottom")
        self.view_manuscript_btn = ModernButton(rrow, text="View manuscript",
                                              style="Ghost.TButton",
                                              state="disabled",
                                              command=self.view_manuscript)
        self.view_manuscript_btn.pack(side="left", padx=(0, 6))
        self.open_report_btn = ModernButton(rrow, text="Open report",
                                          style="Ghost.TButton", state="disabled",
                                          command=self.open_report)
        self.open_report_btn.pack(side="left", padx=(0, 6))
        ModernButton(rrow, text="All reports", style="Ghost.TButton",
                   command=self.open_reports).pack(side="left")

        # log - expands to fill the remaining space above the buttons
        ttk.Label(panel, text="Progress", style="Muted.TLabel").pack(anchor="w")
        self.log = tk.Text(panel, height=10, wrap="word", bg=LOG_BG, fg=LOG_TEXT,
                           insertbackground=LOG_TEXT, relief="flat",
                           padx=10, pady=8, font=(FONT, 9))
        self.log.pack(fill="both", expand=True, pady=(4, 8))
        self.log.configure(state="disabled")

    def _build_checks(self, panel):
        # check engine selector (on top)
        eng = ttk.Frame(panel)
        eng.pack(fill="x", pady=(0, 8))
        ttk.Label(eng, text="Check engine", width=13).pack(side="left")
        engine_frame = ttk.Frame(eng)
        engine_frame.pack(side="left", fill="x", expand=True, padx=6)
        imgs = self._load_engine_logos()
        for value, caption in (("metacheck", "metacheck (R)"),
                               ("chetameck", "ChetaMeck (Python)"),
                               ("plagiarism", "Plagiarism Check")):
            EngineCard(engine_frame, value, caption, imgs.get(value),
                       self.engine_vars[value], self._on_engine_change).pack(
                           side="left", padx=(0, 12))

        # online checks (below engine)
        self.online_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(panel, text="Include online checks (CrossRef, repositories, retractions)",
                        variable=self.online_var).pack(anchor="w", pady=(0, 8))

        ttk.Separator(panel).pack(fill="x", pady=(0, 8))

        # options of the Plagiarism Check engine (shown only for that engine)
        self._plag_frame = ttk.Frame(panel)
        ttk.Label(self._plag_frame, text="Plagiarism Check",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(self._plag_frame, style="Muted.TLabel", wraplength=560,
                  justify="left", text=(
                      "Licence-free: phrases are searched in open full texts "
                      "(Europe PMC, OpenAlex); best candidates, local files and "
                      "your literature folder are compared with the whole "
                      "manuscript (6-word shingles, matches of 8+ words; "
                      "quotes and citations excluded).")).pack(
                          anchor="w", pady=(2, 6))
        prow = ttk.Frame(self._plag_frame)
        prow.pack(fill="x", pady=(0, 2))
        ttk.Label(prow, text="Phrases to search", width=18).pack(side="left")
        tk.Spinbox(prow, from_=20, to=400, increment=20, width=6,
                   textvariable=self.plag_passages, bg=PANEL2, fg=TEXT,
                   insertbackground=TEXT, relief="flat", buttonbackground=PANEL2,
                   highlightthickness=1, highlightbackground=BORDER,
                   highlightcolor=ACCENT, disabledbackground=PANEL2
                   ).pack(side="left", padx=6)
        ttk.Label(prow, text="Seed", width=5).pack(side="left", padx=(14, 0))
        ttk.Entry(prow, textvariable=self.plag_seed, width=9).pack(
            side="left", padx=6)
        ttk.Label(prow, style="Muted.TLabel",
                  text="blank = random (shown in the report)").pack(side="left")
        ttk.Label(self._plag_frame, style="Muted.TLabel", wraplength=640,
                  justify="left", text=(
                      "A phrase = a 9-word excerpt searched online as an exact "
                      "word sequence. Only searched phrases can find online "
                      "sources; a typical manuscript has ~300, so 120 covers "
                      "it only partly. Exact totals, searched and unchecked "
                      "passages are shown in the log and report. Literature "
                      "folder and local files are always compared in full.")
                  ).pack(anchor="w", pady=(2, 2))
        self._plag_last_lbl = ttk.Label(self._plag_frame, style="Muted.TLabel",
                                        wraplength=640, justify="left", text="")
        self._plag_last_lbl.pack(anchor="w")
        ttk.Checkbutton(self._plag_frame, variable=self.plag_skip_used,
                        text="Skip phrases already used in earlier runs of this "
                             "manuscript (check different passages)").pack(
                                 anchor="w", pady=(2, 8))
        erow = ttk.Frame(self._plag_frame)
        erow.pack(fill="x", pady=(0, 2))
        ttk.Label(erow, text="API e-mail", width=18).pack(side="left")
        ttk.Entry(erow, textvariable=self.plag_mailto).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Label(self._plag_frame, style="Muted.TLabel", wraplength=640,
                  justify="left", text=(
                      "Optional. Sent to OpenAlex (faster 'polite pool') and in "
                      "the request header; stored only on this PC, never "
                      "written into reports.")).pack(anchor="w", pady=(0, 4))
        frow = ttk.Frame(self._plag_frame)
        frow.pack(fill="x", pady=(0, 4))
        ttk.Label(frow, text="Compare with files", width=18).pack(side="left")
        ModernButton(frow, text="Add files...", style="Ghost.TButton",
                     command=self._plag_add_files).pack(side="left", padx=6)
        ModernButton(frow, text="Clear", style="Ghost.TButton",
                     command=self._plag_clear_files).pack(side="left")
        lrow = ttk.Frame(self._plag_frame)
        lrow.pack(fill="x", pady=(8, 4))
        ttk.Label(lrow, text="Literature folder", width=18).pack(side="left")
        ttk.Entry(lrow, textvariable=self.plag_lib).pack(
            side="left", fill="x", expand=True, padx=6)
        ModernButton(lrow, text="Browse...", style="Ghost.TButton",
                   command=self._plag_browse_lib).pack(side="left")
        ttk.Label(self._plag_frame, style="Muted.TLabel", wraplength=560,
                  justify="left", text=(
                      "Optional: your Zotero / literature folder (searched "
                      "recursively for PDF, DOCX, TXT, HTML). Text is cached, "
                      "so only the first run is slow.")).pack(anchor="w")
        self._plag_files_lbl = ttk.Label(self._plag_frame, style="Muted.TLabel",
                                         wraplength=560, justify="left",
                                         text="No local comparison files (e.g. "
                                              "add the original study as PDF).")
        self._plag_files_lbl.pack(anchor="w")

        self._modules_wrap = ttk.Frame(panel)
        self._modules_wrap.pack(fill="both", expand=True)
        top = ttk.Frame(self._modules_wrap)
        top.pack(fill="x")
        ttk.Label(top, text="Checks to run", style="Title.TLabel").pack(side="left")
        self.modules_count_lbl = ttk.Label(top, style="Muted.TLabel", text="")
        self.modules_count_lbl.pack(side="left", padx=10)
        ModernButton(top, text="Select none", style="Ghost.TButton",
                   command=self._select_no_modules).pack(side="right", padx=6)
        ModernButton(top, text="Select all", style="Ghost.TButton",
                   command=self._select_all_modules).pack(side="right")

        body = ttk.Frame(self._modules_wrap)
        body.pack(fill="both", expand=True, pady=(10, 0))
        canvas = tk.Canvas(body, bg=PANEL, highlightthickness=0)
        vsb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=PANEL)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        # keep the inner frame's width in sync with the canvas so wrapped text
        # reflows correctly when the window is resized.
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win, width=e.width))
        self._checks_canvas = canvas
        self._checks_window = win
        self._bind_checks_wheel(canvas)

        from chetameck.catalog import CATEGORIES
        self._module_vars = {}
        self._check_sections = {}
        for cat_name, cat in CATEGORIES.items():
            group = tk.Frame(inner, bg=PANEL)
            group.pack(fill="x", pady=(8, 0))
            hdr = tk.Frame(group, bg=PANEL)
            hdr.pack(fill="x")
            arrow = tk.Label(hdr, text="\u25BE", bg=PANEL, fg=ACCENT,
                             font=(FONT_BOLD, 11), cursor="hand2")
            arrow.pack(side="left", padx=(0, 4))
            tk.Label(hdr, text=cat["label"], bg=PANEL, fg=ACCENT,
                     font=(FONT_BOLD, 10)).pack(side="left")
            names = [m[0] for m in cat["modules"]]
            ModernButton(hdr, text="All", style="Small.TButton",
                         command=lambda ns=names: self._set_modules(ns, True)
                         ).pack(side="right", padx=2)
            ModernButton(hdr, text="None", style="Small.TButton",
                         command=lambda ns=names: self._set_modules(ns, False)
                         ).pack(side="right", padx=2)
            body_frame = tk.Frame(group, bg=PANEL)
            body_frame.pack(fill="x")
            self._check_sections[cat_name] = (body_frame, arrow)
            arrow.bind("<Button-1>",
                       lambda e, c=cat_name: self._toggle_checks_section(c))
            for mname, label, desc in cat["modules"]:
                var = tk.BooleanVar(value=(mname in self.selected_modules))
                self._module_vars[mname] = var
                ttk.Checkbutton(body_frame, text=label, variable=var,
                                command=self._update_module_count).pack(
                                    anchor="w", padx=(12, 0))
                if desc:
                    tk.Label(body_frame, text="      " + desc, bg=PANEL, fg=MUTED,
                             font=(FONT, 8), wraplength=430,
                             justify="left").pack(anchor="w", padx=(16, 0))
        self._bind_checks_wheel(inner)
        self._update_module_count()
        self._on_engine_change()

    def selected_engines(self):
        """Return the list of engine names currently selected."""
        return [e for e in pipeline.ENGINES if self.engine_vars[e].get()]

    def _on_engine_change(self):
        sel = set(self.selected_engines())
        if hasattr(self, "rerun_btn"):
            if "plagiarism" in sel:
                self.rerun_btn.pack(side="left", padx=(8, 0), after=self.run_btn)
            else:
                self.rerun_btn.pack_forget()
        show_mod = bool(sel & {"metacheck", "chetameck"})
        show_plag = "plagiarism" in sel
        for w in (self._plag_frame, self._modules_wrap):
            w.pack_forget()
        if show_plag:
            self._plag_frame.pack(fill="x", pady=(0, 8))
        if show_mod:
            self._modules_wrap.pack(fill="both", expand=True)

    @staticmethod
    def _settings_file():
        return config.default_output_dir() / "settings.json"

    def _load_setting(self, key):
        import json
        try:
            return json.loads(self._settings_file().read_text(
                encoding="utf-8")).get(key, "")
        except Exception:  # noqa: BLE001
            return ""

    def _save_setting(self, key, value):
        import json
        try:
            f = self._settings_file()
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                d = {}
            d[key] = value
            f.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _plag_browse_lib(self):
        d = filedialog.askdirectory(title="Choose your literature / Zotero folder",
                                    initialdir=self.plag_lib.get() or None)
        if d:
            self.plag_lib.set(os.path.normpath(d))

    def _plag_add_files(self):
        paths = filedialog.askopenfilenames(
            title="Choose comparison documents",
            filetypes=[("Documents", "*.pdf *.docx *.txt *.md *.html *.htm"),
                       ("All files", "*.*")])
        for p in paths:
            if p not in self.plag_files:
                self.plag_files.append(p)
        self._plag_refresh_files()

    def _plag_clear_files(self):
        self.plag_files = []
        self._plag_refresh_files()

    def _plag_refresh_files(self):
        if self.plag_files:
            self._plag_files_lbl.config(
                text="\n".join(Path(p).name for p in self.plag_files))
        else:
            self._plag_files_lbl.config(
                text="No local comparison files (e.g. add the original "
                     "study as PDF).")

    def _set_modules(self, names, val):
        for n in names:
            if n in self._module_vars:
                self._module_vars[n].set(val)
        self._update_module_count()

    def _toggle_checks_section(self, cat_name):
        body_frame, arrow = self._check_sections[cat_name]
        if body_frame.winfo_manager():
            body_frame.pack_forget()
            arrow.config(text="\u25B8")
        else:
            body_frame.pack(fill="x")
            arrow.config(text="\u25BE")
        if self._checks_canvas.winfo_exists():
            self._checks_canvas.configure(
                scrollregion=self._checks_canvas.bbox("all"))

    def _on_checks_mousewheel(self, event):
        self._checks_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _bind_checks_wheel(self, widget):
        widget.bind("<MouseWheel>", self._on_checks_mousewheel)
        for child in widget.winfo_children():
            self._bind_checks_wheel(child)

    def _select_all_modules(self):
        for v in self._module_vars.values():
            v.set(True)
        self._update_module_count()

    def _select_no_modules(self):
        for v in self._module_vars.values():
            v.set(False)
        self._update_module_count()

    def _update_module_count(self):
        order = self.all_chetameck_modules
        sel = [n for n in order if self._module_vars.get(n) and self._module_vars[n].get()]
        self.selected_modules = sel
        self.modules_count_lbl.config(
            text=f"{len(sel)} of {len(order)} selected")

    def _load_engine_logos(self):
        imgs = {}
        for key, fname in (("metacheck", "metacheck_logo_small.png"),
                           ("chetameck", "chetameck_logo_small.png"),
                           ("plagiarism", "plagcheck_logo_small.png")):
            p = config.BASE_DIR / fname
            if not p.exists():
                p = config.BASE_DIR / "muecos_small.png"
            if p.exists():
                try:
                    im = tk.PhotoImage(file=str(p))
                    if im.width() > 100:
                        im = im.subsample(max(1, round(im.width() / 88)))
                    imgs[key] = im
                except tk.TclError:
                    pass
        self._engine_logo_imgs = imgs
        return imgs

    def _build_about(self, panel):
        ttk.Label(panel, text=f"MüCOS Manuscript Checker v{DESKTOP_APP_VERSION}",
                  style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(panel, text=(
            "Turns a manuscript (PDF / DOCX / DOC / HTML) into a metacheck report.\n"
            "It converts the document to TEI XML with GROBID, then runs automated\n"
            "meta-scientific quality checks."),
            style="Panel.TLabel", wraplength=560, justify="left").pack(anchor="w", pady=(0, 12))
        ttk.Label(panel, text="Dependencies:", style="Muted.TLabel").pack(anchor="w")
        self.about_status_lbl = ttk.Label(panel, style="Panel.TLabel", text="",
                                          wraplength=560, justify="left")
        self.about_status_lbl.pack(anchor="w", pady=(2, 8))
        self.about_ver_lbl = ttk.Label(panel, style="Muted.TLabel", text="")
        self.about_ver_lbl.pack(anchor="w", pady=(0, 12))
        ttk.Label(panel, text="Checks run via the metacheck (R) package, the "
                              "ChetaMeck (Python) engine, or the licence-free "
                              "Plagiarism Check algorithm.",
                  style="Muted.TLabel", wraplength=560).pack(anchor="w")
        ttk.Separator(panel).pack(fill="x", pady=(0, 12))
        ttk.Label(panel, text="Coded by DeepSeek V4 Flash · Prompted by Lukas Röseler",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Not affiliated with the official metacheck app · "
                              "For private use only",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Separator(panel).pack(fill="x", pady=(0, 12))
        upd_row = ttk.Frame(panel)
        upd_row.pack(fill="x")
        self.update_btn = ModernButton(upd_row, text="Check for updates",
                                       style="Ghost.TButton",
                                       command=lambda: self.check_updates(manual=True))
        self.update_btn.pack(side="left")
        self.update_lbl = ttk.Label(upd_row, style="Muted.TLabel", text="")
        self.update_lbl.pack(side="left", padx=10)

    # -------------------------------------------------------------- helpers
    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _ui(self, fn, *args):
        self.after(0, lambda: fn(*args))

    def _refresh_status(self):
        parts = []
        parts.append("R: " + ("✓" if config.RSCRIPT else "✗"))
        parts.append("LibreOffice: " + ("✓" if config.SOFFICE else "✗ (PDF only)"))
        parts.append("ChetaMeck: " + ("✓" if self._chetameck_ok() else "✗"))
        ver = pipeline.get_metacheck_version()
        pkg = ver or "✗ not installed"
        status_text = "   ".join(parts)
        ver_text = (f"metacheck pkg v{pkg} · "
                    f"MüCOS Manuscript Checker v{DESKTOP_APP_VERSION}")
        if hasattr(self, "status_lbl"):
            self.status_lbl.config(text=status_text)
        if hasattr(self, "ver_lbl"):
            self.ver_lbl.config(text=ver_text)
        if hasattr(self, "about_status_lbl"):
            self.about_status_lbl.config(text=status_text)
        if hasattr(self, "about_ver_lbl"):
            self.about_ver_lbl.config(text=ver_text)

    @staticmethod
    def _chetameck_ok():
        try:
            import chetameck  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    # --------------------------------------------------------------- actions
    def browse(self):
        path = filedialog.askopenfilename(
            title="Choose a manuscript",
            filetypes=[
                ("Manuscripts", "*.pdf *.docx *.doc *.html *.htm"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx *.doc"),
                ("HTML", "*.html *.htm"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.manuscript = path
            self.man_entry.delete(0, "end")
            self.man_entry.insert(0, path)
            self._update_view_manuscript()

    def _grobid_url(self):
        custom = self.custom_entry.get().strip()
        if custom:
            return custom
        return self.grobid_by_label.get(self.grobid_box.get(),
                                        config.DEFAULT_GROBID_URL)

    def update_metacheck(self):
        self._append("Updating metacheck…")
        self._append("This may take a minute.")

        def worker():
            try:
                ver = pipeline.update_metacheck(on_log=lambda t: self._ui(self._append, t))
                self._ui(self._append, f"metacheck updated to {ver}.")
            except Exception as e:  # noqa: BLE001
                self._ui(self._append, f"Update failed: {e}")
            finally:
                self._ui(self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def run_again_new_phrases(self):
        """Plagiarism Check: new random seed, skipping all phrases used so far."""
        for e, v in self.engine_vars.items():
            v.set(e == "plagiarism")
        self._on_engine_change()
        self.plag_seed.set("")
        self.plag_skip_used.set(True)
        self.run()

    def run(self):
        if not self.manuscript:
            messagebox.showwarning("ManuscriptChecker", "Please choose a manuscript first.")
            return
        engines = self.selected_engines()
        if not engines:
            messagebox.showwarning("ManuscriptChecker",
                                   "Please select at least one check engine.")
            return
        self.report_path = None
        self.xml_path = None
        self.pdf_path = None
        self.outdir = None
        self.open_report_btn.config(state="disabled")
        self.view_manuscript_btn.config(state="disabled")
        self.run_btn.config(state="disabled")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._append(f"Manuscript: {self.manuscript}")
        self._append(f"GROBID: {self._grobid_url()}")
        self._append(f"Engines: {', '.join(engines)}")

        def on_step(name, status, message):
            icon = {"done": "✔", "running": "…", "error": "✖"}.get(status, "•")
            self._ui(self._append, f"[{icon}] {name}: {message}")

        def worker():
            try:
                if "plagiarism" in engines:
                    self._save_setting("library_dir", self.plag_lib.get().strip())
                    self._save_setting("mailto", self.plag_mailto.get().strip())
                plag_options = {
                    "max_passages": int(self.plag_passages.get() or 120),
                    "extra_files": list(self.plag_files),
                    "online": bool(self.online_var.get()),
                    "library_dir": self.plag_lib.get().strip() or None,
                    "seed": (int(self.plag_seed.get())
                             if self.plag_seed.get().strip().isdigit() else None),
                    "skip_used": bool(self.plag_skip_used.get()),
                    "mailto": self.plag_mailto.get().strip() or None,
                } if "plagiarism" in engines else None
                result = pipeline.run_pipeline(
                    self.manuscript,
                    grobid_url=self._grobid_url(),
                    modules=self.selected_modules,
                    include_online=self.online_var.get(),
                    engines=engines,
                    plag_options=plag_options,
                    on_step=on_step,
                    on_log=lambda t: self._ui(self._append, t),
                )
                self._ui(self._finished, result)
            except Exception as e:  # noqa: BLE001
                self._ui(self._fail, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _finished(self, result):
        self.run_btn.config(state="normal")
        reports = result.get("reports") or []
        done = [r for r in reports if r["status"] == "done"]
        failed = [r for r in reports if r["status"] != "done"]
        if done:
            first = done[0]
            self.report_path = first["report_path"]
            self.xml_path = result.get("xml_path")
            self.pdf_path = result.get("pdf_path")
            self.outdir = result.get("outdir")
            self.open_report_btn.config(state="normal")
            self._update_view_manuscript()
            plag = next((r for r in reports
                         if r.get("engine") == "plagiarism"), None)
            ph = (plag.get("report_json") or {}).get("phrases") if plag else None
            if ph:
                msg = (f"Phrases: {ph['searched']} searched this run (seed "
                       f"{ph['seed']}); {ph['cumulative']} of {ph['total']} "
                       f"({ph['cumulative'] / max(ph['total'], 1):.0%}) searched "
                       f"over {ph['runs']} run(s).")
                self._append(msg)
                self._plag_last_lbl.config(text="Last run: " + msg)
            self._append(f"Done. Opening {len(done)} report(s)…")
            self._append(f"Saved to: {self.outdir}")
            for r in done:
                if r.get("report_path"):
                    webbrowser.open(Path(r["report_path"]).as_uri())
            if failed:
                self._append("Note: some engines failed: " + ", ".join(
                    f"{r.get('engine')}: {r.get('error')}" for r in failed))
        elif reports:
            err = "; ".join(f"{r.get('engine')}: {r.get('error')}"
                            for r in failed)
            self._append(f"FAILED: {err}")
            messagebox.showerror("ManuscriptChecker", err)
        else:
            self._append(f"FAILED: {result.get('error')}")
            messagebox.showerror("ManuscriptChecker", result.get("error"))

    def _fail(self, msg):
        self.run_btn.config(state="normal")
        self._append("ERROR: " + msg)
        messagebox.showerror("ManuscriptChecker", msg)

    # -------------------------------------------------------------- updates
    def check_updates(self, manual=True):
        """Check the GitLab repo for a newer build; download+stage it if found.

        ``manual`` (button press) prompts before downloading; the startup check
        (``manual=False``) downloads automatically and only reports the result.
        """
        import updater
        self.update_btn.config(state="disabled")
        if hasattr(self, "update_lbl"):
            self.update_lbl.config(text="Checking for updates…")

        def worker():
            info = updater.check_for_update()
            self._ui(self._on_update_checked, info, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_checked(self, info, manual):
        if hasattr(self, "update_btn"):
            self.update_btn.config(state="normal")
        if not info:
            self._append("Update check: could not reach the update server.")
            if hasattr(self, "update_lbl"):
                self.update_lbl.config(text="Could not check for updates.")
            return
        if not info.get("available"):
            self._append(f"Update check: up to date (v{info['latest_version']}).")
            if hasattr(self, "update_lbl"):
                self.update_lbl.config(text=f"Up to date (v{info['latest_version']}).")
            return
        latest = info["latest_version"]
        self._append(f"Update available: v{latest} (current v{DESKTOP_APP_VERSION}).")
        if manual:
            ans = messagebox.askyesno(
                "Update available",
                f"A newer version (v{latest}) is available.\n\n"
                f"{info.get('notes', '')}\n\nDownload and install it now?",
                parent=self)
            if not ans:
                if hasattr(self, "update_lbl"):
                    self.update_lbl.config(
                        text=f"Update v{latest} available (not installed).")
                return
        self._download_update(info)

    def _download_update(self, info):
        import updater
        latest = info["latest_version"]
        # If a build is already staged, don't download it again.
        exe = updater.exe_path()
        if exe:
            new = exe.with_name(exe.name + ".new")
            if new.exists() and new.stat().st_size > 0:
                self._append(f"Update v{latest} already downloaded. "
                             "It will install when you close the app.")
                if hasattr(self, "update_lbl"):
                    self.update_lbl.config(
                        text=f"Update v{latest} downloaded — restart to install.")
                return
        if hasattr(self, "update_lbl"):
            self.update_lbl.config(text=f"Downloading v{latest}…")

        def worker():
            try:
                updater.install_update(
                    info["exe_url"],
                    on_log=lambda t: self._ui(self._append, t))
                self._ui(self._append,
                         f"Update v{latest} downloaded. It will install "
                         "automatically when you close and reopen the app.")
                self._ui(self.update_lbl.config, {
                    "text": f"Update v{latest} downloaded — restart to install."})
                self._ui(lambda: messagebox.showinfo(
                    "Update ready",
                    "The update has been downloaded. It will install "
                    "automatically when you close and reopen the app.",
                    parent=self))
            except Exception as e:  # noqa: BLE001
                self._ui(self._append, f"Update failed: {e}")
                self._ui(self.update_lbl.config, {"text": f"Update failed: {e}"})

        threading.Thread(target=worker, daemon=True).start()

    def _startup_update_check(self):
        self.check_updates(manual=False)

    # ---------------------------------------------------------------- open
    def view_manuscript(self):
        target = self.pdf_path or (self.manuscript
                                   if self.manuscript and
                                   str(self.manuscript).lower().endswith(".pdf")
                                   else None)
        if target:
            webbrowser.open(Path(target).as_uri())
        else:
            messagebox.showinfo(
                "ManuscriptChecker",
                "No PDF manuscript is available to view. The selected file is "
                "not a PDF and has not been converted yet.")

    def _update_view_manuscript(self):
        # enabled when a PDF is available: either the original manuscript is a
        # PDF, or the pipeline has produced a converted PDF for a DOCX/HTML input.
        has_pdf = bool(self.pdf_path) or bool(
            self.manuscript and str(self.manuscript).lower().endswith(".pdf"))
        self.view_manuscript_btn.config(
            state="normal" if has_pdf else "disabled")

    def open_report(self):
        if self.report_path:
            webbrowser.open(Path(self.report_path).as_uri())

    def open_reports(self):
        d = config.default_output_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)


if __name__ == "__main__":
    App().mainloop()
