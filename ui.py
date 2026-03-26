from __future__ import annotations

import os
import threading
import time
import shutil
from queue import Queue, Empty
from typing import Dict, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

try:
    from .function import AdbClient, ScreenshotSelector, Settings, resolve_path
    from .main import AutoHunter, Stats
except ImportError:  # run as script
    from function import AdbClient, ScreenshotSelector, Settings, resolve_path
    from main import AutoHunter, Stats


Point = Tuple[int, int]
ROI = Tuple[int, int, int, int]

# ── Dark Neon Palette ────────────────────────────────────────────────────────
BG_DARK    = "#0d0f14"
BG_PANEL   = "#12151c"
BG_CARD    = "#181c26"
BG_INPUT   = "#1e2330"
BG_HOVER   = "#222840"

NEON_CYAN  = "#00e5ff"
NEON_GREEN = "#00ff9d"
NEON_PINK  = "#ff2d78"
NEON_YEL   = "#ffe500"

FG_TEXT    = "#d0d8f0"
FG_DIM     = "#6a7599"
FG_LABEL   = "#a0b0d8"
FG_HEAD    = "#ffffff"

BORDER_GLOW = "#1e3a5f"
BORDER_ACT  = NEON_CYAN

BTN_BG     = "#1a2540"
BTN_ACT    = "#00c8e8"
BTN_START  = "#003d2b"
BTN_STOP   = "#3a0012"

FONT_UI    = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_MONO  = ("Consolas", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI", 11, "bold")


def _neon_frame(parent, glow=BORDER_GLOW, bd=1, bg=BG_CARD, **kw) -> tk.Frame:
    """A tk.Frame with a neon-coloured border wrapper."""
    outer = tk.Frame(parent, bg=glow, bd=0, highlightthickness=0)
    inner = tk.Frame(outer, bg=bg, bd=0, highlightthickness=0, **kw)
    inner.pack(fill="both", expand=True, padx=bd, pady=bd)
    outer._inner = inner
    return outer


class _GlowLabel(tk.Label):
    """Label that looks like a glowing neon badge."""
    def __init__(self, master, text="", color=NEON_CYAN, **kw):
        super().__init__(
            master, text=text, bg=BG_DARK, fg=color,
            font=FONT_BOLD, **kw
        )


class _Section(tk.Frame):
    """Compact dark LabelFrame replacement with neon header line."""
    def __init__(self, parent, title="", accent=NEON_CYAN, **kw):
        super().__init__(parent, bg=BG_CARD, bd=0, highlightthickness=1,
                         highlightbackground=BORDER_GLOW, **kw)
        hdr = tk.Frame(self, bg=BG_CARD)
        hdr.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(hdr, text=title, bg=BG_CARD, fg=accent,
                 font=FONT_BOLD).pack(side="left")
        tk.Frame(hdr, bg=accent, height=1).pack(side="left", fill="x", expand=True, padx=(6, 0), pady=6)
        self.body = tk.Frame(self, bg=BG_CARD)
        self.body.pack(fill="both", expand=True, padx=8, pady=(4, 8))


def _entry(parent, textvariable, width=None, **kw) -> tk.Entry:
    opts = dict(
        bg=BG_INPUT, fg=FG_TEXT, insertbackground=NEON_CYAN,
        relief="flat", font=FONT_UI,
        highlightthickness=1, highlightbackground=BORDER_GLOW,
        highlightcolor=NEON_CYAN,
    )
    if width:
        opts["width"] = width
    opts.update(kw)
    return tk.Entry(parent, textvariable=textvariable, **opts)


def _btn(parent, text, command=None, accent=NEON_CYAN, small=False, **kw) -> tk.Button:
    f = FONT_SMALL if small else FONT_UI
    b = tk.Button(
        parent, text=text, command=command,
        bg=BTN_BG, fg=accent,
        activebackground=BORDER_GLOW, activeforeground=FG_HEAD,
        relief="flat", font=f, cursor="hand2",
        highlightthickness=1, highlightbackground=accent,
        bd=0, padx=10, pady=4,
        **kw
    )
    def _on(e): b.config(bg=BORDER_GLOW)
    def _off(e): b.config(bg=BTN_BG)
    b.bind("<Enter>", _on)
    b.bind("<Leave>", _off)
    return b


def _lbl(parent, text="", fg=FG_LABEL, bold=False, **kw) -> tk.Label:
    f = FONT_BOLD if bold else FONT_UI
    return tk.Label(parent, text=text, bg=BG_CARD, fg=fg, font=f, **kw)


def _lbl2(parent, text="", fg=FG_LABEL, bold=False, bg=BG_DARK, **kw) -> tk.Label:
    """Label for darker backgrounds."""
    f = FONT_BOLD if bold else FONT_UI
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=f, **kw)


class App(tk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, bg=BG_DARK)
        self.master = master
        self.master.title("AutoHunt Dino Mutant: T-Rex")
        self.master.minsize(860, 560)
        self.master.configure(bg=BG_DARK)

        self.settings = Settings(resolve_path("AutoHuntDino/setting.json"))
        adb_path = resolve_path(self.settings.get("adb", "adb_path", default="AutoHuntDino/ADB/adb.exe"))
        self.adb = AdbClient(adb_path)

        self.log_q: Queue[str] = Queue()
        self.stats_q: Queue[Stats] = Queue()
        self.bot_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.connected_serial: str = ""
        self._adb_busy = False
        self._start_time: Optional[float] = None

        self._build_ui()
        self._load_settings_to_ui()
        self._tick()

    def _repo_root(self) -> str:
        return os.path.abspath(os.path.dirname(__file__))

    def _templates_dir(self) -> str:
        return os.path.join(self._repo_root(), "templates")

    def _short_template_value(self, any_path: str) -> str:
        """
        Normalize template path stored in setting.json to short form:
        './templates/<file>'
        """
        p = (any_path or "").strip()
        if not p:
            return ""

        p_norm = p.replace("\\", "/")
        while "//" in p_norm:
            p_norm = p_norm.replace("//", "/")
        if p_norm.startswith("./templates/"):
            return p_norm

        # If it includes templates/<tail>, keep only the tail.
        if "/templates/" in p_norm:
            tail = p_norm.split("/templates/", 1)[1].lstrip("/")
            return "./templates/" + tail

        # Last resort: try to derive from absolute location.
        tdir = os.path.abspath(self._templates_dir())
        if os.path.isabs(p):
            abs_candidate = os.path.abspath(p)
            try:
                if abs_candidate.startswith(tdir + os.sep):
                    rel = os.path.relpath(abs_candidate, tdir)
                    return "./templates/" + rel.replace("\\", "/")
            except Exception:
                pass

        return "./templates/" + os.path.basename(p)

    # ── UI Build ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        nb = self._build_notebook(self)
        nb.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        # status bar
        self.var_status = tk.StringVar(value="Sẵn sàng")
        bar = tk.Frame(self, bg=BG_DARK)
        bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        bar.columnconfigure(0, weight=1)
        tk.Frame(bar, bg=BORDER_GLOW, height=1).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        tk.Label(bar, textvariable=self.var_status, bg=BG_DARK, fg=FG_DIM,
                 font=FONT_SMALL).grid(row=1, column=0, sticky="w")
        tk.Label(bar, text="AutoHunt v1.0", bg=BG_DARK, fg=FG_DIM,
                 font=FONT_SMALL).grid(row=1, column=1, sticky="e")

    def _build_notebook(self, parent) -> tk.Frame:
        """Custom tab notebook with dark neon style."""
        holder = tk.Frame(parent, bg=BG_DARK)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(1, weight=1)

        # Tab bar
        tabbar = tk.Frame(holder, bg=BG_DARK)
        tabbar.grid(row=0, column=0, sticky="ew")

        # Content area
        content = tk.Frame(holder, bg=BG_PANEL, highlightthickness=1,
                            highlightbackground=BORDER_GLOW)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self._tab_frames: Dict[str, tk.Frame] = {}
        self._tab_btns: Dict[str, tk.Button] = {}
        self._active_tab = tk.StringVar(value="main")

        tabs = [("main", "  ⚡ Chính  "), ("setting", "  ⚙ Setting  "), ("info", "  ℹ Infor  ")]

        for key, label in tabs:
            frm = tk.Frame(content, bg=BG_PANEL)
            frm.grid(row=0, column=0, sticky="nsew")
            frm.columnconfigure(0, weight=1)
            frm.rowconfigure(0, weight=1)
            self._tab_frames[key] = frm

            def _switch(k=key):
                self._show_tab(k)

            btn = tk.Button(tabbar, text=label, command=_switch,
                            bg=BG_PANEL, fg=FG_DIM, font=FONT_UI,
                            relief="flat", bd=0, padx=6, pady=6, cursor="hand2",
                            activebackground=BG_CARD, activeforeground=FG_HEAD)
            btn.pack(side="left")
            self._tab_btns[key] = btn

        # Build tab contents
        self.tab_main = self._tab_frames["main"]
        self.tab_setting = self._tab_frames["setting"]
        self.tab_info = self._tab_frames["info"]

        self._build_tab_main()
        self._build_tab_setting()
        self._build_tab_info()

        self._show_tab("main")
        return holder

    def _show_tab(self, key: str) -> None:
        for k, frm in self._tab_frames.items():
            frm.grid_remove()
            self._tab_btns[k].config(
                bg=BG_PANEL, fg=FG_DIM,
                highlightthickness=0
            )
        self._tab_frames[key].grid(row=0, column=0, sticky="nsew")
        self._tab_btns[key].config(
            bg=BG_CARD, fg=NEON_CYAN,
            highlightthickness=1, highlightbackground=NEON_CYAN
        )

    def _build_tab_main(self) -> None:
        f = self.tab_main
        f.columnconfigure(0, weight=0)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(0, weight=1)

        # ── Left panel ──────────────────────────────────────────────────────
        left = tk.Frame(f, bg=BG_PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.columnconfigure(0, weight=1)

        # Connection section
        conn_sec = _Section(left, title="Kết nối giả lập", accent=NEON_CYAN)
        conn_sec.grid(row=0, column=0, sticky="ew")
        g = conn_sec.body
        g.columnconfigure(1, weight=1)

        self.var_port = tk.StringVar(value="5555")
        _lbl(g, "Port").grid(row=0, column=0, sticky="w", pady=(0, 5))
        _entry(g, self.var_port, width=9).grid(row=0, column=1, sticky="ew", pady=(0, 5), padx=(6, 0))

        btnrow = tk.Frame(g, bg=BG_CARD)
        btnrow.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        btnrow.columnconfigure(0, weight=1)
        btnrow.columnconfigure(1, weight=1)
        self.btn_find = _btn(btnrow, "🔍 Tìm", self.on_find_emulator, small=True)
        self.btn_refresh = _btn(btnrow, "↻ Refresh", self.on_refresh_devices, accent=NEON_YEL, small=True)
        self.btn_find.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_refresh.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        _lbl(g, "Thiết bị").grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.var_serial = tk.StringVar(value="")
        self.cbo_serial = ttk.Combobox(g, textvariable=self.var_serial, state="readonly",
                                        font=FONT_UI)
        self._style_combobox()
        self.cbo_serial.grid(row=2, column=1, sticky="ew", pady=(0, 5), padx=(6, 0))

        self.btn_connect = _btn(g, "⚡ Kết nối", self.on_connect, accent=NEON_GREEN)
        self.btn_connect.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        # Connection status badge
        self.lbl_conn = tk.Label(left, text="● Chưa kết nối", bg=BG_PANEL,
                                  fg=NEON_PINK, font=FONT_SMALL)
        self.lbl_conn.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=4)

        # ── Control section ─────────────────────────────────────────────────
        ctrl_sec = _Section(left, title="Điều khiển", accent=NEON_GREEN)
        ctrl_sec.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        st = ctrl_sec.body
        st.columnconfigure(0, weight=1)
        st.columnconfigure(1, weight=1)

        # Stats row
        stats_row = tk.Frame(st, bg=BG_CARD)
        stats_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        stats_row.columnconfigure(0, weight=1)
        stats_row.columnconfigure(1, weight=1)

        # Success badge
        sc_card = tk.Frame(stats_row, bg=BG_INPUT, highlightthickness=1,
                            highlightbackground=NEON_GREEN)
        sc_card.grid(row=0, column=0, sticky="ew", padx=(0, 3), ipady=4)
        tk.Label(sc_card, text="✔ Thành công", bg=BG_INPUT, fg=FG_DIM, font=FONT_SMALL).pack()
        self.var_success = tk.StringVar(value="0")
        tk.Label(sc_card, textvariable=self.var_success, bg=BG_INPUT,
                 fg=NEON_GREEN, font=("Segoe UI", 15, "bold")).pack()

        # Fail badge
        fl_card = tk.Frame(stats_row, bg=BG_INPUT, highlightthickness=1,
                            highlightbackground=NEON_PINK)
        fl_card.grid(row=0, column=1, sticky="ew", padx=(3, 0), ipady=4)
        tk.Label(fl_card, text="✖ Fail streak", bg=BG_INPUT, fg=FG_DIM, font=FONT_SMALL).pack()
        self.var_failstreak = tk.StringVar(value="0")
        tk.Label(fl_card, textvariable=self.var_failstreak, bg=BG_INPUT,
                 fg=NEON_PINK, font=("Segoe UI", 15, "bold")).pack()

        # ── Uptime display ───────────────────────────────────────────────────
        up_card = tk.Frame(st, bg=BG_INPUT, highlightthickness=1,
                            highlightbackground=NEON_YEL)
        up_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8), ipady=3)
        tk.Label(up_card, text="⏱ Thời gian hoạt động", bg=BG_INPUT,
                 fg=FG_DIM, font=FONT_SMALL).pack()
        self.var_uptime = tk.StringVar(value="00:00:00")
        tk.Label(up_card, textvariable=self.var_uptime, bg=BG_INPUT,
                 fg=NEON_YEL, font=("Consolas", 14, "bold")).pack()

        # Start / Stop buttons
        self.btn_start = _btn(st, "▶ START", self.on_start,
                               accent=NEON_GREEN)
        self.btn_stop  = _btn(st, "■ STOP",  self.on_stop,
                               accent=NEON_PINK)
        self.btn_stop.config(state="disabled")

        self.btn_start.grid(row=2, column=0, sticky="ew", padx=(0, 3))
        self.btn_stop.grid( row=2, column=1, sticky="ew", padx=(3, 0))

        _btn(st, "🗑 Clear log", self.on_clear_log,
             accent=FG_DIM, small=True).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )

        # ── Right panel – Log ───────────────────────────────────────────────
        log_sec = _Section(f, title="Log", accent=NEON_CYAN)
        log_sec.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        log_sec.columnconfigure(0, weight=1)
        log_sec.rowconfigure(0, weight=1)
        log_sec.body.columnconfigure(0, weight=1)
        log_sec.body.rowconfigure(0, weight=1)

        self.txt_log = ScrolledText(
            log_sec.body, height=12, wrap="word", font=FONT_MONO,
            bg=BG_DARK, fg=NEON_CYAN, insertbackground=NEON_CYAN,
            relief="flat", bd=0,
            selectbackground=BORDER_GLOW, selectforeground=FG_HEAD,
        )
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        self.txt_log.configure(state="disabled")

        # Make log section actually expand
        f.rowconfigure(0, weight=1)
        log_sec.rowconfigure(0, weight=1)

    def _style_combobox(self) -> None:
        try:
            style = ttk.Style(self.master)
            style.theme_use("clam")
            style.configure("TCombobox",
                fieldbackground=BG_INPUT, background=BG_INPUT,
                foreground=FG_TEXT, arrowcolor=NEON_CYAN,
                bordercolor=BORDER_GLOW, lightcolor=BG_INPUT,
                darkcolor=BG_INPUT, selectbackground=BORDER_GLOW,
                selectforeground=FG_HEAD)
            style.map("TCombobox",
                fieldbackground=[("readonly", BG_INPUT)],
                foreground=[("readonly", FG_TEXT)],
                background=[("readonly", BG_INPUT)])
        except Exception:
            pass

    def _set_adb_busy(self, busy: bool, status_text: Optional[str] = None) -> None:
        self._adb_busy = busy
        state = "disabled" if busy else "normal"
        try:
            self.btn_find.config(state=state)
            self.btn_refresh.config(state=state)
            self.btn_connect.config(state=state)
        except Exception:
            pass
        if status_text:
            # Update connection label with colour cue
            color = NEON_YEL if busy else (NEON_GREEN if "kết nối" in status_text.lower() and "đang" not in status_text.lower() else FG_DIM)
            self.lbl_conn.config(text=f"● {status_text}", fg=color)
            self.var_status.set(status_text)

    def _run_bg(self, work, on_done=None, on_error=None) -> None:
        def _runner():
            try:
                res = work()
            except Exception as e:
                if on_error:
                    self.master.after(0, lambda err=e: on_error(err))
                else:
                    self.master.after(0, lambda err=e: messagebox.showerror("Lỗi", str(err)))
                return
            if on_done:
                self.master.after(0, lambda r=res: on_done(r))

        threading.Thread(target=_runner, daemon=True).start()

    # ── Setting Tab ─────────────────────────────────────────────────────────
    def _build_tab_setting(self) -> None:
        f = self.tab_setting
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        outer = tk.Frame(f, bg=BG_PANEL)
        outer.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        # Sub-tab bar
        sub_holder = tk.Frame(outer, bg=BG_PANEL)
        sub_holder.grid(row=0, column=0, sticky="nsew")
        sub_holder.columnconfigure(0, weight=1)
        sub_holder.rowconfigure(1, weight=1)

        sub_tabbar = tk.Frame(sub_holder, bg=BG_PANEL)
        sub_tabbar.grid(row=0, column=0, sticky="ew")

        sub_content = tk.Frame(sub_holder, bg=BG_PANEL, highlightthickness=1,
                                highlightbackground=BORDER_GLOW)
        sub_content.grid(row=1, column=0, sticky="nsew")
        sub_content.columnconfigure(0, weight=1)
        sub_content.rowconfigure(0, weight=1)

        self._stab_frames: Dict[str, tk.Frame] = {}
        self._stab_btns: Dict[str, tk.Button] = {}

        stabs = [("coords", "Tọa độ"), ("rois", "ROI"), ("templates", "Templates"), ("advanced", "Nâng cao")]

        for key, label in stabs:
            frm = tk.Frame(sub_content, bg=BG_PANEL)
            frm.grid(row=0, column=0, sticky="nsew")
            frm.columnconfigure(0, weight=1)
            self._stab_frames[key] = frm

            def _sw(k=key):
                self._show_stab(k)

            btn = tk.Button(sub_tabbar, text=f" {label} ", command=_sw,
                            bg=BG_PANEL, fg=FG_DIM, font=FONT_SMALL,
                            relief="flat", bd=0, padx=6, pady=5, cursor="hand2")
            btn.pack(side="left")
            self._stab_btns[key] = btn

        self.setting_coords    = self._stab_frames["coords"]
        self.setting_rois      = self._stab_frames["rois"]
        self.setting_templates = self._stab_frames["templates"]
        self.setting_advanced  = self._stab_frames["advanced"]

        self._build_setting_coords(self.setting_coords)
        self._build_setting_rois(self.setting_rois)
        self._build_setting_templates(self.setting_templates)
        self._build_setting_numbers(self.setting_advanced)

        self._show_stab("coords")

        # Save button row
        save_row = tk.Frame(outer, bg=BG_PANEL)
        save_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        save_row.columnconfigure(0, weight=1)
        _btn(save_row, "💾 Lưu setting", self.on_save_settings, accent=NEON_GREEN).grid(
            row=0, column=1, sticky="e"
        )

    def _show_stab(self, key: str) -> None:
        for k, frm in self._stab_frames.items():
            frm.grid_remove()
            self._stab_btns[k].config(bg=BG_PANEL, fg=FG_DIM, highlightthickness=0)
        self._stab_frames[key].grid(row=0, column=0, sticky="nsew")
        self._stab_btns[key].config(bg=BG_CARD, fg=NEON_CYAN,
                                     highlightthickness=1, highlightbackground=NEON_CYAN)

    def _scrollable(self, parent: tk.Frame) -> tk.Frame:
        """Returns a scrollable inner frame."""
        canvas = tk.Canvas(parent, bg=BG_PANEL, bd=0, highlightthickness=0)
        vsb = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG_PANEL)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_conf(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win_id, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_conf)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        inner.columnconfigure(0, weight=1)
        return inner

    def _build_setting_coords(self, parent: tk.Frame) -> None:
        inner = self._scrollable(parent)
        sec = _Section(inner, title="Tọa độ click", accent=NEON_CYAN)
        sec.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        g = sec.body

        self.coord_vars: Dict[str, Tuple[tk.StringVar, tk.StringVar]] = {}
        items = [("dao_map", "Đảo map"), ("hunt", "Hunt (tọa độ)"), ("thu", "Thư")]
        hdr = ["Tên", "X", "Y", ""]
        for c, h in enumerate(hdr):
            tk.Label(g, text=h, bg=BG_CARD, fg=FG_DIM, font=FONT_SMALL).grid(
                row=0, column=c, sticky="w", padx=(0 if c else 0, 8), pady=(0, 4))

        for r, (key, label) in enumerate(items, start=1):
            _lbl(g, label).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 8))
            vx = tk.StringVar(value="0")
            vy = tk.StringVar(value="0")
            self.coord_vars[key] = (vx, vy)
            _entry(g, vx, width=7).grid(row=r, column=1, sticky="w", padx=(0, 4), pady=5)
            _entry(g, vy, width=7).grid(row=r, column=2, sticky="w", padx=(0, 8), pady=5)
            _btn(g, "📌 Chọn điểm", lambda k=key: self.on_pick_point(k),
                 accent=NEON_CYAN, small=True).grid(row=r, column=3, sticky="w", pady=5)

    def _build_setting_rois(self, parent: tk.Frame) -> None:
        inner = self._scrollable(parent)
        sec = _Section(inner, title="ROI (vùng quét)", accent=NEON_CYAN)
        sec.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        g = sec.body

        self.roi_vars: Dict[str, Tuple[tk.StringVar, tk.StringVar, tk.StringVar, tk.StringVar]] = {}
        items = [("check_x", "check X"), ("home", "home"), ("vung_san", "vùng săn"), ("claim", "claim")]

        for c, h in enumerate(["Tên", "x1", "y1", "x2", "y2", ""]):
            tk.Label(g, text=h, bg=BG_CARD, fg=FG_DIM, font=FONT_SMALL).grid(
                row=0, column=c, sticky="w", padx=(0, 4), pady=(0, 4))

        for r, (key, label) in enumerate(items, start=1):
            _lbl(g, label).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 8))
            v1, v2, v3, v4 = (tk.StringVar(value="0") for _ in range(4))
            self.roi_vars[key] = (v1, v2, v3, v4)
            for ci, v in enumerate([v1, v2, v3, v4], start=1):
                _entry(g, v, width=6).grid(row=r, column=ci, sticky="w", padx=(0, 4), pady=5)
            _btn(g, "🖼 Vẽ ROI", lambda k=key: self.on_pick_roi(k),
                 accent=NEON_CYAN, small=True).grid(row=r, column=5, sticky="w", pady=5)

    def _build_setting_templates(self, parent: tk.Frame) -> None:
        inner = self._scrollable(parent)
        sec = _Section(inner, title="Templates (ảnh nhận diện)", accent=NEON_CYAN)
        sec.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        g = sec.body
        g.columnconfigure(1, weight=1)

        self.template_vars: Dict[str, tk.StringVar] = {}
        names = ["Dino1", "Dino2", "X", "Hunt1", "Home", "Claimall", "Claim", "Reset"]

        for r, name in enumerate(names):
            _lbl(g, name, fg=NEON_YEL).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=5)
            v = tk.StringVar(value="")
            self.template_vars[name] = v
            _entry(g, v).grid(row=r, column=1, sticky="ew", padx=(0, 6), pady=5)
            _btn(g, "📂 File", lambda n=name: self.on_pick_template_file(n),
                 accent=NEON_YEL, small=True).grid(row=r, column=2, sticky="w", padx=(0, 4), pady=5)
            _btn(g, "✂ Cắt", lambda n=name: self.on_capture_crop_template(n),
                 accent=NEON_CYAN, small=True).grid(row=r, column=3, sticky="w", pady=5)

    def _build_setting_numbers(self, parent: tk.Frame) -> None:
        inner = self._scrollable(parent)

        sec = _Section(inner, title="Ngưỡng / Delay / Hold / Logic", accent=NEON_CYAN)
        sec.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        g = sec.body
        g.columnconfigure(1, weight=0)
        g.columnconfigure(3, weight=0)

        def _row(parent, label, var, r, c=0, width=10):
            _lbl(parent, label).grid(row=r, column=c, sticky="w", padx=(0, 6), pady=5)
            _entry(parent, var, width=width).grid(row=r, column=c+1, sticky="w", pady=5, padx=(0, 16))

        self.var_thr_default = tk.StringVar()
        self.thr_vars: Dict[str, tk.StringVar] = {}
        self.var_delay_after_click = tk.StringVar()
        self.var_delay_between = tk.StringVar()
        self.var_forbidden_radius = tk.StringVar()
        self.var_fail_reset = tk.StringVar()

        _row(g, "Accuracy (default)", self.var_thr_default, 0, 0)
        _row(g, "Delay after click (s)", self.var_delay_after_click, 0, 2)
        _row(g, "Delay between scans (s)", self.var_delay_between, 1, 0)
        _row(g, "Forbidden radius (px)", self.var_forbidden_radius, 1, 2)
        _row(g, "Fail reset threshold", self.var_fail_reset, 2, 0)

        tk.Frame(g, bg=BORDER_GLOW, height=1).grid(row=3, column=0, columnspan=4, sticky="ew", pady=8)

        tk.Label(g, text="Accuracy riêng từng ảnh (để trống = dùng default):",
                 bg=BG_CARD, fg=FG_DIM, font=FONT_SMALL).grid(row=4, column=0, columnspan=4, sticky="w", pady=(0, 6))

        names = ["Dino1", "Dino2", "X", "Hunt1", "Home", "Claimall", "Claim", "Reset"]
        for i, name in enumerate(names):
            r = 5 + i // 4
            c = (i % 4) * 2
            v = tk.StringVar()
            self.thr_vars[name] = v
            cell = tk.Frame(g, bg=BG_CARD)
            cell.grid(row=r, column=c, columnspan=2, sticky="w", padx=(0, 6), pady=3)
            _lbl(cell, name, fg=NEON_YEL).grid(row=0, column=0, sticky="w", padx=(0, 4))
            _entry(cell, v, width=6).grid(row=0, column=1, sticky="w")

        tk.Frame(g, bg=BORDER_GLOW, height=1).grid(row=7, column=0, columnspan=4, sticky="ew", pady=8)

        self.hold_vars: Dict[str, tk.StringVar] = {}
        holds = [
            ("default", "hold default"),
            ("click_dino", "hold click dino"),
            ("click_x", "hold click X"),
            ("click_hunt_btn", "hold click Hunt1"),
            ("click_hunt_coord", "hold click tọa độ hunt"),
            ("click_map", "hold click đảo map"),
            ("click_mail", "hold click thư"),
            ("click_claim", "hold click claim"),
            ("click_reset", "hold click reset"),
        ]
        for idx, (k, label) in enumerate(holds):
            r = 8 + idx // 2
            c = (idx % 2) * 2
            v = tk.StringVar()
            self.hold_vars[k] = v
            _lbl(g, label).grid(row=r, column=c, sticky="w", padx=(0, 6), pady=5)
            _entry(g, v, width=10).grid(row=r, column=c+1, sticky="w", pady=5, padx=(0, 16))

    def _build_tab_info(self) -> None:
        f = self.tab_info
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        # Scrollable canvas wrapper
        canvas = tk.Canvas(f, bg=BG_PANEL, bd=0, highlightthickness=0)
        vsb = tk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")
        canvas.grid(row=0, column=0, sticky="nsew")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        page = tk.Frame(canvas, bg=BG_PANEL)
        win_id = canvas.create_window((0, 0), window=page, anchor="nw")
        page.columnconfigure(0, weight=1)

        def _on_conf(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        page.bind("<Configure>", _on_conf)
        canvas.bind("<Configure>", _on_canvas_resize)

        # ── Hero banner ─────────────────────────────────────────────────────
        hero = tk.Frame(page, bg=BG_DARK, highlightthickness=1,
                        highlightbackground=NEON_CYAN)
        hero.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        hero.columnconfigure(0, weight=1)

        tk.Label(hero, text="🦖  AutoHunt Dino Mutant: T-Rex",
                 bg=BG_DARK, fg=NEON_CYAN,
                 font=("Segoe UI", 16, "bold")).pack(pady=(14, 2))
        tk.Label(hero, text="Tool tự động hóa việc đi săn trong game",
                 bg=BG_DARK, fg=FG_DIM,
                 font=("Segoe UI", 10)).pack(pady=(0, 4))

        # version chip
        chip_row = tk.Frame(hero, bg=BG_DARK)
        chip_row.pack(pady=(2, 12))
        for txt, col in [("FINN", NEON_PINK), ("LOVE", NEON_PINK), ("MARY", NEON_PINK)]:
            chip = tk.Frame(chip_row, bg=col, bd=0)
            chip.pack(side="left", padx=4)
            tk.Label(chip, text=f" {txt} ", bg=col, fg=BG_DARK,
                     font=("Segoe UI", 9, "bold")).pack()

        # ── Author card ──────────────────────────────────────────────────────
        def _info_card(parent, row, icon, title, value, title_col, val_col):
            card = tk.Frame(parent, bg=BG_CARD, highlightthickness=1,
                            highlightbackground=BORDER_GLOW)
            card.grid(row=row, column=0, sticky="ew", padx=12, pady=4)
            card.columnconfigure(1, weight=1)
            tk.Label(card, text=icon, bg=BG_CARD, fg=title_col,
                     font=("Segoe UI", 13)).grid(row=0, column=0, padx=(12, 8), pady=10)
            inner = tk.Frame(card, bg=BG_CARD)
            inner.grid(row=0, column=1, sticky="ew", pady=10)
            tk.Label(inner, text=title, bg=BG_CARD, fg=FG_DIM,
                     font=("Segoe UI", 9)).pack(anchor="w")
            tk.Label(inner, text=value, bg=BG_CARD, fg=val_col,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")

        _info_card(page, 1, "👤", "Tác giả", "F I N N", NEON_YEL, FG_HEAD)
        _info_card(page, 2, "📦", "Phiên bản", "1.0.0  –  03/2026", NEON_GREEN, FG_HEAD)
        _info_card(page, 3, "🔧", "Công cụ", "ADB Shell  +  OpenCV Template Matching", NEON_CYAN, FG_HEAD)

        # ── Divider ──────────────────────────────────────────────────────────
        div = tk.Frame(page, bg=BORDER_GLOW, height=1)
        div.grid(row=4, column=0, sticky="ew", padx=12, pady=(10, 4))
        tk.Label(page, text="📋  HƯỚNG DẪN SỬ DỤNG",
                 bg=BG_PANEL, fg=NEON_YEL,
                 font=("Segoe UI", 11, "bold")).grid(row=5, column=0, sticky="w", padx=16, pady=(4, 6))

        # ── Step cards ───────────────────────────────────────────────────────
        steps = [
            (NEON_CYAN,  "①", "Kết nối giả lập",
             "Nhập Port → bấm Tìm hoặc Refresh → chọn thiết bị → Kết nối."),
            (NEON_GREEN, "②", "Cấu hình Setting",
             "Vào tab Setting: set tọa độ, vẽ ROI, chọn ảnh template cho từng mục."),
            (NEON_YEL,   "③", "Chỉnh ngưỡng & delay",
             "Tab Nâng cao: điều chỉnh Accuracy, Delay, Hold time cho phù hợp tốc độ máy."),
            (NEON_PINK,  "④", "Bấm START",
             "Tool sẽ tự động quét, click, săn dino và claim thưởng theo vòng lặp."),
            (FG_LABEL,   "⑤", "Theo dõi Log & Stats",
             "Xem Log bên phải tab Chính. Bấm Stop bất cứ lúc nào để dừng ngay."),
        ]

        for i, (col, num, title, desc) in enumerate(steps):
            card = tk.Frame(page, bg=BG_CARD, highlightthickness=1,
                            highlightbackground=col)
            card.grid(row=6 + i, column=0, sticky="ew", padx=12, pady=3)
            card.columnconfigure(1, weight=1)

            # Number badge
            badge = tk.Frame(card, bg=col, width=36)
            badge.grid(row=0, column=0, sticky="ns", padx=(0, 0))
            badge.grid_propagate(False)
            tk.Label(badge, text=num, bg=col, fg=BG_DARK,
                     font=("Segoe UI", 13, "bold")).place(relx=0.5, rely=0.5, anchor="center")

            body = tk.Frame(card, bg=BG_CARD)
            body.grid(row=0, column=1, sticky="ew", padx=12, pady=8)
            tk.Label(body, text=title, bg=BG_CARD, fg=col,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")
            tk.Label(body, text=desc, bg=BG_CARD, fg=FG_TEXT,
                     font=("Segoe UI", 10), wraplength=560, justify="left").pack(anchor="w", pady=(2, 0))

        # ── Notes section ─────────────────────────────────────────────────
        div2 = tk.Frame(page, bg=BORDER_GLOW, height=1)
        div2.grid(row=11, column=0, sticky="ew", padx=12, pady=(12, 4))
        tk.Label(page, text="⚠️  LƯU Ý QUAN TRỌNG",
                 bg=BG_PANEL, fg=NEON_PINK,
                 font=("Segoe UI", 11, "bold")).grid(row=12, column=0, sticky="w", padx=16, pady=(4, 6))

        notes = [
            ("🖥️", "Chỉnh Display giả lập 1920x1080(DPI280) để có thể sự dụng setting mặc định"),
        ]

        note_frame = tk.Frame(page, bg=BG_PANEL)
        note_frame.grid(row=13, column=0, sticky="ew", padx=12, pady=(0, 16))
        note_frame.columnconfigure(0, weight=1)
        note_frame.columnconfigure(1, weight=1)

        for i, (icon, text) in enumerate(notes):
            r, c = divmod(i, 2)
            ncard = tk.Frame(note_frame, bg=BG_INPUT, highlightthickness=1,
                             highlightbackground=NEON_PINK)
            ncard.grid(row=r, column=c, sticky="ew", padx=4, pady=4)
            ncard.columnconfigure(1, weight=1)
            tk.Label(ncard, text=icon, bg=BG_INPUT, fg=NEON_PINK,
                     font=("Segoe UI", 12)).grid(row=0, column=0, padx=(10, 6), pady=8)
            tk.Label(ncard, text=text, bg=BG_INPUT, fg=FG_TEXT,
                     font=("Segoe UI", 10), wraplength=240, justify="left").grid(
                row=0, column=1, sticky="ew", padx=(0, 10), pady=8)

    # ── Settings <-> UI ──────────────────────────────────────────────────────
    def _load_settings_to_ui(self) -> None:
        for k, (vx, vy) in self.coord_vars.items():
            v = self.settings.get("coords", k, default=[0, 0])
            vx.set(str(int(v[0])))
            vy.set(str(int(v[1])))

        for k, vars4 in self.roi_vars.items():
            v = self.settings.get("rois", k, default=[0, 0, 0, 0])
            for i in range(4):
                vars4[i].set(str(int(v[i])))

        for name, var in self.template_vars.items():
            raw = str(self.settings.get("templates", name, default=""))
            var.set(self._short_template_value(raw))

        self.var_thr_default.set(str(self.settings.get("thresholds", "default", default=0.85)))
        for name, v in self.thr_vars.items():
            vv = self.settings.get("thresholds", name, default=None)
            v.set("" if vv is None else str(vv))
        self.var_delay_after_click.set(str(self.settings.get("delays_s", "after_click", default=0.25)))
        self.var_delay_between.set(str(self.settings.get("delays_s", "between_scans", default=0.15)))
        self.var_forbidden_radius.set(str(self.settings.get("forbidden", "radius_px", default=50)))
        self.var_fail_reset.set(str(self.settings.get("logic", "fail_reset_threshold", default=10)))

        for k, v in self.hold_vars.items():
            v.set(str(self.settings.get("hold_ms", k, default=self.settings.get("hold_ms", "default", default=60))))

    def _save_ui_to_settings(self) -> None:
        for k, (vx, vy) in self.coord_vars.items():
            self.settings.set([int(float(vx.get() or 0)), int(float(vy.get() or 0))], "coords", k)

        for k, vars4 in self.roi_vars.items():
            self.settings.set([int(float(x.get() or 0)) for x in vars4], "rois", k)

        for name, var in self.template_vars.items():
            self.settings.set(self._short_template_value(var.get().strip()), "templates", name)

        self.settings.set(float(self.var_thr_default.get() or 0.85), "thresholds", "default")
        for name, v in self.thr_vars.items():
            raw = v.get().strip()
            if raw == "":
                try:
                    if isinstance(self.settings.data.get("thresholds"), dict) and name in self.settings.data["thresholds"]:
                        del self.settings.data["thresholds"][name]
                except Exception:
                    pass
            else:
                self.settings.set(float(raw), "thresholds", name)
        self.settings.set(float(self.var_delay_after_click.get() or 0.25), "delays_s", "after_click")
        self.settings.set(float(self.var_delay_between.get() or 0.15), "delays_s", "between_scans")
        self.settings.set(int(float(self.var_forbidden_radius.get() or 50)), "forbidden", "radius_px")
        self.settings.set(int(float(self.var_fail_reset.get() or 10)), "logic", "fail_reset_threshold")

        for k, v in self.hold_vars.items():
            self.settings.set(int(float(v.get() or 0)), "hold_ms", k)

    # ── Logging ──────────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_q.put(f"[{ts}] {msg}")

    def _flush_log(self) -> None:
        lines = []
        try:
            while True:
                lines.append(self.log_q.get_nowait())
        except Empty:
            pass
        if not lines:
            return
        self.txt_log.configure(state="normal")
        for line in lines[-80:]:
            self.txt_log.insert("end", line + "\n")
        self.txt_log.see("end")
        line_count = int(self.txt_log.index("end-1c").split(".")[0])
        if line_count > 500:
            self.txt_log.delete("1.0", f"{line_count - 400}.0")
        self.txt_log.configure(state="disabled")

    def on_clear_log(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")
        self.log("Đã clear log.")

    # ── Uptime ───────────────────────────────────────────────────────────────
    def _update_uptime(self) -> None:
        if self._start_time is not None:
            elapsed = int(time.time() - self._start_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            self.var_uptime.set(f"{h:02d}:{m:02d}:{s:02d}")
        else:
            self.var_uptime.set("00:00:00")

    # ── Loop ─────────────────────────────────────────────────────────────────
    def _tick(self) -> None:
        self._flush_log()
        self._flush_stats()
        self._update_uptime()
        self.master.after(100, self._tick)

    # ── Stats ─────────────────────────────────────────────────────────────────
    def _on_stats(self, st: Stats) -> None:
        self.stats_q.put(st)

    def _flush_stats(self) -> None:
        latest: Optional[Stats] = None
        try:
            while True:
                latest = self.stats_q.get_nowait()
        except Empty:
            pass
        if not latest:
            return
        self.var_success.set(str(latest.success_total))
        self.var_failstreak.set(str(latest.fail_streak))

    # ── Events ───────────────────────────────────────────────────────────────
    def on_refresh_devices(self) -> None:
        if self._adb_busy:
            return
        self._set_adb_busy(True, "Đang refresh devices...")

        def work():
            return self.adb.list_devices()

        def done(serials):
            self.cbo_serial["values"] = serials
            if serials:
                self.var_serial.set(serials[0])
            self.log(f"Devices: {', '.join(serials) if serials else '(trống)'}")
            self._set_adb_busy(False, f"Đã refresh ({len(serials)})")

        def err(e: Exception):
            self._set_adb_busy(False, "Refresh lỗi")
            messagebox.showerror("Lỗi", f"Không gọi được adb devices:\n{e}")

        self._run_bg(work, on_done=done, on_error=err)

    def on_find_emulator(self) -> None:
        if self._adb_busy:
            return
        self._set_adb_busy(True, "Đang tìm giả lập...")
        host = self.settings.get("adb", "host", default="127.0.0.1")
        ports = self.settings.get("adb", "scan_ports", default=[5555, 5556, 5557, 5558, 5560, 5575, 5585])

        def work():
            found = []
            for p in ports:
                try:
                    out = self.adb.connect(host, int(p))
                    if "connected" in out.lower() or "already connected" in out.lower():
                        found.append((p, out))
                except Exception:
                    continue
            return found

        def done(found):
            for p, out in found:
                self.log(f"Tìm thấy giả lập ({host}:{int(p)}): {out}")
            self._set_adb_busy(False, f"Tìm xong ({len(found)})")
            self.on_refresh_devices()
            if not found:
                self.log("Không tìm thấy giả lập trong danh sách port scan.")

        def err(e: Exception):
            self._set_adb_busy(False, "Tìm lỗi")
            messagebox.showerror("Lỗi", f"Tìm giả lập thất bại:\n{e}")

        self._run_bg(work, on_done=done, on_error=err)

    def on_connect(self) -> None:
        if self._adb_busy:
            return

        serial_in = self.var_serial.get().strip()
        port = self.var_port.get().strip()
        host = self.settings.get("adb", "host", default="127.0.0.1")

        if not serial_in and not port:
            messagebox.showwarning("Thiếu thông tin", "Chọn thiết bị hoặc nhập port.")
            return

        self._set_adb_busy(True, "Đang kết nối...")

        def work():
            serial = serial_in
            if not serial:
                out = self.adb.connect(host, int(port))
                return {"serial": f"{host}:{int(port)}", "connect_out": out}
            return {"serial": serial, "connect_out": None}

        def done(res):
            serial = res["serial"]
            if res.get("connect_out"):
                self.log(res["connect_out"])
            self._set_adb_busy(True, "Đang kiểm tra thiết bị...")

            def work2():
                _ = self.adb.screenshot(serial)
                return True

            def done2(_ok):
                self.connected_serial = serial
                self.lbl_conn.config(text=f"● Đã kết nối: {serial}", fg=NEON_GREEN)
                self.settings.set(serial, "adb", "serial")
                self.settings.save()
                self.log(f"Kết nối OK: {serial}")
                self._set_adb_busy(False, f"Đã kết nối: {serial}")
                self.on_refresh_devices()
                self.var_serial.set(serial)

            def err2(e: Exception):
                self._set_adb_busy(False, "Thiết bị lỗi")
                self.lbl_conn.config(text="● Thiết bị lỗi", fg=NEON_PINK)
                messagebox.showerror("Lỗi", f"Thiết bị không sẵn sàng:\n{e}")

            self._run_bg(work2, on_done=done2, on_error=err2)

        def err(e: Exception):
            self._set_adb_busy(False, "Kết nối lỗi")
            self.lbl_conn.config(text="● Kết nối lỗi", fg=NEON_PINK)
            messagebox.showerror("Lỗi", f"Kết nối thất bại:\n{e}")

        self._run_bg(work, on_done=done, on_error=err)

    def on_start(self) -> None:
        if self.bot_thread and self.bot_thread.is_alive():
            return
        serial = self.connected_serial or self.settings.get("adb", "serial", default="")
        serial = str(serial).strip()
        if not serial:
            messagebox.showwarning("Chưa kết nối", "Bạn cần kết nối giả lập trước.")
            return

        self._save_ui_to_settings()
        self.settings.save()

        self.stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._start_time = time.time()
        self.log("Start")

        hunter = AutoHunter(self.settings, log=self.log, on_stats=self._on_stats)
        self.bot_thread = threading.Thread(target=hunter.run, args=(serial, self.stop_event), daemon=True)
        self.bot_thread.start()

    def on_stop(self) -> None:
        self.stop_event.set()
        self._start_time = None
        self.log("Stop (đang dừng ngay...)")
        self.btn_stop.config(state="disabled")
        self.btn_start.config(state="normal")

    def on_save_settings(self) -> None:
        try:
            self._save_ui_to_settings()
            self.settings.save()
            self.log("Đã lưu setting.")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Lưu setting thất bại:\n{e}")

    def on_pick_roi(self, roi_key: str) -> None:
        serial = self.connected_serial or self.settings.get("adb", "serial", default="")
        if not serial:
            messagebox.showwarning("Chưa kết nối", "Cần kết nối để chụp màn hình.")
            return
        if self._adb_busy:
            return
        self._set_adb_busy(True, "Đang chụp màn hình...")

        def work():
            return self.adb.screenshot(str(serial))

        def done(img):
            self._set_adb_busy(False, "Sẵn sàng")
            sel = ScreenshotSelector(self.master, img, title=f"Vẽ ROI: {roi_key}")
            self.master.wait_window(sel)
            if sel.result_roi:
                v = self.roi_vars[roi_key]
                for i in range(4):
                    v[i].set(str(sel.result_roi[i]))
                self.log(f"ROI {roi_key} = {sel.result_roi}")

        def err(e: Exception):
            self._set_adb_busy(False, "Chụp lỗi")
            messagebox.showerror("Lỗi", f"Chụp màn hình thất bại:\n{e}")

        self._run_bg(work, on_done=done, on_error=err)

    def on_pick_point(self, coord_key: str) -> None:
        serial = self.connected_serial or self.settings.get("adb", "serial", default="")
        if not serial:
            messagebox.showwarning("Chưa kết nối", "Cần kết nối để chụp màn hình.")
            return
        if self._adb_busy:
            return
        self._set_adb_busy(True, "Đang chụp màn hình...")

        def work():
            return self.adb.screenshot(str(serial))

        def done(img):
            self._set_adb_busy(False, "Sẵn sàng")
            sel = ScreenshotSelector(self.master, img, title=f"Chọn điểm: {coord_key}")
            sel.lbl.config(text="Kéo chuột tạo ROI nhỏ đúng vị trí điểm, tool sẽ lấy tâm ROI.")
            self.master.wait_window(sel)
            if sel.result_roi:
                x1, y1, x2, y2 = sel.result_roi
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                vx, vy = self.coord_vars[coord_key]
                vx.set(str(cx))
                vy.set(str(cy))
                self.log(f"Coord {coord_key} = ({cx},{cy})")

        def err(e: Exception):
            self._set_adb_busy(False, "Chụp lỗi")
            messagebox.showerror("Lỗi", f"Chụp màn hình thất bại:\n{e}")

        self._run_bg(work, on_done=done, on_error=err)

    def on_pick_template_file(self, name: str) -> None:
        fp = filedialog.askopenfilename(
            title=f"Chọn ảnh template: {name}",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")],
        )
        if not fp:
            return
        # Copy selected file into app templates dir so settings can store short paths.
        templates_dir = self._templates_dir()
        os.makedirs(templates_dir, exist_ok=True)
        ext = os.path.splitext(fp)[1].lower()
        if not ext:
            ext = ".png"
        out_path = os.path.join(templates_dir, f"{name}{ext}")
        shutil.copy2(fp, out_path)
        short = f"./templates/{name}{ext}"
        self.template_vars[name].set(short)
        self.settings.set(short, "templates", name)
        self.settings.save()
        self.log(f"Template {name} = {short}")

    def on_capture_crop_template(self, name: str) -> None:
        serial = self.connected_serial or self.settings.get("adb", "serial", default="")
        if not serial:
            messagebox.showwarning("Chưa kết nối", "Cần kết nối để chụp màn hình.")
            return
        if self._adb_busy:
            return
        self._set_adb_busy(True, "Đang chụp màn hình...")

        def work():
            return self.adb.screenshot(str(serial))

        def done(img):
            self._set_adb_busy(False, "Sẵn sàng")
            sel = ScreenshotSelector(self.master, img, title=f"Cắt template: {name}")
            sel.lbl.config(text="Kéo chuột chọn vùng muốn cắt làm template.")
            self.master.wait_window(sel)
            if not sel.result_crop:
                return
            out_dir = self._templates_dir()
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{name}.png")
            sel.result_crop.save(out_path)
            short = f"./templates/{name}.png"
            self.template_vars[name].set(short)
            self.settings.set(short, "templates", name)
            self.settings.save()
            self.log(f"Đã lưu template {name}: {short}")

        def err(e: Exception):
            self._set_adb_busy(False, "Chụp lỗi")
            messagebox.showerror("Lỗi", f"Chụp màn hình thất bại:\n{e}")

        self._run_bg(work, on_done=done, on_error=err)


def run_app() -> None:
    root = tk.Tk()
    root.configure(bg=BG_DARK)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    run_app()