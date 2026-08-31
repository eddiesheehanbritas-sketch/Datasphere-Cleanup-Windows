import sys
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path


def load_fonts():
    """Load bundled SAP 72 fonts into Qt's font database."""
    from PyQt5.QtGui import QFontDatabase
    # When frozen (PyInstaller), fonts are in _MEIPASS/assets/fonts/
    # When running from source, they are in the project root's assets/fonts/
    if getattr(sys, "_MEIPASS", None):
        fonts_dir = Path(sys._MEIPASS) / "assets" / "fonts"
    else:
        fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    if fonts_dir.exists():
        for f in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(f))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFrame, QMessageBox, QSizePolicy, QDialog,
    QCheckBox, QInputDialog, QSpinBox, QStackedWidget, QScrollArea, QLineEdit,
    QListWidget, QListWidgetItem,
    QRadioButton, QButtonGroup,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject

# ── Colour palette ─────────────────────────────────────────────────────────────
# SAP Horizon light theme: white canvas, #1873B4 brand blue, subdued greys
_C_WHITE       = "#FFFFFF"
_C_BG          = "#F5F6F7"
_C_SIDEBAR     = "#FFFFFF"
_C_SIDEBAR2    = "#F5F9FE"
_C_TOPBAR      = "#FFFFFF"
_C_CARD        = "#FFFFFF"
_C_CARD_BORDER = "#E5E5E5"
_C_PANEL_HDR   = "#FFFFFF"
_C_TEXT        = "#32363A"
_C_TEXT_DIM    = "#6A6D70"
_C_TEXT_MUTED  = "#9AA3A8"
_C_TEXT_WHITE  = "#FFFFFF"
_C_TEXT_SIDEBAR= "#32363A"
_C_BLUE        = "#0A6ED1"
_C_BLUE_HOVER  = "#0854A0"
_C_BLUE_DIS    = "#D1E4F6"
_C_RED         = "#BB0000"
_C_RED_HOVER   = "#930000"
_C_RED_DIS     = "#F3D1D1"
_C_GREEN       = "#107E3E"
_C_GREEN_HOVER = "#0E6B35"
_C_GREEN_DIS   = "#CFE9DA"
_C_ORANGE      = "#E9730C"
_C_ORANGE_HOVER= "#C8620A"
_C_ORANGE_DIS  = "#F9E3D3"
_C_NAV_ACTIVE  = "#EAF2FB"
_C_NAV_HOVER   = "#F5F9FE"

BUTTON_STYLES = {
    "blue":   {"bg": "#0A6ED1", "hover": "#0854A0", "dis": "#D1E4F6", "dis_text": "#9AA7B7"},
    "red":    {"bg": "#BB0000", "hover": "#930000", "dis": "#F3D1D1", "dis_text": "#B8C2CC"},
    "green":  {"bg": "#107E3E", "hover": "#0E6B35", "dis": "#CFE9DA", "dis_text": "#7B8D86"},
    "orange": {"bg": "#E9730C", "hover": "#C8620A", "dis": "#F9E3D3", "dis_text": "#9A8C7F"},
}

def _btn_style(colour: str) -> str:
    c = BUTTON_STYLES[colour]
    return (
        f"QPushButton {{ background-color: {c['bg']}; color: #FFFFFF; "
        f"font-family: '72', '72 Brand', 'Helvetica Neue', Arial, sans-serif; "
        f"font-size: 14px; font-weight: 600; border: none; border-radius: 6px; "
        f"padding: 0 12px; min-height: 36px; }}"
        f"QPushButton:hover {{ background-color: {c['hover']}; color: #FFFFFF; }}"
        f"QPushButton:disabled {{ background-color: {c['dis']}; color: {c['dis_text']}; }}"
    )

