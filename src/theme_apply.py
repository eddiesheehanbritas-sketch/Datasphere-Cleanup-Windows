"""
theme_apply.py
==============
SAP Datasphere Cleanup Tool — PyQt5 theme helper.

Usage
-----
    from theme_apply import apply_theme, set_nav_active, set_status, write_inline_icons

    app = QApplication(sys.argv)

    # 1. Write the small inline UI icons into your icons/ directory
    #    (only needed once, before compiling resources.qrc → resources_rc.py)
    write_inline_icons("icons")

    # 2. Import compiled resources (must be BEFORE apply_theme)
    import resources_rc  # noqa: F401

    # 3. Load font + stylesheet
    apply_theme(app)

    # 4. During runtime — update nav active state
    set_nav_active(btn_auth_widget, True)
    set_nav_active(btn_pipeline_widget, False)

    # 5. Update a status chip / dot
    set_status(chip_label, "running")   # "idle" | "running" | "success" | "error"
    set_status(dot_label,  "success")

    # 6. Append to log output with colour coding
    log = LogOutput(plain_text_edit_widget)
    log.info("Space cleanup started.")
    log.success("3 spaces removed.")
    log.warning("1 space skipped — owner still active.")
    log.error("API call failed: timeout.")

SAP logo
--------
Load in your TopBar __init__:

    from PyQt5.QtSvg import QSvgWidget
    logo = QSvgWidget(":/logo/sap_logo.svg", parent=top_bar)
    # SAP logo native ratio is 412.4 × 204  (~2.02 : 1)
    target_h = 24
    target_w = round(target_h * 412.4 / 204)   # → 48 px
    logo.setFixedSize(target_w, target_h)

Spacing constants
-----------------
All pixel values that cannot be expressed in QSS are collected here
so you can reference them from Python layout code.
"""

from __future__ import annotations

import os
import pathlib
import sys
import textwrap

from PyQt5.QtCore import QFile, QIODevice, Qt
from PyQt5.QtGui import QFont, QFontDatabase, QColor
from PyQt5.QtWidgets import QApplication, QWidget, QLabel


# ──────────────────────────────────────────────────────────────
#  SPACING CONSTANTS  (px)
# ──────────────────────────────────────────────────────────────

class Spacing:
    """Centralised px values — use in Python layout/margin calls."""
    PAGE_PADDING          = 24   # QScrollArea content widget margins (all sides)
    BETWEEN_CARDS         = 16   # vertical gap between Card frames in layout
    CARD_PADDING          = 16   # QFrame("Card") layout margins (all sides)
    CARD_ROW_SPACING      = 12   # spacing between rows inside a card (QVBoxLayout)
    SECTION_HEADER_TOP    = 24   # spacer above SectionHeader labels
    SECTION_HEADER_BOTTOM =  8   # spacer below SectionHeader labels
    FORM_ROW_SPACING      = 12   # QFormLayout row spacing
    FORM_LABEL_WIDTH      = 160  # fixed min-width for form label column (px)
    SIDEBAR_WIDTH         = 280
    TOP_BAR_HEIGHT        =  56
    LOG_PANEL_HEADER_H    =  28
    LOG_PANEL_DEFAULT_H   = 220  # initial height of QSplitter lower pane
    BUTTON_HEIGHT         =  36
    INPUT_HEIGHT          =  36
    ICON_SIZE_NAV         =  20  # px for sidebar nav icons (render at 20×20)
    DIVIDER_THICKNESS     =   1


# ──────────────────────────────────────────────────────────────
#  COLOUR TOKENS  (hex strings)
# ──────────────────────────────────────────────────────────────

