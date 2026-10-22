from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .capture import CapturePreview, SelectionOverlay
from .jobs import Jobs
from .native import IS_WINDOWS, Hotkeys
from .paths import Settings
from .services import ClipboardMonitor, ContentService, OcrService
from .store import CLIP_KINDS, KINDS, Store
from .style import icon, stylesheet


def label(text, name=None):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    return item


def button(text, callback, image=None, primary=False):
    b = QPushButton(text)
    if image:
        b.setIcon(icon(image, "#ffffff" if primary else "#7385a3"))
    if primary:
        b.setObjectName("Primary")
    b.clicked.connect(callback)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def row_widget(*widgets):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for item in widgets:
        layout.addWidget(item)
    return row


def fill_list(target, records):
    target.clear()
    for r in records:
        marks = ("置顶 · " if r["pinned"] else "") + (
            "收藏 · " if r["favorite"] else ""
        )
        excerpt = (
            "私密内容 · 选择后查看"
            if r["private"]
            else " ".join(
                (r["body"] or r["notes"] or "图片已保存，选择查看详情").split()
            )[:100]
        )
        if r.get("fuzzy_match"):
            excerpt = "近似匹配 · " + excerpt
        when = (
            datetime.fromisoformat(r["updated_at"]).astimezone().strftime("%m/%d %H:%M")
        )
        title = "私密内容" if r["private"] else r["title"]
        item = QListWidgetItem(
            f"{title}\n{marks}{KINDS[r['kind']]}  ·  {when}  ·  {excerpt}"
        )
        item.setData(Qt.ItemDataRole.UserRole, r)
        item.setSizeHint(QSize(220, 76))
        item.setIcon(
            icon(
                "capture"
                if r["kind"] in ("screenshot", "image")
                else "book"
                if r["kind"] == "note"
                else "code"
                if r["kind"] in ("snippet", "code")
                else "file"
            )
        )
        target.addItem(item)


class LocalMarkdownBrowser(QTextBrowser):
    def __init__(self, data):
        super().__init__()
        self.data = data.resolve()
        self.setOpenLinks(False)

    def loadResource(self, kind, url):
        if url.scheme() == "file":
            path = Path(url.toLocalFile()).resolve()
            if path.is_relative_to(self.data):
                return super().loadResource(kind, url)
        elif not url.scheme():
            path = (self.data / url.path()).resolve()
            if path.is_relative_to(self.data):
                return super().loadResource(kind, QUrl.fromLocalFile(str(path)))
        return None


