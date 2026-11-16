"""界面主题引擎：明暗语义 Design Token、跨平台等宽字体、QPalette 与集中式 QSS。

职责：
- 提供克制务实的 Light / Dark 双色板（无大面积渐变或半透明花哨装饰）；
- 监听系统 ``QStyleHints.colorSchemeChanged``，在运行期同步切换调色板与全局样式表，
  并发出 :attr:`ThemeManager.theme_changed` 通知需要重绘的组件（如日志表格、Markdown 对话区）；
- 统一在 ``Fusion`` 基准风格上渲染，确保 Windows / macOS / Linux 观感一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from serial_log_analyzer.core.models.logs import LogLevel

__all__ = [
    "DARK_TOKENS",
    "LIGHT_TOKENS",
    "LevelStyle",
    "ThemeManager",
    "ThemeTokens",
    "build_palette",
    "build_qss",
    "default_tokens",
    "level_styles",
    "monospace_font",
    "resolve_color_scheme",
    "tokens_for_scheme",
]

_MONOSPACE_FAMILIES = [
    "Cascadia Mono",
    "Consolas",
    "SF Mono",
    "Menlo",
    "JetBrains Mono",
    "DejaVu Sans Mono",
    "Courier New",
]


@dataclass(frozen=True)
class LevelStyle:
    """单条日志级别在当前主题下的语义视觉色。

    参数:
        foreground: 级别文本与胶囊文字颜色。
        pill_bg: 级别胶囊低饱和底色。
        row_bg: 高严重度行的微弱提示底色；普通级别为 ``None``。
    """

    foreground: str
    pill_bg: str
    row_bg: str | None = None


@dataclass(frozen=True)
class ThemeTokens:
    """界面语义配色与层级 Token（严禁大面积渐变与重阴影）。"""

    scheme: str
    bg_canvas: str
    bg_surface: str
    bg_elevated: str
    bg_subtle: str
    bg_pressed: str
    border_subtle: str
    border_strong: str
    border_focus: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_on_accent: str
    accent_primary: str
    accent_hover: str
    accent_soft: str
    success: str
    success_bg: str
    warning: str
    warning_bg: str
    danger: str
    danger_hover: str
    danger_bg: str
    info: str
    info_bg: str
    level_verbose: str
    level_verbose_bg: str
    level_debug: str
    level_debug_bg: str
    level_info: str
    level_info_bg: str
    level_warn: str
    level_warn_bg: str
    level_warn_row_bg: str
    level_error: str
    level_error_bg: str
    level_error_row_bg: str
    level_unknown: str
    level_unknown_bg: str


LIGHT_TOKENS = ThemeTokens(
    scheme="light",
    bg_canvas="#F3F5F8",
    bg_surface="#FFFFFF",
    bg_elevated="#F8FAFC",
    bg_subtle="#EAEFF5",
    bg_pressed="#DCE4EE",
    border_subtle="#D8E0EA",
    border_strong="#C3CEDC",
    border_focus="#2563EB",
    text_primary="#0F172A",
    text_secondary="#475569",
    text_muted="#64748B",
    text_on_accent="#FFFFFF",
    accent_primary="#2563EB",
    accent_hover="#1D4ED8",
    accent_soft="#DBEAFE",
    success="#15803D",
    success_bg="#DCFCE7",
    warning="#B45309",
    warning_bg="#FEF3C7",
    danger="#DC2626",
    danger_hover="#B91C1C",
    danger_bg="#FEE2E2",
    info="#0369A1",
    info_bg="#E0F2FE",
    level_verbose="#64748B",
    level_verbose_bg="#F1F5F9",
    level_debug="#2563EB",
    level_debug_bg="#DBEAFE",
    level_info="#15803D",
    level_info_bg="#DCFCE7",
    level_warn="#B45309",
    level_warn_bg="#FEF3C7",
    level_warn_row_bg="#FFFBEB",
    level_error="#DC2626",
    level_error_bg="#FEE2E2",
    level_error_row_bg="#FEF2F2",
    level_unknown="#7C3AED",
    level_unknown_bg="#EDE9FE",
)

DARK_TOKENS = ThemeTokens(
    scheme="dark",
    bg_canvas="#13161C",
    bg_surface="#1A1E26",
    bg_elevated="#222732",
    bg_subtle="#2A303D",
    bg_pressed="#343B4A",
    border_subtle="#2C3341",
    border_strong="#3B4454",
    border_focus="#3B82F6",
    text_primary="#E6EDF5",
    text_secondary="#A3B1C2",
    text_muted="#7D8B9D",
    text_on_accent="#FFFFFF",
    accent_primary="#3B82F6",
    accent_hover="#2563EB",
    accent_soft="#1E3A5F",
    success="#4ADE80",
    success_bg="#173324",
    warning="#FBBF24",
    warning_bg="#382B16",
    danger="#F87171",
    danger_hover="#EF4444",
    danger_bg="#3B1D22",
    info="#38BDF8",
    info_bg="#162E3F",
    level_verbose="#94A3B8",
    level_verbose_bg="#252B36",
    level_debug="#60A5FA",
    level_debug_bg="#1A2E4C",
    level_info="#4ADE80",
    level_info_bg="#173324",
    level_warn="#FBBF24",
    level_warn_bg="#382B16",
    level_warn_row_bg="#241E14",
    level_error="#F87171",
    level_error_bg="#3B1D22",
    level_error_row_bg="#29171B",
    level_unknown="#C084FC",
    level_unknown_bg="#2E2042",
)


def level_styles(tokens: ThemeTokens) -> dict[LogLevel, LevelStyle]:
    """按主题 Token 生成日志级别到前景色/胶囊底色/行底色的映射表。"""

    return {
        LogLevel.VERBOSE: LevelStyle(tokens.level_verbose, tokens.level_verbose_bg),
        LogLevel.DEBUG: LevelStyle(tokens.level_debug, tokens.level_debug_bg),
        LogLevel.INFO: LevelStyle(tokens.level_info, tokens.level_info_bg),
        LogLevel.WARN: LevelStyle(
            tokens.level_warn, tokens.level_warn_bg, tokens.level_warn_row_bg
        ),
        LogLevel.ERROR: LevelStyle(
            tokens.level_error, tokens.level_error_bg, tokens.level_error_row_bg
        ),
        LogLevel.UNKNOWN: LevelStyle(tokens.level_unknown, tokens.level_unknown_bg),
    }


def monospace_font(point_size: float | None = None) -> QFont:
    """构造跨平台等宽字体（带字体栈回退）。"""

    font = QFont()
    font.setFamilies(_MONOSPACE_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    if point_size is not None and point_size > 0:
        font.setPointSizeF(point_size)
    return font


def resolve_color_scheme(
    app: QGuiApplication | None = None,
    scheme: Qt.ColorScheme | None = None,
) -> Qt.ColorScheme:
    """解析生效的明暗模式；``Unknown`` 时按当前调色板窗口亮度回退。"""

    target = scheme
    if target is None and app is not None:
        hints = app.styleHints()
        if hints is not None:
            target = hints.colorScheme()
    if target in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        return target
    if app is not None:
        window_color = app.palette().color(QPalette.ColorRole.Window)
        if window_color.lightness() < 128:
            return Qt.ColorScheme.Dark
    return Qt.ColorScheme.Light


def tokens_for_scheme(scheme: Qt.ColorScheme) -> ThemeTokens:
    """返回指定 :class:`Qt.ColorScheme` 对应的 Token 集合。"""

    return DARK_TOKENS if scheme is Qt.ColorScheme.Dark else LIGHT_TOKENS


def default_tokens() -> ThemeTokens:
    """按当前运行中的应用探测默认 Token；无应用实例时返回浅色 Token。"""

    app = QGuiApplication.instance()
    if isinstance(app, QGuiApplication):
        return tokens_for_scheme(resolve_color_scheme(app))
    return LIGHT_TOKENS


def build_palette(tokens: ThemeTokens) -> QPalette:
    """根据 ``tokens`` 构造完整 ``QPalette``（含禁用态角色）。"""

    palette = QPalette()
    canvas = QColor(tokens.bg_canvas)
    surface = QColor(tokens.bg_surface)
    elevated = QColor(tokens.bg_elevated)
    subtle = QColor(tokens.bg_subtle)
    border = QColor(tokens.border_strong)
    text = QColor(tokens.text_primary)
    muted = QColor(tokens.text_muted)
    accent = QColor(tokens.accent_primary)
    soft_accent = QColor(tokens.accent_soft)

    active_roles = {
        QPalette.ColorRole.Window: canvas,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: surface,
        QPalette.ColorRole.AlternateBase: elevated,
        QPalette.ColorRole.ToolTipBase: elevated,
        QPalette.ColorRole.ToolTipText: text,
        QPalette.ColorRole.PlaceholderText: muted,
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: elevated,
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.BrightText: QColor(tokens.text_on_accent),
        QPalette.ColorRole.Highlight: soft_accent,
        QPalette.ColorRole.HighlightedText: text,
        QPalette.ColorRole.Link: accent,
        QPalette.ColorRole.Mid: border,
        QPalette.ColorRole.Light: subtle,
        QPalette.ColorRole.Dark: border,
        QPalette.ColorRole.Shadow: muted,
    }
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, color in active_roles.items():
            palette.setColor(group, role, color)

    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window, canvas)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, elevated)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, subtle)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, muted)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, subtle)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, muted)
    return palette


def build_qss(tokens: ThemeTokens) -> str:
    """生成全应用统一的克制 QSS 样式表。

    不针对裸 ``QWidget`` 全局设背景色，避免覆盖局部 ``setAutoFillBackground(True)``
    的次要容器调色板。
    """

    t = tokens
    return f"""
