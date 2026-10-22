import time

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from snapmind.capture import ImageCanvas, SelectionOverlay
from snapmind.native import parse_hotkey
from snapmind.paths import Settings
from snapmind.services import ContentService
from snapmind.ui import MainWindow


def wait_for(app, condition, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        QTest.qWait(10)
    assert condition(), "asynchronous operation timed out"


@pytest.fixture
def window(app, paths, monkeypatch):
    monkeypatch.setattr("snapmind.services.IS_WINDOWS", False)
    settings = Settings(paths)
    settings.update(monitor=False, close_to_tray=False)
    main = MainWindow(paths, settings)
    main.show()
    wait_for(app, lambda: not main.io.pending)
    yield main
    main.monitor.suspended = True
    main.search_timer.stop()
    main.prune_timer.stop()
    main.editor.flush()
    main.io.wait()
    main.ocr_jobs.wait()
    app.processEvents()
    main.hotkeys.close()
    main.tray.hide()
    main.monitor.clipboard.dataChanged.disconnect(main.monitor.capture)
    main.quitting = True
    main.close()
    app.processEvents()


def test_first_start_navigation_and_theme(window, app):
    assert window.isVisible()
    for page in (
        "gallery",
        "clipboard",
        "knowledge",
        "snippets",
        "favorites",
        "settings",
        "home",
    ):
        window.navigate(page)
        wait_for(app, lambda: not window.io.pending)
        assert window.nav_buttons[page].isChecked()
        assert window.heading.text()
    window.toggle_theme()
    assert window.settings.get("theme") == "dark"
    window.toggle_theme()


def test_five_clipboard_items_pause_and_self_copy(window, app):
    window.settings.update(monitor=True)
    for i in range(5):
        app.clipboard().setText(f"git command {i}")
        wait_for(app, lambda: not window.io.pending)
    assert len(window.store.search(kinds=["code"])) == 5
    app.clipboard().setText("git command 0")
    wait_for(app, lambda: not window.io.pending)
    assert len(window.store.search()) == 5
    window.copy_record(window.store.search()[0])
    wait_for(app, lambda: not window.io.pending)
    assert len(window.store.search()) == 5
    window.toggle_monitor()
    app.clipboard().setText("paused private value")
    app.processEvents()
    window.io.wait()
    assert window.store.search("paused") == []
    window.toggle_monitor()
    app.clipboard().setText("restored monitoring")
    wait_for(app, lambda: not window.io.pending)
    assert window.store.search("restored")


def test_delayed_clipboard_notification_does_not_capture_own_image(window, app):
    window.settings.update(monitor=True)
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    window.copy_image(image)
    window.monitor.capture()  # Windows may deliver the event after setMimeData returns.
    wait_for(app, lambda: not window.io.pending)
    assert window.store.search() == []


def test_blacklisted_and_unknown_windows_foreground_not_saved(window, app, monkeypatch):
    monkeypatch.setattr("snapmind.services.IS_WINDOWS", True)
    monkeypatch.setattr("snapmind.services.foreground_app", lambda: "keepass.exe")
    window.settings.update(monitor=True)
    app.clipboard().setText("private test fixture")
    app.processEvents()
    assert window.store.search() == []
    monkeypatch.setattr("snapmind.services.foreground_app", lambda: None)
    app.clipboard().setText("unknown foreground fixture")
    app.processEvents()
    assert window.store.search() == []


def test_edit_title_does_not_overwrite_background_ocr_body(window, app):
    rid = window.store.add("screenshot", "title", "")
    window.open_record(rid)
    wait_for(app, lambda: window.editor.record is not None)
    window.store.apply_ocr(rid, "recognized text")
    window.editor.title.setText("edited title")
    window.editor.mark_dirty("title")
    window.editor.flush()
    wait_for(app, lambda: not window.io.pending)
    assert window.store.get(rid)["body"] == "recognized text"
    assert window.store.get(rid)["title"] == "edited title"


def test_selected_capture_automatically_queues_real_ocr(window, app, tmp_path):
    from tools.ocr_fixture import make_fixture

    source = make_fixture(tmp_path / "capture.png")
    # SelectionOverlay's selected signal invokes this without an OCR button press.
    window.capture_selected(QImage(str(source)))
    wait_for(app, lambda: bool(window.store.search("0x09F0")), seconds=15)
    rows = window.store.search("0x09F0")
    assert len(rows) == 1 and rows[0]["kind"] == "screenshot"
    assert "寄存器" in rows[0]["raw_ocr"]
    assert window.paths.resolve(rows[0]["file_path"]).exists()
    wait_for(app, lambda: not window.io.pending and not window.ocr_jobs.pending)
    assert window.previews
    assert "0x09F0" in window.previews[0].ocr_text.toPlainText()
    for preview in list(window.previews):
        preview.close()


def test_markdown_preview_refuses_network_and_outside_data(window, tmp_path):
    browser = window.editor.preview
    assert browser.loadResource(2, QUrl("https://example.com/image.png")) is None
    assert (
        browser.loadResource(2, QUrl.fromLocalFile(str(tmp_path / "outside.png")))
        is None
    )


def test_clipboard_images_html_and_files(window, app, tmp_path):
    window.settings.update(monitor=True)
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    app.clipboard().setImage(image)
    wait_for(app, lambda: not window.io.pending)
    assert len(window.store.search(kinds=["image"])) == 1
    app.clipboard().setImage(image)
    wait_for(app, lambda: not window.io.pending)
    assert len(window.store.search(kinds=["image"])) == 1
    window.settings.update(image_history=False)
    image.fill(Qt.GlobalColor.red)
    app.clipboard().setImage(image)
    app.processEvents()
    assert len(window.store.search(kinds=["image"])) == 1
    mime = QMimeData()
    mime.setHtml("<b>register 0x09F0</b>")
    mime.setText("register 0x09F0")
    app.clipboard().setMimeData(mime)
    wait_for(app, lambda: not window.io.pending)
    record = window.store.search(kinds=["html"])[0]
    assert "<b>" in record["html"]
    window.copy_record(record)
    assert app.clipboard().mimeData().hasHtml()
    mime = QMimeData()
    paths = [tmp_path / "中文 文件.txt", tmp_path / "code.py"]
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    app.clipboard().setMimeData(mime)
    wait_for(app, lambda: not window.io.pending)
    record = window.store.search(kinds=["files"])[0]
    window.copy_record(record)
    assert [u.toLocalFile() for u in app.clipboard().mimeData().urls()] == [
        str(p) for p in paths
    ]


def test_size_limit_and_task_failure_do_not_break_ui(window, app):
    window.settings.update(monitor=True, max_item_mb=1)
    app.clipboard().setText("x" * (1024**2 + 1))
    app.processEvents()
    assert window.store.search() == []
    failures = []
    window.io.submit(lambda: 1 / 0, failed=failures.append)
    wait_for(app, lambda: bool(failures))
    assert "ZeroDivisionError" in failures[0]
    window.new_record("note")
    wait_for(app, lambda: bool(window.editor.record))


def test_edit_autosave_and_search_in_three_steps(window, app):
    rid = window.store.add(
        "screenshot", "寄存器说明", "控制寄存器 0x09F0", raw_ocr="控制寄存器 0x09FO"
    )
    window.focus_search()  # 1. activate search
    window.search.setText("0x09F0")  # 2. enter query
    wait_for(app, lambda: window.records.count() == 1)
    window.records.setCurrentRow(0)  # 3. view result
    wait_for(app, lambda: window.editor.record is not None)
    assert window.editor.record["id"] == rid
    window.editor.body.setPlainText("手工修正 0x09F0")
    wait_for(app, lambda: window.store.get(rid)["body"] == "手工修正 0x09F0")
    assert window.store.get(rid)["raw_ocr"] == "控制寄存器 0x09FO"


def test_clipboard_panel_keyboard_search_copy(window, app):
    window.store.add("text", "target", "unique history phrase")
    window.show_clipboard()
    window.panel.search.setText("unique")
    wait_for(app, lambda: window.panel.list.count() == 1)
    QTest.keyClick(window.panel.search, Qt.Key.Key_Return)
    assert app.clipboard().text() == "unique history phrase"
    assert not window.panel.isVisible()


def test_annotate_undo_redo_and_mosaic(app):
    image = QImage(400, 300, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    canvas = ImageCanvas(image)
    canvas.resize(400, 300)
    canvas.show()
    canvas.tool = "矩形"
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(canvas, QPoint(150, 150))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(150, 150))
    assert canvas.image != image
    changed = canvas.image.copy()
    canvas.undo()
    assert canvas.image == image
    canvas.redo()
    assert canvas.image == changed
    canvas.tool = "马赛克"
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    assert canvas.image != changed
    canvas.close()


def test_capture_logical_to_physical_coordinates_and_escape(app):
    screen = app.primaryScreen()
    image = QImage(
        screen.geometry().width() * 2,
        screen.geometry().height() * 2,
        QImage.Format.Format_RGB32,
    )
    image.fill(Qt.GlobalColor.white)
    overlay = SelectionOverlay(screen, image)
    results = []
    overlay.selected.connect(results.append)
    overlay.show()
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(overlay, QPoint(120, 80))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(120, 80))
    assert len(results) == 1
    assert results[0].width() == 202 and results[0].height() == 122
    cancelled = []
    overlay.cancelled.connect(lambda: cancelled.append(True))
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    assert cancelled
    overlay.close()