class RecordEditor(QFrame):
    saveRequested = Signal(str, dict)
    copyRequested = Signal(dict, bool)
    deleteRequested = Signal(str)
    ocrRequested = Signal(str)
    previewRequested = Signal(dict)
    openRequested = Signal(dict)
    linkRequested = Signal(str)
    unlinkRequested = Signal(str, str)
    openRecordRequested = Signal(str)
    relinkRequested = Signal(dict)
    noteRequested = Signal(str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.record = None
        self.loading = False
        self.dirty = False
        self.dirty_fields = set()
        self.setObjectName("Editor")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        self.empty = label(
            "选择一条内容\n\n查看原图、修正 OCR，或继续整理笔记。", "Muted"
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)
        self.content = QWidget()
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.meta = label("", "Muted")
        self.title = QLineEdit()
        self.title.setPlaceholderText("内容标题")
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("标签，以逗号分隔，例如：寄存器,STM32")
        self.favorite, self.pinned, self.private = (
            QCheckBox("收藏"),
            QCheckBox("置顶"),
            QCheckBox("私密"),
        )
        layout.addWidget(self.meta)
        layout.addWidget(self.title)
        layout.addWidget(self.tags)
        layout.addWidget(row_widget(self.favorite, self.pinned, self.private))
        self.picture = QPushButton("")
        self.picture.setFixedHeight(150)
        self.picture.clicked.connect(
            lambda: self.previewRequested.emit(self.record) if self.record else None
        )
        layout.addWidget(self.picture)
        self.tabs = QTabWidget()
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText(
            "在此编辑识别结果或 Markdown 笔记，修改后自动保存。"
        )
        self.body.setTabStopDistance(28)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("尚无 OCR 原文。图片可点击“识别文字”。")
        self.preview = LocalMarkdownBrowser(paths.data)
        self.preview.setOpenExternalLinks(False)
        self.preview.anchorClicked.connect(
            lambda url: (
                QDesktopServices.openUrl(url)
                if url.scheme() in ("https", "http", "file")
                else None
            )
        )
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("备注 / 文档页码说明")
        self.tabs.addTab(self.body, "正文")
        self.tabs.addTab(self.raw, "OCR 原文")
        self.tabs.addTab(self.preview, "Markdown")
        self.tabs.addTab(self.notes, "备注")
        self.tabs.currentChanged.connect(self.render_markdown)
        layout.addWidget(self.tabs, 1)
        self.links = QListWidget()
        self.links.setMaximumHeight(105)
        self.links.itemDoubleClicked.connect(
            lambda i: self.openRecordRequested.emit(i.data(Qt.ItemDataRole.UserRole))
        )
        self.links.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.links.customContextMenuRequested.connect(self.link_menu)
        layout.addWidget(self.links)
        layout.addWidget(
            row_widget(
                button("关联内容", lambda: self.linkRequested.emit(self.record["id"])),
                button("存为笔记", lambda: self.noteRequested.emit(self.record["id"])),
            )
        )
        self.ocr_button = button(
            "识别文字", lambda: self.ocrRequested.emit(self.record["id"])
        )
        self.open_button = button(
            "打开附件", lambda: self.openRequested.emit(self.record)
        )
        self.locate_button = button(
            "重新定位", lambda: self.relinkRequested.emit(self.record)
        )
        layout.addWidget(
            row_widget(self.ocr_button, self.open_button, self.locate_button)
        )
        layout.addWidget(
            row_widget(
                button(
                    "复制正文",
                    lambda: self.copyRequested.emit(self.record, False),
                    "copy",
                    True,
                ),
                button("删除", lambda: self.deleteRequested.emit(self.record["id"])),
            )
        )
        self.save_status = label("修改后自动保存", "Muted")
        layout.addWidget(self.save_status)
        root.addWidget(self.content, 1)
        self.content.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(650)
        self.timer.timeout.connect(self.flush)
        for field, w in [("title", self.title), ("tags", self.tags)]:
            w.textEdited.connect(lambda text, f=field: self.mark_dirty(f))
        for field, w in [("body", self.body), ("notes", self.notes)]:
            w.textChanged.connect(lambda f=field: self.mark_dirty(f))
        for field, w in [
            ("favorite", self.favorite),
            ("pinned", self.pinned),
            ("private", self.private),
        ]:
            w.toggled.connect(lambda checked, f=field: self.mark_dirty(f))

    def mark_dirty(self, field):
        if not self.loading and self.record:
            self.dirty = True
            self.dirty_fields.add(field)
            self.save_status.setText("正在编辑…")
            self.timer.start()

    def flush(self):
        self.timer.stop()
        if not self.record or not self.dirty:
            return
        fields = dict(
            title=self.title.text().strip() or KINDS[self.record["kind"]],
            body=self.body.toPlainText(),
            tags=",".join(
                t.strip()
                for t in self.tags.text().replace("，", ",").split(",")
                if t.strip()
            ),
            notes=self.notes.toPlainText(),
            favorite=int(self.favorite.isChecked()),
            pinned=int(self.pinned.isChecked()),
            private=int(self.private.isChecked()),
        )
        fields = {
            key: value for key, value in fields.items() if key in self.dirty_fields
        }
        self.record.update(fields)
        self.saveRequested.emit(self.record["id"], fields)
        self.dirty = False
        self.dirty_fields.clear()
        self.save_status.setText("正在保存…")

    def render_markdown(self, *_):
        if self.tabs.currentWidget() is self.preview:
            # QTextDocument may load local images, but never HTTP images.
            import re

            text = re.sub(
                r"!\[[^\]]*\]\(https?://[^)]*\)",
                "[远程图片未加载]",
                self.body.toPlainText(),
                flags=re.I,
            )
            self.preview.document().setBaseUrl(
                QUrl.fromLocalFile(str(self.paths.data) + "/")
            )
            self.preview.setMarkdown(text)

    def set_record(self, record, links=()):
        self.flush()
        self.loading = True
        self.record = dict(record) if record else None
        self.empty.setVisible(not bool(record))
        self.content.setVisible(bool(record))
        if not record:
            self.loading = False
            return
        self.title.setText(record["title"])
        self.tags.setText(record["tags"])
        self.body.setPlainText(record["body"])
        self.raw.setPlainText(record["raw_ocr"])
        self.notes.setPlainText(record["notes"])
        self.favorite.setChecked(bool(record["favorite"]))
        self.pinned.setChecked(bool(record["pinned"]))
        self.private.setChecked(bool(record["private"]))
        self.meta.setText(
            f"{KINDS[record['kind']]}  ·  {record['created_at'][:10]}  ·  本地保存"
        )
        picture = record["kind"] in ("screenshot", "image")
        self.picture.setVisible(picture)
        self.ocr_button.setVisible(picture)
        self.open_button.setVisible(
            bool(record["file_path"] or record["external_path"])
        )
        self.locate_button.setVisible(bool(record["external_path"]))
        if picture:
            pix = QPixmap(str(self.paths.resolve(record["file_path"])))
            self.picture.setText("图片已丢失，请重新导入" if pix.isNull() else "")
            self.picture.setIconSize(QSize(300, 135))
            self.picture.setIcon(
                icon("file")
                if pix.isNull()
                else __import__("PySide6.QtGui", fromlist=["QIcon"]).QIcon(pix)
            )
        self.links.clear()
        for r in links:
            item = QListWidgetItem(
                f"{KINDS[r['kind']]} · {r['title']}"
                + (f" · 第 {r['page']} 页" if r["page"] else "")
            )
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.links.addItem(item)
        self.links.setVisible(bool(links))
        self.dirty = False
        self.dirty_fields.clear()
        self.loading = False
        self.save_status.setText("修改后自动保存 · OCR 原文单独保留")
        self.render_markdown()

    def link_menu(self, point):
        item = self.links.itemAt(point)
        if item and self.record:
            menu = QMenu(self)
            menu.addAction(
                "移除关联",
                lambda: self.unlinkRequested.emit(
                    self.record["id"], item.data(Qt.ItemDataRole.UserRole)
                ),
            )
            menu.exec(self.links.mapToGlobal(point))


class ClipboardPanel(QDialog):
    def __init__(self, main):
        super().__init__(main, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.main = main
        self.setWindowTitle("瞬知 · 剪贴板")
        self.resize(650, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.addWidget(label("随时找回，随手复制", "Section"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "搜索历史…    ↑ ↓ 选择    Enter 复制    Esc 关闭"
        )
        root.addWidget(self.search)
        self.filter = QComboBox()
        self.filter.addItem("全部类型", None)
        for kind in CLIP_KINDS:
            self.filter.addItem(KINDS[kind], kind)
        root.addWidget(self.filter)
        self.list = QListWidget()
        root.addWidget(self.list, 1)
        self.state = label("", "Muted")
        root.addWidget(self.state)
        root.addWidget(label("仅复制到剪贴板，不向其他窗口自动发送粘贴。", "Muted"))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(160)
        self.timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda: self.timer.start())
        self.filter.currentIndexChanged.connect(self.refresh)
        self.list.itemClicked.connect(self.copy_item)
        self.search.returnPressed.connect(
            lambda: self.copy_item(self.list.currentItem())
        )
        self.list.itemActivated.connect(self.copy_item)
        self.search.installEventFilter(self)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.menu)
        self.generation = 0

    def eventFilter(self, obj, event):
        if (
            obj is self.search
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)
        ):
            delta = 1 if event.key() == Qt.Key.Key_Down else -1
            self.list.setCurrentRow(
                max(0, min(self.list.count() - 1, self.list.currentRow() + delta))
            )
            return True
        return super().eventFilter(obj, event)

    def show_panel(self):
        self.search.clear()
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def refresh(self, *_):
        query, kind = self.search.text(), self.filter.currentData()
        self.generation += 1
        generation = self.generation

        def done(rows):
            if generation != self.generation:
                return
            fill_list(self.list, rows)
            self.state.setText(
                f"最近 {len(rows)} 条"
                if rows
                else "没有匹配内容；复制文本或图片后会自动记录。"
            )
            if rows:
                self.list.setCurrentRow(0)

        self.main.io.submit(
            lambda: self.main.store.search(
                query, kinds=[kind] if kind else CLIP_KINDS, limit=80
            ),
            done,
            self.main.error,
        )

    def copy_item(self, item):
        if item:
            r = item.data(Qt.ItemDataRole.UserRole)
            self.main.copy_record(r, r["kind"] == "image")
            self.hide()

    def menu(self, point):
        item = self.list.itemAt(point)
        if not item:
            return
        r = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        for title, field in [
            ("收藏 / 取消收藏", "favorite"),
            ("置顶 / 取消置顶", "pinned"),
        ]:
            menu.addAction(
                title,
                lambda checked=False, f=field: self.main.io.submit(
                    lambda: self.main.store.update(r["id"], **{f: 1 - int(r[f])}),
                    lambda _: self.refresh(),
                    self.main.error,
                ),
            )
        menu.addAction("删除", lambda: self.main.delete_record(r["id"]))
        menu.exec(self.list.mapToGlobal(point))


class MainWindow(QMainWindow):
    def __init__(self, paths, settings=None):
        super().__init__()
        self.paths = paths
        self.settings = settings or Settings(paths)
        self.store = Store(paths)
        self.io = Jobs(parent=self)
        self.ocr_jobs = Jobs(parent=self)
        self.content = ContentService(self.store)
        self.ocr = OcrService(self.store)
        self.monitor = ClipboardMonitor(self.settings, self.content, self.io, self)
        self.monitor.captured.connect(self.captured_clipboard)
        self.monitor.error.connect(self.error)
        self.monitor.privacy.connect(self.status)
        self.ocr_jobs.changed.connect(
            lambda n: self.ocr_status.setText(f"OCR 队列 {n}" if n else "OCR 待命")
        )
        self.io.changed.connect(
            lambda n: self.io_status.setText(f"本地任务 {n}" if n else "存储就绪")
        )
        self.page = "home"
        self.generation = 0
        self.detail_generation = 0
        self.offset = 0
        self.last_count = 0
        self.overlays = []
        self.capture_pending = False
        self.previews = []
        self.active_ocr = set()
        self.quitting = False
        self.restoring = False
        self.shortcuts = []
        self.setWindowTitle("SnapMind 瞬知 · 本地工作台")
        self.setWindowIcon(icon("capture", "#3e73e8", 64))
        self.resize(1280, 840)
        self.setMinimumSize(1020, 680)
        self.build_ui()
        self.panel = ClipboardPanel(self)
        self.hotkeys = Hotkeys(QApplication.instance())
        self.make_tray()
        self.apply_theme()
        QTimer.singleShot(0, self.configure_hotkeys)
        self.prune_timer = QTimer(self)
        self.prune_timer.setInterval(30 * 60 * 1000)
        self.prune_timer.timeout.connect(self.prune)
        self.prune_timer.start()
        self.prune()
        self.navigate("home")

    def build_ui(self):
        main = QWidget()
        main.setObjectName("Main")
        self.setCentralWidget(main)
        outer = QHBoxLayout(main)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(214)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(17, 29, 17, 20)
        nav.setSpacing(7)
        brand = row_widget(label("◈", "Brand"), label("SnapMind", "Brand"))
        nav.addWidget(brand)
        sub = label("瞬知 · 留住每一个灵感", "Muted")
        sub.setContentsMargins(10, 3, 0, 26)
        nav.addWidget(sub)
        self.nav_buttons = {}
        for key, title, image in [
            ("home", "首页", "home"),
            ("gallery", "截图库", "capture"),
            ("clipboard", "剪贴板", "clipboard"),
            ("knowledge", "知识库", "book"),
            ("snippets", "常用片段", "code"),
        ]:
            b = button(
                "  " + title, lambda checked=False, k=key: self.navigate(k), image
            )
            b.setObjectName("Nav")
            b.setCheckable(True)
            nav.addWidget(b)
            self.nav_buttons[key] = b
        nav.addSpacing(23)
        nav.addWidget(label("  我的空间", "Eyebrow"))
        fav = button("  全部收藏", lambda: self.navigate("favorites"), "star")
        fav.setObjectName("Nav")
        fav.setCheckable(True)
        nav.addWidget(fav)
        self.nav_buttons["favorites"] = fav
        nav.addStretch()
        privacy = QFrame()
        privacy.setObjectName("Card")
        pv = QVBoxLayout(privacy)
        pv.setContentsMargins(14, 14, 14, 14)
        pv.addWidget(label("你的内容，只属于你", "Section"))
        local = label("离线识别 · 本机保存\n无需登录，不上传内容", "Muted")
        local.setStyleSheet("font-size:11px;")
        pv.addWidget(local)
        nav.addWidget(privacy)
        settings_button = button(
            "  设置与数据", lambda: self.navigate("settings"), "settings"
        )
        settings_button.setObjectName("Nav")
        settings_button.setCheckable(True)
        self.nav_buttons["settings"] = settings_button
        nav.addWidget(settings_button)
        outer.addWidget(side)
        content = QVBoxLayout()
        content.setContentsMargins(32, 26, 32, 18)
        content.setSpacing(22)
        top = QHBoxLayout()
        top.addWidget(label("WORKSPACE", "Eyebrow"))
        top.addStretch()
        top.addWidget(label("本地优先", "Badge"))
        theme = button("", self.toggle_theme, "moon")
        theme.setToolTip("切换深浅色主题")
        theme.setAccessibleName("切换主题")
        top.addWidget(theme)
        top.addWidget(button("快速截图", self.start_capture, "capture", True))
        add = button("添加内容", lambda: None, "plus")
        menu = QMenu(add)
        menu.addAction("新建 Markdown 笔记", lambda: self.new_record("note"))
        menu.addAction("新建常用片段", lambda: self.new_record("snippet"))
        menu.addAction("导入图片 / PDF / 文件", self.import_files)
        menu.addAction(
            "关联本地 PDF（不复制文件）", lambda: self.import_files(link=True)
        )
        add.setMenu(menu)
        top.addWidget(add)
        content.addLayout(top)
        self.heading = label("我的工作台", "Title")
        self.subtitle = label("捕捉灵感，收纳知识。需要的时候，一搜即得。", "Muted")
        content.addWidget(self.heading)
        content.addWidget(self.subtitle)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText(
            "搜索截图、代码、笔记…                                             Ctrl + K"
        )
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_changed)
        content.addWidget(self.search)
        self.search_timer = QTimer(self)
        self.search_timer.setInterval(170)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(lambda: self.refresh(reset=True))
        self.stack = QStackedWidget()
        self.home_widget = self.build_home()
        self.list_widget = self.build_list()
        self.settings_widget = self.build_settings()
        self.stack.addWidget(self.home_widget)
        self.stack.addWidget(self.list_widget)
        self.stack.addWidget(self.settings_widget)
        content.addWidget(self.stack, 1)
        outer.addLayout(content, 1)
        self.ocr_status = label("OCR 待命", "Muted")
        self.io_status = label("存储就绪", "Muted")
        self.monitor_status = label("", "Muted")
        self.statusBar().addPermanentWidget(self.monitor_status)
        self.statusBar().addPermanentWidget(self.ocr_status)
        self.statusBar().addPermanentWidget(self.io_status)
        self.status("已就绪 · 关闭窗口默认隐藏到托盘，托盘菜单可完全退出。")
        shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut.activated.connect(self.focus_search)
        self.shortcuts.append(shortcut)

    def build_home(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        actions = QHBoxLayout()
        for title, callback, image in [
            ("快速截图\n框选即保存，后台自动识别", self.start_capture, "capture"),
            ("超级剪贴板\n找回历史，快速复制", self.show_clipboard, "clipboard"),
        ]:
            b = button(title, callback, image)
            b.setObjectName("ActionCard")
            b.setIconSize(QSize(30, 30))
            actions.addWidget(b)
        layout.addLayout(actions)
        heads = QHBoxLayout()
        heads.addWidget(label("最近收纳", "Section"))
        self.home_scope = QComboBox()
        for title, scope in [
            ("全部最近", None),
            ("最近截图", ["screenshot", "image"]),
            ("最近剪贴板", list(CLIP_KINDS)),
            ("最近笔记", ["note"]),
            ("收藏内容", "favorite"),
        ]:
            self.home_scope.addItem(title, scope)
        self.home_scope.currentIndexChanged.connect(lambda: self.refresh())
        heads.addWidget(self.home_scope)
        heads.addStretch()
        heads.addWidget(button("查看全部", lambda: self.navigate("all"), "arrow"))
        layout.addLayout(heads)
        self.recent = QListWidget()
        self.recent.itemClicked.connect(
            lambda i: self.open_record(i.data(Qt.ItemDataRole.UserRole)["id"])
        )
        layout.addWidget(self.recent, 1)
        self.home_empty = label(
            "还没有收纳内容。点击“快速截图”，或复制一段文字，开始你的知识工作台。",
            "Muted",
        )
        self.home_empty.setWordWrap(True)
        layout.addWidget(self.home_empty)
        bottom = QHBoxLayout()
        self.recent_notes = QFrame()
        self.recent_notes.setObjectName("Card")
        notes = QVBoxLayout(self.recent_notes)
        notes.addWidget(label("随手记录，慢慢积累", "Section"))
        notes.addWidget(label("Markdown 笔记 · 代码片段 · 文档关联", "Muted"))
        notes.addWidget(button("新建一篇笔记", lambda: self.new_record("note"), "plus"))
        bottom.addWidget(self.recent_notes, 1)
        favorites = QFrame()
        favorites.setObjectName("Card")
        fav = QVBoxLayout(favorites)
        fav.addWidget(label("把常用内容留在手边", "Section"))
        fav.addWidget(label("收藏重要内容，置顶常用命令。", "Muted"))
        fav.addWidget(
            button("打开我的收藏", lambda: self.navigate("favorites"), "star")
        )
        bottom.addWidget(favorites, 1)
        layout.addLayout(bottom)
        return widget

    def build_list(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.addItem("全部类型", None)
        for key, title in KINDS.items():
            self.type_filter.addItem(title, key)
        self.tag_filter = QLineEdit()
        self.tag_filter.setPlaceholderText("筛选标签")
        self.date_after = QLineEdit()
        self.date_after.setPlaceholderText("起始 YYYY-MM-DD")
        self.date_after.setMaximumWidth(150)
        self.date_before = QLineEdit()
        self.date_before.setPlaceholderText("结束 YYYY-MM-DD")
        self.date_before.setMaximumWidth(150)
        self.fav_filter = QCheckBox("仅收藏")
        for w in (
            self.type_filter,
            self.tag_filter,
            self.date_after,
            self.date_before,
            self.fav_filter,
        ):
            filters.addWidget(w)
        layout.addLayout(filters)
        self.type_filter.currentIndexChanged.connect(lambda: self.refresh(reset=True))
        self.fav_filter.toggled.connect(lambda: self.refresh(reset=True))
        for w in (self.tag_filter, self.date_after, self.date_before):
            w.editingFinished.connect(lambda: self.refresh(reset=True))
        splitter = QSplitter()
        self.records = QListWidget()
        self.records.currentItemChanged.connect(self.selection_changed)
        self.editor = RecordEditor(self.paths)
        self.editor.setMinimumWidth(345)
        self.editor.saveRequested.connect(self.save_record)
        self.editor.copyRequested.connect(self.copy_record)
        self.editor.deleteRequested.connect(self.delete_record)
        self.editor.ocrRequested.connect(self.queue_ocr)
        self.editor.previewRequested.connect(self.preview_record)
        self.editor.openRequested.connect(self.open_attachment)
        self.editor.relinkRequested.connect(self.relink_file)
        self.editor.linkRequested.connect(self.choose_link)
        self.editor.unlinkRequested.connect(self.unlink_record)
        self.editor.openRecordRequested.connect(self.open_record)
        self.editor.noteRequested.connect(self.note_from)
        splitter.addWidget(self.records)
        splitter.addWidget(self.editor)
        splitter.setSizes([470, 430])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.list_state = label("", "Muted")
        self.previous = button("上一页", lambda: self.change_page(-1))
        self.next = button("下一页", lambda: self.change_page(1))
        self.batch = button("识别本页未处理图片", self.batch_ocr)
        layout.addWidget(
            row_widget(self.list_state, self.batch, self.previous, self.next)
        )
        return widget

    def build_settings(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(22, 22, 22, 22)
        form.setVerticalSpacing(14)
        self.setting_widgets = {}
        for key, title in [
            ("monitor", "自动记录剪贴板"),
            ("image_history", "保存剪贴板图片"),
            ("auto_ocr", "截图后自动识别"),
            ("close_to_tray", "关闭窗口时隐藏到托盘"),
        ]:
            w = QCheckBox(title)
            w.setChecked(self.settings.get(key))
            self.setting_widgets[key] = w
            form.addRow(w)
        for key, title, low, high in [
            ("max_item_mb", "单条上限（MB，图片按解码大小）", 1, 100),
            ("max_history", "普通剪贴板历史条数", 100, 100000),
            ("retention_days", "普通历史保留天数", 1, 3650),
        ]:
            w = QSpinBox()
            w.setRange(low, high)
            w.setValue(self.settings.get(key))
            self.setting_widgets[key] = w
            form.addRow(title, w)
        for key, title in [
            ("capture_hotkey", "截图快捷键"),
            ("clipboard_hotkey", "剪贴板面板快捷键"),
            ("search_hotkey", "全局搜索快捷键"),
        ]:
            w = QLineEdit(self.settings.get(key))
            self.setting_widgets[key] = w
            form.addRow(title, w)
        self.blacklist = QPlainTextEdit("\n".join(self.settings.get("blacklist")))
        self.blacklist.setMaximumHeight(110)
        form.addRow("不记录这些前台应用\n每行一个 .exe 名称", self.blacklist)
        form.addRow(button("保存设置", self.save_settings, primary=True))
        self.settings_message = label("", "Muted")
        self.settings_message.setWordWrap(True)
        form.addRow(self.settings_message)
        layout.addWidget(card)
        privacy = label(
            "隐私说明：内容仅存本机，默认不联网。数据库未加密；“私密”仅隐藏列表摘要。\n应用黑名单依据复制事件发生时的前台进程判断，无法保证识别所有密码或敏感内容。\n收藏、置顶及被笔记关联的记录不参与自动清理。关闭窗口时若托盘不可用，将正常退出。",
            "Muted",
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        data = QFrame()
        data.setObjectName("Card")
        box = QVBoxLayout(data)
        box.addWidget(label("数据与便携备份", "Section"))
        path_label = label(str(self.paths.data), "Muted")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)
        box.addWidget(path_label)
        box.addWidget(
            row_widget(
                button("备份 / 导出全部", self.backup),
                button("恢复备份", self.restore),
                button(
                    "打开数据目录",
                    lambda: QDesktopServices.openUrl(
                        QUrl.fromLocalFile(str(self.paths.data))
                    ),
                ),
            )
        )
        box.addWidget(button("清空普通剪贴板历史", self.clear_history))
        box.addWidget(
            label(
                "备份包含数据库、图片、托管 PDF 和可读 JSON；外部文件链接不复制源文件。\n恢复会保留恢复前数据副本。设置与黑名单保存在 config/settings.json。",
                "Muted",
            )
        )
        layout.addWidget(data)
        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def navigate(self, page):
        self.editor.flush()
        self.page = page
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.type_filter.blockSignals(True)
        self.type_filter.setCurrentIndex(0)
        self.type_filter.blockSignals(False)
        self.tag_filter.clear()
        self.date_after.clear()
        self.date_before.clear()
        self.fav_filter.blockSignals(True)
        self.fav_filter.setChecked(False)
        self.fav_filter.blockSignals(False)
        titles = {
            "home": ("我的工作台", "捕捉灵感，收纳知识。需要的时候，一搜即得。"),
            "gallery": ("截图库", "留住画面，也留住画面里的知识。"),
            "clipboard": ("超级剪贴板", "每一次复制，都能轻松找回。"),
            "knowledge": ("知识库", "笔记、文档与截图，串起你的知识。"),
            "snippets": ("常用片段", "常用命令与代码模板，一键取用。"),
            "favorites": ("我的收藏", "值得留下的，随时在手边。"),
            "all": ("全部内容", "截图、剪贴板与笔记，统一检索。"),
            "settings": ("设置与数据", "按你的习惯工作，数据始终由你掌握。"),
        }
        title, subtitle = titles.get(page, ("搜索结果", "搜索本地所有内容。"))
        self.heading.setText(title)
        self.subtitle.setText(subtitle)
        for key, b in self.nav_buttons.items():
            b.setChecked(key == page)
        self.search.setVisible(page != "settings")
        self.stack.setCurrentWidget(
            self.home_widget
            if page == "home"
            else self.settings_widget
            if page == "settings"
            else self.list_widget
        )
        self.refresh(reset=True)

    def focus_search(self):
        if self.page == "settings":
            self.navigate("all")
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
        self.search.selectAll()

    def search_changed(self):
        if self.page == "home" and self.search.text():
            self.stack.setCurrentWidget(self.list_widget)
        elif self.page == "home":
            self.stack.setCurrentWidget(self.home_widget)
        self.search_timer.start()

    def refresh(self, reset=False):
        if self.restoring:
            return
        if reset:
            self.offset = 0
        self.generation += 1
        generation = self.generation
        if self.stack.currentWidget() is self.home_widget:

            def home_done(rows):
                if generation == self.generation:
                    fill_list(self.recent, rows)
                    self.home_empty.setVisible(not rows)

            scope = self.home_scope.currentData()
            self.io.submit(
                lambda: self.store.search(
                    limit=5,
                    kinds=scope if isinstance(scope, list) else None,
                    favorite=scope == "favorite",
                ),
                home_done,
                self.error,
            )
            return
        if self.page == "settings":
            return
        kind = self.type_filter.currentData()
        scopes = {
            "gallery": ["screenshot", "image"],
            "clipboard": CLIP_KINDS,
            "snippets": ["snippet"],
        }
        kinds = [kind] if kind else scopes.get(self.page)
        if kind and self.page in scopes and kind not in scopes[self.page]:
            self.show_rows([], generation)
            return
        after, before = self.date_after.text().strip(), self.date_before.text().strip()
        try:
            for date in (after, before):
                if date:
                    datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            self.list_state.setText("日期格式应为 YYYY-MM-DD")
            return
        kwargs = dict(
            query=self.search.text(),
            kinds=kinds,
            favorite=self.page == "favorites" or self.fav_filter.isChecked(),
            knowledge=self.page == "knowledge",
            tag=self.tag_filter.text().strip(),
            after=after,
            before=before,
            offset=self.offset,
            limit=60,
        )
        self.list_state.setText("正在查找…")
        self.io.submit(
            lambda: self.store.search(**kwargs),
            lambda rows: self.show_rows(rows, generation),
            self.error,
        )

    def show_rows(self, rows, generation):
        if generation != self.generation:
            return
        current = self.editor.record["id"] if self.editor.record else None
        self.records.blockSignals(True)
        fill_list(self.records, rows)
        self.records.blockSignals(False)
        self.last_count = len(rows)
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(len(rows) == 60)
        self.list_state.setText(
            f"第 {self.offset // 60 + 1} 页 · {len(rows)} 条"
            if rows
            else "没有匹配内容。试试其他关键词，或添加你的第一条内容。"
        )
        selected = next((i for i, r in enumerate(rows) if r["id"] == current), None)
        if selected is not None:
            self.records.blockSignals(True)
            self.records.setCurrentRow(selected)
            self.records.blockSignals(False)
        elif not rows or current:
            self.editor.set_record(None)

    def change_page(self, direction):
        self.offset = max(0, self.offset + direction * 60)
        self.refresh()

    def selection_changed(self, item, previous):
        if item:
            self.load_detail(item.data(Qt.ItemDataRole.UserRole)["id"])

    def load_detail(self, record_id):
        self.editor.flush()
        self.detail_generation += 1
        generation = self.detail_generation

        def done(pair):
            if generation == self.detail_generation:
                self.editor.set_record(*pair)

        self.io.submit(
            lambda: (self.store.get(record_id), self.store.links(record_id)),
            done,
            self.error,
        )

    def open_record(self, record_id):
        self.navigate("all")
        self.load_detail(record_id)

    def save_record(self, record_id, fields):
        def done(_):
            if (
                self.editor.record
                and self.editor.record["id"] == record_id
                and not self.editor.dirty
            ):
                self.editor.save_status.setText("已保存到本机")

        self.io.submit(lambda: self.store.update(record_id, **fields), done, self.error)

    def status(self, message):
        self.statusBar().showMessage(message, 12000)

    def error(self, message):
        self.status("操作未完成：" + message)
        if self.page == "settings":
            self.settings_message.setText("操作未完成：" + message)

    def new_record(self, kind):
        self.io.submit(
            lambda: self.store.add(
                kind, "未命名笔记" if kind == "note" else "常用片段"
            ),
            lambda rid: self.open_record(rid),
            self.error,
        )

    def note_from(self, record_id):
        self.editor.flush()

        def create():
            r = self.store.get(record_id)
            if not r:
                raise ValueError("原内容已删除")
            body = r["body"]
            if r["file_path"] and r["kind"] in ("image", "screenshot"):
                body = f"![关联截图]({r['file_path']})\n\n" + body
            rid = self.store.add("note", r["title"] + " · 笔记", body, tags=r["tags"])
            self.store.link(rid, record_id)
            return rid

        self.io.submit(create, self.open_record, self.error)

    def choose_link(self, source):
        dialog = QDialog(self)
        dialog.setWindowTitle("关联截图、文档或笔记")
        dialog.resize(580, 460)
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText("输入关键词搜索关联目标")
        listing = QListWidget()
        page = QSpinBox()
        page.setRange(0, 100000)
        page.setPrefix("PDF 页码（0 为不指定）：")
        layout.addWidget(search)
        layout.addWidget(listing, 1)
        layout.addWidget(page)
        state = label("双击选择一条内容", "Muted")
        layout.addWidget(state)
        generation = [0]

        def refresh():
            generation[0] += 1
            version = generation[0]
            query = search.text()
            self.io.submit(
                lambda: self.store.search(query, limit=60),
                lambda rows: (
                    fill_list(listing, [r for r in rows if r["id"] != source])
                    if version == generation[0]
                    else None
                ),
                self.error,
            )

        def choose(item):
            target = item.data(Qt.ItemDataRole.UserRole)
            self.io.submit(
                lambda: self.store.link(
                    source, target["id"], page.value() if target["kind"] == "pdf" else 0
                ),
                lambda _: self.load_detail(source),
                self.error,
            )
            dialog.accept()

        timer = QTimer(dialog)
        timer.setInterval(170)
        timer.setSingleShot(True)
        timer.timeout.connect(refresh)
        search.textChanged.connect(lambda: timer.start())
        listing.itemDoubleClicked.connect(choose)
        refresh()
        dialog.exec()

    def unlink_record(self, source, target):
        self.io.submit(
            lambda: self.store.unlink(source, target),
            lambda _: self.load_detail(source),
            self.error,
        )

    def delete_record(self, record_id):
        if (
            QMessageBox.question(
                self, "删除内容", "删除这条内容及不再被引用的附件？此操作无法撤销。"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.editor.flush()

        def done(_):
            if self.editor.record and self.editor.record["id"] == record_id:
                self.editor.set_record(None)
            self.refresh()
            if self.panel.isVisible():
                self.panel.refresh()

        self.io.submit(lambda: self.store.delete(record_id), done, self.error)

    def copy_record(self, record, image=False):
        try:
            if self.editor.record and self.editor.record["id"] == record["id"]:
                self.editor.flush()
                record = self.editor.record
            self.monitor.copy(record, image)
            self.status("已复制，可以切换到目标窗口粘贴。")
        except Exception as exc:
            self.error(str(exc))

    def captured_clipboard(self, record_id):
        self.refresh()
        if self.panel.isVisible():
            self.panel.refresh()

    def import_files(self, checked=False, link=False):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要关联的 PDF" if link else "导入图片、PDF 或本地文件",
            "",
            "PDF (*.pdf)"
            if link
            else "支持的文件 (*.png *.jpg *.jpeg *.bmp *.webp *.pdf);;所有文件 (*)",
        )
        for filename in files:
            self.io.submit(
                lambda f=filename: self.content.import_file(f, copy=not link),
                self.imported,
                self.error,
            )

    def imported(self, record_id):
        self.status("已导入并保存到本机")
        self.open_record(record_id)
        self.io.submit(
            lambda: self.store.get(record_id),
            lambda r: (
                self.queue_ocr(record_id)
                if r and r["kind"] == "screenshot" and self.settings.get("auto_ocr")
                else None
            ),
            self.error,
        )

    def open_attachment(self, record):
        try:
            path = (
                self.paths.resolve(record["file_path"])
                if record["file_path"]
                else Path(record["external_path"])
            )
            if not path.exists():
                raise FileNotFoundError("附件已丢失；外部链接可点击“重新定位”")
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise RuntimeError("没有可用的默认应用来打开此附件")
        except Exception as exc:
            self.error(str(exc))

    def relink_file(self, record):
        filename, _ = QFileDialog.getOpenFileName(self, "重新定位外部文件")
        if filename:
            self.io.submit(
                lambda: self.store.update(
                    record["id"],
                    external_path=filename,
                    **({"body": filename} if record["kind"] == "files" else {}),
                ),
                lambda _: self.load_detail(record["id"]),
                self.error,
            )

    def start_capture(self, checked=False, screen_index=None):
        if self.overlays or self.capture_pending or self.restoring:
            return
        if not QApplication.screens():
            self.error("没有可用显示器")
            return
        self.capture_pending = True
        self.was_visible = self.isVisible()
        self.hide()
        self.panel.hide()
        for preview in list(self.previews):
            preview.close()
        QTimer.singleShot(180, lambda: self.capture_screens(screen_index))

    def capture_screens(self, screen_index=None):
        try:
            screens = QApplication.screens()
            if screen_index is not None:
                screens = [screens[screen_index]]
            snapshots = [(screen, screen.grabWindow(0).toImage()) for screen in screens]
            if any(image.isNull() for _, image in snapshots):
                raise RuntimeError("系统禁止读取屏幕；请检查屏幕捕获权限")
            for screen, image in snapshots:
                overlay = SelectionOverlay(screen, image)
                overlay.selected.connect(self.capture_selected)
                overlay.cancelled.connect(self.cancel_capture)
                self.overlays.append(overlay)
                overlay.show()
            self.overlays[0].activateWindow()
            self.overlays[0].setFocus()
        except Exception as exc:
            self.cancel_capture()
            self.error(str(exc))

    def close_overlays(self):
        for overlay in self.overlays:
            overlay.close()
        self.overlays.clear()

    def cancel_capture(self):
        self.capture_pending = False
        self.close_overlays()
        if getattr(self, "was_visible", True):
            self.showNormal()

    def capture_selected(self, image):
        self.capture_pending = False
        self.close_overlays()
        self.save_capture(image)

    def save_capture(self, image):
        self.status("正在保存截图…")

        def done(rid):
            self.showNormal()
            self.open_record(rid)
            self.show_preview(rid, image)
            if self.settings.get("auto_ocr"):
                self.queue_ocr(rid)

        def failed(message):
            self.show_main()
            self.error(message)

        self.io.submit(lambda: self.content.image(image, screenshot=True), done, failed)

    def preview_record(self, record):
        from PySide6.QtGui import QImage

        image = QImage(str(self.paths.resolve(record["file_path"])))
        if image.isNull():
            self.error("图片丢失，请重新导入")
            return
        self.show_preview(record["id"], image)

    def show_preview(self, record_id, image):
        preview = CapturePreview(image, self)
        preview.record_id = record_id
        preview.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        preview.saved.connect(self.save_capture)
        preview.copyRequested.connect(self.copy_image)
        preview.exportRequested.connect(self.export_image)
        preview.textCopyRequested.connect(
            lambda text: self.monitor.copy(
                {"kind": "text", "body": text, "raw_ocr": "", "title": "OCR 结果"}
            )
        )
        preview.ocrRequested.connect(lambda: self.queue_ocr(record_id))
        preview.favoriteRequested.connect(
            lambda: self.io.submit(
                lambda: self.store.update(record_id, favorite=1),
                lambda _: self.status("已收藏截图"),
                self.error,
            )
        )
        preview.noteRequested.connect(lambda: self.note_from(record_id))
        self.previews.append(preview)
        self.io.submit(
            lambda: self.store.get(record_id),
            lambda r: (
                preview.show_ocr(r["raw_ocr"])
                if r and r["raw_ocr"] and preview in self.previews
                else None
            ),
            self.error,
        )
        preview.finished.connect(
            lambda _: (
                self.previews.remove(preview) if preview in self.previews else None
            )
        )
        preview.show()

    def copy_image(self, image):
        self.monitor.copy_image(image)
        self.status("图片已复制")

    def export_image(self, image):
        filename, _ = QFileDialog.getSaveFileName(
            self, "保存截图", "截图.png", "PNG 图片 (*.png);;JPEG 图片 (*.jpg)"
        )
        if filename:
            self.io.submit(
                lambda: self.write_image(image, filename),
                lambda _: self.status("图片已保存"),
                self.error,
            )

    @staticmethod
    def write_image(image, filename):
        if not image.save(filename):
            raise OSError("图片保存失败，请检查路径和写入权限")

    def queue_ocr(self, record_id):
        if self.restoring or record_id in self.active_ocr:
            return
        self.editor.flush()
        self.active_ocr.add(record_id)
        for preview in self.previews:
            if preview.record_id == record_id:
                preview.ocr_state.setText("后台识别中，可以继续截图…")

        def done(result):
            self.active_ocr.discard(record_id)
            if result is None:
                return
            _, text, _ = result
            for preview in self.previews:
                if preview.record_id == record_id:
                    preview.show_ocr(text)
            self.status(
                "OCR 已完成并保存"
                if text
                else "未识别到文字；可以手工输入或重新选择更清晰区域。"
            )
            if (
                self.editor.record
                and self.editor.record["id"] == record_id
                and not self.editor.dirty
            ):
                self.load_detail(record_id)
            self.refresh()

        def failed(message):
            self.active_ocr.discard(record_id)
            for preview in self.previews:
                if preview.record_id == record_id:
                    preview.ocr_state.setText("识别失败，请检查图片后重新识别。")
            self.error("OCR " + message)

        # Flush pending IO writes before running this record's OCR.
        self.io.submit(
            lambda: record_id,
            lambda rid: self.ocr_jobs.submit(
                lambda: self.ocr.recognize(rid), done, failed
            ),
            failed,
        )

    def batch_ocr(self):
        count = 0
        for index in range(self.records.count()):
            r = self.records.item(index).data(Qt.ItemDataRole.UserRole)
            if r["kind"] in ("screenshot", "image") and not r["raw_ocr"]:
                self.queue_ocr(r["id"])
                count += 1
        self.status(f"已将 {count} 张图片加入 OCR 队列")

    def show_clipboard(self):
        if not self.restoring:
            self.panel.show_panel()

    def make_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("SnapMind 瞬知 · 内容仅保存在本机")
        menu = QMenu(self)
        menu.addAction("打开主窗口", self.show_main)
        menu.addAction("快速截图", self.start_capture)
        screens = menu.addMenu("截取指定显示器")
        screens.aboutToShow.connect(lambda: self.fill_screen_menu(screens))
        menu.addAction("打开剪贴板", self.show_clipboard)
        self.pause_action = menu.addAction("暂停剪贴板监控", self.toggle_monitor)
        menu.addSeparator()
        menu.addAction("完全退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.show_main()
                if reason == QSystemTrayIcon.ActivationReason.DoubleClick
                else None
            )
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.update_monitor_status()

    def fill_screen_menu(self, menu):
        menu.clear()
        for i, screen in enumerate(QApplication.screens()):
            menu.addAction(
                f"{i + 1} · {screen.name()}",
                lambda checked=False, index=i: self.start_capture(screen_index=index),
            )

    def show_main(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def update_monitor_status(self):
        enabled = self.settings.get("monitor")
        self.monitor_status.setText(
            "● 剪贴板监控中  ·  本地存储" if enabled else "○ 剪贴板已暂停  ·  本地存储"
        )
        self.pause_action.setText("暂停剪贴板监控" if enabled else "恢复剪贴板监控")

    def toggle_monitor(self):
        self.settings.update(monitor=not self.settings.get("monitor"))
        self.setting_widgets["monitor"].setChecked(self.settings.get("monitor"))
        self.update_monitor_status()

    def configure_hotkeys(self):
        bindings = [
            (self.settings.get("capture_hotkey"), self.start_capture),
            (self.settings.get("clipboard_hotkey"), self.show_clipboard),
            (self.settings.get("search_hotkey"), self.focus_search),
        ]
        try:
            errors = self.hotkeys.register(bindings)
            for shortcut in self.shortcuts[1:]:
                shortcut.setEnabled(False)
                shortcut.deleteLater()
            self.shortcuts = self.shortcuts[:1]
            if not IS_WINDOWS:
                for text, callback in bindings:
                    shortcut = QShortcut(QKeySequence(text), self)
                    shortcut.activated.connect(callback)
                    self.shortcuts.append(shortcut)
            self.settings_message.setText(
                "\n".join(errors) if errors else "全局快捷键已注册"
            )
            if errors:
                self.status(" ".join(errors))
            return errors
        except ValueError as exc:
            self.error(str(exc))
            return [str(exc)]

    def save_settings(self):
        from .native import parse_hotkey

        values = {}
        for key, w in self.setting_widgets.items():
            values[key] = (
                w.isChecked()
                if isinstance(w, QCheckBox)
                else w.value()
                if isinstance(w, QSpinBox)
                else w.text().strip()
            )
        try:
            pairs = [
                parse_hotkey(values[key])
                for key in ("capture_hotkey", "clipboard_hotkey", "search_hotkey")
            ]
            if len(set(pairs)) != 3:
                raise ValueError("三个快捷键不能相同")
            values["blacklist"] = [
                p.strip().casefold()
                for p in self.blacklist.toPlainText().splitlines()
                if p.strip()
            ]
            previous = dict(self.settings.values)
            self.settings.update(**values)
            errors = self.configure_hotkeys()
            if errors and IS_WINDOWS:
                self.settings.update(**previous)
                self.settings_message.setText(
                    "快捷键注册失败，设置未应用：" + " ".join(errors)
                )
                return
            self.update_monitor_status()
            self.prune()
            self.settings_message.setText(
                "设置已保存。"
                + (
                    "当前 Linux 环境的全局快捷键需在 Windows 验证。"
                    if not IS_WINDOWS
                    else ""
                )
            )
        except Exception as exc:
            self.error(str(exc))

    def apply_theme(self):
        QApplication.instance().setStyleSheet(
            stylesheet(self.settings.get("theme") == "dark")
        )

    def toggle_theme(self):
        self.settings.update(
            theme="dark" if self.settings.get("theme") == "light" else "light"
        )
        self.apply_theme()

    def prune(self):
        if self.restoring:
            return
        self.io.submit(
            lambda: self.store.prune(
                self.settings.get("retention_days"), self.settings.get("max_history")
            ),
            lambda _: None,
            self.error,
        )

    def clear_history(self):
        if (
            QMessageBox.question(
                self, "清空历史", "清空未收藏、未置顶、未被笔记关联的剪贴板记录？"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.editor.flush()
            self.io.submit(
                lambda: self.store.prune(clear=True),
                lambda n: (self.refresh(), self.status(f"已清理 {n} 条普通记录")),
                self.error,
            )

    def backup(self):
        self.editor.flush()
        if self.ocr_jobs.pending or self.active_ocr:
            self.error("请等待 OCR 队列完成后再备份")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "备份并导出全部数据", "SnapMind-backup.zip", "ZIP 备份 (*.zip)"
        )
        if filename:
            if self.ocr_jobs.pending or self.active_ocr:
                self.error("文件选择期间新增了 OCR 任务，请等待完成后再备份")
                return
            self.monitor.suspended = True
            self.status("正在备份数据库和附件，剪贴板捕获暂时暂停…")

            def finish(message):
                self.monitor.suspended = False
                self.status(message)

            self.io.submit(
                lambda: self.store.backup(filename),
                lambda _: finish("备份完成，含数据库、附件及 JSON 导出"),
                lambda error: finish("备份失败：" + error),
            )

    def restore(self):
        if self.io.pending or self.ocr_jobs.pending or self.active_ocr:
            self.error("请等待后台任务完成后恢复")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "选择 SnapMind 备份", "", "ZIP 备份 (*.zip)"
        )
        if not filename:
            return
        if (
            QMessageBox.question(
                self,
                "恢复备份",
                "当前数据将替换为备份内容，恢复前数据会另存副本。继续？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        if self.io.pending or self.ocr_jobs.pending or self.active_ocr:
            self.error("确认期间新增了后台任务，请等待完成后再恢复")
            return
        self.editor.flush()
        self.restoring = True
        self.monitor.suspended = True
        self.centralWidget().setEnabled(False)
        self.status("正在恢复备份，剪贴板捕获暂时暂停…")
        self.panel.hide()
        for preview in list(self.previews):
            preview.close()

        def finish(message):
            self.restoring = False
            self.monitor.suspended = False
            self.centralWidget().setEnabled(True)
            self.editor.set_record(None)
            self.refresh()
            self.status(message)

        self.io.submit(
            lambda: self.store.restore(filename),
            lambda old: finish("恢复完成，恢复前副本：" + old),
            lambda error: finish("恢复未完成：" + error),
        )

    def changeEvent(self, event):
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and hasattr(self, "tray")
            and self.tray.isVisible()
            and self.settings.get("close_to_tray")
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def closeEvent(self, event):
        self.editor.flush()
        if (
            not self.quitting
            and self.settings.get("close_to_tray")
            and self.tray.isVisible()
        ):
            self.hide()
            event.ignore()
            return
        event.accept()
        self.quit_app()

    def quit_app(self):
        if self.quitting:
            return
        self.quitting = True
        self.monitor.suspended = True
        self.prune_timer.stop()
        self.editor.flush()
        self.hotkeys.close()
        self.tray.hide()
        self.close_overlays()
        # Retain workers and their result objects until every write completes.
        self.io.wait()
        self.ocr_jobs.wait()
        QApplication.instance().quit()
