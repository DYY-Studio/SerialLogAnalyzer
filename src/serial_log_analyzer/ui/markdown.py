"""把 Markdown 渲染成 Qt 富文本 HTML（GitHub 那种形式）。

Qt 的富文本只支持 HTML/CSS 子集，而 ``QTextDocument.toHtml()`` 写出的行内样式压不过
``setDefaultStyleSheet``，所以这里不靠 CSS，直接在文档上改块 / 字符 / 表格格式：
标题分级与 h1/h2 下细线、代码块整片底色、行内代码、引用、表格、链接与行距。

两处与具体机器相关的事实都在运行时决定，不写死：

- 颜色从调色板的 ``Base`` / ``Text`` 按比例派生。主题可能把 ``AlternateBase``、
  ``PlaceholderText`` 设成与正文无关的颜色（实测有主题给的是纯白），角色名不可信。
- 代码字体：Qt 的 markdown 导入器给的等宽族不含中文字形，缺字会走系统回退，
  Windows 上实测首次渲染卡 2.5-4 s（每进程一次）；所以把含中文的片段换成本机探测到的
  「等宽且含中文」字体，探测不到就保持导入器默认，交给平台自行处理。
"""

from __future__ import annotations

import functools
import re

from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QPalette,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
    QTextTable,
    QTextTableCellFormat,
)

__all__ = ["MarkdownRenderer", "split_font_runs"]

# 从 Base/Text 派生的比例：次要材料底色 / 描边 / 次要文字。
_TINT_RATIO = 0.10
_BORDER_RATIO = 0.22
_MUTED_RATIO = 0.55

# 正文字号的倍数，按 GitHub 的标题层级。
_HEADING_SCALES = {1: 2.0, 2: 1.5, 3: 1.25}

_PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
_FIXED = QTextBlockFormat.LineHeightTypes.FixedHeight.value
_SOLID = QTextFrameFormat.BorderStyle.BorderStyle_Solid

# 含中文的等宽字体候选；都找不到就退回「扫一遍等宽且支持中文的族」。
_CJK_MONO_CANDIDATES = (
    "Sarasa Mono SC",
    "Noto Sans Mono CJK SC",
    "NSimSun",
    "SimSun",
    "MS Gothic",
    "WenQuanYi Micro Hei Mono",
    "AR PL UMing CN",
)


def split_font_runs(text: str) -> list[tuple[int, int, bool]]:
    """把文本切成连续的 ``(起点, 终点, 是否含中文)`` 段，用于按段指定等宽字体。"""

    return [
        (match.start(), match.end(), not match.group().isascii())
        for match in re.finditer(r"[^\x00-\x7f]+|[\x00-\x7f]+", text)
    ]


@functools.lru_cache(maxsize=1)
def _cjk_mono_family() -> str | None:
    """找一个「等宽且含中文」的字体族；找不到返回 ``None``。"""

    families = set(QFontDatabase.families())
    for name in _CJK_MONO_CANDIDATES:
        if name in families:
            return name
    for name in sorted(families):
        systems = QFontDatabase.writingSystems(name)
        if QFontDatabase.isFixedPitch(name) and any("Chinese" in item.name for item in systems):
            return name
    return None


def _mix(base: QColor, toward: QColor, ratio: float) -> QColor:
    """按比例混合两个颜色。"""

    return QColor(
        round(base.red() + (toward.red() - base.red()) * ratio),
        round(base.green() + (toward.green() - base.green()) * ratio),
        round(base.blue() + (toward.blue() - base.blue()) * ratio),
    )


def _fragments(block):
    iterator = block.begin()
    while not iterator.atEnd():
        yield iterator.fragment()
        iterator += 1


def _side_of(document: QTextDocument, block) -> QTextCursor:
    """落在指定块上的游标。"""

    cursor = QTextCursor(document)
    cursor.setPosition(block.position())
    return cursor


def _span_of(document: QTextDocument, start: int, end: int) -> QTextCursor:
    """选中 ``[start, end)`` 的游标。"""

    cursor = QTextCursor(document)
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    return cursor


def _code_family(document: QTextDocument) -> str | None:
    """读回导入器给代码用的等宽族（各平台不同名，不能写死）。"""

    inline: str | None = None
    block = document.begin()
    while block.isValid():
        for fragment in _fragments(block):
            families = fragment.charFormat().fontFamilies() or ()
            if not families:
                continue
            if block.blockFormat().nonBreakableLines():
                return families[0]
            if inline is None and QFontDatabase.isFixedPitch(families[0]):
                inline = families[0]
        block = block.next()
    return inline


