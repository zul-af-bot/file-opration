import os
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from file_ops_core import (
    FileOpConfig,
    collect_matching_files,
    compute_new_filename,
    is_file_stable,
    process_file_operation,
    rename_file_in_place,
)
from upscaler_core import (
    UpscaleConfig,
    collect_videos,
    detect_gpu_name,
    get_app_dir,
    get_tool_paths,
    install_ffmpeg,
    install_realesrgan,
    is_file_ready,
    is_image_file,
    load_settings,
    save_settings,
    upscale_image_ai,
    upscale_image_fast,
    upscale_video_ai,
    upscale_video_fast,
)

AI_MODEL_LABELS = {
    "Foto & Video Nyata / Flow (Detail Tinggi)": "realesrgan-x4plus",
    "Video Cepat (3-5x Lebih Cepat)": "realesr-animevideov3",
    "Animasi / Kartun": "realesrgan-x4plus-anime",
}
AI_MODEL_REVERSE = {v: k for k, v in AI_MODEL_LABELS.items()}

TILE_LABELS = {
    "Auto (Default)": 0,
    "Sedang (VRAM 4GB)": 200,
    "Hemat VRAM (Anti-Crash)": 100,
}
TILE_REVERSE = {v: k for k, v in TILE_LABELS.items()}

QUALITY_LABELS = {
    "Tinggi (Rekomendasi)": 18,
    "Seimbang (Hemat Memori)": 21,
}
QUALITY_REVERSE = {v: k for k, v in QUALITY_LABELS.items()}

MEDIA_FILTER_LABELS = {
    "Foto & Video": "all",
    "Hanya Video": "video",
    "Hanya Foto": "image",
}

OUTPUT_MODE_LABELS = {
    "Tambah _1080p di folder yang sama (contoh: file_1080p)": "same_suffix",
    "Timpa / Ganti file asli langsung (Overwrite)": "overwrite",
    "Simpan ke folder lain...": "custom_folder",
}
OUTPUT_MODE_REVERSE = {v: k for k, v in OUTPUT_MODE_LABELS.items()}

ACTION_LABELS = {
    "Pindahkan File (Move)": "move",
    "Salin File (Copy)": "copy",
}
FILTER_LABELS = {
    "Semua File": "all",
    "Hanya Video (.mp4, .mov, dll)": "video",
    "Hanya Foto (.png, .jpg, .webp)": "image",
    "Ekstensi Kustom...": "custom",
}
RENAME_LABELS = {
    "Tambah Awalan / Akhiran": "prefix_suffix",
    "Penomoran Urut (001, 002...)": "sequence",
    "Ganti Teks Tertentu": "replace",
}
CONFLICT_LABELS = {
    "Tambah angka otomatis (_1, _2)": "auto_number",
    "Timpa file yang sama": "overwrite",
    "Lewati jika sudah ada": "skip",
}

THEMES = {
    "light": {
        "bg_app": "#F8FBFF",
        "bg_card": "#FFFFFF",
        "bg_sub": "#F1F6FE",
        "border": "#DFE5F2",
        "text": "#202124",
        "muted": "#5F6368",
        "primary": "#1A73E8",
        "primary_hover": "#1558B0",
        "primary_fg": "#FFFFFF",
        "secondary_bg": "#E8F0FE",
        "secondary_fg": "#1A73E8",
        "success": "#34A853",
        "warning": "#D97706",
        "danger": "#D93025",
        "tree_bg": "#FFFFFF",
        "tree_head": "#F1F5F9",
    },
    "dark_gold": {
        "bg_app": "#0A0704",
        "bg_card": "#141009",
        "bg_sub": "#1D170D",
        "border": "#3A2A12",
        "text": "#FFF6DF",
        "muted": "#C49D72",
        "primary": "#F8B319",
        "primary_hover": "#FFCF3A",
        "primary_fg": "#141007",
        "secondary_bg": "#2B2010",
        "secondary_fg": "#F8B319",
        "success": "#34A853",
        "warning": "#F8B319",
        "danger": "#F97316",
        "tree_bg": "#0E0A05",
        "tree_head": "#1D170D",
    },
}


class FileOprationApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("File Opration by Zul")
        self.root.geometry("840x730")
        self.root.minsize(750, 650)

        self.theme_name = "light"
        self.t = THEMES[self.theme_name]
        self.logo_img: tk.PhotoImage | None = None
        self.icon_img: tk.PhotoImage | None = None

        self.active_tab = "move"  # "move" | "rename" | "upscale"
        self.is_running = False
        self.is_downloading = False
        self.cancel_requested = False

        # Segment 1 (Move/Copy)
        self.move_files: list[Path] = []
        self.move_tree_map: dict[Path, str] = {}

        # Segment 2 (Rename)
        self.rename_files: list[Path] = []
        self.rename_tree_map: dict[Path, str] = {}

        # Segment 3 (Upscale)
        self.media_files: list[Path] = []
        self.media_tree_map: dict[Path, str] = {}
        self.selected_folder: str = ""
        self.show_advanced = False

        self.log_history: list[str] = []
        self.log_window: tk.Toplevel | None = None
        self.log_text_widget: scrolledtext.ScrolledText | None = None
        self.ui_queue: queue.Queue = queue.Queue()
        self.saved_config = load_settings()

        self._load_logo_assets()
        self._build_ui()
        self._apply_theme()
        self._apply_saved_settings()
        tools = self._refresh_tool_status()
        self._detect_gpu_async()
        self._poll_queue()

        if not tools["ffmpeg"] or not tools["realesrgan"]:
            self.root.after(350, lambda: self._start_download_tools(auto=True))

    def _load_logo_assets(self) -> None:
        assets_dir = get_app_dir() / "assets"
        icon_path = assets_dir / "icon32.png"
        logo_path = assets_dir / "app-logo-mark.png"
        try:
            if icon_path.is_file():
                self.icon_img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, self.icon_img)
                self.logo_img = self.icon_img
            elif logo_path.is_file():
                raw = tk.PhotoImage(file=str(logo_path))
                self.logo_img = raw.subsample(4, 4)
                self.root.iconphoto(True, raw)
        except Exception:
            self.logo_img = None

    def _build_ui(self) -> None:
        self.container = tk.Frame(self.root, padx=16, pady=12)
        self.container.pack(fill=tk.BOTH, expand=True)

        # --- Header ---
        self.header = tk.Frame(self.container)
        self.header.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        left_h = tk.Frame(self.header)
        left_h.pack(side=tk.LEFT, fill=tk.X, expand=True)

        if self.logo_img is not None:
            self.lbl_logo = tk.Label(left_h, image=self.logo_img)
            self.lbl_logo.pack(side=tk.LEFT, padx=(0, 10))
        else:
            self.lbl_logo = None

        title_wrap = tk.Frame(left_h)
        title_wrap.pack(side=tk.LEFT)
        self.lbl_title = tk.Label(
            title_wrap,
            text="File Opration by Zul",
            font=("Segoe UI", 15, "bold"),
        )
        self.lbl_title.pack(anchor=tk.W)
        self.lbl_gpu = tk.Label(
            title_wrap,
            text="TheFlow Pro Edition • Mendeteksi GPU...",
            font=("Segoe UI", 8),
        )
        self.lbl_gpu.pack(anchor=tk.W)

        right_h = tk.Frame(self.header)
        right_h.pack(side=tk.RIGHT)

        top_right_row = tk.Frame(right_h)
        top_right_row.pack(anchor=tk.E, pady=(0, 4))
        self.lbl_tool_badge = tk.Label(
            top_right_row,
            text="Memeriksa tools...",
            font=("Segoe UI", 8, "bold"),
        )
        self.lbl_tool_badge.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_theme = tk.Button(
            top_right_row,
            text="🌙 Tema Emas Gelap",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._toggle_theme,
        )
        self.btn_theme.pack(side=tk.LEFT)

        self.btn_download_tools = tk.Button(
            right_h,
            text="Download Tools Otomatis",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=3,
            cursor="hand2",
            command=lambda: self._start_download_tools(auto=False),
        )
        self.btn_download_tools.pack(anchor=tk.E)

        # --- 3-Segment Navigation Bar ---
        self.tab_bar = tk.Frame(self.container)
        self.tab_bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        self.btn_tab_move = tk.Button(
            self.tab_bar,
            text="📂  Pindah File",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=7,
            cursor="hand2",
            command=lambda: self._switch_tab("move"),
        )
        self.btn_tab_move.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.btn_tab_rename = tk.Button(
            self.tab_bar,
            text="✏️  Rename File",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=7,
            cursor="hand2",
            command=lambda: self._switch_tab("rename"),
        )
        self.btn_tab_rename.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.btn_tab_up = tk.Button(
            self.tab_bar,
            text="✨  Upscale Foto & Video",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=7,
            cursor="hand2",
            command=lambda: self._switch_tab("upscale"),
        )
        self.btn_tab_up.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # --- Bottom Footer Status + Progress ---
        self.footer_card = tk.Frame(self.container, highlightthickness=1, padx=14, pady=10)
        self.footer_card.pack(side=tk.BOTTOM, fill=tk.X)

        status_row = tk.Frame(self.footer_card)
        status_row.pack(fill=tk.X, pady=(0, 5))
        self.lbl_status = tk.Label(status_row, text="Siap digunakan.", font=("Segoe UI", 9))
        self.lbl_status.pack(side=tk.LEFT)

        self.btn_log = tk.Button(
            status_row,
            text="Lihat Log",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "underline"),
            cursor="hand2",
            command=self._open_log_window,
        )
        self.btn_log.pack(side=tk.RIGHT)

        self.prog_bar = ttk.Progressbar(
            self.footer_card,
            maximum=100,
            mode="determinate",
            style="TheFlow.Horizontal.TProgressbar",
        )
        self.prog_bar.pack(fill=tk.X, pady=(0, 8))

        self.footer_btn_row = tk.Frame(self.footer_card)
        self.footer_btn_row.pack(fill=tk.X)

        self.btn_start = tk.Button(
            self.footer_btn_row,
            text="▶ Jalankan",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=18,
            pady=7,
            cursor="hand2",
            command=self._on_start_click,
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = tk.Button(
            self.footer_btn_row,
            text="⏹ Stop",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
            state=tk.DISABLED,
            command=self._stop_current,
        )
        self.btn_stop.pack(side=tk.LEFT)

        # --- Main Content Area ---
        self.body_frame = tk.Frame(self.container)
        self.body_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 10))

        self.frame_move = tk.Frame(self.body_frame)
        self.frame_rename = tk.Frame(self.body_frame)
        self.frame_upscale = tk.Frame(self.body_frame)

        self._build_segment_move()
        self._build_segment_rename()
        self._build_segment_upscale()
        self._switch_tab("move")

    # =========================================================================
    # SEGMENT 1: PINDAH FILE
    # =========================================================================
    def _build_segment_move(self) -> None:
        self.move_cards = []

        card_dir = tk.Frame(self.frame_move, highlightthickness=1, padx=12, pady=10)
        card_dir.pack(fill=tk.X, pady=(0, 8))
        self.move_cards.append(card_dir)

        r1 = tk.Frame(card_dir)
        r1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r1, text="Folder Sumber:", width=14).pack(side=tk.LEFT)
        self.var_mv_src = tk.StringVar()
        ttk.Entry(r1, textvariable=self.var_mv_src).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(r1, text="Pilih...", command=self._mv_choose_src).pack(side=tk.LEFT)

        r2 = tk.Frame(card_dir)
        r2.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r2, text="Folder Tujuan:", width=14).pack(side=tk.LEFT)
        self.var_mv_dst = tk.StringVar()
        ttk.Entry(r2, textvariable=self.var_mv_dst).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(r2, text="Pilih...", command=self._mv_choose_dst).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(r2, text="Buka", command=self._mv_open_dst).pack(side=tk.LEFT)

        r3 = tk.Frame(card_dir)
        r3.pack(fill=tk.X)
        self.var_mv_watch = tk.BooleanVar(value=False)
        self._create_check_toggle(
            r3,
            "Pantau Folder Sumber otomatis (file baru masuk langsung dipindahkan)",
            self.var_mv_watch,
            command=self._update_start_button_text,
        ).pack(side=tk.LEFT)

        card_cfg = tk.Frame(self.frame_move, highlightthickness=1, padx=12, pady=10)
        card_cfg.pack(fill=tk.X, pady=(0, 8))
        self.move_cards.append(card_cfg)

        g1 = tk.Frame(card_cfg)
        g1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(g1, text="Tindakan:", width=12).pack(side=tk.LEFT)
        self.var_mv_action = tk.StringVar(value=list(ACTION_LABELS.keys())[0])
        ttk.Combobox(
            g1,
            textvariable=self.var_mv_action,
            state="readonly",
            width=22,
            values=list(ACTION_LABELS.keys()),
        ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(g1, text="Filter:").pack(side=tk.LEFT, padx=(0, 6))
        self.var_mv_filter = tk.StringVar(value=list(FILTER_LABELS.keys())[0])
        cb_f = ttk.Combobox(
            g1,
            textvariable=self.var_mv_filter,
            state="readonly",
            width=24,
            values=list(FILTER_LABELS.keys()),
        )
        cb_f.pack(side=tk.LEFT, padx=(0, 6))
        cb_f.bind("<<ComboboxSelected>>", lambda _e: self._mv_on_filter_change())

        self.var_mv_custom_ext = tk.StringVar(value=".mp4, .png")
        self.entry_mv_ext = ttk.Entry(
            g1, textvariable=self.var_mv_custom_ext, width=14, state=tk.DISABLED
        )
        self.entry_mv_ext.pack(side=tk.LEFT)

        g2 = tk.Frame(card_cfg)
        g2.pack(fill=tk.X)
        ttk.Label(g2, text="Jika nama sama:", width=12).pack(side=tk.LEFT)
        self.var_mv_conflict = tk.StringVar(value=list(CONFLICT_LABELS.keys())[0])
        ttk.Combobox(
            g2,
            textvariable=self.var_mv_conflict,
            state="readonly",
            width=28,
            values=list(CONFLICT_LABELS.keys()),
        ).pack(side=tk.LEFT)

        card_list = tk.Frame(self.frame_move, highlightthickness=1, padx=12, pady=8)
        card_list.pack(fill=tk.BOTH, expand=True)
        self.move_cards.append(card_list)

        top_l = tk.Frame(card_list)
        top_l.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(top_l, text="Daftar File di Folder Sumber", font=("Segoe UI", 9, "bold")).pack(
            side=tk.LEFT
        )
        ttk.Button(top_l, text="🔄 Muat Ulang", command=self._mv_scan_src).pack(side=tk.RIGHT)

        tw = tk.Frame(card_list)
        tw.pack(fill=tk.BOTH, expand=True)
        self.mv_tree = ttk.Treeview(tw, columns=("name", "size", "status"), show="headings", height=5)
        self.mv_tree.heading("name", text="Nama File")
        self.mv_tree.heading("size", text="Ukuran")
        self.mv_tree.heading("status", text="Status")
        self.mv_tree.column("name", width=400, anchor=tk.W)
        self.mv_tree.column("size", width=90, anchor=tk.E)
        self.mv_tree.column("status", width=180, anchor=tk.W)
        vsb = ttk.Scrollbar(tw, orient=tk.VERTICAL, command=self.mv_tree.yview)
        self.mv_tree.configure(yscrollcommand=vsb.set)
        self.mv_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    # =========================================================================
    # SEGMENT 2: RENAME FILE
    # =========================================================================
    def _build_segment_rename(self) -> None:
        self.rename_cards = []

        card_dir = tk.Frame(self.frame_rename, highlightthickness=1, padx=12, pady=10)
        card_dir.pack(fill=tk.X, pady=(0, 8))
        self.rename_cards.append(card_dir)

        r1 = tk.Frame(card_dir)
        r1.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(r1, text="📁 Pilih Folder", command=self._ren_choose_folder).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(r1, text="📄 Pilih File...", command=self._ren_add_files).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(r1, text="Bersihkan", command=self._ren_clear).pack(side=tk.LEFT)
        self.lbl_ren_count = tk.Label(r1, text="0 file", font=("Segoe UI", 8, "bold"), padx=8, pady=2)
        self.lbl_ren_count.pack(side=tk.RIGHT)

        r2 = tk.Frame(card_dir)
        r2.pack(fill=tk.X)
        self.var_ren_watch = tk.BooleanVar(value=False)
        self._create_check_toggle(
            r2,
            "Pantau folder otomatis (file baru langsung di-rename sesuai pola)",
            self.var_ren_watch,
            command=self._update_start_button_text,
        ).pack(side=tk.LEFT)
        self.lbl_ren_folder = tk.Label(r2, text="(Belum ada folder)", font=("Segoe UI", 8))
        self.lbl_ren_folder.pack(side=tk.LEFT, padx=(8, 0))

        card_cfg = tk.Frame(self.frame_rename, highlightthickness=1, padx=12, pady=10)
        card_cfg.pack(fill=tk.X, pady=(0, 8))
        self.rename_cards.append(card_cfg)

        g1 = tk.Frame(card_cfg)
        g1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(g1, text="Pola Rename:", width=12).pack(side=tk.LEFT)
        self.var_ren_mode = tk.StringVar(value=list(RENAME_LABELS.keys())[0])
        cb_ren = ttk.Combobox(
            g1,
            textvariable=self.var_ren_mode,
            state="readonly",
            width=28,
            values=list(RENAME_LABELS.keys()),
        )
        cb_ren.pack(side=tk.LEFT, padx=(0, 12))
        cb_ren.bind("<<ComboboxSelected>>", lambda _e: self._ren_on_mode_change())

        ttk.Label(g1, text="Jika nama sama:").pack(side=tk.LEFT, padx=(0, 6))
        self.var_ren_conflict = tk.StringVar(value=list(CONFLICT_LABELS.keys())[0])
        ttk.Combobox(
            g1,
            textvariable=self.var_ren_conflict,
            state="readonly",
            width=24,
            values=list(CONFLICT_LABELS.keys()),
        ).pack(side=tk.LEFT)

        self.ren_params_frame = tk.Frame(card_cfg)
        self.var_ren_prefix = tk.StringVar(value="flow_")
        self.var_ren_suffix = tk.StringVar(value="")
        self.var_ren_base = tk.StringVar(value="konten")
        self.var_ren_start = tk.StringVar(value="1")
        self.var_ren_find = tk.StringVar(value="")
        self.var_ren_replace = tk.StringVar(value="")

        for v in (
            self.var_ren_prefix,
            self.var_ren_suffix,
            self.var_ren_base,
            self.var_ren_start,
            self.var_ren_find,
            self.var_ren_replace,
        ):
            v.trace_add("write", lambda *_a: self._ren_update_preview())

        self.lbl_ren_preview = tk.Label(
            card_cfg,
            text="Preview: contoh.mp4  →  flow_contoh.mp4",
            font=("Segoe UI", 8, "italic"),
        )
        self.lbl_ren_preview.pack(anchor=tk.W, pady=(4, 0))

        card_list = tk.Frame(self.frame_rename, highlightthickness=1, padx=12, pady=8)
        card_list.pack(fill=tk.BOTH, expand=True)
        self.rename_cards.append(card_list)

        tw = tk.Frame(card_list)
        tw.pack(fill=tk.BOTH, expand=True)
        self.ren_tree = ttk.Treeview(
            tw, columns=("old", "new", "status"), show="headings", height=5
        )
        self.ren_tree.heading("old", text="Nama Asli")
        self.ren_tree.heading("new", text="Nama Baru")
        self.ren_tree.heading("status", text="Status")
        self.ren_tree.column("old", width=260, anchor=tk.W)
        self.ren_tree.column("new", width=260, anchor=tk.W)
        self.ren_tree.column("status", width=150, anchor=tk.W)
        vsb = ttk.Scrollbar(tw, orient=tk.VERTICAL, command=self.ren_tree.yview)
        self.ren_tree.configure(yscrollcommand=vsb.set)
        self.ren_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._ren_on_mode_change()

    # =========================================================================
    # SEGMENT 3: UPSCALE FOTO & VIDEO
    # =========================================================================
    def _build_segment_upscale(self) -> None:
        self.up_cards = []

        card_files = tk.Frame(self.frame_upscale, highlightthickness=1, padx=12, pady=10)
        card_files.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.up_cards.append(card_files)

        top_f = tk.Frame(card_files)
        top_f.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(top_f, text="Antrean Foto & Video", font=("Segoe UI", 9, "bold")).pack(
            side=tk.LEFT
        )
        self.lbl_file_count = tk.Label(top_f, text="0 file", font=("Segoe UI", 8, "bold"), padx=8, pady=2)
        self.lbl_file_count.pack(side=tk.RIGHT)

        btn_bar = tk.Frame(card_files)
        btn_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(
            btn_bar, text="📁 Pilih Folder", command=self._choose_input_folder
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            btn_bar, text="🖼️🎬 Pilih Foto / Video", command=self._add_media_files
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            btn_bar, text="Hapus Terpilih", command=self._remove_selected
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            btn_bar, text="Bersihkan", command=self._clear_files
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(btn_bar, text="Filter:").pack(side=tk.LEFT, padx=(0, 4))
        self.var_up_filter = tk.StringVar(value=list(MEDIA_FILTER_LABELS.keys())[0])
        cb_up_f = ttk.Combobox(
            btn_bar,
            textvariable=self.var_up_filter,
            state="readonly",
            width=14,
            values=list(MEDIA_FILTER_LABELS.keys()),
        )
        cb_up_f.pack(side=tk.LEFT)
        cb_up_f.bind("<<ComboboxSelected>>", lambda _e: self._on_up_filter_change())

        tw = tk.Frame(card_files)
        tw.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.tree = ttk.Treeview(
            tw,
            columns=("name", "type", "size", "status"),
            show="headings",
            height=5,
            selectmode="extended",
        )
        self.tree.heading("name", text="Nama File")
        self.tree.heading("type", text="Jenis")
        self.tree.heading("size", text="Ukuran")
        self.tree.heading("status", text="Status")
        self.tree.column("name", width=330, anchor=tk.W)
        self.tree.column("type", width=70, anchor=tk.CENTER)
        self.tree.column("size", width=80, anchor=tk.E)
        self.tree.column("status", width=160, anchor=tk.W)
        vsb = ttk.Scrollbar(tw, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        out_mode_row = tk.Frame(card_files)
        out_mode_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(out_mode_row, text="Hasil file:").pack(side=tk.LEFT, padx=(0, 6))
        self.var_output_mode = tk.StringVar()
        self.combo_output_mode = ttk.Combobox(
            out_mode_row,
            textvariable=self.var_output_mode,
            state="readonly",
            values=list(OUTPUT_MODE_LABELS.keys()),
        )
        self.combo_output_mode.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.combo_output_mode.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_output_mode_change()
        )
        ttk.Button(out_mode_row, text="Buka Folder", command=self._open_output_dir).pack(
            side=tk.LEFT
        )

        self.custom_out_row = tk.Frame(card_files)
        ttk.Label(self.custom_out_row, text="Folder lain:").pack(side=tk.LEFT, padx=(0, 6))
        self.var_output_dir = tk.StringVar(value="")
        ttk.Entry(self.custom_out_row, textvariable=self.var_output_dir).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(self.custom_out_row, text="Ubah", command=self._choose_output_dir).pack(
            side=tk.LEFT
        )

        self.var_watch_mode = tk.BooleanVar(value=False)
        self.watch_bar = tk.Frame(card_files)
        self.watch_bar.pack(fill=tk.X)
        self.watch_toggle_row = self._create_check_toggle(
            self.watch_bar,
            "Pantau folder otomatis",
            self.var_watch_mode,
            command=self._on_watch_toggle,
        )
        self.watch_toggle_row.pack(side=tk.LEFT)
        self.lbl_watch_folder = tk.Label(
            self.watch_bar, text="(Folder belum dipilih)", font=("Segoe UI", 8)
        )
        self.lbl_watch_folder.pack(side=tk.LEFT, padx=(8, 6))
        ttk.Button(
            self.watch_bar, text="Pilih Folder Pantau", command=self._choose_watch_folder
        ).pack(side=tk.LEFT)

        card_mode = tk.Frame(self.frame_upscale, highlightthickness=1, padx=12, pady=8)
        card_mode.pack(fill=tk.X)
        self.up_cards.append(card_mode)

        mh = tk.Frame(card_mode)
        mh.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(mh, text="Mode Kualitas", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.btn_adv_toggle = tk.Button(
            mh,
            text="⚙️ Opsi Lanjutan ▾",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            cursor="hand2",
            command=self._toggle_advanced,
        )
        self.btn_adv_toggle.pack(side=tk.RIGHT)

        self.var_mode = tk.StringVar(value="fast")
        ttk.Radiobutton(
            card_mode,
            text="⚡ Mode Cepat — Proses hitungan detik (cocok untuk semua laptop)",
            variable=self.var_mode,
            value="fast",
            command=self._on_mode_change,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            card_mode,
            text="✨ Mode AI (Paling Tajam) — Super Resolution 4x → 1080p (disarankan pakai GPU)",
            variable=self.var_mode,
            value="ai",
            command=self._on_mode_change,
        ).pack(anchor=tk.W)

        self.adv_frame = tk.Frame(card_mode, padx=8, pady=6)
        ttk.Label(self.adv_frame, text="Model AI:").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 6), pady=(0, 4)
        )
        self.var_ai_model = tk.StringVar()
        self.combo_ai = ttk.Combobox(
            self.adv_frame,
            textvariable=self.var_ai_model,
            state="disabled",
            width=36,
            values=list(AI_MODEL_LABELS.keys()),
        )
        self.combo_ai.grid(row=0, column=1, sticky=tk.W, padx=(0, 12), pady=(0, 4))

        ttk.Label(self.adv_frame, text="VRAM:").grid(
            row=0, column=2, sticky=tk.W, padx=(0, 6), pady=(0, 4)
        )
        self.var_tile = tk.StringVar()
        self.combo_tile = ttk.Combobox(
            self.adv_frame,
            textvariable=self.var_tile,
            state="disabled",
            width=22,
            values=list(TILE_LABELS.keys()),
        )
        self.combo_tile.grid(row=0, column=3, sticky=tk.W, pady=(0, 4))

        ttk.Label(self.adv_frame, text="Kualitas:").grid(row=1, column=0, sticky=tk.W, padx=(0, 6))
        self.var_quality = tk.StringVar()
        ttk.Combobox(
            self.adv_frame,
            textvariable=self.var_quality,
            state="readonly",
            width=24,
            values=list(QUALITY_LABELS.keys()),
        ).grid(row=1, column=1, sticky=tk.W, padx=(0, 12))

        self.var_skip_existing = tk.BooleanVar(value=True)
        self._create_check_toggle(
            self.adv_frame,
            "Lewati file yang sudah ada",
            self.var_skip_existing,
            font=("Segoe UI", 8),
        ).grid(row=1, column=2, columnspan=2, sticky=tk.W)

    # =========================================================================
    # THEME & NAVIGATION
    # =========================================================================
    def _toggle_theme(self) -> None:
        self.theme_name = "dark_gold" if self.theme_name == "light" else "light"
        self.t = THEMES[self.theme_name]
        self.btn_theme.configure(
            text="☀️ Tema Terang" if self.theme_name == "dark_gold" else "🌙 Tema Emas Gelap"
        )
        self._apply_theme()

    def _apply_theme(self) -> None:
        t = self.t
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=t["bg_card"])
        style.configure("TLabel", background=t["bg_card"], foreground=t["text"], font=("Segoe UI", 9))
        style.configure("TRadiobutton", background=t["bg_card"], foreground=t["text"], font=("Segoe UI", 9))
        style.configure(
            "Treeview",
            font=("Segoe UI", 9),
            rowheight=24,
            background=t["tree_bg"],
            fieldbackground=t["tree_bg"],
            foreground=t["text"],
        )
        style.configure(
            "Treeview.Heading",
            font=("Segoe UI", 9, "bold"),
            background=t["tree_head"],
            foreground=t["text"],
        )
        style.configure(
            "TheFlow.Horizontal.TProgressbar",
            troughcolor=t["border"],
            background=t["primary"],
            thickness=10,
        )

        self.root.configure(bg=t["bg_app"])
        self.container.configure(bg=t["bg_app"])
        self.header.configure(bg=t["bg_app"])
        for child in self.header.winfo_children():
            self._paint_bg_recursive(child, t["bg_app"], t["text"])

        self.lbl_title.configure(fg=t["text"])
        self.lbl_gpu.configure(fg=t["muted"])
        self.btn_theme.configure(bg=t["secondary_bg"], fg=t["secondary_fg"])
        self.btn_download_tools.configure(bg=t["warning"], fg="#FFFFFF")

        self.tab_bar.configure(bg=t["bg_app"])
        self.body_frame.configure(bg=t["bg_app"])
        for f in (self.frame_move, self.frame_rename, self.frame_upscale):
            f.configure(bg=t["bg_app"])

        all_cards = self.move_cards + self.rename_cards + self.up_cards + [self.footer_card]
        for card in all_cards:
            card.configure(bg=t["bg_card"], highlightbackground=t["border"])
            self._paint_bg_recursive(card, t["bg_card"], t["text"])

        self.adv_frame.configure(bg=t["bg_sub"])
        self._paint_bg_recursive(self.adv_frame, t["bg_sub"], t["text"])
        self.lbl_file_count.configure(bg=t["secondary_bg"], fg=t["secondary_fg"])
        self.lbl_ren_count.configure(bg=t["secondary_bg"], fg=t["secondary_fg"])
        self.lbl_ren_preview.configure(fg=t["primary"])
        self.lbl_ren_folder.configure(fg=t["muted"])
        self.btn_adv_toggle.configure(bg=t["bg_card"], fg=t["primary"])
        self.btn_log.configure(bg=t["bg_card"], fg=t["muted"])

        self._style_tabs()
        self._refresh_tool_status()
        self._update_watch_label()
        if not self.is_running:
            self.btn_start.configure(bg=t["primary"], fg=t["primary_fg"])
            self.btn_stop.configure(bg=t["secondary_bg"], fg=t["muted"])

    def _paint_bg_recursive(self, widget: tk.Widget, bg: str, fg: str) -> None:
        if isinstance(widget, tk.Frame):
            widget.configure(bg=bg)
            for c in widget.winfo_children():
                self._paint_bg_recursive(c, bg, fg)
        elif isinstance(widget, tk.Label):
            widget.configure(bg=bg)
            if widget not in (
                self.lbl_tool_badge,
                self.lbl_file_count,
                self.lbl_ren_count,
                self.lbl_watch_folder,
                self.lbl_ren_preview,
                self.lbl_ren_folder,
                self.lbl_gpu,
            ):
                widget.configure(fg=fg)

    def _style_tabs(self) -> None:
        t = self.t
        tabs = {
            "move": self.btn_tab_move,
            "rename": self.btn_tab_rename,
            "upscale": self.btn_tab_up,
        }
        for key, btn in tabs.items():
            if key == self.active_tab:
                btn.configure(bg=t["primary"], fg=t["primary_fg"])
            else:
                btn.configure(bg=t["secondary_bg"], fg=t["secondary_fg"])

    def _switch_tab(self, tab: str) -> None:
        if self.is_running:
            messagebox.showinfo("Sedang Berjalan", "Hentikan proses dulu sebelum berpindah segmen.")
            return
        self.active_tab = tab
        for f in (self.frame_move, self.frame_rename, self.frame_upscale):
            f.pack_forget()
        if tab == "move":
            self.frame_move.pack(fill=tk.BOTH, expand=True)
        elif tab == "rename":
            self.frame_rename.pack(fill=tk.BOTH, expand=True)
        else:
            self.frame_upscale.pack(fill=tk.BOTH, expand=True)
        self._style_tabs()
        self._update_start_button_text()

    def _update_start_button_text(self) -> None:
        if self.active_tab == "move":
            self.btn_start.configure(
                text="👁️ Pantau & Pindah Otomatis" if self.var_mv_watch.get() else "▶ Pindahkan File"
            )
        elif self.active_tab == "rename":
            self.btn_start.configure(
                text="👁️ Pantau & Rename Otomatis" if self.var_ren_watch.get() else "▶ Rename File"
            )
        else:
            self.btn_start.configure(
                text="👁️ Mulai Pantau Folder" if self.var_watch_mode.get() else "▶ Mulai Upscale 1080p"
            )

    def _create_check_toggle(
        self,
        parent: tk.Widget,
        text: str,
        var: tk.BooleanVar,
        command=None,
        font: tuple = ("Segoe UI", 9),
    ) -> tk.Frame:
        row = tk.Frame(parent, cursor="hand2")
        box = tk.Label(row, width=2, font=("Segoe UI", 9, "bold"), relief=tk.SOLID, bd=1, cursor="hand2")
        box.pack(side=tk.LEFT, padx=(0, 7), pady=1)
        lbl = tk.Label(row, text=text, font=font, cursor="hand2")
        lbl.pack(side=tk.LEFT)

        def sync_visual(*_args) -> None:
            if var.get():
                box.configure(text="✓", bg=self.t["success"], fg="#FFFFFF", bd=0)
            else:
                box.configure(text="", bg="#FFFFFF", fg="#202124", bd=1)

        def on_click(_event=None) -> None:
            var.set(not var.get())
            if command:
                command()

        var.trace_add("write", sync_visual)
        sync_visual()
        for w in (row, box, lbl):
            w.bind("<Button-1>", on_click)
        return row

    # =========================================================================
    # SEGMENT 1 LOGIC: PINDAH FILE
    # =========================================================================
    def _current_move_config(self) -> FileOpConfig:
        return FileOpConfig(
            action=ACTION_LABELS.get(self.var_mv_action.get(), "move"),
            filter_type=FILTER_LABELS.get(self.var_mv_filter.get(), "all"),
            custom_exts=self.var_mv_custom_ext.get(),
            rename_mode="keep",
            conflict_policy=CONFLICT_LABELS.get(self.var_mv_conflict.get(), "auto_number"),
        )

    def _mv_choose_src(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Folder Sumber")
        if folder:
            self.var_mv_src.set(folder)
            if not self.var_mv_dst.get().strip():
                self.var_mv_dst.set(str(Path(folder) / "Terorganisir"))
            self._mv_scan_src()

    def _mv_choose_dst(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Folder Tujuan")
        if folder:
            self.var_mv_dst.set(folder)

    def _mv_open_dst(self) -> None:
        dst = self.var_mv_dst.get().strip()
        target = Path(dst) if dst else Path.cwd()
        target.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(target))

    def _mv_on_filter_change(self) -> None:
        state = tk.NORMAL if FILTER_LABELS.get(self.var_mv_filter.get()) == "custom" else tk.DISABLED
        self.entry_mv_ext.configure(state=state)
        self._mv_scan_src()

    def _mv_scan_src(self) -> None:
        src_str = self.var_mv_src.get().strip()
        if not src_str:
            return
        cfg = self._current_move_config()
        self.move_files = collect_matching_files(Path(src_str), cfg)
        for item in self.mv_tree.get_children():
            self.mv_tree.delete(item)
        self.move_tree_map.clear()
        for p in self.move_files:
            try:
                sz = f"{p.stat().st_size / (1024 * 1024):.1f} MB"
            except OSError:
                sz = "-"
            iid = self.mv_tree.insert("", tk.END, values=(p.name, sz, "Menunggu"))
            self.move_tree_map[p] = iid
        self.lbl_status.configure(text=f"{len(self.move_files)} file siap dipindahkan.")

    def _start_move_segment(self) -> None:
        src_str = self.var_mv_src.get().strip()
        dst_str = self.var_mv_dst.get().strip()
        if not src_str or not Path(src_str).is_dir():
            messagebox.showwarning("Folder Sumber", "Pilih Folder Sumber yang valid terlebih dahulu.")
            return
        if not dst_str:
            messagebox.showwarning("Folder Tujuan", "Pilih Folder Tujuan terlebih dahulu.")
            return

        src_dir, dst_dir = Path(src_str), Path(dst_str)
        cfg = self._current_move_config()
        watch = self.var_mv_watch.get()

        if not watch:
            self._mv_scan_src()
            if not self.move_files:
                messagebox.showinfo("Kosong", "Tidak ada file yang cocok di Folder Sumber.")
                return

        self.cancel_requested = False
        self._set_running_state(True)
        self.prog_bar["value"] = 0

        if not watch:
            snapshot = list(self.move_files)

            def worker_once() -> None:
                total = len(snapshot)
                done_cnt = skip_cnt = err_cnt = 0
                try:
                    for i, fpath in enumerate(snapshot):
                        if self.cancel_requested:
                            break
                        try:
                            tag, dest_p = process_file_operation(
                                fpath, dst_dir, cfg, i + 1, lambda s: self.ui_queue.put(("status", s))
                            )
                            if tag == "skipped":
                                skip_cnt += 1
                                self.ui_queue.put(("mv_row_status", (fpath, "Dilewati ⏭️")))
                            else:
                                done_cnt += 1
                                self.ui_queue.put(("mv_row_status", (fpath, "Selesai ✅")))
                                self.ui_queue.put(("log", f"✅ {fpath.name} → {dest_p}"))
                        except Exception as exc:
                            err_cnt += 1
                            self.ui_queue.put(("mv_row_status", (fpath, "Gagal ❌")))
                            self.ui_queue.put(("log", f"❌ Gagal ({fpath.name}): {exc}"))
                        self.ui_queue.put(("prog", ((i + 1) / total) * 100.0))

                    summary = f"Selesai! Diproses: {done_cnt}, Dilewati: {skip_cnt}, Gagal: {err_cnt}"
                    self.ui_queue.put(("status", summary))
                    self.ui_queue.put(("batch_done", summary))
                finally:
                    self.ui_queue.put(("reset_buttons", None))

            threading.Thread(target=worker_once, daemon=True).start()
        else:
            def watch_worker() -> None:
                seen: set[Path] = set()
                self.ui_queue.put(("log", f"👁️ Memantau pindah file: {src_dir}"))
                try:
                    while not self.cancel_requested:
                        # Remove paths that were moved out so newly downloaded files with the same name are detected
                        seen = {p for p in seen if p.exists()}
                        for fpath in collect_matching_files(src_dir, cfg):
                            if self.cancel_requested:
                                break
                            res = fpath.resolve()
                            if res in seen or not is_file_stable(fpath, 0.8):
                                continue
                            seen.add(res)
                            self.ui_queue.put(("mv_add_row", fpath))
                            try:
                                tag, dest_p = process_file_operation(
                                    fpath, dst_dir, cfg, 1, lambda s: self.ui_queue.put(("status", s))
                                )
                                if cfg.action == "move" and tag == "done":
                                    seen.discard(res)
                                st = "Dilewati ⏭️" if tag == "skipped" else "Selesai ✅"
                                self.ui_queue.put(("mv_row_status", (fpath, st)))
                                self.ui_queue.put(("log", f"✅ {fpath.name} → {dest_p}"))
                            except Exception as exc:
                                seen.discard(res)
                                self.ui_queue.put(("mv_row_status", (fpath, "Gagal ❌")))
                                self.ui_queue.put(("log", f"❌ {fpath.name}: {exc}"))

                        if not self.cancel_requested:
                            self.ui_queue.put(("status", f"👁️ Memantau '{src_dir.name}' (menunggu file baru...)"))
                            for _ in range(8):
                                if self.cancel_requested:
                                    break
                                time.sleep(0.2)
                finally:
                    self.ui_queue.put(("status", "Pemantauan pindah file dihentikan."))
                    self.ui_queue.put(("reset_buttons", None))

            threading.Thread(target=watch_worker, daemon=True).start()

    # =========================================================================
    # SEGMENT 2 LOGIC: RENAME FILE
    # =========================================================================
    def _current_rename_config(self) -> FileOpConfig:
        try:
            start_idx = max(1, int(self.var_ren_start.get().strip() or "1"))
        except ValueError:
            start_idx = 1
        return FileOpConfig(
            rename_mode=RENAME_LABELS.get(self.var_ren_mode.get(), "prefix_suffix"),
            prefix=self.var_ren_prefix.get(),
            suffix=self.var_ren_suffix.get(),
            base_name=self.var_ren_base.get(),
            start_index=start_idx,
            find_text=self.var_ren_find.get(),
            replace_text=self.var_ren_replace.get(),
            conflict_policy=CONFLICT_LABELS.get(self.var_ren_conflict.get(), "auto_number"),
        )

    def _ren_choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Folder untuk Rename")
        if not folder:
            return
        self.ren_watch_dir = folder
        self.lbl_ren_folder.configure(text=f"({Path(folder).name})")
        cfg = self._current_rename_config()
        self.rename_files = collect_matching_files(Path(folder), cfg)
        self._ren_rebuild_tree()
        self.lbl_status.configure(text=f"{len(self.rename_files)} file siap di-rename.")

    def _ren_add_files(self) -> None:
        files = filedialog.askopenfilenames(title="Pilih File untuk Rename")
        if not files:
            return
        existing = {p.resolve() for p in self.rename_files}
        for f in files:
            p = Path(f)
            if p.resolve() not in existing:
                self.rename_files.append(p)
                existing.add(p.resolve())
        if self.rename_files:
            self.ren_watch_dir = str(self.rename_files[0].parent)
            self.lbl_ren_folder.configure(text=f"({self.rename_files[0].parent.name})")
        self._ren_rebuild_tree()

    def _ren_clear(self) -> None:
        if self.is_running:
            return
        self.rename_files.clear()
        self._ren_rebuild_tree()
        self.prog_bar["value"] = 0
        self.lbl_status.configure(text="Daftar rename dikosongkan.")

    def _ren_on_mode_change(self) -> None:
        for w in self.ren_params_frame.winfo_children():
            w.destroy()
        mode = RENAME_LABELS.get(self.var_ren_mode.get(), "prefix_suffix")
        self.ren_params_frame.pack(fill=tk.X, pady=(2, 2), before=self.lbl_ren_preview)

        if mode == "prefix_suffix":
            ttk.Label(self.ren_params_frame, text="Awalan:").pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(self.ren_params_frame, textvariable=self.var_ren_prefix, width=16).pack(
                side=tk.LEFT, padx=(0, 12)
            )
            ttk.Label(self.ren_params_frame, text="Akhiran:").pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(self.ren_params_frame, textvariable=self.var_ren_suffix, width=16).pack(
                side=tk.LEFT
            )
        elif mode == "sequence":
            ttk.Label(self.ren_params_frame, text="Nama Dasar:").pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(self.ren_params_frame, textvariable=self.var_ren_base, width=18).pack(
                side=tk.LEFT, padx=(0, 12)
            )
            ttk.Label(self.ren_params_frame, text="Mulai Angka:").pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(self.ren_params_frame, textvariable=self.var_ren_start, width=8).pack(
                side=tk.LEFT
            )
        elif mode == "replace":
            ttk.Label(self.ren_params_frame, text="Cari Teks:").pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(self.ren_params_frame, textvariable=self.var_ren_find, width=18).pack(
                side=tk.LEFT, padx=(0, 12)
            )
            ttk.Label(self.ren_params_frame, text="Ganti Dengan:").pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(self.ren_params_frame, textvariable=self.var_ren_replace, width=18).pack(
                side=tk.LEFT
            )
        self._paint_bg_recursive(self.ren_params_frame, self.t["bg_card"], self.t["text"])
        self._ren_update_preview()

    def _ren_update_preview(self) -> None:
        cfg = self._current_rename_config()
        sample = self.rename_files[0] if self.rename_files else Path("contoh.mp4")
        new_name = compute_new_filename(sample, cfg, cfg.start_index)
        self.lbl_ren_preview.configure(text=f"Preview: {sample.name}  →  {new_name}")
        if self.rename_files:
            self._ren_rebuild_tree()

    def _ren_rebuild_tree(self) -> None:
        for item in self.ren_tree.get_children():
            self.ren_tree.delete(item)
        self.rename_tree_map.clear()
        cfg = self._current_rename_config()
        for idx, p in enumerate(self.rename_files, start=cfg.start_index):
            new_name = compute_new_filename(p, cfg, idx)
            iid = self.ren_tree.insert("", tk.END, values=(p.name, new_name, "Menunggu"))
            self.rename_tree_map[p] = iid
        self.lbl_ren_count.configure(text=f"{len(self.rename_files)} file")

    def _start_rename_segment(self) -> None:
        cfg = self._current_rename_config()
        watch = self.var_ren_watch.get()

        if not watch:
            if not self.rename_files:
                messagebox.showwarning("Belum Ada File", "Pilih folder atau file untuk di-rename dulu.")
                return
        else:
            watch_dir_str = getattr(self, "ren_watch_dir", "")
            if not watch_dir_str or not Path(watch_dir_str).is_dir():
                folder = filedialog.askdirectory(title="Pilih Folder yang Dipantau untuk Rename")
                if not folder:
                    return
                self.ren_watch_dir = folder
                self.lbl_ren_folder.configure(text=f"({Path(folder).name})")

        self.cancel_requested = False
        self._set_running_state(True)
        self.prog_bar["value"] = 0

        if not watch:
            snapshot = list(self.rename_files)

            def worker_once() -> None:
                total = len(snapshot)
                done_cnt = skip_cnt = err_cnt = 0
                try:
                    for i, fpath in enumerate(snapshot):
                        if self.cancel_requested:
                            break
                        try:
                            tag, dest_p = rename_file_in_place(
                                fpath, cfg, cfg.start_index + i, lambda s: self.ui_queue.put(("status", s))
                            )
                            if tag == "skipped":
                                skip_cnt += 1
                                self.ui_queue.put(("ren_row_status", (fpath, "Dilewati ⏭️")))
                            else:
                                done_cnt += 1
                                self.ui_queue.put(("ren_row_status", (fpath, f"Selesai ✅")))
                                self.ui_queue.put(("log", f"✅ Rename: {fpath.name} → {dest_p.name}"))
                        except Exception as exc:
                            err_cnt += 1
                            self.ui_queue.put(("ren_row_status", (fpath, "Gagal ❌")))
                            self.ui_queue.put(("log", f"❌ Rename ({fpath.name}): {exc}"))
                        self.ui_queue.put(("prog", ((i + 1) / total) * 100.0))

                    summary = f"Selesai! Di-rename: {done_cnt}, Dilewati: {skip_cnt}, Gagal: {err_cnt}"
                    self.ui_queue.put(("status", summary))
                    self.ui_queue.put(("batch_done", summary))
                finally:
                    self.ui_queue.put(("reset_buttons", None))

            threading.Thread(target=worker_once, daemon=True).start()
        else:
            watch_dir = Path(self.ren_watch_dir)

            def watch_worker() -> None:
                seq = cfg.start_index
                seen: set[Path] = set()
                self.ui_queue.put(("log", f"👁️ Memantau rename folder: {watch_dir}"))
                try:
                    while not self.cancel_requested:
                        for fpath in collect_matching_files(watch_dir, cfg):
                            if self.cancel_requested:
                                break
                            res = fpath.resolve()
                            if res in seen or not is_file_stable(fpath, 0.8):
                                continue
                            seen.add(res)
                            self.ui_queue.put(("ren_add_row", (fpath, compute_new_filename(fpath, cfg, seq))))
                            try:
                                tag, dest_p = rename_file_in_place(
                                    fpath, cfg, seq, lambda s: self.ui_queue.put(("status", s))
                                )
                                seen.add(dest_p.resolve())
                                seq += 1
                                st = "Dilewati ⏭️" if tag == "skipped" else "Selesai ✅"
                                self.ui_queue.put(("ren_row_status", (fpath, st)))
                                self.ui_queue.put(("log", f"✅ Rename: {fpath.name} → {dest_p.name}"))
                            except Exception as exc:
                                self.ui_queue.put(("ren_row_status", (fpath, "Gagal ❌")))
                                self.ui_queue.put(("log", f"❌ {fpath.name}: {exc}"))

                        if not self.cancel_requested:
                            self.ui_queue.put(("status", f"👁️ Memantau '{watch_dir.name}' (menunggu file baru...)"))
                            for _ in range(8):
                                if self.cancel_requested:
                                    break
                                time.sleep(0.2)
                finally:
                    self.ui_queue.put(("status", "Pemantauan rename dihentikan."))
                    self.ui_queue.put(("reset_buttons", None))

            threading.Thread(target=watch_worker, daemon=True).start()

    # =========================================================================
    # SEGMENT 3 LOGIC: UPSCALE FOTO & VIDEO
    # =========================================================================
    def _on_output_mode_change(self) -> None:
        mode = OUTPUT_MODE_LABELS.get(self.var_output_mode.get(), "same_suffix")
        if mode == "custom_folder":
            self.custom_out_row.pack(fill=tk.X, pady=(0, 4), before=self.watch_bar)
        else:
            self.custom_out_row.pack_forget()

    def _toggle_advanced(self) -> None:
        self.show_advanced = not self.show_advanced
        if self.show_advanced:
            self.adv_frame.pack(fill=tk.X, pady=(6, 0))
            self.btn_adv_toggle.configure(text="⚙️ Opsi Lanjutan ▴")
        else:
            self.adv_frame.pack_forget()
            self.btn_adv_toggle.configure(text="⚙️ Opsi Lanjutan ▾")

    def _update_watch_label(self) -> None:
        if self.selected_folder and Path(self.selected_folder).is_dir():
            name = Path(self.selected_folder).name or self.selected_folder
            self.lbl_watch_folder.configure(text=f"({name})", fg=self.t["primary"])
        else:
            self.lbl_watch_folder.configure(text="(Folder belum dipilih)", fg=self.t["muted"])

    def _choose_watch_folder(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Folder yang Akan Dipantau")
        if not folder:
            return
        self.selected_folder = folder
        self.var_output_dir.set(str(Path(folder) / "1080p"))
        self._update_watch_label()
        self.lbl_status.configure(text=f"Folder pantau dipilih: {Path(folder).name}")

    def _on_watch_toggle(self) -> None:
        if self.var_watch_mode.get():
            if not self.selected_folder or not Path(self.selected_folder).is_dir():
                self._choose_watch_folder()
        self._update_start_button_text()

    def _apply_saved_settings(self) -> None:
        cfg = self.saved_config
        self.var_mode.set(cfg.mode if cfg.mode in ("fast", "ai") else "fast")
        self.var_ai_model.set(
            AI_MODEL_REVERSE.get(cfg.ai_model, list(AI_MODEL_LABELS.keys())[0])
        )
        self.var_tile.set(TILE_REVERSE.get(cfg.tile_size, list(TILE_LABELS.keys())[0]))
        self.var_quality.set(QUALITY_REVERSE.get(cfg.crf, list(QUALITY_LABELS.keys())[0]))
        self.var_skip_existing.set(cfg.skip_existing)
        self.var_output_mode.set(
            OUTPUT_MODE_REVERSE.get(cfg.output_mode, list(OUTPUT_MODE_LABELS.keys())[0])
        )
        if cfg.output_dir:
            self.var_output_dir.set(cfg.output_dir)
        if cfg.watch_folder:
            self.selected_folder = cfg.watch_folder
        self._update_watch_label()
        self._on_mode_change()
        self._on_output_mode_change()

    def _current_upscale_config(self) -> UpscaleConfig:
        return UpscaleConfig(
            mode=self.var_mode.get(),
            ai_model=AI_MODEL_LABELS.get(self.var_ai_model.get(), "realesrgan-x4plus"),
            target_short_side=1080,
            crf=QUALITY_LABELS.get(self.var_quality.get(), 18),
            tile_size=TILE_LABELS.get(self.var_tile.get(), 0),
            skip_existing=self.var_skip_existing.get(),
            output_mode=OUTPUT_MODE_LABELS.get(self.var_output_mode.get(), "same_suffix"),
            output_dir=self.var_output_dir.get().strip(),
            watch_folder=self.selected_folder,
        )

    def _resolve_output_paths(
        self, in_file: Path, config: UpscaleConfig
    ) -> tuple[Path, Path]:
        is_img = is_image_file(in_file)
        out_ext = in_file.suffix if is_img else ".mp4"
        if config.output_mode == "overwrite":
            final_path = in_file.with_suffix(out_ext)
            tmp_path = in_file.parent / f".__tmp_{in_file.stem}_1080p{out_ext}"
            return tmp_path, final_path
        if config.output_mode == "custom_folder" and config.output_dir:
            out_dir = Path(config.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            final_path = out_dir / f"{in_file.stem}_1080p{out_ext}"
            return final_path, final_path
        final_path = in_file.parent / f"{in_file.stem}_1080p{out_ext}"
        return final_path, final_path

    def _on_mode_change(self) -> None:
        state = "readonly" if self.var_mode.get() == "ai" else "disabled"
        self.combo_ai.configure(state=state)
        self.combo_tile.configure(state=state)

    def _rebuild_media_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.media_tree_map.clear()
        for path in self.media_files:
            kind = "Foto" if is_image_file(path) else "Video"
            try:
                size_str = f"{path.stat().st_size / (1024 * 1024):.1f} MB"
            except OSError:
                size_str = "-"
            iid = self.tree.insert("", tk.END, values=(path.name, kind, size_str, "Menunggu"))
            self.media_tree_map[path] = iid
        self.lbl_file_count.configure(text=f"{len(self.media_files)} file")

    def _on_up_filter_change(self) -> None:
        if self.selected_folder and Path(self.selected_folder).is_dir() and not self.is_running:
            mfilter = MEDIA_FILTER_LABELS.get(self.var_up_filter.get(), "all")
            self.media_files = collect_videos(Path(self.selected_folder), media_filter=mfilter)
            self._rebuild_media_tree()

    def _choose_input_folder(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Folder Foto / Video")
        if not folder:
            return
        folder_path = Path(folder)
        self.selected_folder = str(folder_path)
        self._update_watch_label()
        mfilter = MEDIA_FILTER_LABELS.get(self.var_up_filter.get(), "all")
        self.media_files = collect_videos(folder_path, media_filter=mfilter)
        self.var_output_dir.set(str(folder_path / "1080p"))
        self._rebuild_media_tree()
        self.lbl_status.configure(
            text=f"Folder dipilih: {folder_path.name} ({len(self.media_files)} file)"
        )

    def _add_media_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="Pilih Foto atau Video",
            filetypes=[
                ("Foto & Video", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.png *.jpg *.jpeg *.webp *.bmp"),
                ("All Files", "*.*"),
            ],
        )
        if not files:
            return
        existing = {p.resolve() for p in self.media_files}
        for f in files:
            p = Path(f)
            if p.resolve() not in existing:
                self.media_files.append(p)
                existing.add(p.resolve())
        if self.media_files:
            if not self.selected_folder:
                self.selected_folder = str(self.media_files[0].parent)
                self._update_watch_label()
            if not self.var_output_dir.get().strip():
                self.var_output_dir.set(str(self.media_files[0].parent / "1080p"))
        self._rebuild_media_tree()
        self.lbl_status.configure(text=f"{len(self.media_files)} file siap di-upscale.")

    def _remove_selected(self) -> None:
        if self.is_running:
            return
        selected = set(self.tree.selection())
        if not selected:
            return
        self.media_files = [
            p for p in self.media_files if self.media_tree_map.get(p) not in selected
        ]
        self._rebuild_media_tree()

    def _clear_files(self) -> None:
        if self.is_running:
            return
        self.media_files.clear()
        self._rebuild_media_tree()
        self.prog_bar["value"] = 0
        self.lbl_status.configure(text="Siap. Pilih folder atau file untuk memulai.")

    def _choose_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Pilih Folder Hasil")
        if folder:
            self.var_output_dir.set(folder)

    def _open_output_dir(self) -> None:
        target = None
        mode = OUTPUT_MODE_LABELS.get(self.var_output_mode.get(), "same_suffix")
        if mode != "custom_folder":
            if self.media_files:
                target = self.media_files[0].parent
            elif self.selected_folder:
                target = Path(self.selected_folder)
        if target is None:
            out_str = self.var_output_dir.get().strip()
            target = Path(out_str) if out_str else Path.cwd()
        target.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(target))

    def _process_single_media(
        self,
        tools: dict,
        in_file: Path,
        write_path: Path,
        final_path: Path,
        config: UpscaleConfig,
        prefix: str,
    ) -> None:
        def on_prog(pct: float) -> None:
            self.ui_queue.put(("prog", pct))
            self.ui_queue.put(("row_status", (in_file, f"Proses {int(pct)}%")))
            self.ui_queue.put(("status", f"{prefix}{in_file.name} ({int(pct)}%)"))

        if is_image_file(in_file):
            if config.mode == "ai":
                upscale_image_ai(
                    realesrgan_path=tools["realesrgan"],
                    input_path=in_file,
                    output_path=write_path,
                    config=config,
                    status_cb=lambda s: self.ui_queue.put(("status", s)),
                    progress_cb=on_prog,
                    cancel_check=lambda: self.cancel_requested,
                )
            else:
                upscale_image_fast(
                    ffmpeg_path=tools["ffmpeg"],
                    input_path=in_file,
                    output_path=write_path,
                    config=config,
                    status_cb=lambda s: self.ui_queue.put(("status", s)),
                    progress_cb=on_prog,
                    cancel_check=lambda: self.cancel_requested,
                )
        else:
            if config.mode == "ai":
                upscale_video_ai(
                    ffmpeg_path=tools["ffmpeg"],
                    ffprobe_path=tools["ffprobe"],
                    realesrgan_path=tools["realesrgan"],
                    input_path=in_file,
                    output_path=write_path,
                    config=config,
                    status_cb=lambda s: self.ui_queue.put(("status", s)),
                    progress_cb=on_prog,
                    cancel_check=lambda: self.cancel_requested,
                )
            else:
                upscale_video_fast(
                    ffmpeg_path=tools["ffmpeg"],
                    ffprobe_path=tools["ffprobe"],
                    input_path=in_file,
                    output_path=write_path,
                    config=config,
                    status_cb=lambda s: self.ui_queue.put(("status", s)),
                    progress_cb=on_prog,
                    cancel_check=lambda: self.cancel_requested,
                )

        if config.output_mode == "overwrite":
            os.replace(write_path, final_path)
            if in_file.resolve() != final_path.resolve() and in_file.exists():
                in_file.unlink(missing_ok=True)

    def _start_upscale_batch(self) -> None:
        if not self.media_files:
            messagebox.showwarning("Belum Ada File", "Pilih folder atau file foto/video dulu.")
            return
        config = self._current_upscale_config()
        tools = self._validate_tools_for_mode(config)
        if not tools:
            return
        save_settings(config)

        self.cancel_requested = False
        self._set_running_state(True)
        self.prog_bar["value"] = 0
        snapshot = list(self.media_files)

        def worker() -> None:
            total = len(snapshot)
            ok = skipped = err = 0
            try:
                for idx, in_file in enumerate(snapshot, start=1):
                    if self.cancel_requested:
                        break
                    write_path, final_path = self._resolve_output_paths(in_file, config)
                    if config.output_mode != "overwrite" and config.skip_existing and final_path.is_file():
                        skipped += 1
                        self.ui_queue.put(("row_status", (in_file, "Dilewati ⏭️")))
                        continue

                    self.ui_queue.put(("prog", 0.0))
                    self.ui_queue.put(("row_status", (in_file, "Memproses...")))
                    self.ui_queue.put(("log", f"[{idx}/{total}] Memulai: {in_file.name}"))
                    try:
                        self._process_single_media(
                            tools, in_file, write_path, final_path, config, f"[{idx}/{total}] "
                        )
                        ok += 1
                        self.ui_queue.put(("row_status", (in_file, "Selesai ✅")))
                        self.ui_queue.put(("log", f"✅ Selesai: {final_path.name}"))
                    except InterruptedError:
                        if write_path.exists():
                            write_path.unlink(missing_ok=True)
                        self.ui_queue.put(("row_status", (in_file, "Dibatalkan ⏹️")))
                        break
                    except Exception as exc:
                        if config.output_mode == "overwrite" and write_path.exists():
                            write_path.unlink(missing_ok=True)
                        err += 1
                        self.ui_queue.put(("row_status", (in_file, "Gagal ❌")))
                        self.ui_queue.put(("log", f"❌ Gagal ({in_file.name}): {exc}"))

                summary = f"Selesai! Berhasil: {ok}, Dilewati: {skipped}, Gagal: {err}"
                self.ui_queue.put(("status", summary))
                self.ui_queue.put(("batch_done", summary))
            finally:
                self.ui_queue.put(("reset_buttons", None))

        threading.Thread(target=worker, daemon=True).start()

    def _start_upscale_watch(self) -> None:
        watch_str = self.selected_folder
        if not watch_str or not Path(watch_str).is_dir():
            folder = filedialog.askdirectory(title="Pilih Folder yang Akan Dipantau")
            if not folder:
                return
            watch_str = folder
            self.selected_folder = watch_str
            self._update_watch_label()

        watch_dir = Path(watch_str)
        config = self._current_upscale_config()
        tools = self._validate_tools_for_mode(config)
        if not tools:
            return
        save_settings(config)

        self.cancel_requested = False
        self._set_running_state(True)
        self.prog_bar["value"] = 0

        watch_queue: queue.Queue[Path] = queue.Queue()
        seen: set[Path] = set()

        def scanner() -> None:
            self.ui_queue.put(("log", f"👁️ Memantau folder: {watch_dir}"))
            while not self.cancel_requested:
                mfilter = MEDIA_FILTER_LABELS.get(self.var_up_filter.get(), "all")
                for in_file in collect_videos(watch_dir, media_filter=mfilter):
                    if self.cancel_requested:
                        break
                    if in_file.name.startswith(".__tmp_"):
                        continue
                    resolved = in_file.resolve()
                    if resolved in seen:
                        continue
                    _, final_path = self._resolve_output_paths(in_file, config)
                    if config.output_mode != "overwrite" and config.skip_existing and final_path.is_file():
                        seen.add(resolved)
                        continue
                    if not is_file_ready(in_file, wait_seconds=1.0):
                        continue
                    seen.add(resolved)
                    self.ui_queue.put(("add_tree_row", in_file))
                    self.ui_queue.put(("log", f"📥 Masuk antrean: {in_file.name}"))
                    watch_queue.put(in_file)

                for _ in range(8):
                    if self.cancel_requested:
                        break
                    time.sleep(0.2)

        def worker() -> None:
            try:
                while not self.cancel_requested:
                    try:
                        in_file = watch_queue.get(timeout=0.5)
                    except queue.Empty:
                        if not self.cancel_requested:
                            self.ui_queue.put(
                                ("status", f"👁️ Memantau '{watch_dir.name}' (menunggu foto/video baru...)")
                            )
                        continue

                    write_path, final_path = self._resolve_output_paths(in_file, config)
                    self.ui_queue.put(("prog", 0.0))
                    self.ui_queue.put(("row_status", (in_file, "Memproses...")))
                    try:
                        self._process_single_media(
                            tools, in_file, write_path, final_path, config, "Otomatis: "
                        )
                        seen.add(final_path.resolve())
                        self.ui_queue.put(("row_status", (in_file, "Selesai ✅")))
                        self.ui_queue.put(("log", f"✅ Selesai: {final_path.name}"))
                    except InterruptedError:
                        if write_path.exists():
                            write_path.unlink(missing_ok=True)
                        self.ui_queue.put(("row_status", (in_file, "Dibatalkan ⏹️")))
                        break
                    except Exception as exc:
                        if config.output_mode == "overwrite" and write_path.exists():
                            write_path.unlink(missing_ok=True)
                        self.ui_queue.put(("row_status", (in_file, "Gagal ❌")))
                        self.ui_queue.put(("log", f"❌ Gagal ({in_file.name}): {exc}"))
            finally:
                self.ui_queue.put(("status", "Pemantauan dihentikan."))
                self.ui_queue.put(("reset_buttons", None))

        threading.Thread(target=scanner, daemon=True).start()
        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # SHARED CONTROLS, DOWNLOADER & QUEUE POLLING
    # =========================================================================
    def _detect_gpu_async(self) -> None:
        threading.Thread(
            target=lambda: self.ui_queue.put(("gpu", detect_gpu_name())), daemon=True
        ).start()

    def _log(self, msg: str) -> None:
        self.log_history.append(msg)
        if len(self.log_history) > 300:
            self.log_history.pop(0)
        if self.log_text_widget and self.log_text_widget.winfo_exists():
            self.log_text_widget.configure(state=tk.NORMAL)
            self.log_text_widget.insert(tk.END, msg + "\n")
            self.log_text_widget.see(tk.END)
            self.log_text_widget.configure(state=tk.DISABLED)

    def _open_log_window(self) -> None:
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("Log Aktivitas — File Opration by Zul")
        win.geometry("620x360")
        txt = scrolledtext.ScrolledText(win, font=("Consolas", 9), state=tk.NORMAL)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        txt.insert(tk.END, "\n".join(self.log_history) + ("\n" if self.log_history else ""))
        txt.see(tk.END)
        txt.configure(state=tk.DISABLED)
        self.log_window = win
        self.log_text_widget = txt

    def _refresh_tool_status(self) -> dict:
        tools = get_tool_paths()
        has_ff = bool(tools["ffmpeg"])
        has_ai = bool(tools["realesrgan"])
        if has_ff and has_ai:
            self.lbl_tool_badge.configure(text="Tools: Lengkap ✅", fg=self.t["success"])
            self.btn_download_tools.pack_forget()
        elif has_ff:
            self.lbl_tool_badge.configure(text="FFmpeg ✅ | AI Belum Ada", fg=self.t["warning"])
            self.btn_download_tools.configure(text="Download AI Tools")
            self.btn_download_tools.pack(anchor=tk.E)
        else:
            self.lbl_tool_badge.configure(text="Tools Belum Lengkap", fg=self.t["danger"])
            self.btn_download_tools.configure(text="Download Tools Otomatis")
            self.btn_download_tools.pack(anchor=tk.E)
        return tools

    def _start_download_tools(self, auto: bool = False) -> None:
        if self.is_downloading or self.is_running:
            return
        cur_tools = get_tool_paths()
        if cur_tools["ffmpeg"] and cur_tools["realesrgan"]:
            self._refresh_tool_status()
            return

        self.is_downloading = True
        self.btn_download_tools.configure(state=tk.DISABLED)
        self.btn_start.configure(state=tk.DISABLED)
        pct_re = re.compile(r"(\d+)%")

        def handle_dl_msg(label: str, msg: str) -> None:
            self.ui_queue.put(("status", f"{label}: {msg}"))
            self.ui_queue.put(("tool_badge", (f"{label}: {msg}", self.t["warning"])))
            m = pct_re.search(msg)
            if m:
                self.ui_queue.put(("prog", float(m.group(1))))

        def worker() -> None:
            try:
                if not cur_tools["ffmpeg"]:
                    self.ui_queue.put(("log", "Mengunduh FFmpeg otomatis..."))
                    install_ffmpeg(progress_cb=lambda m: handle_dl_msg("FFmpeg", m))
                    self.ui_queue.put(("log", "✅ FFmpeg berhasil dipasang."))

                if not cur_tools["realesrgan"]:
                    self.ui_queue.put(("log", "Mengunduh Real-ESRGAN AI otomatis..."))
                    install_realesrgan(progress_cb=lambda m: handle_dl_msg("AI Tools", m))
                    self.ui_queue.put(("log", "✅ Real-ESRGAN AI berhasil dipasang."))

                self.ui_queue.put(("prog", 100.0))
                self.ui_queue.put(("status", "Semua komponen lengkap! Siap digunakan."))
                self.ui_queue.put(("tools_done", (True, auto)))
            except Exception as exc:
                self.ui_queue.put(("log", f"❌ Gagal mengunduh tools: {exc}"))
                self.ui_queue.put(("status", "Gagal mengunduh tools. Cek koneksi internet."))
                self.ui_queue.put(("tools_done", (False, auto)))

        threading.Thread(target=worker, daemon=True).start()

    def _validate_tools_for_mode(self, config: UpscaleConfig) -> dict | None:
        tools = self._refresh_tool_status()
        if not tools["ffmpeg"] or (config.mode == "ai" and not tools["realesrgan"]):
            self._start_download_tools(auto=False)
            messagebox.showinfo(
                "Mengunduh Komponen",
                "Komponen belum lengkap, aplikasi sedang mengunduhnya otomatis. Tunggu hingga status hijau (Lengkap).",
            )
            return None
        return tools

    def _on_start_click(self) -> None:
        if self.is_running or self.is_downloading:
            return
        if self.active_tab == "move":
            self._start_move_segment()
        elif self.active_tab == "rename":
            self._start_rename_segment()
        else:
            if self.var_watch_mode.get():
                self._start_upscale_watch()
            else:
                self._start_upscale_batch()

    def _stop_current(self) -> None:
        if self.is_running:
            self.cancel_requested = True
            self.btn_stop.configure(state=tk.DISABLED)
            self.lbl_status.configure(text="Menghentikan proses...")

    def _set_running_state(self, running: bool) -> None:
        self.is_running = running
        t = self.t
        if running:
            self.btn_start.configure(state=tk.DISABLED, bg=t["secondary_bg"], fg=t["muted"])
            self.btn_download_tools.configure(state=tk.DISABLED)
            self.btn_stop.configure(state=tk.NORMAL, bg=t["danger"], fg="#FFFFFF")
        else:
            self.btn_start.configure(state=tk.NORMAL, bg=t["primary"], fg=t["primary_fg"])
            self.btn_download_tools.configure(state=tk.NORMAL)
            self.btn_stop.configure(state=tk.DISABLED, bg=t["secondary_bg"], fg=t["muted"])

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "status":
                    self.lbl_status.configure(text=payload)
                elif kind == "gpu":
                    self.lbl_gpu.configure(text=f"TheFlow Pro Edition • GPU: {payload}")
                elif kind == "tool_badge":
                    text, color = payload
                    self.lbl_tool_badge.configure(text=text, fg=color)
                elif kind == "prog":
                    self.prog_bar["value"] = payload
                elif kind == "mv_add_row":
                    p_obj = payload
                    try:
                        sz = f"{p_obj.stat().st_size / (1024 * 1024):.1f} MB"
                    except OSError:
                        sz = "-"
                    if p_obj not in self.move_tree_map:
                        self.move_files.append(p_obj)
                        iid = self.mv_tree.insert("", tk.END, values=(p_obj.name, sz, "Menunggu"))
                        self.move_tree_map[p_obj] = iid
                    else:
                        iid = self.move_tree_map[p_obj]
                        if self.mv_tree.exists(iid):
                            self.mv_tree.item(iid, values=(p_obj.name, sz, "Menunggu"))
                elif kind == "mv_row_status":
                    p_obj, st = payload
                    iid = self.move_tree_map.get(p_obj)
                    if iid and self.mv_tree.exists(iid):
                        vals = list(self.mv_tree.item(iid, "values"))
                        if len(vals) == 3:
                            vals[2] = st
                            self.mv_tree.item(iid, values=vals)
                elif kind == "ren_add_row":
                    p_obj, new_name = payload
                    if p_obj not in self.rename_tree_map:
                        self.rename_files.append(p_obj)
                        iid = self.ren_tree.insert("", tk.END, values=(p_obj.name, new_name, "Menunggu"))
                        self.rename_tree_map[p_obj] = iid
                        self.lbl_ren_count.configure(text=f"{len(self.rename_files)} file")
                elif kind == "ren_row_status":
                    p_obj, st = payload
                    iid = self.rename_tree_map.get(p_obj)
                    if iid and self.ren_tree.exists(iid):
                        vals = list(self.ren_tree.item(iid, "values"))
                        if len(vals) == 3:
                            vals[2] = st
                            self.ren_tree.item(iid, values=vals)
                elif kind == "add_tree_row":
                    p_obj = payload
                    if p_obj not in self.media_tree_map:
                        self.media_files.append(p_obj)
                        ftype = "Foto" if is_image_file(p_obj) else "Video"
                        try:
                            size_str = f"{p_obj.stat().st_size / (1024 * 1024):.1f} MB"
                        except OSError:
                            size_str = "-"
                        iid = self.tree.insert(
                            "", tk.END, values=(p_obj.name, ftype, size_str, "Menunggu")
                        )
                        self.media_tree_map[p_obj] = iid
                        self.lbl_file_count.configure(text=f"{len(self.media_files)} file")
                elif kind == "row_status":
                    p_obj, status_txt = payload
                    iid = self.media_tree_map.get(p_obj)
                    if iid and self.tree.exists(iid):
                        vals = list(self.tree.item(iid, "values"))
                        if len(vals) == 4:
                            vals[3] = status_txt
                            self.tree.item(iid, values=vals)
                elif kind == "tools_done":
                    ok, is_auto = payload
                    self.is_downloading = False
                    self.btn_download_tools.configure(state=tk.NORMAL)
                    self.btn_start.configure(state=tk.NORMAL, bg=self.t["primary"], fg=self.t["primary_fg"])
                    self._refresh_tool_status()
                    if ok and not is_auto:
                        messagebox.showinfo("Berhasil", "Tools berhasil diunduh dan siap digunakan!")
                elif kind == "batch_done":
                    messagebox.showinfo("Selesai", payload)
                elif kind == "reset_buttons":
                    self._set_running_state(False)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


def main() -> None:
    root = tk.Tk()
    FileOprationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
