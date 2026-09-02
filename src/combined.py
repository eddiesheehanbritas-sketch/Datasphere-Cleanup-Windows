import sys
import logging
import threading
import contextvars
from datetime import datetime, timezone
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFrame, QMessageBox, QSizePolicy,
    QDialog, QCheckBox, QInputDialog, QSpinBox, QStackedWidget, QScrollArea,
    QGroupBox, QLineEdit, QListWidget, QListWidgetItem,
    QRadioButton, QButtonGroup, QComboBox, QFormLayout,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject

from src.app import (
    Worker, STYLESHEET, _btn_style,
    _C_WHITE, _C_BG, _C_SIDEBAR, _C_TOPBAR,
    _C_CARD, _C_CARD_BORDER, _C_PANEL_HDR,
    _C_TEXT, _C_TEXT_DIM, _C_TEXT_MUTED, _C_TEXT_WHITE, _C_TEXT_SIDEBAR,
    _C_BLUE, _C_BLUE_HOVER, _C_BLUE_DIS,
    _C_RED, _C_RED_HOVER, _C_RED_DIS,
    _C_GREEN, _C_GREEN_HOVER, _C_GREEN_DIS,
    _C_ORANGE, _C_ORANGE_HOVER, _C_ORANGE_DIS,
    _C_NAV_ACTIVE, _C_NAV_HOVER,
)


# Per-tenant log routing signal. Set in _patch_combined_logger at the start of each
# tenant coroutine; read in _TenantLogHandler.emit. A contextvar propagates into
# asyncio.wait_for child tasks, so log lines emitted inside wrapped coroutines are
# attributed to the correct tenant instead of being dropped.
_active_tenant_prefix: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "active_tenant_prefix", default=None
)


class _TenantLogHandler(logging.Handler):
    """Routes log records to the shared GUI log box with [EU10] or [US10] prefix.

    Filters by a contextvar (_active_tenant_prefix) so concurrent EU10/US10 coroutines
    don't cross-contaminate each other's log output in the GUI. A contextvar is used
    rather than raw asyncio.Task identity because it propagates automatically into child
    tasks spawned by asyncio.wait_for(...) — without it, any log line emitted inside a
    wait_for-wrapped coroutine (e.g. 'Workshop N: found M user(s)', which runs inside
    asyncio.wait_for in run_portal_scrape) would be attributed to the child task, fail the
    identity check, and be silently dropped from the GUI while still reaching the file log.
    Falls back to asyncio.Task identity, then OS thread ident, for the serial sign-in path.
    """

    def __init__(self, app, prefix: str, task=None, thread_ident: int = None):
        super().__init__()
        self._app = app
        self._prefix = prefix
        self._task = task          # asyncio.Task — used when running concurrently
        self._ident = thread_ident # OS thread ident — used for sign-in (serial, non-async)

    def emit(self, record):
        import asyncio
        # Preferred signal: the contextvar set by _patch_combined_logger. It propagates
        # into asyncio.wait_for child tasks, so lines logged inside wrapped coroutines
        # (the per-workshop 'found N user(s)' line) are still attributed to this tenant.
        active = _active_tenant_prefix.get()
        if active is not None:
            if active != self._prefix:
                return
            self._app.log(f"{self._prefix} {self.format(record)}")
            return
        # Fallbacks for paths that don't set the contextvar.
        if self._task is not None:
            # Concurrent mode: only emit for records from our asyncio task
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if current is not self._task:
                return
        elif self._ident is not None:
            if threading.current_thread().ident != self._ident:
                return
        self._app.log(f"{self._prefix} {self.format(record)}")


def _load_cfg(tenant: str, demo_mode: bool = False) -> dict:
    from src.config import load_tenant_config
    from pathlib import Path as _Path
    cfg = load_tenant_config(tenant, "config/settings.yaml")
    if demo_mode:
        for key in ("deleted_file", "processed_workshops_file"):
            if key in cfg.get("outputs", {}):
                p = _Path(cfg["outputs"][key])
                cfg["outputs"][key] = str(p.parent / f"demo_{p.name}")
    return cfg


def _all_tenants() -> list:
    """Return the ordered list of tenant names from config/settings.yaml."""
    from src.config import load_config
    raw = load_config("config/settings.yaml")
    return list(raw.get("tenants", {}).keys())


