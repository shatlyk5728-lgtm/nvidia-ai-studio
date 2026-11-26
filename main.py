import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

import keyring
from openai import OpenAI
from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QLineEdit, QComboBox, QDialog, QFormLayout,
    QMessageBox, QListWidget, QListWidgetItem, QSplitter, QFrame, QCheckBox
)

APP_NAME = "NVIDIA AI Studio"
BASE_URL = "https://integrate.api.nvidia.com/v1"
SERVICE_NAME = "NVIDIA AI Studio"
DATA_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "NVIDIA AI Studio"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "chats.sqlite3"


def get_api_key():
    try:
        return keyring.get_password(SERVICE_NAME, "api_key") or ""
    except Exception:
        return ""


def save_api_key(value):
    try:
        if value.strip():
            keyring.set_password(SERVICE_NAME, "api_key", value.strip())
        else:
            try:
                keyring.delete_password(SERVICE_NAME, "api_key")
            except Exception:
                pass
        return True
    except Exception as exc:
        raise RuntimeError(f"Не удалось сохранить ключ в Windows Credential Manager: {exc}")


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, created TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, role TEXT, content TEXT, created TEXT)")
    con.commit()
    return con


class ApiWorker(QThread):
    token = Signal(str)
    done = Signal()
    error = Signal(str)
    models_ready = Signal(list)

    def __init__(self, mode, api_key, payload=None):
        super().__init__()
        self.mode, self.api_key, self.payload = mode, api_key, payload or {}

    def run(self):
        try:
            client = OpenAI(api_key=self.api_key, base_url=BASE_URL, timeout=90, max_retries=2)
            if self.mode == "models":
                result = client.models.list()
                self.models_ready.emit(sorted([m.id for m in result.data]))
            elif self.mode == "chat":
                stream = client.chat.completions.create(
                    model=self.payload["model"],
                    messages=self.payload["messages"],
                    temperature=self.payload.get("temperature", 0.7),
                    max_tokens=self.payload.get("max_tokens", 2048),
                    stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        self.token.emit(chunk.choices[0].delta.content)
                self.done.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.key = QLineEdit(get_api_key())
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("nvapi-...")
        self.show_key = QCheckBox("Показать ключ")
        self.show_key.toggled.connect(lambda v: self.key.setEchoMode(QLineEdit.Normal if v else QLineEdit.Password))
        wrap = QWidget()
        wlayout = QVBoxLayout(wrap)
        wlayout.setContentsMargins(0, 0, 0, 0)
        wlayout.addWidget(self.key)
        wlayout.addWidget(self.show_key)
        form.addRow("NVIDIA API key:", wrap)
        layout.addLayout(form)
        note = QLabel("Ключ хранится в защищённом хранилище Windows Credential Manager.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        buttons = QHBoxLayout()
        save = QPushButton("Сохранить")
        cancel = QPushButton("Отмена")
        save.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 760)
        self.settings = QSettings("NVIDIA", "AI Studio")
        self.current_chat = None
        self.messages = []
        self.worker = None
        self.busy = False
        self._build_ui()
        self._load_chats()
        self._apply_style()
        if get_api_key():
            self.load_models()

    def _build_ui(self):
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(255)
        sl = QVBoxLayout(side)
        brand = QLabel("✦  NVIDIA AI Studio")
        brand.setObjectName("brand")
        sl.addWidget(brand)
        new_btn = QPushButton("+  Новый чат")
        new_btn.clicked.connect(self.new_chat)
        sl.addWidget(new_btn)
        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self.open_chat)
        sl.addWidget(self.chat_list, 1)
        settings_btn = QPushButton("⚙  Настройки")
        settings_btn.clicked.connect(self.open_settings)
        sl.addWidget(settings_btn)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(26, 20, 26, 20)
        top = QHBoxLayout()
        title = QLabel("Чат")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addStretch()
        self.model_box = QComboBox()
        self.model_box.setMinimumWidth(270)
        self.model_box.setEditable(True)
        self.model_box.setInsertPolicy(QComboBox.NoInsert)
        top.addWidget(QLabel("Модель"))
        top.addWidget(self.model_box)
        refresh = QPushButton("↻")
        refresh.setToolTip("Обновить список моделей")
        refresh.clicked.connect(self.load_models)
        top.addWidget(refresh)
        ml.addLayout(top)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setAcceptRichText(False)
        self.transcript.setPlaceholderText("Начните новый диалог с NVIDIA AI…")
        self.transcript.setObjectName("transcript")
        ml.addWidget(self.transcript, 1)

        self.status = QLabel("Готово")
        self.status.setObjectName("muted")
        ml.addWidget(self.status)
        composer = QHBoxLayout()
        self.input = QTextEdit()
        self.input.setFixedHeight(92)
        self.input.setPlaceholderText("Напишите сообщение… (Ctrl+Enter — отправить)")
        self.input.installEventFilter(self)
        composer.addWidget(self.input, 1)
        self.send_btn = QPushButton("Отправить  ➤")
        self.send_btn.setFixedSize(135, 92)
        self.send_btn.clicked.connect(self.send_message)
        composer.addWidget(self.send_btn)
        ml.addLayout(composer)

        outer.addWidget(side)
        outer.addWidget(main, 1)
        self.setCentralWidget(root)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget { background:#111318; color:#e8eaf0; font-family:'Segoe UI'; font-size:10pt; }
            #sidebar { background:#171a21; border-right:1px solid #292e39; }
            #brand { color:#76b900; font-size:16pt; font-weight:700; padding:12px 4px 18px; }
            #pageTitle { font-size:19pt; font-weight:600; }
            #muted { color:#8d95a5; }
            QTextEdit, QLineEdit, QComboBox, QListWidget { background:#1b1f28; border:1px solid #303644; border-radius:9px; padding:10px; selection-background-color:#76b900; }
            #transcript { padding:18px; font-size:11pt; }
            QPushButton { background:#252b35; border:1px solid #394150; border-radius:9px; padding:11px 14px; }
            QPushButton:hover { background:#303846; border-color:#76b900; }
            QPushButton:disabled { color:#727987; background:#20242c; }
            QComboBox { padding:8px; }
            QListWidget { border:0; background:transparent; padding:4px; }
            QListWidget::item { padding:11px; border-radius:7px; }
            QListWidget::item:selected { background:#293522; color:#a8dc55; }
        """)

    def _load_chats(self):
        self.chat_list.clear()
        con = db()
        for cid, title in con.execute("SELECT id,title FROM chats ORDER BY id DESC"):
            item = QListWidgetItem(title or "Новый чат")
            item.setData(Qt.UserRole, cid)
            self.chat_list.addItem(item)
        con.close()

    def new_chat(self):
        self.current_chat = None
        self.messages = []
        self.transcript.clear()
        self.status.setText("Новый диалог")
        self.input.setFocus()

    def open_chat(self, item):
        cid = item.data(Qt.UserRole)
        self.current_chat = cid
        con = db()
        rows = con.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (cid,)).fetchall()
        con.close()
        self.messages = [{"role": r, "content": c} for r, c in rows]
        self._render()

    def _ensure_chat(self, first_text):
        if self.current_chat is None:
            title = first_text.replace("\n", " ")[:42] or "Новый чат"
            con = db()
            cur = con.execute("INSERT INTO chats(title,created) VALUES(?,?)", (title, datetime.now().isoformat()))
            self.current_chat = cur.lastrowid
            con.commit()
            con.close()
            self._load_chats()

    def _store(self, role, content):
        con = db()
        con.execute("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,?)",
                    (self.current_chat, role, content, datetime.now().isoformat()))
        con.commit()
        con.close()

    def _render(self):
        lines = []
        for m in self.messages:
            who = "Вы" if m["role"] == "user" else "NVIDIA AI"
            lines.append(f"{who}\n{'─' * 48}\n{m['content']}\n")
        self.transcript.setPlainText("\n".join(lines))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            try:
                save_api_key(dlg.key.text())
                self.status.setText("Ключ сохранён")
                self.load_models()
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка", str(exc))

    def load_models(self):
        key = get_api_key()
        if not key:
            self.status.setText("Добавьте NVIDIA API key в настройках")
            return
        self.status.setText("Загружаю модели…")
        self._start_worker(ApiWorker("models", key))
        self.worker.models_ready.connect(self._models_loaded)

    def _models_loaded(self, models):
        current = self.model_box.currentText()
        self.model_box.clear()
        self.model_box.addItems(models)
        preferred = self.settings.value("model", "")
        target = preferred or current
        if target:
            idx = self.model_box.findText(target)
            if idx >= 0:
                self.model_box.setCurrentIndex(idx)
            else:
                self.model_box.setEditText(target)
        elif models:
            self.model_box.setCurrentIndex(0)
        self.status.setText(f"Доступно моделей: {len(models)}")

    def _start_worker(self, worker):
        self.worker = worker
        worker.error.connect(self._worker_error)
        worker.start()

    def _worker_error(self, message):
        self.busy = False
        self.send_btn.setEnabled(True)
        self.status.setText("Ошибка запроса")
        QMessageBox.warning(self, "Ошибка NVIDIA API", message)

    def send_message(self):
        if self.busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        key = get_api_key()
        if not key:
            self.open_settings()
            return
        model = self.model_box.currentText().strip()
        if not model:
            QMessageBox.information(self, "Модель", "Выберите модель или обновите список.")
            return
        self._ensure_chat(text)
        self.messages.append({"role": "user", "content": text})
        self._store("user", text)
        self.input.clear()
        self._render()
        self.messages.append({"role": "assistant", "content": ""})
        self.busy = True
        self.send_btn.setEnabled(False)
        self.status.setText(f"Ответ от {model}…")
        worker = ApiWorker("chat", key, {"model": model, "messages": self.messages[:-1]})
        worker.token.connect(self._on_token)
        worker.done.connect(self._on_done)
        self._start_worker(worker)

    def _on_token(self, token):
        self.messages[-1]["content"] += token
        self._render()

    def _on_done(self):
        self.busy = False
        self.send_btn.setEnabled(True)
        answer = self.messages[-1]["content"]
        self._store("assistant", answer)
        self.settings.setValue("model", self.model_box.currentText())
        self.status.setText("Готово")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
