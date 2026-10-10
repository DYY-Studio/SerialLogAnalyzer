"""
生成 SerialLogAnalyzer UI 使用文档
"""
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn


def create_user_guide():
    doc = Document()

    # ===== 设置默认字体 =====
    doc.styles['Normal'].font.name = '微软雅黑'
    doc.styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    doc.styles['Normal'].font.size = Pt(11)

    # ===== 标题样式 =====
    title_style = doc.styles.add_style('Title Style', WD_STYLE_TYPE.PARAGRAPH)
    title_style.font.name = '微软雅黑'
    title_style._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    title_style.font.size = Pt(22)
    title_style.font.bold = True
    title_style.font.color.rgb = RGBColor(0x2B, 0x6C, 0xB0)
    title_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_style.paragraph_format.space_after = Pt(24)

    # ===== 一级标题样式 =====
    h1_style = doc.styles.add_style('Heading 1 Style', WD_STYLE_TYPE.PARAGRAPH)
    h1_style.font.name = '微软雅黑'
    h1_style._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    h1_style.font.size = Pt(16)
    h1_style.font.bold = True
    h1_style.font.color.rgb = RGBColor(0x2D, 0x37, 0x48)
    h1_style.paragraph_format.space_before = Pt(18)
    h1_style.paragraph_format.space_after = Pt(12)

    # ===== 二级标题样式 =====
    h2_style = doc.styles.add_style('Heading 2 Style', WD_STYLE_TYPE.PARAGRAPH)
    h2_style.font.name = '微软雅黑'
    h2_style._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    h2_style.font.size = Pt(13)
    h2_style.font.bold = True
    h2_style.font.color.rgb = RGBColor(0x2B, 0x6C, 0xB0)
    h2_style.paragraph_format.space_before = Pt(12)
    h2_style.paragraph_format.space_after = Pt(6)

    # ===== 正文样式（首行缩进） =====
    body_style = doc.styles.add_style('Body Style', WD_STYLE_TYPE.PARAGRAPH)
    body_style.font.name = '微软雅黑'
    body_style._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    body_style.font.size = Pt(11)
    body_style.paragraph_format.first_line_indent = Pt(22)
    body_style.paragraph_format.space_after = Pt(6)
    body_style.paragraph_format.line_spacing = 1.5

    # ===== 列表样式（无缩进） =====
    list_style = doc.styles.add_style('List Style', WD_STYLE_TYPE.PARAGRAPH)
    list_style.font.name = '微软雅黑'
    list_style._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    list_style.font.size = Pt(11)
    list_style.paragraph_format.left_indent = Pt(22)
    list_style.paragraph_format.space_after = Pt(4)
    list_style.paragraph_format.line_spacing = 1.4

    # ===== 提示框样式 =====
    tip_style = doc.styles.add_style('Tip Style', WD_STYLE_TYPE.PARAGRAPH)
    tip_style.font.name = '微软雅黑'
    tip_style._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    tip_style.font.size = Pt(10)
    tip_style.font.color.rgb = RGBColor(0x71, 0x80, 0x96)
    tip_style.paragraph_format.left_indent = Pt(22)
    tip_style.paragraph_format.space_after = Pt(8)

    # ================================================================
    # 文档内容
    # ================================================================

    # --- 封面标题 ---
    title = doc.add_paragraph('SerialLogAnalyzer', style='Title Style')
    subtitle = doc.add_paragraph('串口日志分析工具 — 用户使用手册', style='Title Style')
    subtitle.runs[0].font.size = Pt(14)
    subtitle.runs[0].font.color.rgb = RGBColor(0x71, 0x80, 0x96)
    subtitle.runs[0].font.bold = False

    doc.add_paragraph()
    doc.add_paragraph('版本：Demo 模式', style='Tip Style').alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph('更新日期：2026年10月', style='Tip Style').alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_page_break()

    # --- 一、软件简介 ---
    doc.add_paragraph('一、软件简介', style='Heading 1 Style')
    doc.add_paragraph(
        'SerialLogAnalyzer 是一款面向嵌入式开发与硬件调试的串口日志分析工具。'
        '软件通过串口连接目标设备，实时接收并显示设备输出的日志信息，'
        '同时集成了 AI 智能分析能力，可自动识别日志中的错误、异常和关键事件，'
        '帮助开发者快速定位问题、缩短调试周期。',
        style='Body Style'
    )
    doc.add_paragraph('核心功能包括：', style='Body Style')
    doc.add_paragraph('• 实时串口日志接收与分级显示', style='List Style')
    doc.add_paragraph('• 关键字过滤与日志级别筛选', style='List Style')
    doc.add_paragraph('• 日志导出与清空管理', style='List Style')
    doc.add_paragraph('• 命令行发送与设备交互', style='List Style')
    doc.add_paragraph('• AI 智能分析与多轮对话追问', style='List Style')

    # --- 二、界面总览 ---
    doc.add_paragraph('二、界面总览', style='Heading 1 Style')
    doc.add_paragraph(
        '软件主界面采用左右分栏布局，左侧为日志主区域，右侧为 AI 分析面板，'
        '底部为串口控制栏。整体布局遵循"日志为主、分析为辅"的设计原则，'
        '确保调试人员能够快速浏览日志并随时调用分析功能。',
        style='Body Style'
    )

    doc.add_paragraph('界面布局分为以下五个区域：', style='Body Style')
    doc.add_paragraph('① 过滤栏 — 位于日志表格上方，用于筛选日志内容', style='List Style')
    doc.add_paragraph('② 日志表格区 — 左侧主区域，显示所有接收到的日志', style='List Style')
    doc.add_paragraph('③ 命令输入区 — 日志表格下方，用于向设备发送命令', style='List Style')
    doc.add_paragraph('④ 串口控制栏 — 窗口底部，用于配置串口参数与连接管理', style='List Style')
    doc.add_paragraph('⑤ AI 分析面板 — 右侧区域，包含分析设置与结果展示', style='List Style')

    # --- 三、功能模块详解 ---
    doc.add_paragraph('三、功能模块详解', style='Heading 1 Style')

    # 3.1 日志表格区
    doc.add_paragraph('3.1 日志表格区', style='Heading 2 Style')
    doc.add_paragraph(
        '日志表格是软件的核心区域，以表格形式逐条显示从串口接收到的日志信息。'
        '表格采用交替行底色设计，便于横向阅读时区分不同日志行。',
        style='Body Style'
    )
    doc.add_paragraph('表格包含以下列：', style='Body Style')
    doc.add_paragraph('• # — 日志序号，从 1 开始递增，唯一标识每条日志', style='List Style')
    doc.add_paragraph('• 时间 — 日志接收时间，精确到秒', style='List Style')
    doc.add_paragraph('• 级别 — 日志严重级别（DEBUG / INFO / WARN / ERROR），以彩色标签区分', style='List Style')
    doc.add_paragraph('• 模块 — 产生日志的源模块名称（如 kernel、wifi、uart 等）', style='List Style')
    doc.add_paragraph('• 消息 — 日志正文内容，长文本自动截断显示', style='List Style')

    doc.add_paragraph('操作说明：', style='Body Style')
    doc.add_paragraph('• 单击某行可选中该条日志，选中行将高亮显示', style='List Style')
    doc.add_paragraph('• 支持多选（按住 Ctrl / Shift 点击）', style='List Style')
    doc.add_paragraph('• 新日志到达时自动滚动到最新一行', style='List Style')
    doc.add_paragraph('• 鼠标悬停可查看完整日志内容', style='List Style')

    # 3.2 过滤栏
    doc.add_paragraph('3.2 过滤栏', style='Heading 2 Style')
    doc.add_paragraph(
        '过滤栏位于日志表格上方，提供两种筛选方式：关键字过滤和级别过滤。'
        '两种方式可同时使用，取交集效果。',
        style='Body Style'
    )
    doc.add_paragraph('关键字过滤：', style='Body Style')
    doc.add_paragraph('• 在输入框中输入关键字，实时过滤包含该关键字的日志', style='List Style')
    doc.add_paragraph('• 支持模糊匹配，不区分大小写', style='List Style')
    doc.add_paragraph('• 清空输入框即可恢复显示全部日志', style='List Style')

    doc.add_paragraph('级别过滤：', style='Body Style')
    doc.add_paragraph('• 提供 DEBUG、INFO、WARN、ERROR 四个复选框', style='List Style')
    doc.add_paragraph('• 勾选对应级别即显示该级别日志，取消勾选则隐藏', style='List Style')
    doc.add_paragraph('• 默认全部勾选，显示所有级别的日志', style='List Style')

    doc.add_paragraph('操作按钮：', style='Body Style')
    doc.add_paragraph('• 导出 — 将当前日志列表保存为文件', style='List Style')
    doc.add_paragraph('• 清空 — 清空日志表格中的所有内容', style='List Style')

    # 3.3 命令输入区
    doc.add_paragraph('3.3 命令输入区', style='Heading 2 Style')
    doc.add_paragraph(
        '命令输入区位于日志表格下方，用于向连接的串口设备发送指令。'
        '输入命令后按回车键或点击"发送"按钮即可发送。',
        style='Body Style'
    )
    doc.add_paragraph('• 输入框 — 输入要发送的命令内容', style='List Style')
    doc.add_paragraph('• 发送按钮 — 将输入框中的命令发送到设备', style='List Style')
    doc.add_paragraph('• 发送后输入框自动清空，可继续输入下一条命令', style='List Style')

    # 3.4 串口控制栏
    doc.add_paragraph('3.4 串口控制栏', style='Heading 2 Style')
    doc.add_paragraph(
        '串口控制栏位于窗口最底部，用于配置串口参数并管理连接状态。',
        style='Body Style'
    )
    doc.add_paragraph('串口选择：', style='Body Style')
    doc.add_paragraph('• 下拉列表显示当前可用的串口设备', style='List Style')
    doc.add_paragraph('• 选择目标串口后，设置波特率即可连接', style='List Style')

    doc.add_paragraph('波特率：', style='Body Style')
    doc.add_paragraph('• 常用波特率：9600、19200、38400、57600、115200 等', style='List Style')
    doc.add_paragraph('• 默认值为 115200，可手动输入自定义值', style='List Style')

    doc.add_paragraph('设置按钮：', style='Body Style')
    doc.add_paragraph('• 点击"⚙ 设置"打开高级串口设置对话框', style='List Style')
    doc.add_paragraph('• 可配置数据位、停止位、校验位、流控等参数', style='List Style')

    doc.add_paragraph('连接/断开按钮：', style='Body Style')
    doc.add_paragraph('• 未连接状态：显示蓝色"连接"按钮', style='List Style')
    doc.add_paragraph('• 已连接状态：按钮变为红色"断开"，点击可断开连接', style='List Style')
    doc.add_paragraph('• 连接成功后，设备输出的日志将实时显示在表格中', style='List Style')

    # 3.5 分析设置面板
    doc.add_paragraph('3.5 分析设置面板', style='Heading 2 Style')
    doc.add_paragraph(
        '分析设置面板位于右侧上方，用于配置 AI 分析的上下文范围和分析目标。',
        style='Body Style'
    )
    doc.add_paragraph('上下文选择：', style='Body Style')
    doc.add_paragraph('• 选中的日志 — 仅分析用户选中的日志条目', style='List Style')
    doc.add_paragraph('• 选中 + 前后各10条 — 包含选中日志及相邻上下文', style='List Style')
    doc.add_paragraph('• 最近的50条 — 分析最近接收到的50条日志', style='List Style')
    doc.add_paragraph('• 仅错误日志 — 自动筛选所有 ERROR 级别的日志进行分析', style='List Style')

    doc.add_paragraph('目标设置：', style='Body Style')
    doc.add_paragraph('• 提供预设分析目标，也可自定义输入', style='List Style')
    doc.add_paragraph('• 预设目标包括：错误原因分析、事件解释、关键事件总结等', style='List Style')

    doc.add_paragraph('操作按钮：', style='Body Style')
    doc.add_paragraph('• 开始分析 — 按照当前设置发起 AI 分析请求', style='List Style')
    doc.add_paragraph('• 新会话 — 清空当前对话历史，开始全新的分析会话', style='List Style')

    # 3.6 分析结果区
    doc.add_paragraph('3.6 分析结果区', style='Heading 2 Style')
    doc.add_paragraph(
        '分析结果区位于右侧中部，以文本形式展示 AI 分析的输出内容。'
        '支持流式输出，分析过程中内容会逐字显示。',
        style='Body Style'
    )
    doc.add_paragraph('• 首次使用时显示占位提示文字', style='List Style')
    doc.add_paragraph('• 分析进行中，内容实时流式更新', style='List Style')
    doc.add_paragraph('• 多轮对话时，历史结果保留在文本框中', style='List Style')

    # 3.7 追问输入区
    doc.add_paragraph('3.7 追问输入区', style='Heading 2 Style')
    doc.add_paragraph(
        '追问输入区位于右侧底部，用于在分析结果基础上继续提问，实现多轮对话。',
        style='Body Style'
    )
    doc.add_paragraph('• 在输入框中输入追问内容，按回车或点击"发送"', style='List Style')
    doc.add_paragraph('• AI 会结合之前的分析上下文给出进一步解答', style='List Style')
    doc.add_paragraph('• 适合在初步分析结果基础上深入挖掘问题细节', style='List Style')

    # --- 四、快速操作指南 ---
    doc.add_paragraph('四、快速操作指南', style='Heading 1 Style')

    doc.add_paragraph('4.1 首次连接设备', style='Heading 2 Style')
    doc.add_paragraph('步骤一：在底部"串口"下拉列表中选择目标设备', style='List Style')
    doc.add_paragraph('步骤二：确认波特率（通常为 115200）', style='List Style')
    doc.add_paragraph('步骤三：点击蓝色"连接"按钮', style='List Style')
    doc.add_paragraph('步骤四：连接成功后，日志将实时显示在左侧表格中', style='List Style')

    doc.add_paragraph('4.2 筛选并定位问题', style='Heading 2 Style')
    doc.add_paragraph('步骤一：在过滤栏输入关键字（如 "error"、"fail"）', style='List Style')
    doc.add_paragraph('步骤二：取消勾选 DEBUG 和 INFO，只保留 WARN 和 ERROR', style='List Style')
    doc.add_paragraph('步骤三：在过滤结果中查找异常日志', style='List Style')

    doc.add_paragraph('4.3 使用 AI 分析日志', style='Heading 2 Style')
    doc.add_paragraph('步骤一：在日志表格中选中可疑的日志行', style='List Style')
    doc.add_paragraph('步骤二：右侧"上下文"选择"选中 + 前后各10条"', style='List Style')
    doc.add_paragraph('步骤三："目标"选择或输入分析需求', style='List Style')
    doc.add_paragraph('步骤四：点击"开始分析"，等待结果输出', style='List Style')
    doc.add_paragraph('步骤五：如有疑问，在底部追问输入框继续提问', style='List Style')

    # --- 五、常见问题 ---
    doc.add_paragraph('五、常见问题', style='Heading 1 Style')

    doc.add_paragraph('Q1：串口列表中找不到设备怎么办？', style='Heading 2 Style')
    doc.add_paragraph(
        '请检查设备是否已通过 USB 连接到电脑，驱动是否正常安装。'
        '部分 USB 转串口芯片（如 CH340、CP210x）需要单独安装驱动程序。',
        style='Body Style'
    )

    doc.add_paragraph('Q2：连接成功但没有日志输出？', style='Heading 2 Style')
    doc.add_paragraph(
        '请确认波特率设置与设备端一致。常见波特率不匹配会导致收到乱码或无数据。'
        '可尝试切换不同波特率测试，或通过"设置"按钮检查数据位、停止位等参数。',
        style='Body Style'
    )

    doc.add_paragraph('Q3：AI 分析没有反应？', style='Heading 2 Style')
    doc.add_paragraph(
        'Demo 模式下 AI 分析为模拟演示功能。正式版本需要配置 API 密钥和模型服务提供商，'
        '可通过设置对话框进行配置。',
        style='Body Style'
    )

    doc.add_paragraph('Q4：日志太多导致界面卡顿？', style='Heading 2 Style')
    doc.add_paragraph(
        '建议使用过滤功能减少显示的日志数量。定期点击"清空"按钮清理历史日志，'
        '或使用"导出"功能保存后再清空。',
        style='Body Style'
    )

    # --- 页脚说明 ---
    doc.add_paragraph()
    doc.add_paragraph()
    doc.add_paragraph('— 文档结束 —', style='Tip Style').alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 保存
    output_path = r"C:\Users\Administrator\Doubao\chats\2026-10-10\new-chat\SerialLogAnalyzer\docs\SerialLogAnalyzer_用户使用手册.docx"
    doc.save(output_path)
    print(f"文档已生成：{output_path}")
    return output_path


if __name__ == "__main__":
    create_user_guide()