class Colors:
    # Brand
    PRIMARY              = "#0A6ED1"
    PRIMARY_HOVER        = "#0854A0"
    PRIMARY_PRESSED      = "#074B8A"
    PRIMARY_DISABLED_BG  = "#D1E4F6"
    PRIMARY_DISABLED_FG  = "#9AA7B7"

    # Semantic
    SUCCESS              = "#107E3E"
    ERROR                = "#BB0000"
    WARNING              = "#E9730C"

    # Text
    TEXT_PRIMARY         = "#32363A"
    TEXT_SECONDARY       = "#6A6D70"
    TEXT_MUTED           = "#9AA3A8"
    TEXT_DISABLED        = "#9AA3A8"
    TEXT_HEADING         = "#0B1F32"
    TEXT_LINK            = "#0A6ED1"

    # Surfaces
    BG_APP               = "#F5F6F7"
    BG_CARD              = "#FFFFFF"
    BG_SIDEBAR           = "#FFFFFF"
    BG_TOPBAR            = "#FFFFFF"
    BG_LOG               = "#0E223A"

    # Borders / dividers
    BORDER_CARD          = "#E5E5E5"
    BORDER_INPUT_REST    = "#CED2D9"
    BORDER_INPUT_HOVER   = "#ACB4BE"
    BORDER_INPUT_FOCUS   = "#0A6ED1"
    DIVIDER              = "#E5E5E5"

    # Status chip tints
    CHIP_IDLE_BG         = "#F0F2F4"
    CHIP_RUNNING_BG      = "#EAF2FB"
    CHIP_SUCCESS_BG      = "#E4F2E9"
    CHIP_ERROR_BG        = "#F8E1E1"

    # Status dots
    DOT_IDLE             = "#9AA3A8"
    DOT_RUNNING          = "#0A6ED1"
    DOT_SUCCESS          = "#107E3E"
    DOT_ERROR            = "#BB0000"

    # Log text accents
    LOG_DEFAULT          = "#EAF2FB"
    LOG_INFO             = "#B3D3F6"
    LOG_SUCCESS          = "#8FD3A6"
    LOG_WARNING          = "#F9C97D"
    LOG_ERROR            = "#FFB3B3"
    LOG_TIMESTAMP        = "#B3C0CC"


# ──────────────────────────────────────────────────────────────
#  INLINE SVG ICONS
#  Small utility icons generated on demand — not from brand lib.
# ──────────────────────────────────────────────────────────────

INLINE_ICONS: dict[str, str] = {
    # 16×16 white checkmark on transparent background
    "check_white.svg": textwrap.dedent("""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
          <polyline points="2,8 6,13 14,4" fill="none" stroke="#FFFFFF"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    """),

    # 16×16 white horizontal dash (indeterminate checkbox)
    "check_indeterminate_white.svg": textwrap.dedent("""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
          <line x1="3" y1="8" x2="13" y2="8" stroke="#FFFFFF"
                stroke-width="2" stroke-linecap="round"/>
        </svg>
    """),

    # 16×16 radio-checked — white filled 8px dot centred, no background
    "radio_checked.svg": textwrap.dedent("""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
          <circle cx="8" cy="8" r="4" fill="#0A6ED1"/>
        </svg>
    """),

    # 16×16 chevron down (SAP blue)
    "chevron_down.svg": textwrap.dedent("""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
          <polyline points="3,5 8,11 13,5" fill="none" stroke="#0A6ED1"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    """),

    # 16×16 chevron down (grey — disabled)
    "chevron_down_grey.svg": textwrap.dedent("""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
          <polyline points="3,5 8,11 13,5" fill="none" stroke="#9AA3A8"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    """),

    # 16×16 chevron up (SAP blue)
    "chevron_up.svg": textwrap.dedent("""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
          <polyline points="3,11 8,5 13,11" fill="none" stroke="#0A6ED1"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    """),

    # 16×16 chevron up (grey)
    "chevron_up_grey.svg": textwrap.dedent("""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">
          <polyline points="3,11 8,5 13,11" fill="none" stroke="#9AA3A8"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    """),
}


def write_inline_icons(icon_dir: str = "icons") -> None:
    """
    Write the small utility SVG icons into icon_dir.
    Call this once before compiling resources.qrc → resources_rc.py.

        from theme_apply import write_inline_icons
        write_inline_icons("icons")
    """
    out = pathlib.Path(icon_dir)
    out.mkdir(parents=True, exist_ok=True)
    for filename, svg_src in INLINE_ICONS.items():
        dest = out / filename
        dest.write_text(svg_src, encoding="utf-8")
        print(f"  Wrote: {dest}")
    print(f"Inline icons written to {out.resolve()}")


# ──────────────────────────────────────────────────────────────
#  FONT LOADING
# ──────────────────────────────────────────────────────────────