def test_pdf_import_extract_and_link(window, app, tmp_path):
    path = tmp_path / "technical manual.pdf"
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 50 750 Td (Register 0x09F0 configuration) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(str(path))
    content = ContentService(window.store)
    copied = content.import_file(str(path))
    r = window.store.get(copied)
    assert "0x09F0" in r["body"]
    assert window.paths.resolve(r["file_path"]).exists()
    linked = content.import_file(str(path), copy=False)
    assert window.store.get(linked)["external_path"] == str(path)
    assert window.store.get(linked)["file_path"] == ""
    path.unlink()
    errors = []
    window.error = errors.append
    window.open_attachment(window.store.get(linked))
    assert errors and "丢失" in errors[0]


@pytest.mark.parametrize("text", ["Ctrl+Alt+A", "Ctrl+Shift+F12", "Alt+1"])
def test_valid_hotkeys(text):
    assert parse_hotkey(text)[1] > 0


@pytest.mark.parametrize("text", ["A", "Ctrl", "Ctrl+A+B", "Win+Shift+S", "Ctrl+NOPE"])
def test_reject_invalid_or_reserved_hotkeys(text):
    with pytest.raises(ValueError):
        parse_hotkey(text)


def test_backup_rechecks_ocr_after_nested_file_dialog(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    archive = tmp_path / "not-created.zip"
    errors = []
    window.error = errors.append

    def choose(*args):
        window.active_ocr.add("started-during-file-dialog")
        return str(archive), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    window.backup()
    assert errors and "新增了 OCR" in errors[0]
    assert not archive.exists()
    window.active_ocr.clear()


def test_new_capture_releases_old_preview_and_deduplicates_pending_shortcut(
    window, app, monkeypatch
):
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    window.show_preview("saved-record", image)
    calls = []
    monkeypatch.setattr(window, "capture_screens", lambda index: calls.append(index))
    window.start_capture()
    window.start_capture()
    assert window.capture_pending
    assert not window.previews
    QTest.qWait(220)
    app.processEvents()
    assert len(calls) == 1
    window.cancel_capture()
    assert not window.capture_pending


def test_restore_rechecks_tasks_after_confirmation(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    archive = tmp_path / "backup.zip"
    window.store.backup(str(archive))
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args: (str(archive), "")
    )
    errors = []
    window.error = errors.append

    def confirm(*args):
        window.active_ocr.add("started-during-confirmation")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    window.restore()
    assert errors and "新增了后台任务" in errors[0]
    assert not window.restoring
    window.active_ocr.clear()
