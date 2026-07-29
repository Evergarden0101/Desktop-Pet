"""The in-app Character Manager.

Lets you browse the character library, import a new character from any image on
disk (choose a picture -> it gets cut into body parts and registered), preview
it, switch the active character, and rename/duplicate/delete your own packs -
all without touching the command line.
"""

from __future__ import annotations

import os
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..characters import (
    SUPPORTED_IMAGE_EXTENSIONS,
    CharacterError,
    CharacterInfo,
    delete_character,
    duplicate_character,
    import_character,
    list_characters,
    rename_character,
)

if TYPE_CHECKING:  # pragma: no cover
    from .controller import PetApp

_METHOD_CHOICES = [
    ("auto_humanoid", "Automatic (recommended)"),
    ("pose", "Pose detection (needs MediaPipe)"),
]

#: Human-readable names for character.json's render modes.
_MODE_LABELS = {
    "shapes": "drawn shapes",
    "image": "cut from a picture",
    "hybrid": "picture + drawn limbs",
    "auto": "automatic",
}

_FILE_FILTER = (
    "Images ("
    + " ".join(f"*{ext}" for ext in SUPPORTED_IMAGE_EXTENSIONS)
    + ");;All files (*)"
)


class CharacterDialog(QDialog):
    def __init__(self, app: "PetApp"):
        super().__init__()
        self.app = app
        self.setWindowTitle("Desktop Pet - Characters")
        self.setMinimumSize(660, 460)

        self._infos: List[CharacterInfo] = []
        self._pending_image: Optional[str] = None

        layout = QHBoxLayout(self)
        layout.addWidget(self._library_panel(), 3)
        layout.addWidget(self._side_panel(), 4)
        self.reload()

    # --------------------------------------------------------------- panels
    def _library_panel(self) -> QWidget:
        box = QGroupBox("Your characters")
        vbox = QVBoxLayout(box)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(48, 48))
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._use_selected())
        vbox.addWidget(self.list_widget)

        row = QHBoxLayout()
        self.use_button = QPushButton("Use this character")
        self.use_button.clicked.connect(self._use_selected)
        row.addWidget(self.use_button)
        vbox.addLayout(row)

        row2 = QHBoxLayout()
        for label, slot in (
            ("Rename", self._rename_selected),
            ("Duplicate", self._duplicate_selected),
            ("Delete", self._delete_selected),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row2.addWidget(button)
            setattr(self, f"_{label.lower()}_button", button)
        vbox.addLayout(row2)
        return box

    def _side_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(self._preview_group())
        vbox.addWidget(self._import_group())
        vbox.addStretch(1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        vbox.addWidget(close)
        return panel

    def _preview_group(self) -> QWidget:
        box = QGroupBox("Preview")
        vbox = QVBoxLayout(box)
        self.preview_label = QLabel("Select a character")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(150)
        vbox.addWidget(self.preview_label)
        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setStyleSheet("color: palette(mid);")
        vbox.addWidget(self.details_label)
        return box

    def _import_group(self) -> QWidget:
        box = QGroupBox("Add a character from a picture")
        form = QFormLayout(box)

        picker = QWidget()
        row = QHBoxLayout(picker)
        row.setContentsMargins(0, 0, 0, 0)
        self.path_label = QLineEdit()
        self.path_label.setPlaceholderText("Choose a PNG/JPG of your character...")
        self.path_label.setReadOnly(True)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_label, 1)
        row.addWidget(browse)
        form.addRow("Picture", picker)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Character name")
        form.addRow("Name", self.name_edit)

        self.method_combo = QComboBox()
        for value, label in _METHOD_CHOICES:
            self.method_combo.addItem(label, value)
        form.addRow("Body parts", self.method_combo)

        self.import_button = QPushButton("Add character")
        self.import_button.clicked.connect(self._do_import)
        form.addRow(self.import_button)

        hint = QLabel(
            "Tip: a full-body, front-facing picture with a transparent "
            "background gives the cleanest body-part cuts."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        form.addRow(hint)

        self.detector_label = QLabel(self._detector_status())
        self.detector_label.setWordWrap(True)
        self.detector_label.setStyleSheet("color: palette(mid);")
        form.addRow(self.detector_label)
        return box

    @staticmethod
    def _detector_status() -> str:
        """Tell the user which analysis their imports will get."""
        from ..rig import detect

        try:
            import mediapipe  # noqa: F401
        except Exception:
            return (
                "Photos: using outline analysis. Install MediaPipe "
                "(pip install mediapipe) for much better results from "
                "photographs of people."
            )
        if detect.model_available():
            return "Photos: using person detection — best quality."
        return (
            "Photos: person detection is available; its model (~6 MB) "
            "downloads automatically the first time you import a picture."
        )

    # ---------------------------------------------------------------- data
    def reload(self, select: Optional[str] = None) -> None:
        self._infos = list_characters()
        self.list_widget.clear()
        target_row = 0
        for row, info in enumerate(self._infos):
            suffix = "  (built in)" if info.builtin else ""
            active = "  ★" if info.name == self.app.character_name else ""
            item = QListWidgetItem(f"{info.name}{active}{suffix}")
            preview = info.preview_path
            if preview:
                pixmap = QPixmap(preview)
                if not pixmap.isNull():
                    item.setIcon(pixmap.scaled(
                        48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
            self.list_widget.addItem(item)
            wanted = select or self.app.character_name
            if info.name == wanted:
                target_row = row
        if self._infos:
            self.list_widget.setCurrentRow(target_row)

    def _selected(self) -> Optional[CharacterInfo]:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._infos):
            return self._infos[row]
        return None

    def _on_selection_changed(self, _row: int) -> None:
        info = self._selected()
        if info is None:
            self.preview_label.setText("Select a character")
            self.details_label.setText("")
            return

        preview = info.preview_path
        if preview:
            pixmap = QPixmap(preview)
            if not pixmap.isNull():
                self.preview_label.setPixmap(
                    pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            else:
                self.preview_label.setText("(no preview)")
        else:
            self.preview_label.setText("Drawn from shapes\n(no picture needed)")

        bits = [f"Style: {_MODE_LABELS.get(info.render_mode, info.render_mode)}"]
        if info.part_count:
            bits.append(f"{info.part_count} body parts")
        if info.author:
            bits.append(f"by {info.author}")
        if info.builtin:
            bits.append("built in - duplicate it to make changes")
        self.details_label.setText("  ·  ".join(bits))

        for attr in ("_rename_button", "_delete_button"):
            button = getattr(self, attr, None)
            if button is not None:
                button.setEnabled(info.can_delete)

    # -------------------------------------------------------------- actions
    def _browse(self) -> None:
        start = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a character picture", start, _FILE_FILTER
        )
        if not path:
            return
        self._pending_image = path
        self.path_label.setText(path)
        if not self.name_edit.text().strip():
            self.name_edit.setText(os.path.splitext(os.path.basename(path))[0])

    def _do_import(self) -> None:
        if not self._pending_image:
            QMessageBox.information(self, "Choose a picture", "Pick an image first.")
            return
        name = self.name_edit.text().strip() or "My character"
        method = self.method_combo.currentData()

        self.import_button.setEnabled(False)
        self.import_button.setText("Working...")
        try:
            info = import_character(self._pending_image, name, method=method)
        except CharacterError as exc:
            QMessageBox.warning(self, "Could not add character", str(exc))
            return
        finally:
            self.import_button.setEnabled(True)
            self.import_button.setText("Add character")

        self._pending_image = None
        self.path_label.clear()
        self.name_edit.clear()
        self.reload(select=info.name)
        self.detector_label.setText(self._detector_status())

        if QMessageBox.question(
            self,
            "Character added",
            f"'{info.name}' is ready. Use it now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        ) == QMessageBox.Yes:
            self.app.set_character(info.name)
            self.reload(select=info.name)

    def _use_selected(self) -> None:
        info = self._selected()
        if info is None:
            return
        self.app.set_character(info.name)
        self.reload(select=info.name)

    def _rename_selected(self) -> None:
        info = self._selected()
        if info is None or info.builtin:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename character", "New name:", text=info.name
        )
        if not ok:
            return
        try:
            renamed = rename_character(info.name, new_name)
        except CharacterError as exc:
            QMessageBox.warning(self, "Could not rename", str(exc))
            return
        if self.app.character_name == info.name:
            self.app.set_character(renamed.name)
        self.reload(select=renamed.name)

    def _duplicate_selected(self) -> None:
        info = self._selected()
        if info is None:
            return
        try:
            copy = duplicate_character(info.name)
        except CharacterError as exc:
            QMessageBox.warning(self, "Could not duplicate", str(exc))
            return
        self.reload(select=copy.name)

    def _delete_selected(self) -> None:
        info = self._selected()
        if info is None or info.builtin:
            return
        if QMessageBox.question(
            self,
            "Delete character",
            f"Delete '{info.name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            delete_character(info.name)
        except CharacterError as exc:
            QMessageBox.warning(self, "Could not delete", str(exc))
            return
        # If the deleted pack was in use, fall back to the built-in default.
        if self.app.character_name == info.name:
            self.app.set_character("default")
        self.reload()