def _code_ranges(document: QTextDocument) -> list[tuple[int, int]]:
    """连续代码行的区间 ``(起, 止)``，止为最后一行的末字符位置。"""

    ranges: list[tuple[int, int]] = []
    block = document.begin()
    while block.isValid():
        if block.blockFormat().nonBreakableLines():
            last = block
            while last.next().isValid() and last.next().blockFormat().nonBreakableLines():
                last = last.next()
            ranges.append((block.position(), last.position() + last.length() - 1))
            block = last.next()
        else:
            block = block.next()
    return ranges


def _styled_cells(frame: QTextTable, border: QColor, head_tint: QColor) -> None:
    """表格：内边距 + 描边 + 表头底色。"""

    table_format = frame.format().toTableFormat()
    table_format.setCellPadding(6)
    table_format.setCellSpacing(0)
    frame.setFormat(table_format)
    for row in range(frame.rows()):
        for column in range(frame.columns()):
            cell = frame.cellAt(row, column)
            cell_format: QTextTableCellFormat = cell.format().toTableCellFormat()
            cell_format.setBorder(1)
            cell_format.setBorderBrush(border)
            cell_format.setBorderStyle(_SOLID)
            if row == 0:
                cell_format.setBackground(head_tint)
                cell_format.setFontWeight(700)
            cell.setFormat(cell_format)


