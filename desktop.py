"""MaoMao Read desktop: a real browser on the left, the reading coach on the right.

You read directly on the web page: press "Read on this page", click a paragraph, read it aloud,
and the mistakes are colored right on the page. The panes talk through console messages
prefixed "MAOMAO:" (see static/page_reader.js and window.desktop* in static/index.html).
Run:  .venv/bin/python desktop.py
"""

import json
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEnginePermission, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLineEdit, QMainWindow, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

import script
from app import ROOT
from app import app as web_app

HOME = "https://zh.wikipedia.org/wiki/Wikipedia:首页"
PAGE_READER = (ROOT / "static" / "page_reader.js").read_text(encoding="utf-8")
PREFIX = "MAOMAO:"


PORT = 8765  # fixed, because saved data (review deck, progress) belongs to this exact address


def start_server() -> str:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", PORT))
        except OSError:  # already in use: fall back to any free port (saved data won't carry over this run)
            s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(web_app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}/"


_profile = None


def profile() -> QWebEngineProfile:
    """A persistent profile, so the review deck, progress history and settings survive restarts
    (Qt 6's default profile is off-the-record and forgets everything on exit)."""
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile("maomao")
        _profile.setPersistentStoragePath(str(ROOT / "output" / "browser-profile"))
        _profile.setCachePath(str(ROOT / "output" / "browser-cache"))
        _profile.downloadRequested.connect(save_download)
    return _profile


def save_download(download) -> None:
    """Files the coach makes (the progress CSV) get a Save dialog. Downloads started by websites in the
    browser pane are refused, so no site can save files to your computer through the app."""
    url = download.url().toString()
    if not (url.startswith(("blob:http://127.0.0.1:", "data:")) or download.page() and
            download.page().url().host() == "127.0.0.1"):
        download.cancel()
        return
    default = Path.home() / "Downloads" / (download.downloadFileName() or "maomao-progress.csv")
    path, _ = QFileDialog.getSaveFileName(None, "Save file", str(default))
    if not path:
        download.cancel()
        return
    download.setDownloadDirectory(str(Path(path).parent))
    download.setDownloadFileName(Path(path).name)
    download.accept()


class BridgePage(QWebEnginePage):
    """Forwards "MAOMAO:" console messages to a handler; everything else is ignored."""

    def __init__(self, parent, on_message):
        super().__init__(profile(), parent)
        self.on_message = on_message

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith(PREFIX):
            try:
                self.on_message(json.loads(message[len(PREFIX):]))
            except (ValueError, TypeError):
                pass


class BrowserPage(BridgePage):
    """Links that open new windows load in the same pane."""

    def createWindow(self, _type):
        return self


class ReaderPage(BridgePage):
    """The reader pane may use the microphone; nothing else gets it."""

    def __init__(self, parent, on_message):
        super().__init__(parent, on_message)
        self.permissionRequested.connect(self.on_permission)

    def on_permission(self, permission: QWebEnginePermission):
        local = permission.origin().host() == "127.0.0.1"
        if local and permission.permissionType() == QWebEnginePermission.PermissionType.MediaAudioCapture:
            permission.grant()
        else:
            permission.deny()


