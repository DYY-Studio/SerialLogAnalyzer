"""
全局 QSS 样式表 - 明亮浅色主题（汇报PPT风格）
"""

LIGHT_THEME_QSS = """
/* ===== 全局基础 ===== */
QWidget {
    background-color: #f8f9fa;
    color: #2d3748;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #ffffff;
}

/* ===== 工具栏区域 ===== */
QToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    padding: 8px 16px;
    spacing: 10px;
}

/* ===== 按钮 ===== */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e0;
    border-radius: 6px;
    padding: 6px 18px;
    color: #2d3748;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #f7fafc;
    border-color: #4299e1;
    color: #2b6cb0;
}

QPushButton:pressed {
    background-color: #edf2f7;
}

QPushButton:checked {
    background-color: #3182ce;
    border-color: #3182ce;
    color: white;
}

QPushButton:checked:hover {
    background-color: #2b6cb0;
    border-color: #2b6cb0;
}

/* ===== 输入框 / 下拉框 ===== */
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e0;
    border-radius: 6px;
    padding: 6px 12px;
    selection-background-color: #3182ce;
    selection-color: white;
}

QLineEdit:focus, QComboBox:focus {
    border-color: #3182ce;
    outline: none;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e0;
    border-radius: 6px;
    selection-background-color: #3182ce;
    selection-color: white;
    outline: none;
    padding: 4px;
}

/* ===== 表格 ===== */
QTableView {
    background-color: #ffffff;
    alternate-background-color: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    gridline-color: #edf2f7;
    selection-background-color: #bee3f8;
    selection-color: #2d3748;
}

QTableView::item {
    padding: 6px 10px;
    border-bottom: 1px solid #f7fafc;
}

QTableView::item:selected {
    background-color: #bee3f8;
}

QHeaderView::section {
    background-color: #f7fafc;
    color: #4a5568;
    padding: 10px 12px;
    border: none;
    border-right: 1px solid #e2e8f0;
    border-bottom: 2px solid #e2e8f0;
    font-weight: 600;
}

QHeaderView::section:hover {
    background-color: #edf2f7;
}

/* ===== 文本编辑区 ===== */
QTextEdit {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px;
    font-family: "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 13px;
    line-height: 1.6;
}

/* ===== 复选框 ===== */
QCheckBox {
    spacing: 6px;
    color: #4a5568;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1.5px solid #cbd5e0;
    background-color: #ffffff;
}

QCheckBox::indicator:hover {
    border-color: #3182ce;
}

QCheckBox::indicator:checked {
    background-color: #3182ce;
    border-color: #3182ce;
    image: url(ui/resources/checkmark.png);
}

QCheckBox::indicator:checked:hover {
    background-color: #2b6cb0;
    border-color: #2b6cb0;
}

/* ===== 分组框（卡片） ===== */
QGroupBox {
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    margin-top: 16px;
    padding-top: 20px;
    font-weight: 600;
    color: #2d3748;
    background-color: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #2b6cb0;
}

/* ===== 状态栏 ===== */
QStatusBar {
    background-color: #f7fafc;
    border-top: 1px solid #e2e8f0;
    color: #718096;
}

/* ===== 分割器 ===== */
QSplitter::handle {
    background-color: #e2e8f0;
    width: 2px;
}

QSplitter::handle:hover {
    background-color: #3182ce;
}

/* ===== 滚动条 ===== */
QScrollBar:vertical {
    background: #f7fafc;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #cbd5e0;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #a0aec0;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #f7fafc;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #cbd5e0;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #a0aec0;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ===== 标签 ===== */
QLabel {
    color: #4a5568;
}

/* ===== 工具提示 ===== */
QToolTip {
    background-color: #2d3748;
    color: #ffffff;
    border: none;
    padding: 8px 12px;
    border-radius: 6px;
}
"""