class MarkdownRenderer:
    """把 Markdown 渲染成 Qt 富文本 HTML；颜色与字体按当前环境决定。

    参数:
        palette: 取色用的调色板（一般是结果区自己的调色板）。
        base_point_size: 正文字号，标题按 GitHub 的层级比例放大。
    """

    def __init__(self, palette: QPalette, base_point_size: float) -> None:
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        self._point_size = base_point_size if base_point_size > 0 else 9.0
        self._tint = _mix(base, text, _TINT_RATIO)
        self._muted = _mix(base, text, _MUTED_RATIO)
        self._border = _mix(base, text, _BORDER_RATIO)

    @property
    def tint(self) -> QColor:
        """次要材料（代码块、思考块）的底色。"""

        return self._tint

    @property
    def muted(self) -> QColor:
        """次要文字的灰度色。"""

        return self._muted

    def html(self, markdown: str) -> str:
        """渲染为 HTML；空文本返回空串。"""

        if not markdown:
            return ""
        document = QTextDocument()
        document.setMarkdown(markdown)
        mono = _code_family(document)
        self._style_blocks(document)
        self._style_headings(document)
        self._style_inline_code(document, mono)
        self._heading_rules(document)
        self._style_code_frames(document)
        self._style_code_fonts(document, mono)
        self._style_tables(document)
        return document.toHtml()

    # ------------------------------------------------------------------

    def _style_blocks(self, document: QTextDocument) -> None:
        """块级：间距与行高；代码块自身的底色与内缩交给外面的 frame。"""

        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        block = document.begin()
        while block.isValid():
            fmt = block.blockFormat()
            if fmt.headingLevel():
                fmt.setTopMargin(self._point_size * 0.8)
                fmt.setBottomMargin(self._point_size * 0.4)
                fmt.setLineHeight(125, _PROPORTIONAL)
            elif fmt.nonBreakableLines():
                fmt.setLeftMargin(0)
                fmt.setRightMargin(0)
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
                fmt.setLineHeight(145, _PROPORTIONAL)
            elif fmt.property(QTextFormat.Property.BlockQuoteLevel):
                fmt.setForeground(self._muted)
                fmt.setTopMargin(self._point_size * 0.4)
                fmt.setBottomMargin(self._point_size * 0.4)
                fmt.setLineHeight(150, _PROPORTIONAL)
            else:
                fmt.setTopMargin(self._point_size * 0.5)
                fmt.setBottomMargin(self._point_size * 0.5)
                fmt.setLineHeight(150, _PROPORTIONAL)
            _side_of(document, block).setBlockFormat(fmt)
            block = block.next()
        cursor.endEditBlock()

    def _style_headings(self, document: QTextDocument) -> None:
        """标题字号按层级放大。"""

        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        block = document.begin()
        while block.isValid():
            scale = _HEADING_SCALES.get(block.blockFormat().headingLevel())
            if scale:
                for fragment in _fragments(block):
                    if fragment.isValid():
                        char = fragment.charFormat()
                        char.setFontPointSize(self._point_size * scale)
                        _span_of(
                            document,
                            fragment.position(),
                            fragment.position() + fragment.length(),
                        ).mergeCharFormat(char)
            block = block.next()
        cursor.endEditBlock()

    def _style_inline_code(self, document: QTextDocument, mono: str | None) -> None:
        """行内代码加底色（方角：Qt 不支持圆角）。"""

        if mono is None:
            return
        targets: list[tuple[int, int, QTextCharFormat]] = []
        block = document.begin()
        while block.isValid():
            if not block.blockFormat().nonBreakableLines():
                for fragment in _fragments(block):
                    if fragment.isValid() and mono in (fragment.charFormat().fontFamilies() or ()):
                        char = QTextCharFormat(fragment.charFormat())
                        char.setBackground(self._tint)
                        targets.append(
                            (
                                fragment.position(),
                                fragment.position() + fragment.length(),
                                char,
                            )
                        )
            block = block.next()

        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        for start, end, char in targets:
            _span_of(document, start, end).mergeCharFormat(char)
        cursor.endEditBlock()

    def _heading_rules(self, document: QTextDocument) -> None:
        """h1/h2 下面插一条 1px 细线。

        插入的空块默认继承标题级别（于是又高又大），所以要显式清掉级别并压到 1pt。
        """

        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        block = document.begin()
        while block.isValid():
            if block.blockFormat().headingLevel() in (1, 2):
                cursor.setPosition(block.position() + block.length() - 1)
                cursor.insertBlock()
                fmt = cursor.blockFormat()
                fmt.setHeadingLevel(0)
                fmt.setBackground(self._border)
                fmt.setLineHeight(1.0, _FIXED)
                fmt.setTopMargin(2)
                fmt.setBottomMargin(self._point_size * 0.5)
                fmt.setLeftMargin(0)
                cursor.setBlockFormat(fmt)
                char = cursor.blockCharFormat()
                char.setFontPointSize(1)
                cursor.setBlockCharFormat(char)
                block = cursor.block()
            block = block.next()
        cursor.endEditBlock()

    def _style_code_frames(self, document: QTextDocument) -> None:
        """把连续代码行包进一个 frame：整片底色 + 内边距。

        逐行加底色会在行与行之间露出缝隙（行距落在底色之外），所以要包成一整片。
        """

        ranges = _code_ranges(document)
        if not ranges:
            return
        fmt = QTextFrameFormat()
        fmt.setBackground(self._tint)
        fmt.setPadding(8)
        fmt.setTopMargin(self._point_size * 0.5)
        fmt.setBottomMargin(self._point_size * 0.5)
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        for start, end in reversed(ranges):  # 从后往前，前面的位置才不受影响
            _span_of(document, start, end).insertFrame(fmt)
        cursor.endEditBlock()

    def _style_code_fonts(self, document: QTextDocument, mono: str | None) -> None:
        """含中文的代码片段换成「等宽且含中文」的字体，不进系统回退路径。"""

        cjk = _cjk_mono_family()
        if mono is None or cjk is None:
            return
        targets: list[tuple[int, str, QTextCharFormat]] = []
        block = document.begin()
        while block.isValid():
            for fragment in _fragments(block):
                if not fragment.isValid() or mono not in (fragment.charFormat().fontFamilies() or ()):
                    continue
                if not fragment.text().isascii():
                    targets.append((fragment.position(), fragment.text(), fragment.charFormat()))
            block = block.next()

        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        for position, text, char in targets:
            for start, end, is_cjk in split_font_runs(text):
                run = QTextCharFormat(char)
                run.setFontFamilies([cjk if is_cjk else mono])
                _span_of(document, position + start, position + end).setCharFormat(run)
        cursor.endEditBlock()

    def _style_tables(self, document: QTextDocument) -> None:
        """表格：内边距 + 描边 + 表头底色。"""

        def walk(frame) -> None:
            if isinstance(frame, QTextTable):
                _styled_cells(frame, self._border, self._tint)
            iterator = frame.begin()
            while not iterator.atEnd():
                child = iterator.currentFrame()
                if child is not None:
                    walk(child)
                iterator += 1

        walk(document.rootFrame())