def _load_72_font() -> str:
    """
    Attempt to load the '72' / 'SAP 72' / '72 Brand' font family.

    On macOS with the SAP 72 family installed system-wide, Qt detects
    it automatically as family name "72".  If not installed, returns
    the Arial fallback family name so the app remains functional.
    """
    db = QFontDatabase()
    available = db.families()

    for candidate in ("72", "SAP 72", "72 Brand", "72 Brand Text"):
        if candidate in available:
            return candidate

    # Attempt to load from bundled font directories if present.
    font_dirs = []
    if getattr(sys, "_MEIPASS", None):
        font_dirs.append(pathlib.Path(sys._MEIPASS) / "assets" / "fonts")
    here = pathlib.Path(__file__).resolve().parent
    font_dirs.append(here.parent / "assets" / "fonts")
    font_dirs.append(here / "fonts")
    for fonts_dir in font_dirs:
        if fonts_dir.exists():
            for ext in ("*.ttf", "*.otf"):
                for fpath in fonts_dir.glob(ext):
                    fid = QFontDatabase.addApplicationFont(str(fpath))
                    if fid >= 0:
                        loaded = QFontDatabase.applicationFontFamilies(fid)
                        if loaded and loaded[0] in ("72", "72 Brand"):
                            return loaded[0]
    # Re-check after loading
    for candidate in ("72", "72 Brand"):
        if candidate in QFontDatabase().families():
            return candidate

    print(
        "[theme_apply] WARNING: SAP 72 font not found. "
        "Falling back to Arial. Install the '72' font family for correct rendering."
    )
    return "Arial"


# ──────────────────────────────────────────────────────────────
#  MAIN APPLY FUNCTION
# ──────────────────────────────────────────────────────────────

def apply_theme(app: QApplication, qss_path: str | None = None) -> None:
    """
    Load and apply the Datasphere QSS theme to the QApplication.

    Parameters
    ----------
    app       : QApplication instance (must exist before calling)
    qss_path  : Optional explicit path to datasphere_theme.qss.
                Defaults to the file sitting next to this module.
    """
    # 1. Font
    family = _load_72_font()
    default_font = QFont(family, 14)
    default_font.setWeight(QFont.Normal)
    app.setFont(default_font)

    # 2. QSS
    if qss_path is None:
        # Look in several candidate locations: bundled (_MEIPASS/theme),
        # project theme/ dir (dev), or next to this module.
        candidates = []
        if getattr(sys, "_MEIPASS", None):
            candidates.append(pathlib.Path(sys._MEIPASS) / "theme" / "datasphere_theme.qss")
        here = pathlib.Path(__file__).resolve().parent
        candidates.append(here.parent / "theme" / "datasphere_theme.qss")
        candidates.append(here / "datasphere_theme.qss")
        for c in candidates:
            if c.exists():
                qss_path = str(c)
                break
        else:
            qss_path = str(candidates[-1])

    if not os.path.exists(qss_path):
        raise FileNotFoundError(
            f"QSS file not found: {qss_path}\n"
            "Ensure datasphere_theme.qss is in the same directory as theme_apply.py."
        )

    with open(qss_path, "r", encoding="utf-8") as f:
        stylesheet = f.read()

    # Substitute font family placeholder so it matches the installed font name
    stylesheet = stylesheet.replace('"72"', f'"{family}"')
    stylesheet = stylesheet.replace('"SAP 72"', f'"{family}"')

    app.setStyleSheet(stylesheet)
    print(f"[theme_apply] Theme applied (font: '{family}').")


# ──────────────────────────────────────────────────────────────
#  RUNTIME HELPERS
# ──────────────────────────────────────────────────────────────

def set_nav_active(widget: QWidget, active: bool) -> None:
    """
    Toggle the active state on a sidebar nav item widget.
    Forces Qt to re-evaluate the [active="true"] QSS rule.

    Example
    -------
        set_nav_active(self.btn_auth, True)
        set_nav_active(self.btn_pipeline, False)
        set_nav_active(self.btn_workshop, False)
    """
    widget.setProperty("active", active)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


_STATUS_STATES = frozenset({"idle", "running", "success", "error"})


def set_status(widget: QWidget, state: str) -> None:
    """
    Set the 'state' dynamic property on a StatusChip or StatusDot QLabel.
    Triggers QSS re-evaluation for colour-coded rendering.

    Parameters
    ----------
    widget : A QLabel with objectName "StatusChip" or "StatusDot"
    state  : One of "idle" | "running" | "success" | "error"

    Example
    -------
        set_status(self.status_chip, "running")
        set_status(self.status_dot, "running")
    """
    if state not in _STATUS_STATES:
        raise ValueError(f"state must be one of {_STATUS_STATES}, got {state!r}")
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# ──────────────────────────────────────────────────────────────
#  LOG OUTPUT HELPER
# ──────────────────────────────────────────────────────────────