class CombinedApp(QMainWindow):
    _log_signal     = pyqtSignal(str)
    _status_signal  = pyqtSignal(str)
    _summary_signal = pyqtSignal(str)
    _buttons_signal = pyqtSignal(bool)
    _dialog_signal  = pyqtSignal(str, str, object)
    _eu10_progress_signal = pyqtSignal(str)
    _us10_progress_signal = pyqtSignal(str)

    _SECTION_AUTH     = 0
    _SECTION_PIPELINE = 1
    _SECTION_WORKSHOP = 2

    def __init__(self, demo_mode: bool = False):
        super().__init__()
        self._demo_mode = demo_mode
        self._threads_running   = 0
        self._thread_eu10       = None
        self._thread_us10       = None
        self._worker_eu10       = None
        self._worker_us10       = None
        self._stage2_report_eu10 = None
        self._stage2_report_us10 = None
        self._nav_buttons       = []
        self._active_tenants    = list(_all_tenants())
        self._tenant_checkboxes = {}  # kept for test compatibility — no longer used in UI
        self._start_date_from_edit = None  # QLineEdit — set in _build_pipeline_page
        self._start_date_to_edit   = None  # QLineEdit — set in _build_pipeline_page
        self._end_date_from_edit   = None  # QLineEdit — set in _build_pipeline_page
        self._end_date_to_edit     = None  # QLineEdit — set in _build_pipeline_page
        self._workshop_id_from_edit = None  # QLineEdit — set in _build_pipeline_page
        self._workshop_id_to_edit   = None  # QLineEdit — set in _build_pipeline_page
        self._workshop_queue    = []   # list of workshop ID strings waiting to be scraped
        _tenants_label = " + ".join(t.upper() for t in self._active_tenants)
        self._tenants_label = _tenants_label
        title = f"Datasphere Cleanup — DEMO ({_tenants_label})" if demo_mode else f"Datasphere Cleanup — {_tenants_label}"
        self.setWindowTitle(title)
        self.resize(980, 740)
        self.setMinimumSize(820, 600)
        self._log_signal.connect(self._append_log)
        self._status_signal.connect(self._on_status_update)
        self._summary_signal.connect(lambda m: self.summary_lbl.setText(m))
        self._buttons_signal.connect(self._set_buttons_enabled)
        self._dialog_signal.connect(self._show_login_dialog)
        self._eu10_progress_signal.connect(lambda m: self.status_lbl.setText(m))
        self._us10_progress_signal.connect(lambda m: self.summary_lbl.setText(m))

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Top bar (EKX white shell + SAP logo)
        topbar = QWidget()
        topbar.setObjectName("TopBar")
        topbar.setFixedHeight(56)
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(16, 0, 16, 0)
        tb.setSpacing(12)
        # SAP logo
        try:
            from src.theme_apply import make_sap_logo_widget
            logo = make_sap_logo_widget(topbar, height_px=24)
            tb.addWidget(logo)
            tb.addSpacing(4)
        except Exception as e:
            print(f"[combined] Could not load SAP logo: {e}")
        title_lbl = QLabel("SAP Datasphere Cleanup")
        title_lbl.setObjectName("TopBarTitle")
        sub_lbl = QLabel(f"DEMO MODE  ·  {self._tenants_label}" if self._demo_mode else "Space Management Automation")
        sub_lbl.setObjectName("TopBarSubtitle")
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(title_lbl)
        col.addWidget(sub_lbl)
        tb.addLayout(col)
        tb.addStretch()
        self._indicator = QLabel("● Idle")
        self._indicator.setStyleSheet("color: #6A6D70; font-size: 12px;")
        tb.addWidget(self._indicator)
        root.addWidget(topbar)

        # Body: sidebar + right pane
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        root.addLayout(body, stretch=1)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 12, 0, 12)
        sl.setSpacing(2)

        from PyQt5.QtGui import QIcon
        from PyQt5.QtCore import QSize
        self._nav_icons = {
            self._SECTION_AUTH:     (":/icons/nav_auth_active.svg", ":/icons/nav_auth_grey.svg"),
            self._SECTION_PIPELINE: (":/icons/nav_pipeline_active.svg", ":/icons/nav_pipeline_grey.svg"),
            self._SECTION_WORKSHOP: (":/icons/nav_workshop_active.svg", ":/icons/nav_workshop_grey.svg"),
        }
        for label, idx in [
            ("Authentication", self._SECTION_AUTH),
            ("Pipeline",       self._SECTION_PIPELINE),
            ("Workshop",       self._SECTION_WORKSHOP),
        ]:
            btn = QPushButton("  " + label)
            btn.setObjectName("SidebarItem")
            btn.setProperty("active", idx == 0)
            active_icon, grey_icon = self._nav_icons[idx]
            btn.setIcon(QIcon(active_icon if idx == 0 else grey_icon))
            btn.setIconSize(QSize(20, 20))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _checked, i=idx: self._switch_section(i))
            sl.addWidget(btn)
            self._nav_buttons.append(btn)
        sl.addStretch()
        footer = QLabel(f"{self._tenants_label} — DEMO" if self._demo_mode else self._tenants_label)
        footer.setObjectName("SidebarFooterText")
        footer.setStyleSheet(f"color: {_C_TEXT_MUTED}; font-size: 12px; padding: 0 16px;")
        footer.setAlignment(Qt.AlignLeft)
        sl.addWidget(footer)
        body.addWidget(sidebar)

        sd = QFrame()
        sd.setObjectName("divider_dark")
        sd.setFrameShape(QFrame.VLine)
        sd.setFixedWidth(1)
        body.addWidget(sd)

        right = QWidget()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(0)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        self._stack.setObjectName("panel")
        self._stack.addWidget(self._build_auth_page())
        self._stack.addWidget(self._build_pipeline_page())
        self._stack.addWidget(self._build_workshop_page())
        right_layout.addWidget(self._stack, stretch=1)

        # Log panel header
        log_hdr = QWidget()
        log_hdr.setObjectName("LogPanelHeader")
        log_hdr_row = QHBoxLayout(log_hdr)
        log_hdr_row.setContentsMargins(12, 0, 12, 0)
        log_hdr_row.setSpacing(8)
        log_sec = QLabel("LOG OUTPUT")
        log_sec.setObjectName("LogPanelTitle")
        log_hdr_row.addWidget(log_sec)
        log_hdr_row.addStretch()
        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(52)
        btn_clear.setFixedHeight(24)
        btn_clear.setStyleSheet(
            "QPushButton { background-color: #2A3E59; color: #B3C0CC; "
            "font-size: 11px; font-weight: 400; border-radius: 4px; border: none; padding: 0 8px; }"
            "QPushButton:hover { background-color: #3A5070; color: #EAF2FB; }"
        )
        btn_clear.clicked.connect(lambda: self.log_box.clear())
        log_hdr_row.addWidget(btn_clear)
        right_layout.addWidget(log_hdr)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("LogOutput")
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(200)
        right_layout.addWidget(self.log_box)
        body.addWidget(right, stretch=1)

        # Status bar
        div2 = QFrame()
        div2.setObjectName("divider")
        div2.setFrameShape(QFrame.HLine)
        div2.setFixedHeight(1)
        root.addWidget(div2)
        statusbar = QWidget()
        statusbar.setObjectName("statusbar")
        statusbar.setFixedHeight(44)
        statusbar.setStyleSheet("QWidget#statusbar { background-color: #FFFFFF; border-top: 1px solid #E5E5E5; }")
        sb = QHBoxLayout(statusbar)
        sb.setContentsMargins(20, 0, 20, 0)
        sb.setSpacing(8)
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("status")
        self.status_lbl.setStyleSheet(f"color: {_C_TEXT}; font-size: 13px; font-weight: 600;")
        # Status chip (idle/running/success/error indicator)
        self._status_dot = QLabel("")
        self._status_dot.setObjectName("StatusDot")
        self._status_chip = QLabel("Idle")
        self._status_chip.setObjectName("StatusChip")
        from src.theme_apply import set_status
        set_status(self._status_dot, "idle")
        set_status(self._status_chip, "idle")
        self.summary_lbl = QLabel("")
        self.summary_lbl.setObjectName("summary")
        self.summary_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 13px;")
        self.summary_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sb.addWidget(self.status_lbl)
        sb.addStretch()
        sb.addWidget(self._status_dot)
        sb.addWidget(self._status_chip)
        sb.addWidget(self.summary_lbl)
        root.addWidget(statusbar)

    # ── Page builders ──────────────────────────────────────────────────────────

    def _page_header(self, parent_layout, title: str, subtitle: str):
        hdr = QWidget()
        hdr.setObjectName("panel_hdr")
        hdr.setStyleSheet("QWidget#panel_hdr { background-color: #FFFFFF; border-bottom: 1px solid #E5E5E5; }")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 16)
        hl.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        s = QLabel(subtitle)
        s.setObjectName("HelperText")
        hl.addWidget(t)
        hl.addWidget(s)
        parent_layout.addWidget(hdr)

    def _scroll_content(self, parent_layout) -> QVBoxLayout:
        scroll = QScrollArea()
        scroll.setObjectName("ContentScrollArea")
        scroll.setWidgetResizable(True)
        w = QWidget()
        w.setObjectName("ContentArea")
        cl = QVBoxLayout(w)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(16)
        scroll.setWidget(w)
        parent_layout.addWidget(scroll, stretch=1)
        return cl

    def _card(self, vtype=True) -> tuple:
        c = QFrame()
        c.setObjectName("Card")
        l = QVBoxLayout(c) if vtype else QHBoxLayout(c)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(12)
        return c, l

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("SectionHeader")
        return lbl

    def _desc_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("HelperText")
        lbl.setWordWrap(True)
        return lbl

    _BTN_NAME_MAP = {
        "blue":   "BtnPrimary",
        "red":    "BtnDestructive",
        "green":  "BtnSuccess",
        "orange": "BtnWarning",
    }

    def _btn(self, text, style):
        b = QPushButton(text)
        b.setObjectName(self._BTN_NAME_MAP.get(style, "BtnPrimary"))
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return b

    def _build_auth_page(self):
        page = QWidget()
        page.setObjectName("panel")
        pl = QVBoxLayout(page)
        pl.setSpacing(0)
        pl.setContentsMargins(0, 0, 0, 0)
        self._page_header(pl, "Authentication", "BROWSER SESSIONS  ·  REQUIRED BEFORE FIRST RUN")
        cl = self._scroll_content(pl)

        # ── Tenant selection ───────────────────────────────────────────────────
        cl.addWidget(self._section_label("ACTIVE TENANTS"))
        tc, tl = self._card()
        tl.addWidget(self._desc_label(
            "Select which tenants to include. Sign-in and all pipeline stages "
            "will only operate on the selected tenants."))

        self._tenant_list_widget = QListWidget()
        self._tenant_list_widget.setSelectionMode(QListWidget.NoSelection)
        self._tenant_list_widget.setStyleSheet(
            f"QListWidget {{ background-color: {_C_CARD}; border: 1px solid {_C_CARD_BORDER}; "
            f"border-radius: 5px; padding: 4px; }}"
            f"QListWidget::item {{ color: {_C_TEXT}; font-size: 12px; padding: 5px 8px; border: none; }}"
            f"QListWidget::item:hover {{ background-color: {_C_NAV_HOVER}; border-radius: 3px; }}"
        )

        _BUILTIN_DISPLAY = {
            "eu10":   "EU10(1)", "eu10_2": "EU10(2)",
            "us10":   "US10(1)", "us10_2": "US10(2)",
            "ap11":   "AP11(1)", "ap11_2": "AP11(2)",
        }

        try:
            from src.config import load_config as _load_raw
            _raw_tenants = _load_raw("config/settings.yaml").get("tenants", {})
        except Exception:
            _raw_tenants = {}

        for tenant, block in _raw_tenants.items():
            display = block.get("display_name") or _BUILTIN_DISPLAY.get(tenant, tenant.upper())
            try:
                url = block.get("datasphere", {}).get("base_url", "")
            except Exception:
                url = ""
            label = f"{display}    {url}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, tenant)
            self._tenant_list_widget.addItem(item)

        row_count = self._tenant_list_widget.count()
        self._tenant_list_widget.setFixedHeight(row_count * 34 + 10)
        self._tenant_list_widget.itemChanged.connect(self._on_tenant_selection_changed)
        tl.addWidget(self._tenant_list_widget)

        self._no_tenant_warning = QLabel("⚠  Select at least one tenant.")
        self._no_tenant_warning.setStyleSheet("color: #e05252; font-size: 12px; font-weight: bold;")
        self._no_tenant_warning.setVisible(False)
        tl.addWidget(self._no_tenant_warning)
        cl.addWidget(tc)

        # ── Manage Tenants ─────────────────────────────────────────────────────
        cl.addWidget(self._section_label("MANAGE TENANTS"))
        mc, ml = self._card()
        ml.addWidget(self._desc_label(
            "Add custom tenants or remove previously added ones. "
            "Changes take effect immediately and persist across app restarts."))

        # Existing user-added tenants list
        self._managed_tenants_layout = QVBoxLayout()
        self._managed_tenants_layout.setSpacing(4)
        ml.addLayout(self._managed_tenants_layout)
        self._refresh_managed_tenants_list()

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color: {_C_CARD_BORDER};")
        ml.addWidget(div)

        # Add tenant form
        form_label = QLabel("Add New Tenant")
        form_label.setStyleSheet(f"color: {_C_TEXT}; font-size: 12px; font-weight: bold; margin-top: 6px;")
        ml.addWidget(form_label)

        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignRight)

        label_style = f"color: {_C_TEXT_DIM}; font-size: 12px;"

        self._new_tenant_name = QLineEdit()
        self._new_tenant_name.setPlaceholderText("e.g. EU10(3)")
        self._new_tenant_name.setStyleSheet(self._input_style())
        lbl_name = QLabel("Name:")
        lbl_name.setStyleSheet(label_style)
        form.addRow(lbl_name, self._new_tenant_name)

        self._new_tenant_url = QLineEdit()
        self._new_tenant_url.setPlaceholderText("https://...")
        self._new_tenant_url.setStyleSheet(self._input_style())
        lbl_url = QLabel("Base URL:")
        lbl_url.setStyleSheet(label_style)
        form.addRow(lbl_url, self._new_tenant_url)

        self._new_tenant_region = QComboBox()
        self._new_tenant_region.addItems(["EU10", "US10", "AP11"])
        self._new_tenant_region.setMinimumWidth(120)
        self._new_tenant_region.setStyleSheet(self._combo_style())
        lbl_region = QLabel("DC Region:")
        lbl_region.setStyleSheet(label_style)
        form.addRow(lbl_region, self._new_tenant_region)

        # Type: Internal / Public
        type_widget = QWidget()
        type_layout = QHBoxLayout(type_widget)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.setSpacing(12)
        self._new_tenant_type_group = QButtonGroup(self)
        self._rb_internal = QRadioButton("Internal")
        self._rb_public   = QRadioButton("Public")
        self._rb_internal.setChecked(True)
        self._rb_internal.setStyleSheet(f"color: {_C_TEXT}; font-size: 12px;")
        self._rb_public.setStyleSheet(f"color: {_C_TEXT}; font-size: 12px;")
        self._new_tenant_type_group.addButton(self._rb_internal, 0)
        self._new_tenant_type_group.addButton(self._rb_public, 1)
        type_layout.addWidget(self._rb_internal)
        type_layout.addWidget(self._rb_public)
        type_layout.addStretch()
        lbl_type = QLabel("Type:")
        lbl_type.setStyleSheet(label_style)
        form.addRow(lbl_type, type_widget)

        # Path style: dwaas-ui / dwaas-core
        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(12)
        self._new_tenant_path_group = QButtonGroup(self)
        self._rb_dwaas_ui   = QRadioButton("dwaas-ui")
        self._rb_dwaas_core = QRadioButton("dwaas-core")
        self._rb_dwaas_ui.setChecked(True)
        self._rb_dwaas_ui.setStyleSheet(f"color: {_C_TEXT}; font-size: 12px;")
        self._rb_dwaas_core.setStyleSheet(f"color: {_C_TEXT}; font-size: 12px;")
        self._new_tenant_path_group.addButton(self._rb_dwaas_ui, 0)
        self._new_tenant_path_group.addButton(self._rb_dwaas_core, 1)
        path_layout.addWidget(self._rb_dwaas_ui)
        path_layout.addWidget(self._rb_dwaas_core)
        path_layout.addStretch()
        lbl_path = QLabel("Path style:")
        lbl_path.setStyleSheet(label_style)
        form.addRow(lbl_path, path_widget)

        ml.addLayout(form)

        self._add_tenant_error = QLabel("")
        self._add_tenant_error.setStyleSheet("color: #e05252; font-size: 11px;")
        self._add_tenant_error.setVisible(False)
        ml.addWidget(self._add_tenant_error)

        btn_add = self._btn("Add Tenant", "green")
        btn_add.clicked.connect(self._on_add_tenant)
        ml.addWidget(btn_add)

        cl.addWidget(mc)

        # ── Portal sign-in ─────────────────────────────────────────────────────
        cl.addWidget(self._section_label("PORTAL"))
        c1, l1 = self._card()
        l1.addWidget(self._desc_label(
            "Save your SAP Self-Service Content Portal session for the selected tenants. "
            "Required for Stage 1 and Workshop Cleanup."))
        self.btn_sign_portal = self._btn(self._sign_in_label("Portal"), "blue")
        self.btn_sign_portal.clicked.connect(self._run_sign_in_portal)
        l1.addWidget(self.btn_sign_portal)
        cl.addWidget(c1)

        # ── Datasphere sign-in ─────────────────────────────────────────────────
        cl.addWidget(self._section_label("DATASPHERE"))
        c2, l2 = self._card()
        l2.addWidget(self._desc_label(
            "Save your SAP Datasphere Space Management session for the selected tenants. "
            "Required for Stage 2, Stage 3, and Stage 4."))
        self.btn_sign_ds = self._btn(self._sign_in_label("Datasphere"), "blue")
        self.btn_sign_ds.clicked.connect(self._run_sign_in_datasphere)
        l2.addWidget(self.btn_sign_ds)
        cl.addWidget(c2)
        cl.addStretch()
        return page

    def _tenants_str(self) -> str:
        """Comma-separated uppercase tenant names, or 'None Selected'."""
        if not self._active_tenants:
            return "None Selected"
        return ", ".join(t.upper() for t in self._active_tenants)

    def _sign_in_label(self, service: str) -> str:
        return f"Sign In — {service} ({self._tenants_str()})"

    def _stage_label(self, name: str) -> str:
        return f"{name} ({self._tenants_str()})"

    def _on_tenant_selection_changed(self):
        """Rebuild self._active_tenants from checked list items; update labels and guards."""
        self._active_tenants = []
        for i in range(self._tenant_list_widget.count()):
            item = self._tenant_list_widget.item(i)
            if item.checkState() == Qt.Checked:
                self._active_tenants.append(item.data(Qt.UserRole))
        none_selected = len(self._active_tenants) == 0
        self._no_tenant_warning.setVisible(none_selected)
        self.btn_sign_portal.setText(self._sign_in_label("Portal"))
        self.btn_sign_ds.setText(self._sign_in_label("Datasphere"))
        self.btn_stage1.setText(self._stage_label("Stage 1 — Discover"))
        self.btn_stage2.setText(self._stage_label("Stage 2 — Delete"))
        self.btn_stage3.setText(self._stage_label("Stage 3 — Verify"))
        self.btn_stage4.setText(self._stage_label("Stage 4 — Purge"))
        self.btn_workshop_scrape.setText(self._stage_label(f"Launch ({len(self._workshop_queue)})"))
        # Disable all action buttons when no tenant is selected
        for btn in (self.btn_sign_portal, self.btn_sign_ds,
                    self.btn_stage1, self.btn_stage2, self.btn_stage3, self.btn_stage4):
            btn.setEnabled(not none_selected)
        self.btn_workshop_scrape.setEnabled(not none_selected and len(self._workshop_queue) > 0)

    def _input_style(self) -> str:
        return (
            f"QLineEdit {{ background-color: #FFFFFF; color: {_C_TEXT}; "
            f"border: 1px solid #CED2D9; border-radius: 6px; "
            f"min-height: 36px; padding: 0 10px; font-size: 14px; }}"
            f"QLineEdit:hover {{ border-color: #ACB4BE; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C_BLUE}; }}"
        )

    def _combo_style(self) -> str:
        return (
            f"QComboBox {{ background-color: #FFFFFF; color: {_C_TEXT}; "
            f"border: 1px solid #CED2D9; border-radius: 6px; "
            f"min-height: 36px; padding: 0 10px; font-size: 14px; }}"
            f"QComboBox:hover {{ border-color: #ACB4BE; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background-color: #FFFFFF; color: {_C_TEXT}; "
            f"border: 1px solid {_C_CARD_BORDER}; "
            f"selection-background-color: {_C_NAV_HOVER}; }}"
        )

    def _refresh_managed_tenants_list(self):
        """Rebuild the list of user-added tenants shown in the Manage Tenants card."""
        from src.config import is_user_added_tenant, load_config
        # Clear existing rows
        while self._managed_tenants_layout.count():
            item = self._managed_tenants_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            raw = load_config("config/settings.yaml")
            tenants = raw.get("tenants", {})
        except Exception:
            tenants = {}

        user_added = {k: v for k, v in tenants.items() if v.get("user_added", False)}

        if not user_added:
            lbl = QLabel("No custom tenants added yet.")
            lbl.setStyleSheet(f"color: {_C_TEXT_MUTED}; font-size: 12px; padding: 4px 0;")
            self._managed_tenants_layout.addWidget(lbl)
            return

        for key, block in user_added.items():
            display = block.get("display_name", key.upper())
            url = block.get("datasphere", {}).get("base_url", "")
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            lbl = QLabel(f"{display}    {url}")
            lbl.setStyleSheet(f"color: {_C_TEXT}; font-size: 12px;")
            row_layout.addWidget(lbl, 1)
            btn_remove = QPushButton("Remove")
            btn_remove.setFixedWidth(90)
            btn_remove.setStyleSheet(_btn_style("red"))
            btn_remove.clicked.connect(lambda checked, k=key, d=display: self._on_remove_tenant(k, d))
            row_layout.addWidget(btn_remove)
            self._managed_tenants_layout.addWidget(row)

    def _on_add_tenant(self):
        """Validate form and add the new tenant to settings.yaml."""
        from src.config import add_tenant
        name    = self._new_tenant_name.text().strip()
        url     = self._new_tenant_url.text().strip()
        region  = self._new_tenant_region.currentText()
        is_pub  = self._rb_public.isChecked()
        path_st = "dwaas-core" if self._rb_dwaas_core.isChecked() else "dwaas-ui"

        self._add_tenant_error.setVisible(False)

        try:
            key = add_tenant(
                display_name=name,
                base_url=url,
                dc_region=region,
                is_public=is_pub,
                path_style=path_st,
            )
        except ValueError as e:
            self._add_tenant_error.setText(str(e))
            self._add_tenant_error.setVisible(True)
            return
        except Exception as e:
            self._add_tenant_error.setText(f"Unexpected error: {e}")
            self._add_tenant_error.setVisible(True)
            return

        # Clear form
        self._new_tenant_name.clear()
        self._new_tenant_url.clear()
        self._new_tenant_region.setCurrentIndex(0)
        self._rb_internal.setChecked(True)
        self._rb_dwaas_ui.setChecked(True)

        # Refresh both the managed list and the active tenant checklist
        try:
            self._refresh_managed_tenants_list()
            self._rebuild_tenant_list_widget()
        except Exception as e:
            import traceback
            import logging
            logging.getLogger(__name__).error(
                f"Error refreshing tenant list after add:\n{traceback.format_exc()}"
            )
            self._add_tenant_error.setText(f"Tenant added but UI refresh failed: {e}")
            self._add_tenant_error.setVisible(True)
            return
        self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Tenant '{name}' (key: {key}) added successfully.")

    def _on_remove_tenant(self, tenant_key: str, display_name: str):
        """Confirm and remove a user-added tenant."""
        from src.config import remove_tenant

        # Use a custom dialog — the global stylesheet hides QMessageBox buttons.
        dlg = QDialog(self)
        dlg.setWindowTitle("Remove Tenant")
        dlg.setStyleSheet(f"background-color: {_C_BG}; color: {_C_TEXT};")
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setSpacing(16)
        dlg_layout.setContentsMargins(24, 20, 24, 20)

        msg = QLabel(f"Remove '{display_name}'?\n\nAll associated output files and session files will be deleted.")
        msg.setStyleSheet(f"color: {_C_TEXT}; font-size: 13px;")
        msg.setWordWrap(True)
        dlg_layout.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(_btn_style("blue"))
        btn_cancel.clicked.connect(dlg.reject)
        btn_confirm = QPushButton("Remove")
        btn_confirm.setStyleSheet(_btn_style("red"))
        btn_confirm.clicked.connect(dlg.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_confirm)
        dlg_layout.addLayout(btn_row)

        if dlg.exec_() != QDialog.Accepted:
            return
        try:
            remove_tenant(tenant_key)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not remove tenant: {e}")
            return

        self._refresh_managed_tenants_list()
        self._rebuild_tenant_list_widget()
        self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Tenant '{display_name}' removed.")

    def _rebuild_tenant_list_widget(self):
        """Reload the active tenants checklist from settings.yaml after add/remove."""
        from src.config import load_config
        self._tenant_list_widget.blockSignals(True)

        # Preserve existing check states so unchecked tenants stay unchecked.
        prev_states = {
            self._tenant_list_widget.item(i).data(Qt.UserRole):
                self._tenant_list_widget.item(i).checkState()
            for i in range(self._tenant_list_widget.count())
        }

        self._tenant_list_widget.clear()

        try:
            raw = load_config("config/settings.yaml")
            tenants = raw.get("tenants", {})
        except Exception:
            tenants = {}

        _BUILTIN_DISPLAY = {
            "eu10": "EU10(1)", "eu10_2": "EU10(2)",
            "us10": "US10(1)", "us10_2": "US10(2)",
            "ap11": "AP11(1)", "ap11_2": "AP11(2)",
        }

        for key, block in tenants.items():
            display = block.get("display_name") or _BUILTIN_DISPLAY.get(key, key.upper())
            try:
                url = block.get("datasphere", {}).get("base_url", "")
            except Exception:
                url = ""
            label = f"{display}    {url}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # New tenants default to Checked; existing tenants keep their prior state.
            item.setCheckState(prev_states.get(key, Qt.Checked))
            item.setData(Qt.UserRole, key)
            self._tenant_list_widget.addItem(item)

        row_count = self._tenant_list_widget.count()
        self._tenant_list_widget.setFixedHeight(row_count * 34 + 10)
        self._tenant_list_widget.blockSignals(False)
        self._on_tenant_selection_changed()

    def _build_pipeline_page(self):
        page = QWidget()
        page.setObjectName("panel")
        pl = QVBoxLayout(page)
        pl.setSpacing(0)
        pl.setContentsMargins(0, 0, 0, 0)
        self._page_header(pl, "Pipeline", f"FOUR-STAGE CLEANUP  ·  {self._tenants_label.upper()}")
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
            e.setFixedWidth(130)
            e.setStyleSheet(
                f"QLineEdit {{ background: white; color: {_C_TEXT}; "
                f"border: 1px solid #CED2D9; border-radius: 6px; "
                f"min-height: 36px; padding: 0 10px; font-size: 13px; }}"
                f"QLineEdit:hover {{ border-color: #ACB4BE; }}"
                f"QLineEdit:focus {{ border: 1px solid {_C_BLUE}; }}"
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

        region_row = QHBoxLayout()
        region_row.setSpacing(10)
        region_lbl = QLabel("DC Region:")
        region_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        region_lbl.setFixedWidth(110)
        self._dc_region_combo = QComboBox()
        self._dc_region_combo.addItems(["Use tenant default", "EU10", "US10", "AP11"])
        self._dc_region_combo.setFixedWidth(160)
        self._dc_region_combo.setStyleSheet(
            f"QComboBox {{ background: white; color: {_C_TEXT}; "
            f"border: 1px solid #CED2D9; border-radius: 6px; "
            f"min-height: 36px; padding: 0 10px; font-size: 13px; }}"
            f"QComboBox:hover {{ border-color: #ACB4BE; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        )
        region_row.addWidget(region_lbl)
        region_row.addWidget(self._dc_region_combo)
        region_row.addStretch()
        dl.addLayout(region_row)

        max_row = QHBoxLayout()
        max_row.setSpacing(10)
        max_lbl = QLabel("Max workshops:")
        max_lbl.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        self._max_workshops_edit = QLineEdit()
        self._max_workshops_edit.setPlaceholderText("e.g. 300 (blank = config default)")
        self._max_workshops_edit.setFixedWidth(200)
        self._max_workshops_edit.setStyleSheet(
            f"QLineEdit {{ background: white; color: {_C_TEXT}; "
            f"border: 1px solid #CED2D9; border-radius: 6px; "
            f"min-height: 36px; padding: 0 10px; font-size: 13px; }}"
            f"QLineEdit:hover {{ border-color: #ACB4BE; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C_BLUE}; }}"
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
        self._search_custom_edit.setStyleSheet(
            f"QLineEdit {{ background: white; color: {_C_TEXT}; "
            f"border: 1px solid #CED2D9; border-radius: 6px; "
            f"min-height: 32px; padding: 0 8px; font-size: 13px; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C_BLUE}; }}"
            f"QLineEdit:disabled {{ background: {_C_BG}; border-color: {_C_CARD_BORDER}; }}"
        )
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
             "Scrapes the SAP portal for expired trial users from cleaned workshops "
             "on the selected tenants and adds them to each tenant's sweep queue.",
             "Stage 1 — Discover", "blue", "_run_stage1", "btn_stage1"),
            ("STAGE 2 — DELETE",
             "Searches Datasphere for all spaces belonging to each pending workshop "
             "on the selected tenants and bulk-deletes them.",
             "Stage 2 — Delete", "blue", "_run_stage2", "btn_stage2"),
            ("STAGE 3 — VERIFY",
             "Re-checks every space reported as deleted on the selected tenants to confirm "
             "it is gone. Flags discrepancies for manual re-processing.",
             "Stage 3 — Verify", "blue", "_run_stage3", "btn_stage3"),
            ("STAGE 4 — PURGE",
             "Permanently removes from the Datasphere recycle bin on the selected tenants "
             "all spaces deleted by this tool that are 7+ days old.",
             "Stage 4 — Purge", "orange", "_run_stage4", "btn_stage4"),
        ]
        for sec, desc, btn_text, colour, handler, attr in stages:
            cl.addWidget(self._section_label(sec))
            card, l = self._card()
            l.addWidget(self._desc_label(desc))
            btn = self._btn(self._stage_label(btn_text), colour)
            btn.clicked.connect(getattr(self, handler))
            setattr(self, attr, btn)
            l.addWidget(btn)
            cl.addWidget(card)
        cl.addStretch()
        return page

    def _build_workshop_page(self):
        page = QWidget()
        page.setObjectName("panel")
        pl = QVBoxLayout(page)
        pl.setSpacing(0)
        pl.setContentsMargins(0, 0, 0, 0)
        self._page_header(pl, "Workshop Cleanup",
                          "TARGETED WORKSHOP LOOKUP  ·  ADDS TO SWEEP QUEUE")
        cl = self._scroll_content(pl)

        cl.addWidget(self._section_label("FIND WORKSHOPS BY ID"))
        c, l = self._card()
        l.addWidget(self._desc_label(
            "Add one or more 5–7 digit workshop IDs to the queue, then launch. "
            "Each workshop is looked up in order and added to each tenant's sweep queue."))

        # Input row: text field + Add button
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._workshop_id_input = QLineEdit()
        self._workshop_id_input.setPlaceholderText("Workshop ID (5–7 digits)")
        self._workshop_id_input.setFixedHeight(36)
        self._workshop_id_input.setStyleSheet(
            f"QLineEdit {{ background: white; color: {_C_TEXT}; "
            f"border: 1px solid #CED2D9; border-radius: 6px; "
            f"min-height: 36px; padding: 0 10px; font-size: 13px; }}"
            f"QLineEdit:hover {{ border-color: #ACB4BE; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C_BLUE}; }}"
        )
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
            f"QListWidget {{ background: #FFFFFF; color: {_C_TEXT}; "
            f"border: 1px solid {_C_CARD_BORDER}; border-radius: 6px; font-size: 13px; }}"
            f"QListWidget::item {{ padding: 5px 8px; }}"
            f"QListWidget::item:selected {{ background-color: {_C_NAV_ACTIVE}; color: {_C_TEXT}; }}"
            f"QListWidget::item:hover {{ background-color: {_C_NAV_HOVER}; }}"
        )
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
        self.btn_workshop_scrape = self._btn(self._stage_label("Launch (0)"), "blue")
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
        self.btn_workshop_scrape.setText(self._stage_label(f"Launch ({len(self._workshop_queue)})"))
        self.btn_workshop_scrape.setEnabled(len(self._active_tenants) > 0)

    def _remove_from_workshop_queue(self):
        selected = self._workshop_queue_widget.selectedItems()
        if not selected:
            return
        item = selected[0]
        workshop_id = item.text()
        row = self._workshop_queue_widget.row(item)
        self._workshop_queue_widget.takeItem(row)
        self._workshop_queue.remove(workshop_id)
        self.btn_workshop_scrape.setText(self._stage_label(f"Launch ({len(self._workshop_queue)})"))
        self.btn_workshop_scrape.setEnabled(len(self._workshop_queue) > 0 and len(self._active_tenants) > 0)

    # ── Sidebar navigation ─────────────────────────────────────────────────────

    def _switch_section(self, idx: int):
        self._stack.setCurrentIndex(idx)
        from src.theme_apply import set_nav_active
        from PyQt5.QtGui import QIcon
        for i, btn in enumerate(self._nav_buttons):
            set_nav_active(btn, i == idx)
            active_icon, grey_icon = self._nav_icons[i]
            btn.setIcon(QIcon(active_icon if i == idx else grey_icon))

    # ── Logging ────────────────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        self.log_box.append(msg)

    def log(self, msg: str):
        self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")

    def _patch_combined_logger(self, tenant: str, run_id: str):
        """Install per-tenant file and GUI log handlers on the root logger.

        Called at the start of each run_tenant coroutine inside asyncio.gather().
        Both calls are made from different asyncio Tasks but the same OS thread,
        so we must not mutate the shared handler list non-atomically.

        Safety: we only remove our own prefix's handler (identified by both prefix
        string AND task identity) and add a fresh one. setup_logging is likewise
        keyed by (thread_ident=None, tenant=tenant) so EU10 and US10 maintain
        independent file handlers even though both pass thread_ident=None.
        """
        import logging as _logging
        import asyncio
        from src.logging_setup import setup_logging, ThreadFileHandler

        cfg = _load_cfg(tenant)
        # File logging — keyed by tenant so EU10 and US10 don't overwrite each other.
        setup_logging(
            logs_dir=cfg["outputs"]["logs_dir"],
            run_id=run_id,
            thread_ident=None,
            tenant=tenant,
        )
        # GUI logging — one _TenantLogHandler per tenant, filtered by asyncio Task.
        current_task = asyncio.current_task()
        prefix = f"[{tenant.upper()}]"
        # Set the routing contextvar for this tenant's task. Because run_tenant runs as a
        # distinct task under asyncio.gather, each tenant gets its own context, and any
        # child task spawned via asyncio.wait_for inherits this value — so per-workshop
        # 'found N user(s)' lines are routed to the GUI instead of dropped.
        _active_tenant_prefix.set(prefix)
        root = _logging.getLogger("datasphere-cleanup")
        # Replace only this tenant's handler — leave the other tenant's handler intact.
        # Build the new list and call addHandler once; never assign root.handlers directly
        # with a comprehension that could race with the other tenant's concurrent call.
        old = [h for h in list(root.handlers)
               if isinstance(h, _TenantLogHandler) and h._prefix == prefix]
        for h in old:
            root.removeHandler(h)
        new_h = _TenantLogHandler(self, prefix, task=current_task)
        new_h.setFormatter(_logging.Formatter("%(name)s: %(message)s"))
        root.addHandler(new_h)

    # ── Thread runners ─────────────────────────────────────────────────────────

    async def _gather_tenants(self, tenants, make_coro):
        """Run each tenant's coroutine concurrently, ISOLATING failures.

        Uses return_exceptions=True so one tenant raising cannot cancel a sibling that
        may be mid-deletion (which would leave that tenant's state half-written — a space
        deleted in SAP but never recorded in deleted_<tenant>.txt). Any per-tenant
        exception is logged with tenant attribution and surfaced to the GUI, so a failure
        is never silently swallowed. Returns the list of results/exceptions in order.
        """
        import asyncio
        results = await asyncio.gather(
            *[make_coro(t) for t in tenants], return_exceptions=True
        )
        for tenant, res in zip(tenants, results):
            if isinstance(res, BaseException):
                self._log_signal.emit(
                    f"[{tenant.upper()}] ERROR — this tenant's run failed and was isolated "
                    f"so other tenants could finish safely: {res!r}"
                )
        return results

    def _set_buttons_enabled(self, enabled: bool):
        for btn in (self.btn_sign_portal, self.btn_sign_ds,
                    self.btn_stage1, self.btn_stage2, self.btn_stage3, self.btn_stage4):
            btn.setEnabled(enabled)
        # Launch only re-enables if queue is non-empty
        self.btn_workshop_scrape.setEnabled(enabled and len(self._workshop_queue) > 0)
        if enabled:
            self._indicator.setText("● Idle")
            self._indicator.setStyleSheet("color: #6A6D70; font-size: 12px;")
            self._set_status_chip("idle")
        else:
            self._indicator.setText("● Running")
            self._indicator.setStyleSheet("color: #0A6ED1; font-size: 12px; font-weight: 600;")
            self._set_status_chip("running")

    def _set_status_chip(self, state: str):
        """Update the status chip colour and label. States: idle, running, success, error."""
        from src.theme_apply import set_status
        labels = {"idle": "Idle", "running": "Running", "success": "Done", "error": "Error"}
        self._status_chip.setText(labels.get(state, "Idle"))
        set_status(self._status_chip, state)
        set_status(self._status_dot, state)

    def _on_status_update(self, msg: str):
        self.status_lbl.setText(msg)
        m = msg.lower()
        if "failed" in m or "error" in m or "abort" in m:
            self._set_status_chip("error")
        elif "complete" in m or "saved" in m or "scraped" in m or "swept" in m or "purged" in m:
            self._set_status_chip("success")

    def _run_concurrent(self, coro_fn, label: str):
        """Run an async coroutine in a QThread via asyncio.run(). The coroutine should
        use asyncio.gather() internally to run both tenants concurrently."""
        if self._threads_running > 0:
            self.log("A task is already running — please wait.")
            return
        self._threads_running = 1
        self._buttons_signal.emit(False)
        self._status_signal.emit(f"{label} running…")
        self.log(f"── {label} started ──")

        def sync_wrapper():
            import asyncio
            asyncio.run(coro_fn())

        self._thread_eu10 = QThread()
        self._worker_eu10 = Worker(sync_wrapper)
        self._worker_eu10.moveToThread(self._thread_eu10)
        self._thread_eu10.started.connect(self._worker_eu10.run)
        self._worker_eu10.error_signal.connect(lambda e: self.log(f"ERROR: {e}"))
        self._worker_eu10.error_signal.connect(
            lambda e: self._status_signal.emit(f"{label} failed")
        )
        self._worker_eu10.done_signal.connect(self._on_one_thread_done)
        self._thread_eu10.start()
        self._thread_us10 = None

    def _run_single(self, fn, label: str):
        """Run a synchronous task (sign-in — human-in-the-loop, must stay serial)."""
        if self._threads_running > 0:
            self.log("A task is already running — please wait.")
            return
        self._threads_running = 1
        self._buttons_signal.emit(False)
        self._status_signal.emit(f"{label} running…")
        self.log(f"── {label} started ──")
        self._thread_eu10 = QThread()
        self._worker_eu10 = Worker(fn)
        self._worker_eu10.moveToThread(self._thread_eu10)
        self._thread_eu10.started.connect(self._worker_eu10.run)
        self._worker_eu10.error_signal.connect(lambda e: self.log(f"ERROR: {e}"))
        self._worker_eu10.error_signal.connect(
            lambda e: self._status_signal.emit(f"{label} failed")
        )
        self._worker_eu10.done_signal.connect(self._on_one_thread_done)
        self._thread_eu10.start()
        self._thread_us10 = None

    def _on_one_thread_done(self):
        self._threads_running -= 1
        if self._threads_running == 0:
            self._buttons_signal.emit(True)
            if self._thread_eu10 is not None:
                self._thread_eu10.quit()
                self._thread_eu10.wait()
            self._thread_eu10 = None
            self._thread_us10 = None

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
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK — Session Saved")
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)
        dlg.exec_()
        event.set()

    # ── Button handlers ────────────────────────────────────────────────────────

    def _run_sign_in_portal(self):
        def task():
            import asyncio
            from src.auth import save_portal_session
            for tenant in self._active_tenants:
                cfg = _load_cfg(tenant)
                ready = threading.Event()
                self.log(f"[{tenant.upper()}] Browser opening — log in to Portal, then click OK.")
                self._dialog_signal.emit(
                    f"Sign In — Portal ({tenant.upper()})",
                    f"A browser has opened.\n\nLog in to the SAP portal for {tenant.upper()}, "
                    "then click 'OK — Session Saved' to save your session.",
                    ready,
                )
                asyncio.run(save_portal_session(cfg, wait_callback=lambda: ready.wait()))
                self.log(f"[{tenant.upper()}] Portal session saved.")
            tenants = ", ".join(t.upper() for t in self._active_tenants)
            self._status_signal.emit(f"Portal sessions saved ({tenants})")
        self._run_single(task, "Sign In Portal — All Tenants")

    def _run_sign_in_datasphere(self):
        def task():
            import asyncio
            from src.auth import save_datasphere_session
            for tenant in self._active_tenants:
                cfg = _load_cfg(tenant)
                ready = threading.Event()
                self.log(f"[{tenant.upper()}] Browser opening — log in to Datasphere, then click OK.")
                self._dialog_signal.emit(
                    f"Sign In — Datasphere ({tenant.upper()})",
                    f"A browser has opened.\n\nLog in to Datasphere Space Management for {tenant.upper()}, "
                    "then click 'OK — Session Saved' to save your session.",
                    ready,
                )
                asyncio.run(save_datasphere_session(cfg, wait_callback=lambda: ready.wait()))
                self.log(f"[{tenant.upper()}] Datasphere session saved.")
            tenants = ", ".join(t.upper() for t in self._active_tenants)
            self._status_signal.emit(f"Datasphere sessions saved ({tenants})")
        self._run_single(task, "Sign In Datasphere — All Tenants")

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
        _dc_sel = self._dc_region_combo.currentText()
        dc_region_override = None if _dc_sel == "Use tenant default" else _dc_sel

        async def task():
            import asyncio
            from src.stage1_discovery import _run_stage1_async
            from src.portal_client import load_pending_workshops

            async def run_tenant(tenant):
                cfg = _load_cfg(tenant, self._demo_mode)
                cfg["portal"]["start_date_from"] = start_date_from
                cfg["portal"]["start_date_to"]   = start_date_to
                cfg["portal"]["end_date_from"]   = end_date_from
                cfg["portal"]["end_date_to"]     = end_date_to
                cfg["portal"]["workshop_id_from"] = workshop_id_from
                cfg["portal"]["workshop_id_to"]   = workshop_id_to
                cfg["portal"]["search_term"] = search_term
                if dc_region_override is not None:
                    cfg["portal"]["dc_region"] = dc_region_override
                run_id = f"{tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                self._patch_combined_logger(tenant, run_id)
                def on_progress(msg: str) -> None:
                    self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] [{tenant.upper()}] {msg}")
                await _run_stage1_async(cfg=cfg, run_id=run_id, max_workshops=5 if self._demo_mode else max_workshops_override, progress_callback=on_progress)
                pending_count = len(load_pending_workshops(cfg))
                self.log(
                    f"[{tenant.upper()}] Stage 1 complete — "
                    f"{pending_count} workshop(s) in pending-sweep queue"
                )

            tenants = self._active_tenants
            await self._gather_tenants(tenants, run_tenant)
            label = " + ".join(t.upper() for t in tenants)
            self._status_signal.emit(f"Stage 1 complete ({label})")
        self._run_concurrent(task, "Stage 1 — Discover")

    def _run_workshop_scrape(self):
        if not self._workshop_queue:
            self.log("Workshop queue is empty — add at least one workshop ID first.")
            return

        queue = list(self._workshop_queue)

        search_term = self._selected_search_term()

        async def task():
            import asyncio
            from src.stage1_discovery import _run_workshop_scrape_async
            from src.portal_client import load_pending_workshops

            for workshop_id in queue:
                async def run_tenant(tenant, wid=workshop_id):
                    cfg = _load_cfg(tenant, self._demo_mode)
                    cfg["portal"]["search_term"] = search_term
                    run_id = f"{tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                    self._patch_combined_logger(tenant, run_id)
                    def on_progress(msg: str) -> None:
                        self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] [{tenant.upper()}] {msg}")
                    await _run_workshop_scrape_async(workshop_id=wid, cfg=cfg, run_id=run_id, progress_callback=on_progress)
                    pending_count = len(load_pending_workshops(cfg))
                    self.log(
                        f"[{tenant.upper()}] Workshop {wid} scraped — "
                        f"{pending_count} workshop(s) in pending-sweep queue"
                    )

                tenants = self._active_tenants
                await self._gather_tenants(tenants, run_tenant)
                self._status_signal.emit(f"Workshop {workshop_id} scraped ({' + '.join(t.upper() for t in tenants)})")

            self._status_signal.emit(f"{len(queue)} workshop(s) scraped ({' + '.join(t.upper() for t in self._active_tenants)})")

        # Clear the queue in the UI now that we've captured it
        self._workshop_queue.clear()
        self._workshop_queue_widget.clear()
        self.btn_workshop_scrape.setText(self._stage_label("Launch (0)"))
        self.btn_workshop_scrape.setEnabled(False)

        label = f"Scrape {len(queue)} Workshop(s)"
        self._run_concurrent(task, label)

    def _run_stage2(self):
        from src.portal_client import load_pending_workshops
        tenants = self._active_tenants
        counts = {}
        for t in tenants:
            try:
                counts[t] = len(load_pending_workshops(_load_cfg(t, self._demo_mode)))
            except Exception as exc:
                self.log(f"ERROR reading {t.upper()} sweep queue — {exc}")
                return
        if all(counts[t] == 0 for t in tenants):
            self.log("All sweep queues are empty — run Stage 1 first.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm Deletion — All Tenants")
        dlg.setMinimumWidth(440)
        dlg.setStyleSheet(self._dlg_stylesheet(_C_RED, _C_RED_HOVER))
        dl = QVBoxLayout(dlg)
        dl.setSpacing(16)
        dl.setContentsMargins(20, 20, 20, 20)
        counts_text = "  |  ".join(f"{t.upper()}: {counts[t]} workshop(s)" for t in tenants)
        lbl = QLabel(
            f"{counts_text} in sweep queues.\n\n"
            "This will permanently delete Datasphere spaces on ALL tenants.\n\nProceed?"
        )
        lbl.setWordWrap(True)
        dl.addWidget(lbl)
        chk = QCheckBox("Preview only — no changes will be made")
        chk.setChecked(False)
        dl.addWidget(chk)
        br = QHBoxLayout()
        bn = QPushButton("Cancel")
        bn.setObjectName("cancel")
        bn.clicked.connect(dlg.reject)
        by = QPushButton("Yes, proceed")
        by.setObjectName("confirm")
        by.clicked.connect(dlg.accept)
        br.addWidget(bn)
        br.addWidget(by)
        dl.addLayout(br)
        if dlg.exec_() != QDialog.Accepted:
            return
        self._do_run_stage2(dry_run=chk.isChecked())

    def _do_run_stage2(self, dry_run: bool = False):
        async def task():
            import asyncio
            from src.stage2_deletion import _run_stage2_workshops_async
            from src.portal_client import load_pending_workshops
            from src.report import generate_report

            async def run_tenant(tenant):
                cfg = _load_cfg(tenant, self._demo_mode)
                run_id = f"{tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                self._patch_combined_logger(tenant, run_id)
                def on_progress(msg: str) -> None:
                    self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] [{tenant.upper()}] {msg}")
                # SAFETY GATE (mirror of the CLI): a live deletion requires BOTH
                # cfg["dry_run"] is False AND the user explicitly asking for live (the
                # dialog's dry-run box left unchecked → dry_run arg is False). If config
                # says dry_run:true, force dry-run regardless of the checkbox, so a
                # default click-through can never delete live data.
                cfg_dry_run = cfg.get("dry_run", True)
                effective_dry_run = dry_run or cfg_dry_run
                if not dry_run and cfg_dry_run:
                    self.log(
                        f"[{tenant.upper()}] Config has dry_run set to true — forcing preview mode. "
                        f"Set dry_run to false in config to enable live deletions."
                    )
                if effective_dry_run:
                    self.log(f"[{tenant.upper()}] PREVIEW MODE: no spaces will be deleted")
                results = await _run_stage2_workshops_async(
                    cfg=cfg, dry_run=effective_dry_run, run_id=run_id,
                    progress_callback=on_progress,
                )
                report_path = generate_report(
                    results=results, run_id=run_id,
                    reports_dir=cfg["outputs"]["reports_dir"],
                    dry_run=effective_dry_run,
                )
                # Store report path keyed by tenant for Stage 3 to pick up
                setattr(self, f"_stage2_report_{tenant}", report_path)
                d  = sum(1 for r in results if r.outcome == "deleted")
                fa = sum(1 for r in results if r.outcome == "failed")
                sk = sum(1 for r in results if r.outcome == "skipped_dry_run")
                rem = len(load_pending_workshops(cfg))
                if effective_dry_run:
                    self.log(
                        f"[{tenant.upper()}] Stage 2 preview complete — "
                        f"{sk} would delete, {fa} failed, {rem} workshop(s) remaining"
                    )
                else:
                    self.log(
                        f"[{tenant.upper()}] Stage 2 complete — "
                        f"{d} deleted, {fa} failed, {rem} workshop(s) remaining"
                    )

            tenants = self._active_tenants
            await self._gather_tenants(tenants, run_tenant)
            label = " + ".join(t.upper() for t in tenants)
            self._status_signal.emit(
                f"Stage 2 preview complete ({label})" if dry_run else f"Stage 2 complete ({label})"
            )
        self._run_concurrent(task, "Stage 2 — Dry Run" if dry_run else "Stage 2 — Delete")

    def _run_stage3(self):
        tenants = self._active_tenants
        reports = {}
        for tenant in tenants:
            report_attr = f"_stage2_report_{tenant}"
            r = getattr(self, report_attr, None)
            if not r:
                cfg = _load_cfg(tenant, self._demo_mode)
                found = sorted(
                    Path(cfg["outputs"]["reports_dir"]).glob(f"report_{tenant}_*.json"),
                    reverse=True,
                )
                if not found:
                    self.log(f"[{tenant.upper()}] No Stage 2 report found — run Stage 2 first.")
                    return
                r = str(found[0])
                setattr(self, report_attr, r)
                self.log(f"[{tenant.upper()}] Using most recent report: {Path(r).name}")
            reports[tenant] = r

        async def task():
            import asyncio, json
            from src.stage3_verify import _run_stage3_async

            async def run_tenant(tenant):
                cfg = _load_cfg(tenant, self._demo_mode)
                run_id = f"{tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                self._patch_combined_logger(tenant, run_id)
                def on_progress(msg: str) -> None:
                    self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] [{tenant.upper()}] {msg}")
                vpath = await _run_stage3_async(report_path=reports[tenant], cfg=cfg, run_id=run_id, progress_callback=on_progress)
                with open(vpath, encoding="utf-8") as f:
                    v = json.load(f)["summary"]
                self.log(
                    f"[{tenant.upper()}] Stage 3 complete — "
                    f"{v['confirmed_deleted']} confirmed, "
                    f"{v['still_exists']} still exist, "
                    f"{v['check_failed']} check failed"
                )

            tenants = self._active_tenants
            await self._gather_tenants(tenants, run_tenant)
            label = " + ".join(t.upper() for t in tenants)
            self._status_signal.emit(f"Stage 3 complete ({label})")
        self._run_concurrent(task, "Stage 3 — Verify")

    def _run_stage4(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm Recycle Bin Purge — All Tenants")
        dlg.setMinimumWidth(460)
        dlg.setStyleSheet(self._dlg_stylesheet(_C_ORANGE, _C_ORANGE_HOVER))
        dl = QVBoxLayout(dlg)
        dl.setSpacing(16)
        dl.setContentsMargins(20, 20, 20, 20)
        lbl = QLabel(
            "Permanently delete from the Datasphere recycle bin (on ALL tenants) "
            "all spaces deleted by this tool.\n\n"
            "Spaces deleted by others will not be touched.\n\nThis cannot be undone. Proceed?"
        )
        lbl.setWordWrap(True)
        dl.addWidget(lbl)
        spin_style = (f"QSpinBox {{ background: white; color: {_C_TEXT}; "
                      f"border: 1px solid {_C_CARD_BORDER}; border-radius: 4px; padding: 3px 6px; }}")
        lr = QHBoxLayout()
        ll = QLabel("Max spaces to purge per tenant (0 = no limit):")
        ll.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        spin = QSpinBox()
        spin.setRange(0, 9999)
        spin.setValue(10)
        spin.setStyleSheet(spin_style)
        lr.addWidget(ll)
        lr.addWidget(spin)
        dl.addLayout(lr)
        ar = QHBoxLayout()
        al = QLabel("Min age (days, 0 = purge all):")
        al.setStyleSheet(f"color: {_C_TEXT_DIM}; font-size: 12px;")
        age_spin = QSpinBox()
        age_spin.setRange(0, 365)
        age_spin.setValue(7)
        age_spin.setStyleSheet(spin_style)
        ar.addWidget(al)
        ar.addWidget(age_spin)
        dl.addLayout(ar)
        chk = QCheckBox("Preview only — no changes will be made")
        chk.setChecked(False)
        dl.addWidget(chk)
        br = QHBoxLayout()
        bn = QPushButton("Cancel")
        bn.setObjectName("cancel")
        bn.clicked.connect(dlg.reject)
        by = QPushButton("Yes, proceed")
        by.setObjectName("confirm")
        by.clicked.connect(dlg.accept)
        br.addWidget(bn)
        br.addWidget(by)
        dl.addLayout(br)
        if dlg.exec_() != QDialog.Accepted:
            return

        dry_run = chk.isChecked()
        max_purge = spin.value()
        min_age = age_spin.value()

        async def task():
            import asyncio
            from src.stage4_purge import _run_stage4_async

            async def run_tenant(tenant):
                cfg = _load_cfg(tenant, self._demo_mode)
                run_id = f"{tenant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                self._patch_combined_logger(tenant, run_id)
                def on_progress(msg: str) -> None:
                    self._log_signal.emit(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] [{tenant.upper()}] {msg}")
                if dry_run:
                    self.log(f"[{tenant.upper()}] PREVIEW MODE: no spaces will be permanently deleted")
                if max_purge > 0:
                    self.log(f"[{tenant.upper()}] Stopping after {max_purge} space(s)")
                if min_age == 0:
                    self.log(f"[{tenant.upper()}] Min age set to 0 — purging all deleted spaces regardless of age")
                results = await _run_stage4_async(cfg=cfg, dry_run=dry_run, run_id=run_id, max_purge=max_purge, min_age_days=min_age, progress_callback=on_progress)
                pu = sum(1 for r in results if r.outcome == "purged")
                dr = sum(1 for r in results if r.outcome == "skipped_dry_run")
                sk = sum(1 for r in results if r.outcome == "skipped_not_ours")
                fa = sum(1 for r in results if r.outcome == "failed")
                if dry_run:
                    self.log(f"[{tenant.upper()}] Stage 4 preview — {dr} would purge, {sk} skipped (not ours), {fa} failed")
                else:
                    self.log(f"[{tenant.upper()}] Stage 4 complete — {pu} purged, {sk} skipped (not ours), {fa} failed")

            tenants = self._active_tenants
            await self._gather_tenants(tenants, run_tenant)
            label = " + ".join(t.upper() for t in tenants)
            self._status_signal.emit(
                f"Stage 4 dry-run complete ({label})" if dry_run else f"Stage 4 complete ({label})"
            )
        self._run_concurrent(task, "Stage 4 — Dry Run" if dry_run else "Stage 4 — Purge")


def main(demo_mode: bool = False):
    from src.config import setup_app_home
    setup_app_home()
    app = QApplication(sys.argv)
    # Load compiled Qt resources (SAP logo, nav icons) before applying the theme.
    try:
        from src import resources_rc  # noqa: F401
    except Exception as e:
        print(f"[combined] Warning: could not load resources_rc: {e}")
    from src.theme_apply import apply_theme
    apply_theme(app)
    window = CombinedApp(demo_mode=demo_mode)
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec_())


def main_demo():
    main(demo_mode=True)


if __name__ == "__main__":
    main()