QMainWindow {{
    background-color: {t.bg_canvas};
    color: {t.text_primary};
}}
QMainWindow::separator {{
    background-color: {t.border_subtle};
    width: 1px;
    height: 1px;
}}
QMenuBar {{
    background-color: {t.bg_canvas};
    color: {t.text_primary};
    border-bottom: 1px solid {t.border_subtle};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {t.bg_subtle};
}}
QMenu {{
    background-color: {t.bg_surface};
    color: {t.text_primary};
    border: 1px solid {t.border_strong};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 20px 5px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {t.accent_soft};
    color: {t.text_primary};
}}
QMenu::separator {{
    height: 1px;
    background-color: {t.border_subtle};
    margin: 4px 8px;
}}
QToolBar {{
    background-color: {t.bg_canvas};
    border: none;
    border-bottom: 1px solid {t.border_subtle};
    spacing: 6px;
    padding: 4px 8px;
}}
QStatusBar {{
    background-color: {t.bg_canvas};
    color: {t.text_secondary};
    border-top: 1px solid {t.border_subtle};
    padding: 2px 8px;
}}
QStatusBar::item {{
    border: none;
}}
QLabel[role="status-pill"] {{
    background-color: {t.bg_elevated};
    color: {t.text_secondary};
    border: 1px solid {t.border_subtle};
    border-radius: 4px;
    padding: 1px 8px;
    font-size: 11px;
}}
QToolButton#status-alerts {{
    background-color: {t.bg_elevated};
    color: {t.text_secondary};
    border: 1px solid {t.border_subtle};
    border-radius: 4px;
    padding: 1px 8px;
    font-size: 11px;
}}
QToolButton#status-alerts:hover {{
    background-color: {t.bg_subtle};
    color: {t.text_primary};
    border-color: {t.border_strong};
}}
QToolButton#status-alerts[alertState="warning"] {{
    background-color: {t.warning_bg};
    color: {t.warning};
    border-color: {t.warning};
    font-weight: 600;
}}
QToolButton#status-alerts[alertState="danger"] {{
    background-color: {t.danger_bg};
    color: {t.danger};
    border-color: {t.danger};
    font-weight: 600;
}}
#dock-title-bar {{
    background-color: {t.bg_elevated};
    border-top: 1px solid {t.border_subtle};
    border-bottom: 1px solid {t.border_subtle};
}}
#dock-title-label {{
    color: {t.text_secondary};
    font-weight: 600;
    font-size: 11px;
}}
#log-empty-title, #chat-empty-title, #anomaly-empty-title {{
    color: {t.text_secondary};
    font-weight: 600;
    font-size: 13px;
}}
#log-empty-hint, #chat-empty-hint, #anomaly-empty-hint {{
    color: {t.text_muted};
    font-size: 12px;
}}
QFrame#anomaly-alert-banner {{
    background-color: {t.warning_bg};
    border: 1px solid {t.warning};
    border-radius: 4px;
}}
QFrame#anomaly-alert-banner[severity="critical"],
QFrame#anomaly-alert-banner[severity="high"] {{
    background-color: {t.danger_bg};
    border-color: {t.danger};
}}
QFrame[role="section-divider"] {{
    background-color: {t.border_subtle};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QLabel[role="section-title"] {{
    color: {t.text_secondary};
    font-weight: 600;
    font-size: 12px;
    padding-top: 2px;
}}
QFrame#turn-card[role="user"] {{
    background-color: {t.bg_elevated};
    border: 1px solid {t.border_subtle};
    border-radius: 6px;
}}
QFrame#turn-card[role="assistant"] {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_subtle};
    border-left: 3px solid {t.accent_primary};
    border-radius: 6px;
}}
#collapsible-block {{
    border: 1px solid {t.border_subtle};
    border-radius: 4px;
}}
QFrame#chat-composer {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_strong};
    border-radius: 6px;
}}
QLabel[role="card-badge"] {{
    background-color: {t.bg_subtle};
    color: {t.text_secondary};
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel[role="muted-caption"] {{
    color: {t.text_muted};
    font-size: 11px;
}}
QToolButton[chip="cmd"] {{
    background-color: {t.bg_elevated};
    color: {t.text_secondary};
    border: 1px solid {t.border_subtle};
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
}}
QToolButton[chip="cmd"]:hover {{
    background-color: {t.bg_subtle};
    color: {t.text_primary};
    border-color: {t.border_strong};
}}
QDockWidget {{
    color: {t.text_primary};
}}
QDockWidget::title {{
    background-color: {t.bg_elevated};
    color: {t.text_secondary};
    border-top: 1px solid {t.border_subtle};
    border-bottom: 1px solid {t.border_subtle};
    padding: 5px 10px;
    font-weight: 600;
    text-align: left;
}}
QTabWidget::pane {{
    border: 1px solid {t.border_subtle};
    border-radius: 6px;
    background-color: {t.bg_surface};
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {t.text_secondary};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 6px 12px;
    margin-right: 2px;
    font-weight: 500;
}}
QTabBar::tab:hover {{
    color: {t.text_primary};
    background-color: {t.bg_subtle};
}}
QTabBar::tab:selected {{
    color: {t.text_primary};
    background-color: {t.bg_surface};
    border-bottom: 2px solid {t.accent_primary};
}}
QPushButton {{
    background-color: {t.bg_elevated};
    color: {t.text_primary};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    padding: 4px 12px;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {t.bg_subtle};
}}
QPushButton:pressed {{
    background-color: {t.bg_pressed};
}}
QPushButton:disabled {{
    background-color: {t.bg_subtle};
    color: {t.text_muted};
    border-color: {t.border_subtle};
}}
QPushButton[variant="primary"] {{
    background-color: {t.accent_primary};
    color: {t.text_on_accent};
    border-color: {t.accent_primary};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background-color: {t.accent_hover};
    border-color: {t.accent_hover};
}}
QPushButton[variant="primary"]:disabled {{
    background-color: {t.bg_subtle};
    color: {t.text_muted};
    border-color: {t.border_subtle};
}}
QPushButton[variant="danger"] {{
    background-color: {t.danger_bg};
    color: {t.danger};
    border-color: {t.danger};
    font-weight: 600;
}}
QPushButton[variant="danger"]:hover {{
    background-color: {t.danger};
    color: {t.text_on_accent};
}}
QPushButton[variant="danger"]:disabled {{
    background-color: {t.bg_subtle};
    color: {t.text_muted};
    border-color: {t.border_subtle};
}}
QPushButton[variant="ghost"] {{
    background-color: transparent;
    color: {t.text_secondary};
    border-color: transparent;
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {t.bg_subtle};
    color: {t.text_primary};
}}
QPushButton[compact="row"] {{
    padding: 1px 6px;
    min-height: 18px;
    font-size: 11px;
}}
QToolButton {{
    background-color: transparent;
    color: {t.text_secondary};
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px 6px;
}}
QToolButton:hover {{
    background-color: {t.bg_subtle};
    color: {t.text_primary};
}}
QToolButton:checked {{
    background-color: {t.accent_soft};
    color: {t.text_primary};
    border-color: {t.accent_primary};
}}
QToolButton[role="disclosure"],
QToolButton[role="disclosure"]:checked {{
    background-color: transparent;
    color: {t.text_secondary};
    border: 1px solid transparent;
    padding: 2px 4px;
    font-weight: 600;
}}
QToolButton[role="disclosure"]:hover {{
    background-color: {t.bg_subtle};
    color: {t.text_primary};
}}
QToolButton[chip="level"] {{
    background-color: transparent;
    color: {t.text_muted};
    border: 1px solid {t.border_subtle};
    border-radius: 10px;
    padding: 2px 8px;
}}
QToolButton[chip="level"]:hover {{
    background-color: {t.bg_subtle};
    color: {t.text_primary};
}}
QToolButton[chip="level"]:checked {{
    background-color: {t.bg_surface};
    color: {t.text_primary};
    border-color: {t.border_strong};
    font-weight: 500;
}}
QToolButton[chip="toggle"] {{
    background-color: transparent;
    color: {t.text_secondary};
    border: 1px solid {t.border_subtle};
    border-radius: 10px;
    padding: 2px 9px;
}}
QToolButton[chip="toggle"]:hover {{
    background-color: {t.bg_subtle};
    color: {t.text_primary};
}}
QToolButton[chip="toggle"]:checked {{
    background-color: {t.accent_soft};
    color: {t.text_primary};
    border-color: {t.accent_primary};
    font-weight: 500;
}}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: {t.bg_surface};
    color: {t.text_primary};
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: {t.accent_soft};
    selection-color: {t.text_primary};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {t.border_focus};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background-color: {t.bg_elevated};
    color: {t.text_muted};
    border-color: {t.border_subtle};
}}
QComboBox QAbstractItemView {{
    background-color: {t.bg_surface};
    color: {t.text_primary};
    border: 1px solid {t.border_strong};
    selection-background-color: {t.accent_soft};
    selection-color: {t.text_primary};
    outline: 0;
}}
QTableView {{
    background-color: {t.bg_surface};
    alternate-background-color: {t.bg_elevated};
    color: {t.text_primary};
    border: 1px solid {t.border_subtle};
    border-radius: 4px;
    gridline-color: {t.border_subtle};
    selection-background-color: {t.accent_soft};
    selection-color: {t.text_primary};
}}
QTableView::item:selected {{
    background-color: {t.accent_soft};
    color: {t.text_primary};
}}
QHeaderView::section {{
    background-color: {t.bg_elevated};
    color: {t.text_secondary};
    border: none;
    border-bottom: 1px solid {t.border_subtle};
    border-right: 1px solid {t.border_subtle};
    padding: 5px 8px;
    font-weight: 600;
}}
QScrollArea {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_subtle};
    border-radius: 4px;
}}
QGroupBox {{
    border: 1px solid {t.border_subtle};
    border-radius: 6px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
    color: {t.text_secondary};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QCheckBox, QRadioButton {{
    spacing: 6px;
    color: {t.text_primary};
}}
QCheckBox::indicator:unchecked {{
    width: 14px;
    height: 14px;
    border: 1px solid {t.border_strong};
    background-color: {t.bg_surface};
    border-radius: 3px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {t.text_muted};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.border_strong};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.text_muted};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t.border_strong};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t.text_muted};
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
    height: 0px;
    width: 0px;
}}
""".strip()


class ThemeManager(QObject):
    """集中式主题管理器：统一风格基底、响应系统明暗变化并广播 Token。

    参数:
        app: 当前 ``QApplication`` 实例。
        parent: 可选父对象。

    信号:
        theme_changed(object): 明暗主题切换后发出最新的 :class:`ThemeTokens`。
    """

    theme_changed = Signal(object)

    def __init__(self, app: QApplication, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._fusion_applied = False
        self._tokens = tokens_for_scheme(resolve_color_scheme(app))
        hints = app.styleHints()
        if hints is not None:
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)

    @property
    def tokens(self) -> ThemeTokens:
        """当前生效的主题 Token。"""

        return self._tokens

    def apply(self) -> ThemeTokens:
        """把当前 Token 应用到 ``QApplication``（Fusion 风格 + 调色板 + QSS）。"""

        if not self._fusion_applied:
            self._app.setStyle("Fusion")
            self._fusion_applied = True
        self._app.setPalette(build_palette(self._tokens))
        self._app.setStyleSheet(build_qss(self._tokens))
        return self._tokens

    def apply_scheme(self, scheme: Qt.ColorScheme) -> ThemeTokens:
        """显式切换明暗主题并刷新全局调色板、QSS 与观察者。"""

        resolved = resolve_color_scheme(self._app, scheme)
        self._tokens = tokens_for_scheme(resolved)
        self.apply()
        self.theme_changed.emit(self._tokens)
        return self._tokens

    def _on_system_scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        self.apply_scheme(scheme)