class LogOutput:
    """
    Thin wrapper around a QPlainTextEdit / QTextEdit for the log panel.
    Inserts HTML-coloured lines using the Datasphere dark-panel palette.

    Example
    -------
        self.log = LogOutput(self.plain_text_edit)
        self.log.info("Space scan started.")
        self.log.success("Deleted: DS_Academy_Trial_1234")
        self.log.warning("Skipping space — expiry unclear.")
        self.log.error("API error: 403 Forbidden")
        self.log.raw("Raw monospace text line.")
    """

    # Map level → hex colour (from Colors)
    _PALETTE = {
        "info":      Colors.LOG_INFO,
        "success":   Colors.LOG_SUCCESS,
        "warning":   Colors.LOG_WARNING,
        "error":     Colors.LOG_ERROR,
        "timestamp": Colors.LOG_TIMESTAMP,
        "default":   Colors.LOG_DEFAULT,
    }

    def __init__(self, widget) -> None:
        """
        widget : QPlainTextEdit or QTextEdit with objectName "LogOutput"
        """
        self._w = widget
        # Make it read-only so users can select/copy but not edit
        self._w.setReadOnly(True)

    def _append(self, level: str, message: str) -> None:
        import html as html_mod
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        ts_color = self._PALETTE["timestamp"]
        msg_color = self._PALETTE.get(level, self._PALETTE["default"])
        safe_msg = html_mod.escape(message)

        html_line = (
            f'<span style="color:{ts_color};font-size:12px;">[{ts}]</span>'
            f'&nbsp;'
            f'<span style="color:{msg_color};font-size:12px;">{safe_msg}</span>'
        )
        self._w.appendHtml(html_line)
        # Auto-scroll to bottom
        sb = self._w.verticalScrollBar()
        sb.setValue(sb.maximum())

    def info(self, message: str) -> None:
        """Informational line — light blue."""
        self._append("info", message)

    def success(self, message: str) -> None:
        """Success line — green."""
        self._append("success", message)

    def warning(self, message: str) -> None:
        """Warning line — amber/yellow."""
        self._append("warning", message)

    def error(self, message: str) -> None:
        """Error line — red."""
        self._append("error", message)

    def raw(self, message: str) -> None:
        """Plain default-colour line."""
        self._append("default", message)

    def clear(self) -> None:
        """Clear all log content."""
        self._w.clear()


# ──────────────────────────────────────────────────────────────
#  SAP LOGO HELPER
# ──────────────────────────────────────────────────────────────

def make_sap_logo_widget(parent: QWidget, height_px: int = 24):
    """
    Create a QSvgWidget displaying the SAP logo at the correct aspect ratio.

    The SAP logo native dimensions are 412.4 × 204 px (ratio ≈ 2.02:1).
    Width is derived from height to preserve the ratio exactly.

    Parameters
    ----------
    parent    : Parent widget (typically TopBar)
    height_px : Desired rendered height in px (default 24)

    Returns
    -------
    QSvgWidget sized correctly, ready to add to a layout.
    """
    try:
        from PyQt5.QtSvg import QSvgWidget
    except ImportError:
        raise ImportError(
            "PyQt5.QtSvg not available. Install PyQt5 with SVG support: "
            "pip install PyQt5"
        )

    NATIVE_W, NATIVE_H = 412.4, 204.0
    target_w = round(height_px * NATIVE_W / NATIVE_H)

    logo = QSvgWidget(":/logo/sap_logo.svg", parent=parent)
    logo.setFixedSize(target_w, height_px)
    logo.setObjectName("TopBarLogo")
    return logo


# ──────────────────────────────────────────────────────────────
#  EXAMPLE MINIMAL INTEGRATION SNIPPET
# ──────────────────────────────────────────────────────────────
#
#  Copy this into your main.py:
#
#  ┌─────────────────────────────────────────────────────────┐
#  │  import sys                                             │
#  │  from PyQt5.QtWidgets import QApplication               │
#  │                                                         │
#  │  # Write inline icons before first resource compilation │
#  │  from theme_apply import write_inline_icons             │
#  │  write_inline_icons("icons")                            │
#  │                                                         │
#  │  # Compile resources (run once from terminal):          │
#  │  #   pyrcc5 resources.qrc -o resources_rc.py            │
#  │                                                         │
#  │  import resources_rc  # noqa: F401                      │
#  │                                                         │
#  │  from theme_apply import apply_theme                    │
#  │  from your_app import MainWindow                        │
#  │                                                         │
#  │  app = QApplication(sys.argv)                           │
#  │  apply_theme(app)                                       │
#  │                                                         │
#  │  window = MainWindow()                                  │
#  │  window.show()                                          │
#  │  sys.exit(app.exec_())                                  │
#  └─────────────────────────────────────────────────────────┘