class Window(QMainWindow):
    def __init__(self, reader_url: str):
        super().__init__()
        self.setWindowTitle("猫猫读 MaoMao Read")
        self.resize(1500, 900)
        self.read_after_load = False
        self.lang = "zh"  # the coach pane tells us its language and character set when it loads
        self.script = "s"

        # Left: browser with a toolbar
        self.web = QWebEngineView()
        self.web.setPage(BrowserPage(self.web, self.from_browser))
        self.address = QLineEdit()
        self.address.setPlaceholderText("Web address or search")
        self.address.returnPressed.connect(self.go)
        self.web.urlChanged.connect(lambda u: self.address.setText(u.toString()))
        self.web.loadFinished.connect(self.page_loaded)

        def button(label, slot, tip=""):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            return b

        self.read_btn = button("🐾 Read on this page", self.toggle_reading, "Click any paragraph on the page to read it aloud")
        self.read_btn.setCheckable(True)
        bar = QHBoxLayout()
        bar.addWidget(button("←", self.web.back))
        bar.addWidget(button("→", self.web.forward))
        bar.addWidget(button("⟳", self.web.reload))
        bar.addWidget(self.address, 1)
        bar.addWidget(self.read_btn)
        self.left = left = QWidget()
        col = QVBoxLayout(left)
        col.setContentsMargins(6, 6, 6, 6)
        col.addLayout(bar)
        col.addWidget(self.web, 1)

        # Right: the reading coach (local web app)
        self.reader = QWebEngineView()
        self.reader.setPage(ReaderPage(self.reader, self.from_reader))
        self.reader.loadFinished.connect(lambda ok: self.reader.page().runJavaScript("window.desktopMode && window.desktopMode()"))
        self.reader.load(QUrl(f"{reader_url}?v={int(time.time())}"))  # new address each run: never an old saved copy

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.reader)
        split.setSizes([850, 650])
        left.hide()  # the coach starts at full width; it shows the browser when you open an article or a site
        self.setCentralWidget(split)
        self.web.load(QUrl(HOME))

    def go(self):
        text = self.address.text().strip()
        if " " in text or "." not in text:
            url = QUrl("https://zh.wikipedia.org/w/index.php?search=" + QUrl.toPercentEncoding(text).data().decode())
        else:
            url = QUrl.fromUserInput(text)
        self.web.load(url)

    # --- browser pane ---
    def page_js(self, code: str):
        self.web.page().runJavaScript(PAGE_READER + "\n" + code)

    def toggle_reading(self, on: bool):
        self.read_btn.setText("🐾 Reading… (click a paragraph)" if on else "🐾 Read on this page")
        self.page_js(f"__mm.start({json.dumps(self.lang)}, {json.dumps(self.script)})" if on else "__mm.stop()")
        if not on:
            self.reader_js("window.desktopStopped()")

    def page_loaded(self, ok: bool):
        # A new page means a fresh set of passages; keep reading mode on if it was on
        if self.read_after_load or self.read_btn.isChecked():
            self.read_after_load = False
            self.read_btn.setChecked(True)
            self.toggle_reading(True)
        else:  # tell the page its language, and show it in the chosen character set, reading or not
            self.page_js(f"__mm.prime({json.dumps(self.lang)}, {json.dumps(self.script)})")

    def from_browser(self, msg: dict):
        if msg.get("type") == "passage":
            self.reader_js(f"window.desktopPassage({json.dumps(msg, ensure_ascii=False)})")
        elif msg.get("type") == "convert":
            to = msg.get("script", "")
            texts = [script.convert(str(t)[:20_000], to) for t in msg.get("texts", [])[:20_000]]
            self.page_js(f"__mm.applyTexts({json.dumps(texts, ensure_ascii=False)}, {json.dumps(to)})")
        elif msg.get("type") == "reading":  # you highlighted text with reading mode off: it's on now
            self.read_btn.setChecked(True)
            self.read_btn.setText("🐾 Reading… (click a paragraph)")
        elif msg.get("type") == "define":
            self.reader_js(f"window.desktopDefine({json.dumps(msg, ensure_ascii=False)})")
        elif msg.get("type") == "error":
            self.reader_js(f"window.loadArticle({json.dumps({'error': msg.get('message', '')}, ensure_ascii=False)})")

    # --- reader pane ---
    def reader_js(self, code: str):
        self.reader.page().runJavaScript(code)

    def from_reader(self, msg: dict):
        kind = msg.get("type")
        if kind == "lang":
            self.lang = "en" if msg.get("lang") == "en" else "zh"
            new_script = msg.get("script", "") if msg.get("script") in ("s", "t", "") else ""
            changed, self.script = new_script != self.script, new_script
            if changed and self.read_btn.isChecked():
                self.page_js(f"__mm.start({json.dumps(self.lang)}, {json.dumps(self.script)})")
            elif not self.read_btn.isChecked():
                self.page_js(f"__mm.prime({json.dumps(self.lang)}, {json.dumps(self.script)})")
            if self.lang == "en" and "zh.wikipedia.org" in self.web.url().toString():
                self.web.load(QUrl("https://simple.wikipedia.org/wiki/Cat"))
        elif kind == "open" and str(msg.get("url", "")).startswith(("http://", "https://")):
            self.read_after_load = True
            self.web.load(QUrl(msg["url"]))
        elif kind == "mark":
            self.page_js(f"__mm.mark({json.dumps(msg.get('results', []), ensure_ascii=False)})")
        elif kind == "pinyin":
            self.page_js(f"__mm.setPinyin({json.dumps(msg.get('pinyin'), ensure_ascii=False)}, {json.dumps(bool(msg.get('show')))})")
        elif kind == "browser":  # the coach hides the browser when it isn't in use (stories, Review, Progress)
            self.left.setVisible(bool(msg.get("show")))
        elif kind == "nav":
            self.page_js("__mm.next()" if msg.get("dir") == 1 else "__mm.prev()")


STYLE = """
QMainWindow, QWidget { background: #fbf3e8; color: #3d2f28; font-size: 14px; }
QLineEdit { background: #fffdf9; border: 2px solid #f0e0cc; border-radius: 14px; padding: 6px 12px; }
QLineEdit:focus { border-color: #e8823a; }
QPushButton { background: #fffdf9; border: 2px solid #f0e0cc; border-radius: 14px; padding: 6px 14px; }
QPushButton:hover { background: #fde9d6; }
QSplitter::handle { background: #f0e0cc; width: 3px; }
"""

if __name__ == "__main__":
    qt = QApplication(sys.argv)
    qt.setStyleSheet(STYLE)
    win = Window(start_server())
    win.show()
    sys.exit(qt.exec())