STYLESHEET = f"""
/* ── Global ── */
QMainWindow, QWidget#central {{
    background-color: {_C_BG};
    font-family: '72', '72 Brand', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    color: {_C_TEXT};
}}

/* ── Top bar (Blue Shell) ── */
QWidget#topbar {{
    background-color: #0A6ED1;
    min-height: 56px;
}}
QLabel#app_title {{
    color: #FFFFFF;
    font-size: 20px;
    font-weight: 700;
}}
QLabel#app_subtitle {{
    color: rgba(255,255,255,0.85);
    font-size: 12px;
    font-weight: 400;
}}

/* ── Sidebar ── */
QWidget#sidebar {{
    background-color: #FFFFFF;
    border-right: 1px solid #E5E5E5;
    min-width: 220px;
    max-width: 220px;
}}
QPushButton#nav {{
    background-color: transparent;
    color: {_C_TEXT_DIM};
    font-family: '72', '72 Brand', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    font-weight: 400;
    text-align: left;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    padding: 0 16px;
    min-height: 40px;
}}
QPushButton#nav:hover {{
    background-color: #F5F9FE;
    color: {_C_TEXT};
}}
QPushButton#nav_active {{
    background-color: #EAF2FB;
    color: {_C_TEXT};
    font-family: '72', '72 Brand', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    font-weight: 500;
    text-align: left;
    border: none;
    border-left: 3px solid #0A6ED1;
    border-radius: 0px;
    padding: 0 16px;
    min-height: 40px;
}}

/* ── Main panel ── */
QWidget#panel {{
    background-color: {_C_BG};
}}
QWidget#panel_hdr {{
    background-color: #FFFFFF;
    border-bottom: 1px solid #E5E5E5;
    padding: 0 24px;
    min-height: 64px;
}}
QLabel#panel_title {{
    color: #0B1F32;
    font-size: 20px;
    font-weight: 700;
}}
QLabel#panel_subtitle {{
    color: {_C_TEXT_DIM};
    font-size: 12px;
    font-weight: 400;
}}
QLabel#section {{
    color: #0B1F32;
    font-size: 16px;
    font-weight: 600;
    margin-top: 24px;
    margin-bottom: 8px;
}}
QLabel#desc {{
    color: {_C_TEXT_DIM};
    font-size: 13px;
    line-height: 1.5;
}}
QWidget#card {{
    background-color: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 8px;
}}

/* ── Status bar ── */
QWidget#statusbar {{
    background-color: #FFFFFF;
    border-top: 1px solid #E5E5E5;
    min-height: 44px;
}}
QLabel#status {{
    color: {_C_TEXT};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#summary {{
    color: {_C_TEXT_DIM};
    font-size: 13px;
    background-color: transparent;
}}

/* ── Buttons ── */
QPushButton {{
    font-family: '72', '72 Brand', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    font-weight: 600;
    border: none;
    border-radius: 6px;
    padding: 0 16px;
    min-height: 36px;
    color: #FFFFFF;
}}
QPushButton#blue {{
    background-color: #0A6ED1;
    color: #FFFFFF;
}}
QPushButton#blue:hover    {{ background-color: #0854A0; }}
QPushButton#blue:pressed  {{ background-color: #074B8A; }}
QPushButton#blue:disabled {{ background-color: #D1E4F6; color: #9AA7B7; }}

QPushButton#red {{
    background-color: #BB0000;
    color: #FFFFFF;
}}
QPushButton#red:hover    {{ background-color: #930000; }}
QPushButton#red:pressed  {{ background-color: #7B0000; }}
QPushButton#red:disabled {{ background-color: #F3D1D1; color: #B8C2CC; }}

QPushButton#green {{
    background-color: #107E3E;
    color: #FFFFFF;
}}
QPushButton#green:hover    {{ background-color: #0E6B35; }}
QPushButton#green:pressed  {{ background-color: #0C5C2E; }}
QPushButton#green:disabled {{ background-color: #CFE9DA; color: #7B8D86; }}

QPushButton#orange {{
    background-color: #E9730C;
    color: #FFFFFF;
}}
QPushButton#orange:hover    {{ background-color: #C8620A; }}
QPushButton#orange:pressed  {{ background-color: #A75208; }}
QPushButton#orange:disabled {{ background-color: #F9E3D3; color: #9A8C7F; }}

/* ── Inputs ── */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: #FFFFFF;
    border: 1px solid #CED2D9;
    border-radius: 6px;
    min-height: 36px;
    padding: 0 10px;
    color: {_C_TEXT};
    font-size: 14px;
    selection-background-color: #CFE3FA;
    selection-color: #0B1F32;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #ACB4BE; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid #0A6ED1; }}
QLineEdit:disabled, QSpinBox:disabled {{
    background-color: {_C_BG};
    border-color: #E5E5E5;
    color: {_C_TEXT_MUTED};
}}

QComboBox {{
    background-color: #FFFFFF;
    border: 1px solid #CED2D9;
    border-radius: 6px;
    min-height: 36px;
    padding: 0 10px;
    color: {_C_TEXT};
    font-size: 14px;
}}
QComboBox:hover {{ border-color: #ACB4BE; }}
QComboBox:focus {{ border: 1px solid #0A6ED1; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background-color: #FFFFFF;
    color: {_C_TEXT};
    border: 1px solid #E5E5E5;
    selection-background-color: #F5F9FE;
    selection-color: {_C_TEXT};
}}

/* ── Checkboxes ── */
QCheckBox {{ color: {_C_TEXT}; font-size: 14px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #ACB4BE;
    border-radius: 2px;
    background: #FFFFFF;
}}
QCheckBox::indicator:hover {{ border-color: #0A6ED1; }}
QCheckBox::indicator:checked {{ background: #0A6ED1; border-color: #0A6ED1; }}
QCheckBox::indicator:disabled {{ background: {_C_BG}; border-color: #E5E5E5; }}

/* ── Radio buttons ── */
QRadioButton {{ color: {_C_TEXT}; font-size: 14px; spacing: 8px; }}
QRadioButton::indicator {{
    width: 16px; height: 16px;
    border-radius: 8px;
    border: 1px solid #ACB4BE;
    background: #FFFFFF;
}}
QRadioButton::indicator:hover {{ border-color: #0A6ED1; }}
QRadioButton::indicator:checked {{ background-color: #0A6ED1; border-color: #0A6ED1; }}
QRadioButton::indicator:disabled {{ border-color: #E5E5E5; }}

/* ── Log panel header ── */
QLabel#log_header {{
    background-color: #0E223A;
    color: #B3C0CC;
    font-size: 12px;
    font-weight: 600;
    padding: 6px 12px;
    border-top: 1px solid #E5E5E5;
    border-bottom: 1px solid #2A3E59;
}}

/* ── Log output ── */
QTextEdit#log {{
    background-color: #0E223A;
    color: #EAF2FB;
    font-family: "SF Mono", Menlo, Monaco, "Courier New", monospace;
    font-size: 12px;
    border: none;
    border-radius: 0px;
    padding: 12px;
    selection-background-color: #2A3E59;
}}

/* ── Dividers ── */
QFrame#divider {{
    color: #E5E5E5;
    background-color: #E5E5E5;
    max-height: 1px;
}}
QFrame#divider_dark {{
    color: #E5E5E5;
    background-color: #E5E5E5;
    max-width: 1px;
}}

/* ── Scroll ── */
QScrollArea {{ border: none; background-color: {_C_BG}; }}
QScrollBar:vertical {{
    background: {_C_BG}; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #CED2D9; border-radius: 4px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: #ACB4BE; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ── List widgets ── */
QListWidget {{
    background-color: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 6px;
    padding: 4px;
    color: {_C_TEXT};
    font-size: 14px;
}}
QListWidget::item {{ padding: 6px 8px; border: none; color: {_C_TEXT}; }}
QListWidget::item:hover {{ background-color: #F5F9FE; border-radius: 3px; }}
QListWidget::item:selected {{ background-color: #EAF2FB; color: {_C_TEXT}; border-radius: 3px; }}

/* ── Dialogs ── */
QDialog {{
    background-color: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 8px;
}}
"""


class Worker(QObject):
    done_signal  = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        # done_signal MUST fire in every exit path (success or failure) so the GUI
        # re-enables buttons and clears the running state — otherwise a failed run leaves
        # the UI permanently wedged. On failure we surface the FULL traceback (not just
        # str(exc)) so the operator can see where it failed and does not mistake a
        # half-completed run for a clean one. BaseException is caught too so a Ctrl-C /
        # SystemExit during a run cannot skip done_signal and wedge the buttons.
        try:
            self._fn()
            self.done_signal.emit()
        except Exception:
            import traceback
            self.error_signal.emit(traceback.format_exc().rstrip())
            self.done_signal.emit()
        except BaseException:
            import traceback
            self.error_signal.emit("Run interrupted:\n" + traceback.format_exc().rstrip())
            self.done_signal.emit()
            raise


class _GUILogHandler(logging.Handler):
    def __init__(self, app):
        super().__init__()
        self._app = app

    def emit(self, record):
        self._app.log(self.format(record))


