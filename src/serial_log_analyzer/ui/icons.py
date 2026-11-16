"""内嵌 SVG 单色自适应图标渲染器（零额外外部依赖）。

基于 ``PySide6.QtSvg.QSvgRenderer`` 按目标颜色与逻辑尺寸在内存中渲染矢量图标，
同时生成 1x 与 2x 像素图，适配 HiDPI 与明暗主题切换。
"""

from __future__ import annotations

import functools

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

__all__ = ["available_icons", "render_icon", "render_pixmap"]

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="{color}" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)

_ICON_PATHS: dict[str, str] = {
    "refresh": (
        '<path d="M21 12a9 9 0 1 1-2.64-6.36"/>'
        '<polyline points="21 3 21 9 15 9"/>'
    ),
    "connect": (
        '<path d="M12 22v-5"/>'
        '<path d="M9 8V2"/>'
        '<path d="M15 8V2"/>'
        '<path d="M18 8v5a6 6 0 0 1-12 0V8z"/>'
    ),
    "disconnect": (
        '<path d="M18 6 6 18"/>'
        '<path d="m6 6 12 12"/>'
    ),
    "sliders": (
        '<line x1="4" y1="21" x2="4" y2="14"/>'
        '<line x1="4" y1="10" x2="4" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="12"/>'
        '<line x1="12" y1="8" x2="12" y2="3"/>'
        '<line x1="20" y1="21" x2="20" y2="16"/>'
        '<line x1="20" y1="12" x2="20" y2="3"/>'
        '<line x1="1" y1="14" x2="7" y2="14"/>'
        '<line x1="9" y1="8" x2="15" y2="8"/>'
        '<line x1="17" y1="16" x2="23" y2="16"/>'
    ),
    "search": (
        '<circle cx="11" cy="11" r="7"/>'
        '<path d="m21 21-4.35-4.35"/>'
    ),
    "clear": (
        '<path d="M3 6h18"/>'
        '<path d="M8 6V4h8v2"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "send": (
        '<path d="M12 19V5"/>'
        '<path d="m5 12 7-7 7 7"/>'
    ),
    "stop": (
        '<rect x="6" y="6" width="12" height="12" rx="2"/>'
    ),
    "new-session": (
        '<path d="M12 5v14"/>'
        '<path d="M5 12h14"/>'
    ),
    "export": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/>'
        '<line x1="12" y1="15" x2="12" y2="3"/>'
    ),
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 2v3M12 19v3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12'
        'M2 12h3M19 12h3M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12"/>'
    ),
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "alert": (
        '<path d="m10.29 3.86-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.71-3.14l-8-14'
        'a2 2 0 0 0-3.42 0Z"/>'
        '<line x1="12" y1="9" x2="12" y2="13"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "locate": (
        '<circle cx="12" cy="12" r="7"/>'
        '<circle cx="12" cy="12" r="2"/>'
        '<line x1="12" y1="2" x2="12" y2="5"/>'
        '<line x1="12" y1="19" x2="12" y2="22"/>'
        '<line x1="2" y1="12" x2="5" y2="12"/>'
        '<line x1="19" y1="12" x2="22" y2="12"/>'
    ),
    "terminal": (
        '<polyline points="4 17 10 11 4 5"/>'
        '<line x1="12" y1="19" x2="20" y2="19"/>'
    ),
    "mail": (
        '<rect x="2" y="4" width="20" height="16" rx="2"/>'
        '<path d="m22 7-10 6L2 7"/>'
    ),
}


def available_icons() -> tuple[str, ...]:
    """返回内置支持的图标名称元组。"""

    return tuple(sorted(_ICON_PATHS))


def render_pixmap(name: str, color: str | QColor, *, size: int = 16, dpr: float = 1.0) -> QPixmap:
    """将指定 SVG 图标按颜色与像素密度渲染为 :class:`QPixmap`。

    参数:
        name: 图标名称，须存在于 :func:`available_icons`。
        color: 线条颜色（十六进制串或 ``QColor``）。
        size: 逻辑尺寸（像素）。
        dpr: 设备像素比（如 ``1.0``、``2.0``）。

    异常:
        KeyError: 图标名称不存在。
        ValueError: ``size`` 或 ``dpr`` 非正数，或颜色非法。
    """

    if size <= 0:
        raise ValueError(f"图标尺寸必须为正整数：{size}")
    if dpr <= 0:
        raise ValueError(f"像素比必须为正数：{dpr}")
    qcolor = QColor(color)
    if not qcolor.isValid():
        raise ValueError(f"非法图标颜色：{color!r}")
    return _cached_pixmap(name, qcolor.name(QColor.NameFormat.HexArgb), size, round(dpr, 2))


def render_icon(name: str, color: str | QColor, *, size: int = 16) -> QIcon:
    """将指定 SVG 图标渲染为支持 1x / 2x 高清缩放的 :class:`QIcon`。

    参数:
        name: 图标名称，须存在于 :func:`available_icons`。
        color: 线条颜色（十六进制串或 ``QColor``）。
        size: 逻辑尺寸（像素）。
    """

    icon = QIcon()
    icon.addPixmap(render_pixmap(name, color, size=size, dpr=1.0))
    icon.addPixmap(render_pixmap(name, color, size=size, dpr=2.0))
    return icon


@functools.lru_cache(maxsize=256)
def _cached_pixmap(name: str, color_hex: str, size: int, dpr: float) -> QPixmap:
    body = _ICON_PATHS[name]
    svg = _SVG_TEMPLATE.format(color=color_hex, body=body).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():  # pragma: no cover - 内置 SVG 常量均经单测校验
        raise ValueError(f"图标 SVG 解析失败：{name}")
    pixel_size = max(1, round(size * dpr))
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap
