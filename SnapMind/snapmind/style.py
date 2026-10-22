from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "home": '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    "capture": '<path d="M8 3H4a1 1 0 0 0-1 1v4m13-5h4a1 1 0 0 1 1 1v4M3 16v4a1 1 0 0 0 1 1h4m8 0h4a1 1 0 0 0 1-1v-4"/><rect x="7" y="7" width="10" height="10" rx="2"/>',
    "clipboard": '<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="2" width="6" height="5" rx="1"/><path d="M9 12h6m-6 4h4"/>',
    "book": '<path d="M12 5v16M3 3c4-1 6 0 9 2 3-2 5-3 9-2v16c-4-1-6 0-9 2-3-2-5-3-9-2z"/>',
    "code": '<path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18"/>',
    "settings": '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2" fill="white"/><circle cx="16" cy="12" r="2" fill="white"/><circle cx="10" cy="18" r="2" fill="white"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "plus": '<path d="M12 4v16M4 12h16"/>',
    "star": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    "moon": '<path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11z"/>',
    "file": '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8m-8 4h6"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 5V3H3v13h2"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "shield": '<path d="m12 3 9 4v6c0 4-6 7-9 8-3-1-9-4-9-8V7z"/><path d="m8 12 3 3 5-6"/>',
}


def icon(name, color="#65738c", size=22):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">{PATHS.get(name, PATHS["file"])}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    pix.setDevicePixelRatio(2)
    return QIcon(pix)


def stylesheet(dark=False):
    bg, surface, side = (
        ("#111827", "#1b2434", "#151e2e") if dark else ("#f6f8fc", "#ffffff", "#f0f4fa")
    )
    text, muted, line = (
        ("#e6edf8", "#a6b4cc", "#303d52") if dark else ("#1c2b46", "#77869e", "#e5eaf2")
    )
    return f"""
    * {{ font-family: "Segoe UI", "Microsoft YaHei UI", "Noto Sans CJK SC"; font-size: 13px; color: {text}; }}
    QMainWindow, QDialog, QWidget#Main {{ background: {bg}; }}
    QWidget#Sidebar {{ background: {side}; border-right: 1px solid {line}; }}
    QFrame#Card, QFrame#Editor {{ background: {surface}; border: 1px solid {line}; border-radius: 14px; }}
    QLabel {{ background: transparent; border: none; }}
    QLabel#Brand {{ font-size: 21px; font-weight: 750; letter-spacing: -0.5px; }}
    QLabel#Title {{ font-size: 28px; font-weight: 700; }}
    QLabel#Section {{ font-size: 16px; font-weight: 650; }}
    QLabel#Muted {{ color: {muted}; }}
    QLabel#Eyebrow {{ color: {muted}; font-size: 11px; letter-spacing: 2px; }}
    QLabel#Badge {{ background: {"#263953" if dark else "#eaf0ff"}; color: {"#a5c3ff" if dark else "#4a72bb"}; border-radius: 6px; padding: 4px 8px; font-size: 11px; }}
    QPushButton {{ background: {surface}; border: 1px solid {line}; border-radius: 8px; padding: 9px 14px; font-weight: 500; }}
    QPushButton:hover {{ background: {"#2a3b54" if dark else "#eef3fc"}; border-color: #9db8ec; }}
    QPushButton:pressed {{ background: {"#344b6b" if dark else "#e0eaff"}; }}
    QPushButton:disabled {{ color: {muted}; }}
    QPushButton#Primary {{ color: white; background: #3e73e8; border-color: #3e73e8; }}
    QPushButton#Primary:hover {{ background: #3064d7; }}
    QPushButton#Nav {{ text-align: left; border: none; background: transparent; padding: 12px 17px; border-radius: 9px; color: {muted}; }}
    QPushButton#Nav:checked {{ background: {"#283c60" if dark else "#dfeaff"}; color: {"#b7d0ff" if dark else "#3466c5"}; font-weight: 650; }}
    QPushButton#ActionCard {{ text-align: left; border-radius: 14px; padding: 24px; min-height: 68px; font-size: 16px; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QKeySequenceEdit {{ background: {surface}; border: 1px solid {line}; border-radius: 7px; padding: 8px; selection-background-color: #3e73e8; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: #7ba4ef; }}
    QLineEdit#Search {{ padding: 13px 16px; border-radius: 11px; font-size: 14px; }}
    QListWidget {{ background: {surface}; border: 1px solid {line}; border-radius: 12px; padding: 6px; outline: none; }}
    QListWidget::item {{ border-radius: 8px; padding: 12px; border-bottom: 1px solid {line}; }}
    QListWidget::item:selected {{ background: {"#2b4064" if dark else "#eaf0ff"}; color: {text}; }}
    QListWidget::item:hover {{ background: {"#26354c" if dark else "#f4f7fc"}; }}
    QScrollArea, QStackedWidget {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ width: 7px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {"#41506a" if dark else "#ccd6e5"}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QStatusBar {{ background: {surface}; border-top: 1px solid {line}; color: {muted}; padding: 3px; }}
    QToolTip {{ background: {surface}; border: 1px solid {line}; padding: 6px; }}
    QMenu {{ background: {surface}; border: 1px solid {line}; padding: 5px; }}
    QMenu::item {{ padding: 8px 22px; }} QMenu::item:selected {{ background: {"#2b4064" if dark else "#eaf0ff"}; }}
    QTabWidget::pane {{ border: 1px solid {line}; border-radius: 8px; background: {surface}; }}
    QTabBar::tab {{ padding: 9px 14px; background: transparent; }}
    QTabBar::tab:selected {{ color: #5385ef; border-bottom: 2px solid #5385ef; }}
    QCheckBox {{ spacing: 9px; }}
    """