class App(QMainWindow):
    _log_signal     = pyqtSignal(str)
    _status_signal  = pyqtSignal(str)
    _summary_signal = pyqtSignal(str)
    _buttons_signal = pyqtSignal(bool)
    _dialog_signal  = pyqtSignal(str, str, object)

    _SECTION_AUTH     = 0
    _SECTION_PIPELINE = 1
    _SECTION_WORKSHOP = 2

    def __init__(self, tenant: str = "eu10"):
        super().__init__()
        self._demo_mode = False
        self._tenant    = tenant
        title = f"Datasphere Cleanup — {tenant.upper()}"
        self.setWindowTitle(title)
        self.resize(980, 740)
        self.setMinimumSize(820, 600)

        self._stage2_report = None
        self._running       = False
        self._thread        = None
        self._workshop_queue = []  # list of workshop ID strings waiting to be scraped
        self._nav_buttons   = []
        self._start_date_from_edit = None  # QLineEdit — set in _build_pipeline_page
        self._start_date_to_edit   = None  # QLineEdit — set in _build_pipeline_page
        self._end_date_from_edit   = None  # QLineEdit — set in _build_pipeline_page
        self._end_date_to_edit     = None  # QLineEdit — set in _build_pipeline_page
        self._workshop_id_from_edit = None  # QLineEdit — set in _build_pipeline_page
        self._workshop_id_to_edit   = None  # QLineEdit — set in _build_pipeline_page

        self._log_signal.connect(self._append_log)
        self._status_signal.connect(lambda m: self.status_lbl.setText(m))
        self._summary_signal.connect(lambda m: self.summary_lbl.setText(m))
        self._buttons_signal.connect(self._set_buttons_enabled)
        self._dialog_signal.connect(self._show_login_dialog)

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Top bar ──────────────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(52)
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 0, 20, 0)
        tb.setSpacing(10)

        title_lbl = QLabel("DATASPHERE CLEANUP")
        title_lbl.setObjectName("app_title")
        sub = f"SAP {self._tenant.upper()}  ·  Space Management Automation"
        sub_lbl = QLabel(sub)
        sub_lbl.setObjectName("app_subtitle")
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(title_lbl)
        col.addWidget(sub_lbl)
        tb.addLayout(col)
        tb.addStretch()

        self._indicator = QLabel("● Idle")
        self._indicator.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        tb.addWidget(self._indicator)
        root.addWidget(topbar)

        # ── Body: sidebar + right pane ────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        root.addLayout(body, stretch=1)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(185)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(10, 18, 10, 18)
        sl.setSpacing(3)

        for label, idx in [
            ("🔐  Authentication", self._SECTION_AUTH),
            ("⚙️  Pipeline",       self._SECTION_PIPELINE),
            ("🏫  Workshop",       self._SECTION_WORKSHOP),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("nav_active" if idx == 0 else "nav")
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _checked, i=idx: self._switch_section(i))
            sl.addWidget(btn)
            self._nav_buttons.append(btn)

        sl.addStretch()
        ver = QLabel(f"{self._tenant.upper()} Tenant")
        ver.setStyleSheet(f"color: {_C_TEXT_MUTED}; font-size: 10px;")
        ver.setAlignment(Qt.AlignCenter)
        sl.addWidget(ver)
        body.addWidget(sidebar)

        # Sidebar border
        sd = QFrame(); sd.setObjectName("divider_dark")
        sd.setFrameShape(QFrame.VLine); sd.setFixedWidth(1)
        body.addWidget(sd)

        # Right pane: stacked pages on top, shared log on bottom
        right = QWidget()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(0)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Stacked pages (controls only — no log box inside)
        self._stack = QStackedWidget()
        self._stack.setObjectName("panel")
        self._stack.addWidget(self._build_auth_page())
        self._stack.addWidget(self._build_pipeline_page())
        self._stack.addWidget(self._build_workshop_page())
        right_layout.addWidget(self._stack, stretch=1)

        # ── Shared log — lives here, always visible ──────────────────────────
        log_hdr_row = QHBoxLayout()
        log_hdr_row.setContentsMargins(20, 8, 20, 4)
        log_sec = QLabel("LOG OUTPUT")
        log_sec.setObjectName("section")
        log_hdr_row.addWidget(log_sec)
        log_hdr_row.addStretch()

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(60)
        btn_clear.setFixedHeight(22)
        btn_clear.setStyleSheet(
            f"QPushButton {{ background-color: {_C_CARD_BORDER}; color: {_C_TEXT_DIM}; "
            f"font-size: 10px; font-weight: normal; border-radius: 4px; padding: 2px 8px; }}"
            f"QPushButton:hover {{ background-color: {_C_BLUE}; color: white; }}"
        )
        btn_clear.clicked.connect(lambda: self.log_box.clear())
        log_hdr_row.addWidget(btn_clear)
        right_layout.addLayout(log_hdr_row)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("log")
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(200)
        self.log_box.setStyleSheet(
            "QTextEdit { background-color: #1e2d3d; color: #d0e8f8; "
            "font-family: Menlo, Monaco, 'Courier New', monospace; "
            "font-size: 11px; border: 1px solid #c0cfe0; border-radius: 5px; padding: 8px; }"
        )
        log_wrap = QWidget()
        log_wrap.setStyleSheet(f"background-color: {_C_BG};")
        lw = QVBoxLayout(log_wrap)
        lw.setContentsMargins(20, 0, 20, 10)
        lw.addWidget(self.log_box)
        right_layout.addWidget(log_wrap)

        body.addWidget(right, stretch=1)

        # ── Status bar ───────────────────────────────────────────────────────
        div2 = QFrame(); div2.setObjectName("divider")
        div2.setFrameShape(QFrame.HLine); div2.setFixedHeight(1)
        root.addWidget(div2)

        statusbar = QWidget()
        statusbar.setObjectName("statusbar")
        statusbar.setFixedHeight(44)
        sb = QHBoxLayout(statusbar)
        sb.setContentsMargins(20, 0, 20, 0)
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("status")
        self.status_lbl.setStyleSheet(f"color: {_C_TEXT_WHITE}; font-size: 12px; font-weight: bold;")
        self.summary_lbl = QLabel("")
        self.summary_lbl.setObjectName("summary")
        self.summary_lbl.setStyleSheet(f"color: rgba(255,255,255,0.85); font-size: 12px;")
        self.summary_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sb.addWidget(self.status_lbl)
        sb.addStretch()
        sb.addWidget(self.summary_lbl)
        root.addWidget(statusbar)

    # ── Page builders ──────────────────────────────────────────────────────────

    def _page_header(self, parent_layout, title: str, subtitle: str):
        hdr = QWidget()
        hdr.setObjectName("panel_hdr")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(24, 12, 24, 12)
        hl.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("panel_title")
        t.setStyleSheet(f"color: {_C_TEXT}; font-size: 17px; font-weight: bold;")
        s = QLabel(subtitle)
        s.setObjectName("panel_subtitle")
        s.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        hl.addWidget(t); hl.addWidget(s)
        parent_layout.addWidget(hdr)

    def _scroll_content(self, parent_layout) -> QVBoxLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {_C_BG}; }}")
        w = QWidget(); w.setStyleSheet(f"background-color: {_C_BG};")
        cl = QVBoxLayout(w)
        cl.setContentsMargins(24, 18, 24, 18)
        cl.setSpacing(14)
        scroll.setWidget(w)
        parent_layout.addWidget(scroll, stretch=1)
        return cl

    def _card(self, vtype=True) -> tuple:
        c = QWidget(); c.setObjectName("card")
        l = QVBoxLayout(c) if vtype else QHBoxLayout(c)
        l.setContentsMargins(16, 14, 16, 14)
        l.setSpacing(10)
        return c, l

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("section")
        lbl.setStyleSheet(f"color: {_C_BLUE}; font-size: 10px; font-weight: bold; letter-spacing: 2px;")
        return lbl

    def _desc_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("desc")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        return lbl

    def _btn(self, text, style):
        b = QPushButton(text)
        b.setObjectName(style)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.setStyleSheet(_btn_style(style))
        return b

    def _build_auth_page(self):
        page = QWidget(); page.setObjectName("panel")
        pl = QVBoxLayout(page); pl.setSpacing(0); pl.setContentsMargins(0, 0, 0, 0)
        self._page_header(pl, "Authentication", "BROWSER SESSIONS  ·  REQUIRED BEFORE FIRST RUN")
        cl = self._scroll_content(pl)

        cl.addWidget(self._section_label("PORTAL"))
        c1, l1 = self._card()
        l1.addWidget(self._desc_label(
            "Save your SAP Self-Service Content Portal session. "
            "Required for Stage 1 and Workshop Cleanup."))
        self.btn_sign_portal = self._btn("Sign In — Portal", "blue")
        self.btn_sign_portal.clicked.connect(self._run_sign_in_portal)
        l1.addWidget(self.btn_sign_portal)
        cl.addWidget(c1)

        cl.addWidget(self._section_label("DATASPHERE"))
        c2, l2 = self._card()
        l2.addWidget(self._desc_label(
            "Save your SAP Datasphere Space Management session. "
            "Required for Stage 2, Stage 3, and Stage 4."))
        self.btn_sign_ds = self._btn("Sign In — Datasphere", "blue")
        self.btn_sign_ds.clicked.connect(self._run_sign_in_datasphere)
        l2.addWidget(self.btn_sign_ds)
        cl.addWidget(c2)
        cl.addStretch()
        return page

    def _build_pipeline_page(self):
        page = QWidget(); page.setObjectName("panel")
        pl = QVBoxLayout(page); pl.setSpacing(0); pl.setContentsMargins(0, 0, 0, 0)
        self._page_header(pl, "Pipeline", "FOUR-STAGE CLEANUP  ·  RUN IN ORDER")
        cl = self._scroll_content(pl)

        # ── Date range filter (optional — Stage 1 only) ────────────────────────
        cl.addWidget(self._section_label("DATE RANGE FILTER  ·  STAGE 1 ONLY"))
        dc, dl = self._card()
        dl.addWidget(self._desc_label(
            "Optional: filter workshops by planned start date and/or planned end date before "
            "scraping. The two ranges are independent — fill either, both, or neither. A range "
            "applies only when both its From and To are set. Format: YYYY-MM-DD"))

        def _date_edit(placeholder):
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            e.setFixedWidth(120)
            e.setStyleSheet(
                f"QLineEdit {{ background: white; color: {_C_TEXT}; "
                f"border: 1px solid {_C_CARD_BORDER}; border-radius: 4px; padding: 4px 8px; font-size: 12px; }}"
            )
            return e

        def _range_row(title, from_edit, to_edit):
            row = QHBoxLayout()
            row.setSpacing(10)
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
            title_lbl.setFixedWidth(110)
            from_lbl = QLabel("From:")
            from_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
            from_lbl.setFixedWidth(38)
            to_lbl = QLabel("To:")
            to_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
            to_lbl.setFixedWidth(24)
            row.addWidget(title_lbl)
            row.addWidget(from_lbl)
            row.addWidget(from_edit)
            row.addWidget(to_lbl)
            row.addWidget(to_edit)
            row.addStretch()
            return row

        self._start_date_from_edit = _date_edit("e.g. 2024-01-01")
        self._start_date_to_edit   = _date_edit("e.g. 2025-01-01")
        self._end_date_from_edit   = _date_edit("e.g. 2024-01-01")
        self._end_date_to_edit     = _date_edit("e.g. 2025-01-01")
        dl.addLayout(_range_row("Start date range:", self._start_date_from_edit, self._start_date_to_edit))
        dl.addLayout(_range_row("End date range:", self._end_date_from_edit, self._end_date_to_edit))
        self._workshop_id_from_edit = _date_edit("e.g. 277373")
        self._workshop_id_to_edit   = _date_edit("e.g. 281952")
        dl.addLayout(_range_row("Workshop ID range:", self._workshop_id_from_edit, self._workshop_id_to_edit))

        max_row = QHBoxLayout()
        max_row.setSpacing(10)
        max_lbl = QLabel("Max workshops:")
        max_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        self._max_workshops_edit = QLineEdit()
        self._max_workshops_edit.setPlaceholderText("e.g. 300 (blank = config default)")
        self._max_workshops_edit.setFixedWidth(200)
        self._max_workshops_edit.setStyleSheet(
            f"QLineEdit {{ background: white; color: {_C_TEXT}; "
            f"border: 1px solid {_C_CARD_BORDER}; border-radius: 4px; padding: 4px 8px; font-size: 12px; }}"
        )
        max_row.addWidget(max_lbl)
        max_row.addWidget(self._max_workshops_edit)
        max_row.addStretch()
        dl.addLayout(max_row)

        from src.portal_client import SEARCH_TERM_OVERVIEW, SEARCH_TERM_INTEGRATION, SEARCH_TERM_BASIC_TRIAL
        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        search_lbl = QLabel("Workbook:")
        search_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        self._search_overview_radio = QRadioButton(SEARCH_TERM_OVERVIEW)
        self._search_integration_radio = QRadioButton(SEARCH_TERM_INTEGRATION)
        self._search_basic_trial_radio = QRadioButton(SEARCH_TERM_BASIC_TRIAL)
        self._search_custom_radio = QRadioButton("Custom:")
        self._search_overview_radio.setChecked(True)
        for _rb in (self._search_overview_radio, self._search_integration_radio,
                    self._search_basic_trial_radio, self._search_custom_radio):
            _rb.setStyleSheet(f"color: {_C_TEXT}; font-size: 12px;")
        self._search_term_group = QButtonGroup(self)
        self._search_term_group.addButton(self._search_overview_radio)
        self._search_term_group.addButton(self._search_integration_radio)
        self._search_term_group.addButton(self._search_basic_trial_radio)
        self._search_term_group.addButton(self._search_custom_radio)
        self._search_custom_edit = QLineEdit()
        self._search_custom_edit.setPlaceholderText("Enter custom search term…")
        self._search_custom_edit.setFixedHeight(28)
        self._search_custom_edit.setEnabled(False)
        self._search_custom_edit.setStyleSheet(f"font-size: 12px;")
        self._search_custom_radio.toggled.connect(self._search_custom_edit.setEnabled)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self._search_overview_radio)
        search_row.addWidget(self._search_integration_radio)
        search_row.addWidget(self._search_basic_trial_radio)
        search_row.addWidget(self._search_custom_radio)
        search_row.addWidget(self._search_custom_edit)
        search_row.addStretch()
        dl.addLayout(search_row)
        cl.addWidget(dc)

        stages = [
            ("STAGE 1 — DISCOVER",
             f"Scrapes the SAP portal for expired trial users from cleaned "
             f"{self._tenant.upper()} workshops and adds them to the sweep queue.",
             "Stage 1 — Discover", "blue", "_run_stage1", "btn_stage1"),
            ("STAGE 2 — DELETE",
             "Searches Datasphere for all spaces belonging to each pending workshop "
             "and bulk-deletes them.",
             "Stage 2 — Delete", "red", "_run_stage2", "btn_stage2"),
            ("STAGE 3 — VERIFY",
             "Re-checks every space reported as deleted to confirm it is gone. "
             "Flags discrepancies for manual re-processing.",
             "Stage 3 — Verify", "green", "_run_stage3", "btn_stage3"),
            ("STAGE 4 — PURGE",
             "Permanently removes from the Datasphere recycle bin all spaces "
             "deleted by this tool that are 7+ days old.",
             "Stage 4 — Purge", "orange", "_run_stage4", "btn_stage4"),
        ]
        for sec, desc, btn_text, colour, handler, attr in stages:
            cl.addWidget(self._section_label(sec))
            card, l = self._card()
            l.addWidget(self._desc_label(desc))
            btn = self._btn(btn_text, colour)
            btn.clicked.connect(getattr(self, handler))
            setattr(self, attr, btn)
            l.addWidget(btn)
            cl.addWidget(card)
        cl.addStretch()
        return page

    def _build_workshop_page(self):
        page = QWidget(); page.setObjectName("panel")
        pl = QVBoxLayout(page); pl.setSpacing(0); pl.setContentsMargins(0, 0, 0, 0)
        self._page_header(pl, "Workshop Cleanup", "TARGETED WORKSHOP LOOKUP  ·  ADDS TO SWEEP QUEUE")
        cl = self._scroll_content(pl)

        cl.addWidget(self._section_label("FIND WORKSHOPS BY ID"))
        c, l = self._card()
        l.addWidget(self._desc_label(
            "Add one or more 5–7 digit workshop IDs to the queue, then launch. "
            "Each workshop is looked up in order and added to the sweep queue."))

        # Input row: text field + Add button
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._workshop_id_input = QLineEdit()
        self._workshop_id_input.setPlaceholderText("Workshop ID (5–7 digits)")
        self._workshop_id_input.setFixedHeight(32)
        self._workshop_id_input.setStyleSheet(
            f"background: #1e2530; color: #d0e8f8; border: 1px solid {_C_CARD_BORDER}; "
            f"border-radius: 4px; padding: 0 8px; font-size: 13px;")
        self._workshop_id_input.returnPressed.connect(self._add_to_workshop_queue)
        input_row.addWidget(self._workshop_id_input)
        btn_add = self._btn("Add", "blue")
        btn_add.setFixedWidth(70)
        btn_add.clicked.connect(self._add_to_workshop_queue)
        input_row.addWidget(btn_add)
        l.addLayout(input_row)

        # Queue list
        self._workshop_queue_widget = QListWidget()
        self._workshop_queue_widget.setFixedHeight(120)
        self._workshop_queue_widget.setStyleSheet(
            f"background: #1e2530; color: #d0e8f8; border: 1px solid {_C_CARD_BORDER}; "
            f"border-radius: 4px; font-size: 13px;")
        self._workshop_queue_widget.setSelectionMode(QListWidget.SingleSelection)
        l.addWidget(self._workshop_queue_widget)

        queue_hint = QLabel("Select an item and press Remove to delete it from the queue.")
        queue_hint.setStyleSheet(f"color: {_C_TEXT_MUTED}; font-size: 11px;")
        l.addWidget(queue_hint)

        # Remove + Launch row
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        btn_remove = self._btn("Remove Selected", "orange")
        btn_remove.clicked.connect(self._remove_from_workshop_queue)
        action_row.addWidget(btn_remove)
        action_row.addStretch()
        self.btn_workshop_scrape = self._btn("Launch (0)", "blue")
        self.btn_workshop_scrape.setEnabled(False)
        self.btn_workshop_scrape.clicked.connect(self._run_workshop_scrape)
        action_row.addWidget(self.btn_workshop_scrape)
        l.addLayout(action_row)

        cl.addWidget(c)
        cl.addStretch()
        return page

    def _add_to_workshop_queue(self):
        workshop_id = self._workshop_id_input.text().strip()
        if not workshop_id:
            return
        if not workshop_id.isdigit() or not (5 <= len(workshop_id) <= 7):
            QMessageBox.warning(self, "Invalid ID", "Workshop ID must be 5–7 digits.")
            return
        if workshop_id in self._workshop_queue:
            QMessageBox.information(self, "Already queued", f"{workshop_id} is already in the queue.")
            return
        self._workshop_queue.append(workshop_id)
        self._workshop_queue_widget.addItem(workshop_id)
        self._workshop_id_input.clear()
        self.btn_workshop_scrape.setText(f"Launch ({len(self._workshop_queue)})")
        self.btn_workshop_scrape.setEnabled(True)

    def _remove_from_workshop_queue(self):
        selected = self._workshop_queue_widget.selectedItems()
        if not selected:
            return
        item = selected[0]
        workshop_id = item.text()
        row = self._workshop_queue_widget.row(item)
        self._workshop_queue_widget.takeItem(row)
        self._workshop_queue.remove(workshop_id)
        self.btn_workshop_scrape.setText(f"Launch ({len(self._workshop_queue)})")
        self.btn_workshop_scrape.setEnabled(len(self._workshop_queue) > 0)

    # ── Sidebar navigation ─────────────────────────────────────────────────────

    def _switch_section(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setObjectName("nav_active" if i == idx else "nav")
            btn.setStyle(btn.style())

    # ── Logging ────────────────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        self.log_box.append(msg)

    def log(self, msg: str):
        self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")

    def _patch_logger(self, run_id: str = None):
        from src.logging_setup import setup_logging
        import logging as _logging
        cfg = self._load_cfg()
        setup_logging(logs_dir=cfg.get("outputs", {}).get("logs_dir", "outputs/logs"), run_id=run_id)
        root_logger = _logging.getLogger("datasphere-cleanup")
        root_logger.handlers = [h for h in root_logger.handlers if not isinstance(h, _GUILogHandler)]
        h = _GUILogHandler(self)
        h.setFormatter(_logging.Formatter("%(name)s: %(message)s"))
        root_logger.addHandler(h)
        root_logger.setLevel(_logging.DEBUG)

    # ── Thread runner ──────────────────────────────────────────────────────────

    def _set_buttons_enabled(self, enabled: bool):
        for btn in (self.btn_sign_portal, self.btn_sign_ds,
                    self.btn_stage1, self.btn_stage2, self.btn_stage3, self.btn_stage4):
            btn.setEnabled(enabled)
        self.btn_workshop_scrape.setEnabled(enabled and len(self._workshop_queue) > 0)
        if enabled:
            self._indicator.setText("● Idle")
            self._indicator.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        else:
            self._indicator.setText("● Running")
            self._indicator.setStyleSheet("color: #7eeaff; font-size: 11px; font-weight: bold;")

    def _run_in_thread(self, fn, label: str):
        if self._running:
            self.log("Another task is already running — please wait.")
            return
        self._running = True
        self._buttons_signal.emit(False)
        self._status_signal.emit(f"{label} running…")
        self.log(f"── {label} started ──")
        self._thread = QThread()
        self._worker = Worker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.error_signal.connect(lambda e: self.log(f"ERROR: {e}"))
        self._worker.error_signal.connect(lambda e: self._status_signal.emit(f"{label} failed"))
        self._worker.done_signal.connect(self._on_task_done)
        self._thread.start()

    def _on_task_done(self):
        self._running = False
        self._buttons_signal.emit(True)
        self._thread.quit()
        self._thread.wait()

    # ── Config ─────────────────────────────────────────────────────────────────

    def _load_cfg(self):
        from src.config import load_tenant_config
        cfg = load_tenant_config(self._tenant, "config/settings.yaml")
        if self._demo_mode:
            for key in ("deleted_file", "processed_workshops_file"):
                if key in cfg.get("outputs", {}):
                    p = Path(cfg["outputs"][key])
                    cfg["outputs"][key] = str(p.parent / f"demo_{p.name}")
        return cfg

    # ── Dialog helpers ─────────────────────────────────────────────────────────

    def _dlg_stylesheet(self, confirm_colour: str, confirm_hover: str) -> str:
        return f"""
            QDialog {{ background-color: {_C_WHITE}; }}
            QLabel  {{ color: {_C_TEXT}; font-size: 13px; }}
            QCheckBox {{ color: {_C_TEXT_DIM}; font-size: 12px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; }}
            QPushButton {{ font-size: 13px; font-weight: bold; border: none;
                           border-radius: 5px; padding: 9px 20px; color: #ffffff; }}
            QPushButton#cancel  {{ background-color: #8fa3b5; }}
            QPushButton#cancel:hover  {{ background-color: #6a8099; }}
            QPushButton#confirm {{ background-color: {confirm_colour}; }}
            QPushButton#confirm:hover {{ background-color: {confirm_hover}; }}
        """

    # ── Button handlers ────────────────────────────────────────────────────────

    def _show_login_dialog(self, title: str, message: str, event):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(400)
        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {_C_WHITE}; }}
            QLabel  {{ color: {_C_TEXT}; font-size: 13px; }}
            QPushButton {{ font-size: 13px; font-weight: bold; border: none;
                           border-radius: 5px; padding: 9px 28px; color: #ffffff;
                           background-color: {_C_BLUE}; }}
            QPushButton:hover {{ background-color: {_C_BLUE_HOVER}; }}
        """)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        lbl = QLabel(message); lbl.setWordWrap(True)
        layout.addWidget(lbl)
        btn_row = QHBoxLayout(); btn_row.addStretch()
        ok_btn = QPushButton("OK — Session Saved")
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)
        dlg.exec_()
        event.set()

    def _run_sign_in_portal(self):
        def task():
            import asyncio
            self._patch_logger()
            from src.auth import save_portal_session
            ready = threading.Event()
            self.log("Browser opening — log in, then click 'OK — Session Saved' in the dialog.")
            self._dialog_signal.emit(
                "Sign In — Portal",
                "A browser has opened.\n\nLog in to the SAP portal, then click 'OK — Session Saved' to save your session.",
                ready)
            asyncio.run(save_portal_session(self._load_cfg(), wait_callback=lambda: ready.wait()))
            self.log("Portal session saved.")
            self._status_signal.emit("Portal session saved")
        self._run_in_thread(task, "Sign In Portal")

    def _run_sign_in_datasphere(self):
        def task():
            import asyncio
            self._patch_logger()
            from src.auth import save_datasphere_session
            ready = threading.Event()
            self.log("Browser opening — log in, then click 'OK — Session Saved' in the dialog.")
            self._dialog_signal.emit(
                "Sign In — Datasphere",
                "A browser has opened.\n\nLog in to Datasphere Space Management, then click 'OK — Session Saved' to save your session.",
                ready)
            asyncio.run(save_datasphere_session(self._load_cfg(), wait_callback=lambda: ready.wait()))
            self.log("Datasphere session saved.")
            self._status_signal.emit("Datasphere session saved")
        self._run_in_thread(task, "Sign In Datasphere")

    def _selected_search_term(self):
        from src.portal_client import SEARCH_TERM_OVERVIEW
        if self._search_custom_radio.isChecked():
            return self._search_custom_edit.text().strip() or SEARCH_TERM_OVERVIEW
        return self._search_term_group.checkedButton().text()

    def _run_stage1(self):
        start_date_from = self._start_date_from_edit.text().strip() or None
        start_date_to   = self._start_date_to_edit.text().strip() or None
        end_date_from   = self._end_date_from_edit.text().strip() or None
        end_date_to     = self._end_date_to_edit.text().strip() or None
        workshop_id_from = self._workshop_id_from_edit.text().strip() or None
        workshop_id_to   = self._workshop_id_to_edit.text().strip() or None
        _mw_text  = self._max_workshops_edit.text().strip()
        max_workshops_override = int(_mw_text) if _mw_text.isdigit() else None
        search_term = self._selected_search_term()

        def task():
            cfg = self._load_cfg()
            cfg["portal"]["start_date_from"] = start_date_from
            cfg["portal"]["start_date_to"]   = start_date_to
            cfg["portal"]["end_date_from"]   = end_date_from
            cfg["portal"]["end_date_to"]     = end_date_to
            cfg["portal"]["workshop_id_from"] = workshop_id_from
            cfg["portal"]["workshop_id_to"]   = workshop_id_to
            cfg["portal"]["search_term"] = search_term
            run_id = f"{self._tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            self._patch_logger(run_id)
            from src.stage1_discovery import run_stage1
            from src.portal_client import load_pending_workshops
            run_stage1(cfg=cfg, run_id=run_id,
                       max_workshops=max_workshops_override,
                       progress_callback=lambda msg: self._status_signal.emit(msg))
            pending_count = len(load_pending_workshops(cfg))
            self.log(f"Stage 1 complete — {pending_count} workshop(s) in sweep queue")
            self._status_signal.emit("Stage 1 complete")
            self._summary_signal.emit(
                "Stage 1: Sweep queue empty" if pending_count == 0
                else f"Stage 1: {pending_count} workshop(s) queued for sweep")
        self._run_in_thread(task, "Stage 1 — Discover")

    def _run_workshop_scrape(self):
        if not self._workshop_queue:
            self.log("Workshop queue is empty — add at least one workshop ID first.")
            return

        queue = list(self._workshop_queue)

        # Clear the queue in the UI now that we've captured it
        self._workshop_queue.clear()
        self._workshop_queue_widget.clear()
        self.btn_workshop_scrape.setText("Launch (0)")
        self.btn_workshop_scrape.setEnabled(False)

        search_term = self._selected_search_term()

        def task():
            cfg = self._load_cfg()
            cfg["portal"]["search_term"] = search_term
            from src.stage1_discovery import run_workshop_scrape
            from src.portal_client import load_pending_workshops
            pending_count = 0
            for workshop_id in queue:
                run_id = f"{self._tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                self._patch_logger(run_id)
                run_workshop_scrape(workshop_id=workshop_id, cfg=cfg, run_id=run_id)
                pending_count = len(load_pending_workshops(cfg))
                self.log(f"Workshop {workshop_id} added to sweep queue — {pending_count} workshop(s) queued")
            self._status_signal.emit(f"{len(queue)} workshop(s) added")
            self._summary_signal.emit(f"{len(queue)} workshop(s) added  |  {pending_count} workshop(s) in sweep queue")
        self._run_in_thread(task, f"Scrape {len(queue)} Workshop(s)")

    def _run_stage2(self):
        cfg = self._load_cfg()
        from src.portal_client import load_pending_workshops
        try:
            pending_count = len(load_pending_workshops(cfg))
        except Exception as exc:
            self.log(f"ERROR: Could not read sweep queue — {exc}"); return
        if pending_count == 0:
            self.log("Sweep queue is empty — run Stage 1 first."); return

        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm Deletion")
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet(self._dlg_stylesheet(_C_RED, _C_RED_HOVER))
        dl = QVBoxLayout(dlg); dl.setSpacing(16); dl.setContentsMargins(20, 20, 20, 20)
        lbl = QLabel(f"{pending_count} workshop(s) in the sweep queue.\n\n"
                     "This will permanently delete Datasphere spaces.\n\nProceed?")
        lbl.setWordWrap(True); dl.addWidget(lbl)
        chk = QCheckBox("Preview only — no changes will be made")
        chk.setChecked(False); dl.addWidget(chk)
        br = QHBoxLayout()
        bn = QPushButton("Cancel");      bn.setObjectName("cancel");  bn.clicked.connect(dlg.reject)
        by = QPushButton("Yes, proceed"); by.setObjectName("confirm"); by.clicked.connect(dlg.accept)
        br.addWidget(bn); br.addWidget(by); dl.addLayout(br)
        if dlg.exec_() != QDialog.Accepted: return
        self._do_run_stage2(dry_run=chk.isChecked())

    def _do_run_stage2(self, dry_run: bool = False):
        def task():
            cfg = self._load_cfg()
            run_id = f"{self._tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            self._patch_logger(run_id)
            from src.stage2_deletion import run_stage2_workshops
            from src.portal_client import load_pending_workshops
            from src.report import generate_report
            # SAFETY GATE (mirror of the CLI): live deletion requires BOTH cfg["dry_run"]
            # is False AND the user leaving the dialog's dry-run box unchecked. If config
            # says dry_run:true, force dry-run regardless of the checkbox so a default
            # click-through can never delete live data.
            cfg_dry_run = cfg.get("dry_run", True)
            effective_dry_run = dry_run or cfg_dry_run
            if not dry_run and cfg_dry_run:
                self.log("Config has dry_run set to true — forcing preview mode. "
                         "Set dry_run to false in config to enable live deletions.")
            if effective_dry_run: self.log("PREVIEW MODE: no spaces will be deleted")
            results = run_stage2_workshops(cfg=cfg, dry_run=effective_dry_run, run_id=run_id,
                                           progress_callback=lambda msg: self._status_signal.emit(msg))
            self._stage2_report = generate_report(results=results, run_id=run_id,
                reports_dir=cfg["outputs"]["reports_dir"], dry_run=effective_dry_run)
            d  = sum(1 for r in results if r.outcome == "deleted")
            fa = sum(1 for r in results if r.outcome == "failed")
            sk = sum(1 for r in results if r.outcome == "skipped_dry_run")
            rem = len(load_pending_workshops(cfg))
            if effective_dry_run:
                self.log(f"Stage 2 preview complete — {sk} would delete, {fa} failed, {rem} workshop(s) remaining")
                self._status_signal.emit("Stage 2 preview complete")
                self._summary_signal.emit(f"PREVIEW: {sk} would delete  |  {fa} failed  |  {rem} remaining")
            else:
                self.log(f"Stage 2 complete — {d} deleted, {fa} failed, {rem} workshop(s) remaining")
                self._status_signal.emit("Stage 2 complete")
                self._summary_signal.emit(f"Stage 2: {d} deleted  |  {fa} failed  |  {rem} remaining")
        self._run_in_thread(task, "Stage 2 — Dry Run" if dry_run else "Stage 2 — Delete")

    def _run_stage3(self):
        if not self._stage2_report:
            cfg = self._load_cfg()
            reports = sorted(
                Path(cfg["outputs"]["reports_dir"]).glob(f"report_{self._tenant}_*.json"),
                reverse=True,
            )
            if not reports:
                self.log("No Stage 2 report found — run Stage 2 first."); return
            self._stage2_report = str(reports[0])
            self.log(f"Using most recent report: {Path(self._stage2_report).name}")

        def task():
            cfg = self._load_cfg()
            run_id = f"{self._tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            self._patch_logger(run_id)
            from src.stage3_verify import run_stage3
            vpath = run_stage3(report_path=self._stage2_report, cfg=cfg, run_id=run_id,
                               progress_callback=lambda msg: self._status_signal.emit(msg))
            import json
            with open(vpath, encoding="utf-8") as f:
                v = json.load(f)["summary"]
            self.log(f"Stage 3 complete — {v['confirmed_deleted']} confirmed, "
                     f"{v['still_exists']} still exist, {v['check_failed']} check failed")
            self._status_signal.emit("Stage 3 complete")
            self._summary_signal.emit(f"Stage 3: {v['confirmed_deleted']} confirmed  |  "
                                      f"{v['still_exists']} still exist  |  {v['check_failed']} check failed")
        self._run_in_thread(task, "Stage 3 — Verify")

    def _run_stage4(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm Recycle Bin Purge")
        dlg.setMinimumWidth(440)
        dlg.setStyleSheet(self._dlg_stylesheet(_C_ORANGE, _C_ORANGE_HOVER))
        dl = QVBoxLayout(dlg); dl.setSpacing(16); dl.setContentsMargins(20, 20, 20, 20)
        lbl = QLabel("Permanently delete from the Datasphere recycle bin all spaces\n"
                     "deleted by this tool.\n\n"
                     "Spaces deleted by others will not be touched.\n\nThis cannot be undone. Proceed?")
        lbl.setWordWrap(True); dl.addWidget(lbl)
        spin_style = (f"QSpinBox {{ background: white; color: {_C_TEXT}; "
                      f"border: 1px solid {_C_CARD_BORDER}; border-radius: 4px; padding: 3px 6px; }}")
        lr = QHBoxLayout()
        ll = QLabel("Max spaces to purge (0 = no limit):")
        ll.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        spin = QSpinBox(); spin.setRange(0, 9999); spin.setValue(10)
        spin.setStyleSheet(spin_style)
        lr.addWidget(ll); lr.addWidget(spin); dl.addLayout(lr)
        ar = QHBoxLayout()
        al = QLabel("Min age (days, 0 = purge all):")
        al.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        age_spin = QSpinBox(); age_spin.setRange(0, 365); age_spin.setValue(7)
        age_spin.setStyleSheet(spin_style)
        ar.addWidget(al); ar.addWidget(age_spin); dl.addLayout(ar)
        chk = QCheckBox("Preview only — no changes will be made")
        chk.setChecked(False); dl.addWidget(chk)
        br = QHBoxLayout()
        bn = QPushButton("Cancel");      bn.setObjectName("cancel");  bn.clicked.connect(dlg.reject)
        by = QPushButton("Yes, proceed"); by.setObjectName("confirm"); by.clicked.connect(dlg.accept)
        br.addWidget(bn); br.addWidget(by); dl.addLayout(br)
        if dlg.exec_() != QDialog.Accepted: return

        dry_run = chk.isChecked()
        max_purge = spin.value()
        min_age = age_spin.value()

        def task():
            cfg = self._load_cfg()
            run_id = f"{self._tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            self._patch_logger(run_id)
            from src.stage4_purge import run_stage4
            if dry_run: self.log("PREVIEW MODE: no spaces will be permanently deleted")
            if max_purge > 0: self.log(f"Stopping after {max_purge} space(s)")
            if min_age == 0: self.log("Min age set to 0 — purging all deleted spaces regardless of age")
            results = run_stage4(cfg=cfg, dry_run=dry_run, run_id=run_id, max_purge=max_purge,
                                 min_age_days=min_age,
                                 progress_callback=lambda msg: self._status_signal.emit(msg))
            pu = sum(1 for r in results if r.outcome == "purged")
            dr = sum(1 for r in results if r.outcome == "skipped_dry_run")
            sk = sum(1 for r in results if r.outcome == "skipped_not_ours")
            fa = sum(1 for r in results if r.outcome == "failed")
            if dry_run:
                self.log(f"Stage 4 preview — {dr} would purge, {sk} skipped (not ours), {fa} failed")
                self._status_signal.emit("Stage 4 preview complete")
                self._summary_signal.emit(f"PREVIEW: {dr} would purge  |  {sk} skipped  |  {fa} failed")
            else:
                self.log(f"Stage 4 complete — {pu} purged, {sk} skipped (not ours), {fa} failed")
                self._status_signal.emit("Stage 4 complete")
                self._summary_signal.emit(f"Stage 4: {pu} purged  |  {sk} skipped  |  {fa} failed")
        self._run_in_thread(task, "Stage 4 — Dry Run" if dry_run else "Stage 4 — Purge")


def main(tenant: str = "eu10"):
    from src.config import setup_app_home
    setup_app_home()
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = App(tenant=tenant)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
