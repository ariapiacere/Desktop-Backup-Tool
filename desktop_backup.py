"""
Desktop Backup Tool
====================
Organizes recent Desktop files into a structured backup folder.
Supports GUI (Tkinter), dry-run, configurable file grouping, and full logging.

Usage:
    python desktop_backup.py            → Launches Tkinter GUI
    python desktop_backup.py --cli      → Runs interactive CLI mode
"""

import os
import sys
import json
import shutil
import logging
import argparse
import platform
import ctypes
from datetime import datetime, timedelta
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "config.json"
LOG_PATH = SCRIPT_DIR / "backup_log.txt"

DEFAULT_CONFIG = {
    "time_window_hours": 24,
    "destination_drive": "",
    "excluded_folders": ["node_modules", ".git", "__pycache__"],
    "ignored_extensions": [".tmp", ".log", ".lnk", ".ini"],
    "dry_run": False,
    "logging_enabled": True,
    "file_type_groups": {
        "images":    [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".heic"],
        "documents": [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".odt", ".rtf", ".md"],
        "videos":    [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
        "audio":     [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
        "archives":  [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
        "code":      [".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".sh", ".bat", ".ps1"],
    },
}


def load_config() -> dict:
    """Load config from JSON file, filling in missing keys from defaults."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so new keys are always present
            merged = DEFAULT_CONFIG.copy()
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] Could not read config.json ({e}). Using defaults.")
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    """Persist config to JSON file."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def setup_logger(enabled: bool) -> logging.Logger:
    logger = logging.getLogger("DesktopBackup")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("[%(asctime)s] %(levelname)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    if enabled:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# ─────────────────────────────────────────────────────────────────────────────
# DESKTOP DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def get_desktop_path() -> Path:
    """
    Dynamically detect the Desktop path, including OneDrive-redirected desktops.
    Works on Windows 10/11 even with folder redirection.
    """
    # Method 1: Windows Shell API (most reliable, handles OneDrive redirect)
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            )
            desktop, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            p = Path(desktop)
            if p.exists():
                return p
        except Exception:
            pass

    # Method 2: USERPROFILE env var fallback
    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile:
        p = Path(userprofile) / "Desktop"
        if p.exists():
            return p

    # Method 3: Generic home dir
    p = Path.home() / "Desktop"
    if p.exists():
        return p

    # Method 4: OneDrive Desktop
    onedrive = os.environ.get("OneDrive", "")
    if onedrive:
        p = Path(onedrive) / "Desktop"
        if p.exists():
            return p

    raise FileNotFoundError("Could not locate the Desktop folder.")


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP FOLDER NAMING
# ─────────────────────────────────────────────────────────────────────────────

def make_backup_folder(drive: str) -> Path:
    """
    Create or reuse backup folder on the given drive.
    Format: MM.DD.YY_backup (NO _1, _2 suffix)
    """
    drive = drive.rstrip(":\\/").upper()
    date_str = datetime.now().strftime("%m.%d.%y")
    base_name = f"{date_str}_backup"
    root = Path(f"{drive}:\\")

    if not root.exists():
        raise FileNotFoundError(f"Drive {drive}: does not exist or is not accessible.")

    candidate = root / base_name

    # ✅ ใช้โฟลเดอร์เดิมถ้ามีอยู่แล้ว
    if not candidate.exists():
        candidate.mkdir(parents=True)

    return candidate


# ─────────────────────────────────────────────────────────────────────────────
# FILE CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_file(file_path: Path, groups: dict) -> str:
    """Return the subfolder name for a given file based on its extension."""
    ext = file_path.suffix.lower()
    for group, extensions in groups.items():
        if ext in [e.lower() for e in extensions]:
            return group
    return "others"


def is_hidden_or_system(file_path: Path) -> bool:
    """Check if a file has hidden or system attributes (Windows only)."""
    if platform.system() != "Windows":
        return False
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(file_path))
        if attrs == -1:
            return False
        FILE_ATTRIBUTE_HIDDEN = 0x2
        FILE_ATTRIBUTE_SYSTEM = 0x4
        return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
    except Exception:
        return False


def is_recent(file_path: Path, hours: int) -> bool:
    """Return True if max(ctime, mtime) is within the given number of hours."""
    cutoff = datetime.now() - timedelta(hours=hours)
    try:
        stat = file_path.stat()
        newest = max(stat.st_ctime, stat.st_mtime)
        return datetime.fromtimestamp(newest) >= cutoff
    except OSError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CORE BACKUP ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class BackupResult:
    def __init__(self):
        self.scanned   = 0
        self.moved     = 0
        self.skipped   = 0
        self.errors    = 0
        self.details   = []   # list of (status, src, dst_or_reason)

    def add(self, status: str, src: Path, extra: str = ""):
        self.details.append((status, str(src), extra))

    def summary(self) -> str:
        lines = [
            "─" * 55,
            "  BACKUP SUMMARY",
            "─" * 55,
            f"  Files scanned  : {self.scanned}",
            f"  Files moved    : {self.moved}",
            f"  Files skipped  : {self.skipped}",
            f"  Errors         : {self.errors}",
            "─" * 55,
        ]
        return "\n".join(lines)


def run_backup(cfg: dict, progress_callback=None) -> tuple[BackupResult, Path | None]:
    """
    Main backup engine.

    Args:
        cfg:               Configuration dict.
        progress_callback: Optional callable(message: str) for UI updates.

    Returns:
        (BackupResult, backup_folder_path_or_None)
    """
    result = BackupResult()
    logger = setup_logger(cfg.get("logging_enabled", True))
    dry_run = cfg.get("dry_run", False)

    def notify(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    # ── Resolve Desktop ──────────────────────────────────────────────────────
    try:
        desktop = get_desktop_path()
        notify(f"Desktop detected: {desktop}")
    except FileNotFoundError as e:
        logger.error(str(e))
        result.errors += 1
        return result, None

    # ── Prepare backup folder ────────────────────────────────────────────────
    drive = cfg.get("destination_drive", "").strip()
    if not drive:
        logger.error("No destination drive configured.")
        result.errors += 1
        return result, None

    try:
        if dry_run:
            # Simulate folder path without creating it
            date_str = datetime.now().strftime("%m.%d.%y")
            backup_folder = Path(f"{drive.upper()}:\\{date_str}_backup")
            notify(f"[DRY RUN] Backup folder would be: {backup_folder}")
        else:
            backup_folder = make_backup_folder(drive)
            notify(f"Backup folder created: {backup_folder}")
    except FileNotFoundError as e:
        logger.error(str(e))
        result.errors += 1
        return result, None

    # ── Settings ─────────────────────────────────────────────────────────────
    hours          = cfg.get("time_window_hours", 24)
    excluded_dirs  = {d.lower() for d in cfg.get("excluded_folders", [])}
    ignored_exts   = {e.lower() for e in cfg.get("ignored_extensions", [])}
    type_groups    = cfg.get("file_type_groups", {})

    notify(f"Time window   : last {hours} hour(s)")
    notify(f"Dry run       : {dry_run}")
    notify(f"Excluded dirs : {excluded_dirs or 'none'}")
    notify(f"Ignored exts  : {ignored_exts or 'none'}")
    notify("Scanning Desktop…")

    # ── Scan Desktop (top-level files only) ──────────────────────────────────
    try:
        entries = list(desktop.iterdir())
    except PermissionError as e:
        logger.error(f"Cannot read Desktop: {e}")
        result.errors += 1
        return result, backup_folder

    for entry in entries:
        # Skip directories
        if not entry.is_file():
            if entry.is_dir() and entry.name.lower() in excluded_dirs:
                notify(f"  SKIP (excluded dir): {entry.name}")
            continue

        result.scanned += 1
        ext = entry.suffix.lower()
        name = entry.name

        # Skip .lnk shortcuts explicitly
        if ext == ".lnk":
            result.skipped += 1
            result.add("SKIP", entry, "shortcut (.lnk)")
            notify(f"  SKIP (shortcut)    : {name}")
            continue

        # Skip ignored extensions
        if ext in ignored_exts:
            result.skipped += 1
            result.add("SKIP", entry, f"ignored extension ({ext})")
            notify(f"  SKIP (ignored ext) : {name}")
            continue

        # Skip hidden/system files
        if is_hidden_or_system(entry):
            result.skipped += 1
            result.add("SKIP", entry, "hidden/system file")
            notify(f"  SKIP (hidden/sys)  : {name}")
            continue

        # Skip non-recent files
        if not is_recent(entry, hours):
            result.skipped += 1
            result.add("SKIP", entry, f"not recent (>{hours}h)")
            notify(f"  SKIP (not recent)  : {name}")
            continue

        # Classify and move
        subfolder_name = classify_file(entry, type_groups)
        dest_dir = backup_folder / subfolder_name

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        dest_file = dest_dir / name

        # Handle name collisions at destination
        if dest_file.exists() and not dry_run:
            stem = entry.stem
            suffix = entry.suffix
            counter = 1
            while dest_file.exists():
                dest_file = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        if dry_run:
            result.moved += 1
            result.add("DRY-RUN", entry, str(dest_file))
            notify(f"  [DRY RUN] Would move: {name}  →  {dest_dir.name}/")
        else:
            try:
                shutil.move(str(entry), str(dest_file))
                result.moved += 1
                result.add("MOVED", entry, str(dest_file))
                notify(f"  MOVED: {name}  →  {subfolder_name}/")
                logger.info(f"MOVED: {entry}  →  {dest_file}")
            except PermissionError:
                result.errors += 1
                result.skipped += 1
                result.add("ERROR", entry, "PermissionError (file in use?)")
                logger.warning(f"  ERROR (permission): {name}")
            except OSError as e:
                result.errors += 1
                result.skipped += 1
                result.add("ERROR", entry, str(e))
                logger.warning(f"  ERROR: {name} — {e}")

    notify(result.summary())
    return result, backup_folder


# ─────────────────────────────────────────────────────────────────────────────
# TKINTER GUI
# ─────────────────────────────────────────────────────────────────────────────

def launch_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox, scrolledtext
    except ImportError:
        print("Tkinter is not available. Falling back to CLI mode.")
        run_cli()
        return

    cfg = load_config()

    # ── Color palette ────────────────────────────────────────────────────────
    BG       = "#1e1e2e"
    SURFACE  = "#2a2a3d"
    ACCENT   = "#7c3aed"
    ACCENT2  = "#a855f7"
    TEXT     = "#e2e8f0"
    MUTED    = "#94a3b8"
    SUCCESS  = "#22c55e"
    WARNING  = "#f59e0b"
    ERROR    = "#ef4444"
    ENTRY_BG = "#13131f"

    root = tk.Tk()
    root.title("🗂 Desktop Backup Tool")
    root.configure(bg=BG)
    root.resizable(True, True)
    root.minsize(680, 680)

    # ── Center on screen ─────────────────────────────────────────────────────
    root.update_idletasks()
    w, h = 760, 760
    x = (root.winfo_screenwidth()  - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    # ── Fonts ────────────────────────────────────────────────────────────────
    FONT_H    = ("Segoe UI", 15, "bold")
    FONT_SUB  = ("Segoe UI", 11, "bold")
    FONT_BODY = ("Segoe UI", 10)
    FONT_MONO = ("Consolas", 9)

    # ── Helpers ──────────────────────────────────────────────────────────────
    def styled_label(parent, text, font=FONT_BODY, fg=TEXT, bg=BG, **kwargs):
    	return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **kwargs)

    def styled_entry(parent, textvariable, width=12):
        e = tk.Entry(parent, textvariable=textvariable, font=FONT_BODY,
                     bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT,
                     relief="flat", bd=0, width=width,
                     highlightthickness=1, highlightbackground=ACCENT,
                     highlightcolor=ACCENT2)
        return e

    def styled_button(parent, text, command, color=ACCENT, fg=TEXT, **kwargs):
        btn = tk.Button(
            parent, text=text, command=command,
            bg=color, fg=fg, font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, cursor="hand2",
            activebackground=ACCENT2, activeforeground=TEXT,
            padx=14, pady=8, **kwargs
        )
        return btn

    def section_frame(parent, title):
        outer = tk.Frame(parent, bg=SURFACE, padx=14, pady=10)
        outer.pack(fill="x", padx=18, pady=(0, 12))
        tk.Label(outer, text=title, font=FONT_SUB, fg=ACCENT2, bg=SURFACE).pack(anchor="w")
        tk.Frame(outer, height=1, bg=ACCENT).pack(fill="x", pady=(2, 8))
        return outer

    # ── Variables ────────────────────────────────────────────────────────────
    var_drive      = tk.StringVar(value=cfg.get("destination_drive", "D"))
    var_hours      = tk.StringVar(value=str(cfg.get("time_window_hours", 24)))
    var_dry_run    = tk.BooleanVar(value=cfg.get("dry_run", False))
    var_logging    = tk.BooleanVar(value=cfg.get("logging_enabled", True))
    var_excluded   = tk.StringVar(value=", ".join(cfg.get("excluded_folders", [])))
    var_ignored    = tk.StringVar(value=", ".join(cfg.get("ignored_extensions", [])))

    # ── Build UI ─────────────────────────────────────────────────────────────
    # Header
    header = tk.Frame(root, bg=ACCENT, pady=14)
    header.pack(fill="x")
    tk.Label(header, text="🗂  Desktop Backup Tool",
             font=FONT_H, fg=TEXT, bg=ACCENT).pack()
    tk.Label(header, text="Organize recent files from your Desktop into a structured backup",
             font=FONT_BODY, fg="#d8b4fe", bg=ACCENT).pack()

    canvas   = tk.Canvas(root, bg=BG, highlightthickness=0)
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    content  = tk.Frame(canvas, bg=BG)
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")

    def on_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfig(canvas_window, width=canvas.winfo_width())

    content.bind("<Configure>", on_configure)
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))

    # Mouse wheel scroll
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    # ── Desktop Path Preview ─────────────────────────────────────────────────
    sf_desktop = section_frame(content, "📂  Desktop Location")
    try:
        desktop_path = get_desktop_path()
        desktop_text = str(desktop_path)
        desktop_color = SUCCESS
    except FileNotFoundError:
        desktop_text = "Could not detect Desktop path"
        desktop_color = ERROR
    tk.Label(sf_desktop, text=desktop_text, font=FONT_MONO,
             fg=desktop_color, bg=SURFACE, wraplength=640, justify="left").pack(anchor="w")

    # ── Destination ──────────────────────────────────────────────────────────
    sf_dest = section_frame(content, "💾  Destination Drive")
    row_dest = tk.Frame(sf_dest, bg=SURFACE)
    row_dest.pack(fill="x")
    styled_label(row_dest, "Drive letter:", bg=SURFACE).pack(side="left")
    e_drive = styled_entry(row_dest, var_drive, width=4)
    e_drive.pack(side="left", padx=(8, 4))
    styled_label(row_dest, ":\\   (e.g. D, E, F)", fg=MUTED, bg=SURFACE).pack(side="left")

    # ── Time Window ──────────────────────────────────────────────────────────
    sf_time = section_frame(content, "⏱  Time Window")
    row_time = tk.Frame(sf_time, bg=SURFACE)
    row_time.pack(fill="x")
    styled_label(row_time, "Move files modified/created within the last", bg=SURFACE).pack(side="left")
    e_hours = styled_entry(row_time, var_hours, width=5)
    e_hours.pack(side="left", padx=8)
    styled_label(row_time, "hour(s)", bg=SURFACE).pack(side="left")

    # ── Options ──────────────────────────────────────────────────────────────
    sf_opts = section_frame(content, "⚙️  Options")

    def make_check(parent, text, variable, desc=""):
        frm = tk.Frame(parent, bg=SURFACE)
        frm.pack(fill="x", pady=2)
        cb = tk.Checkbutton(frm, text=text, variable=variable,
                            bg=SURFACE, fg=TEXT, selectcolor=ENTRY_BG,
                            activebackground=SURFACE, activeforeground=TEXT,
                            font=FONT_BODY, cursor="hand2")
        cb.pack(side="left")
        if desc:
            tk.Label(frm, text=f"  {desc}", fg=MUTED, bg=SURFACE, font=("Segoe UI", 9)).pack(side="left")

    make_check(sf_opts, "Dry Run Mode",   var_dry_run, "— Preview only, no files will be moved")
    make_check(sf_opts, "Enable Logging", var_logging,  "— Write backup_log.txt alongside this script")

    # ── Excluded Folders ─────────────────────────────────────────────────────
    sf_excl = section_frame(content, "🚫  Excluded Folders")
    styled_label(sf_excl, "Comma-separated folder names to exclude:", fg=MUTED, bg=SURFACE).pack(anchor="w")
    e_excl = tk.Entry(sf_excl, textvariable=var_excluded, font=FONT_BODY,
                      bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
                      highlightthickness=1, highlightbackground=ACCENT, highlightcolor=ACCENT2)
    e_excl.pack(fill="x", pady=(4, 0))

    # ── Ignored Extensions ───────────────────────────────────────────────────
    sf_ign = section_frame(content, "📄  Ignored Extensions")
    styled_label(sf_ign, "Comma-separated extensions to skip (e.g. .tmp, .log):", fg=MUTED, bg=SURFACE).pack(anchor="w")
    e_ign = tk.Entry(sf_ign, textvariable=var_ignored, font=FONT_BODY,
                     bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
                     highlightthickness=1, highlightbackground=ACCENT, highlightcolor=ACCENT2)
    e_ign.pack(fill="x", pady=(4, 0))

    # ── File Type Groups ─────────────────────────────────────────────────────
    sf_groups = section_frame(content, "🗃  File Type Groups")
    styled_label(sf_groups, "Customize which extensions map to which subfolder:", fg=MUTED, bg=SURFACE).pack(anchor="w")

    group_vars = {}
    for group_name, exts in cfg.get("file_type_groups", {}).items():
        row = tk.Frame(sf_groups, bg=SURFACE)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=f"{group_name:<12}", font=("Consolas", 10, "bold"),
                 fg=ACCENT2, bg=SURFACE, width=12, anchor="w").pack(side="left")
        var = tk.StringVar(value=", ".join(exts))
        group_vars[group_name] = var
        e = tk.Entry(row, textvariable=var, font=FONT_MONO,
                     bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
                     highlightthickness=1, highlightbackground=ACCENT, highlightcolor=ACCENT2)
        e.pack(side="left", fill="x", expand=True, padx=(8, 0))

    # ── Log Output ───────────────────────────────────────────────────────────
    sf_log = section_frame(content, "📋  Output Log")
    log_box = scrolledtext.ScrolledText(
        sf_log, height=12, font=FONT_MONO,
        bg=ENTRY_BG, fg=TEXT, insertbackground=TEXT,
        relief="flat", state="disabled", wrap="word"
    )
    log_box.pack(fill="both", expand=True)

    def log_append(msg: str):
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        root.update_idletasks()

    # ── Action Buttons ───────────────────────────────────────────────────────
    btn_row = tk.Frame(content, bg=BG)
    btn_row.pack(pady=16)

    def collect_config_from_ui() -> dict | None:
        drive_val = var_drive.get().strip().upper()
        if not drive_val or len(drive_val) != 1 or not drive_val.isalpha():
            messagebox.showerror("Invalid Drive", "Please enter a single drive letter (e.g. D).")
            return None
        try:
            hours_val = int(var_hours.get().strip())
            if hours_val <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Hours", "Time window must be a positive integer.")
            return None

        excl = [x.strip() for x in var_excluded.get().split(",") if x.strip()]
        ign  = [x.strip() for x in var_ignored.get().split(",") if x.strip()]

        rebuilt_groups = {}
        for g, var in group_vars.items():
            rebuilt_groups[g] = [x.strip() for x in var.get().split(",") if x.strip()]

        return {
            "destination_drive":  drive_val,
            "time_window_hours":  hours_val,
            "dry_run":            var_dry_run.get(),
            "logging_enabled":    var_logging.get(),
            "excluded_folders":   excl,
            "ignored_extensions": ign,
            "file_type_groups":   rebuilt_groups,
        }

    def on_run():
        new_cfg = collect_config_from_ui()
        if new_cfg is None:
            return
        save_config(new_cfg)
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")

        btn_run.configure(state="disabled", text="⏳ Running…")
        root.update_idletasks()

        try:
            result, folder = run_backup(new_cfg, progress_callback=log_append)
            color = WARNING if new_cfg["dry_run"] else SUCCESS
            log_append(f"\n✅ Done!  Backup folder: {folder}")
            if not new_cfg["dry_run"]:
                messagebox.showinfo(
                    "Backup Complete",
                    f"✅ Backup finished!\n\n"
                    f"📁 Folder : {folder}\n"
                    f"📦 Moved  : {result.moved}\n"
                    f"⏭ Skipped : {result.skipped}\n"
                    f"❌ Errors  : {result.errors}"
                )
            else:
                messagebox.showinfo(
                    "Dry Run Complete",
                    f"🔍 Dry run finished — no files were moved.\n\n"
                    f"📦 Would move : {result.moved}\n"
                    f"⏭ Would skip  : {result.skipped}"
                )
        except Exception as e:
            log_append(f"CRITICAL ERROR: {e}")
            messagebox.showerror("Error", str(e))
        finally:
            btn_run.configure(state="normal", text="▶  Run Backup")

    def on_save():
        new_cfg = collect_config_from_ui()
        if new_cfg:
            save_config(new_cfg)
            messagebox.showinfo("Saved", "Configuration saved to config.json ✅")

    def on_open_log():
        if LOG_PATH.exists():
            os.startfile(str(LOG_PATH))
        else:
            messagebox.showinfo("No Log", "No log file found yet. Run a backup first.")

    btn_run  = styled_button(btn_row, "▶  Run Backup",    on_run,     color=ACCENT)
    btn_save = styled_button(btn_row, "💾  Save Config",  on_save,    color="#0f766e")
    btn_log  = styled_button(btn_row, "📄  Open Log",     on_open_log, color="#1e40af")



    btn_run .pack(side="left", padx=6)
    btn_save.pack(side="left", padx=6)
    btn_log .pack(side="left", padx=6)

    # Footer
    tk.Label(content, text=f"Config: {CONFIG_PATH}  |  Log: {LOG_PATH}",
             font=("Segoe UI", 8), fg=MUTED, bg=BG).pack(pady=(0, 10))

    root.mainloop()


# ─────────────────────────────────────────────────────────────────────────────
# CLI MODE
# ─────────────────────────────────────────────────────────────────────────────

def run_cli():
    print("\n" + "═" * 55)
    print("  🗂  Desktop Backup Tool  —  CLI Mode")
    print("═" * 55)

    cfg = load_config()

    try:
        desktop = get_desktop_path()
        print(f"\n  Desktop: {desktop}")
    except FileNotFoundError as e:
        print(f"\n  ❌ {e}")
        return

    # Drive
    default_drive = cfg.get("destination_drive") or "D"
    drive = input(f"\n  Destination drive letter [{default_drive}]: ").strip().upper() or default_drive
    cfg["destination_drive"] = drive

    # Time window
    default_hours = cfg.get("time_window_hours", 24)
    hours_input = input(f"  Time window in hours [{default_hours}]: ").strip()
    cfg["time_window_hours"] = int(hours_input) if hours_input.isdigit() else default_hours

    # Dry run
    dry = input("  Enable dry-run? (y/N): ").strip().lower()
    cfg["dry_run"] = dry == "y"

    # Save updated config
    save_config(cfg)

    print("\n" + "─" * 55)
    result, folder = run_backup(cfg)
    print(f"\n  Backup folder: {folder}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Desktop Backup Tool")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode instead of GUI")
    args = parser.parse_args()

    if args.cli:
        run_cli()
    else:
        launch_gui()
