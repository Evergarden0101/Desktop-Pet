"""The Character Manager: import images and manage the cast, inside the app.

Two screens:

* :class:`ImportDialog` -- pick an image, watch the cutout update live as you
  change the background settings, tick the figures you want, import.
* :class:`ManagerWindow` -- the cast list, with an animated preview, rename,
  rebuild, delete, and how many of each are on the desktop.

The heavy work (background removal, frame generation) runs on a worker thread
so the pets keep crawling while it happens.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QProgressBar, QPushButton, QSlider, QSpinBox,
                               QSplitter, QVBoxLayout, QWidget)

from .pipeline import extract as ex
from .pipeline import frames as fr

THUMB = QSize(72, 96)
PREVIEW_MAX = 320


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())  # copy: detach from the temp buffer


def checkerboard(size: QSize) -> QPixmap:
    """A light chequer so transparent regions of a cutout are obvious."""
    pm = QPixmap(size)
    pm.fill(QColor(248, 248, 250))
    painter = QPainter(pm)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(232, 234, 240))
    step = 8
    for y in range(0, size.height(), step):
        for x in range(0, size.width(), step):
            if (x // step + y // step) % 2:
                painter.drawRect(x, y, step, step)
    painter.end()
    return pm


class Job(QThread):
    """Run one callable off the GUI thread, reporting progress."""

    progressed = Signal(float, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn(lambda f, m: self.progressed.emit(float(f), str(m)))
        except Exception as exc:  # a bad image should not take the app down
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.succeeded.emit(result)


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------

class SourceView(QLabel):
    """The source image with the detected figure boxes drawn over it."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(PREVIEW_MAX, 240)
        self.setAlignment(Qt.AlignCenter)
        self._pixmap: QPixmap | None = None
        self._boxes: list[tuple[int, int, int, int]] = []
        self._src_size = (1, 1)

    def set_source(self, img: Image.Image) -> None:
        self._src_size = img.size
        self._pixmap = pil_to_qpixmap(img)
        self.update()

    def set_boxes(self, boxes) -> None:
        self._boxes = list(boxes)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(244, 245, 248))
        if self._pixmap is None:
            painter.setPen(QColor(120, 120, 130))
            painter.drawText(self.rect(), Qt.AlignCenter, "No image chosen")
            return

        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
        ox = (self.width() - scaled.width()) // 2
        oy = (self.height() - scaled.height()) // 2
        painter.drawPixmap(ox, oy, scaled)

        sx = scaled.width() / max(1, self._src_size[0])
        sy = scaled.height() / max(1, self._src_size[1])
        painter.setBrush(Qt.NoBrush)
        for i, (x0, y0, x1, y1) in enumerate(self._boxes, start=1):
            painter.setPen(QPen(QColor(236, 92, 140), 2))
            rect = (ox + x0 * sx, oy + y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy)
            painter.drawRect(*[int(v) for v in rect])
            painter.drawText(int(rect[0]) + 4, int(rect[1]) + 16, str(i))


class ImportDialog(QDialog):
    """Choose an image, tune the cutout, pick the figures, import them."""

    def __init__(self, pets_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import characters from an image")
        self.resize(880, 560)
        self.pets_dir = pets_dir

        self._source: Image.Image | None = None
        self._rgba: Image.Image | None = None
        self._boxes: list = []
        self._cutouts: list[Image.Image] = []
        self._job: Job | None = None
        self.imported: list[Path] = []

        self.view = SourceView()
        self.figures = QListWidget()
        self.figures.setViewMode(QListWidget.IconMode)
        self.figures.setIconSize(THUMB)
        self.figures.setResizeMode(QListWidget.Adjust)
        self.figures.setSelectionMode(QAbstractItemView.NoSelection)
        self.figures.setMinimumWidth(260)
        self.figures.setSpacing(6)

        self.pick = QPushButton("Choose image...")
        self.pick.clicked.connect(self.choose_file)

        self.use_rembg = QCheckBox("Use rembg (best on photos)")
        self.use_rembg.setChecked(ex.rembg_available())
        self.use_rembg.setEnabled(ex.rembg_available())
        if not ex.rembg_available():
            self.use_rembg.setToolTip(
                "rembg is not installed in this build.\n"
                "pip install rembg onnxruntime for photo-quality cutouts.")

        self.tolerance = QSlider(Qt.Horizontal)
        self.tolerance.setRange(2, 80)
        self.tolerance.setValue(ex.DEFAULT_TOLERANCE)
        self.tolerance_label = QLabel(str(ex.DEFAULT_TOLERANCE))

        self.max_figures = QSpinBox()
        self.max_figures.setRange(1, 12)
        self.max_figures.setValue(6)

        self.height_px = QSpinBox()
        self.height_px.setRange(200, 900)
        self.height_px.setSingleStep(20)
        self.height_px.setValue(420)

        self.status = QLabel("Choose an image to begin.")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Import")
        self.buttons.accepted.connect(self.do_import)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)

        # a debounce, so dragging the slider does not queue a dozen re-detects
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(220)
        self._debounce.timeout.connect(self.redetect)

        for widget, signal in ((self.tolerance, "valueChanged"),
                               (self.max_figures, "valueChanged"),
                               (self.height_px, "valueChanged"),
                               (self.use_rembg, "toggled")):
            getattr(widget, signal).connect(self._queue_redetect)
        self.tolerance.valueChanged.connect(
            lambda v: self.tolerance_label.setText(str(v)))

        form = QFormLayout()
        form.addRow(self.pick)
        form.addRow(self.use_rembg)
        tol_row = QHBoxLayout()
        tol_row.addWidget(self.tolerance)
        tol_row.addWidget(self.tolerance_label)
        tol_box = QWidget()
        tol_box.setLayout(tol_row)
        form.addRow("Background tolerance", tol_box)
        form.addRow("Max figures", self.max_figures)
        form.addRow("Cutout height", self.height_px)

        settings = QGroupBox("Source")
        settings.setLayout(form)

        left = QVBoxLayout()
        left.addWidget(self.view, 1)
        left.addWidget(settings)

        right = QVBoxLayout()
        right.addWidget(QLabel("Figures found (tick the ones to import)"))
        right.addWidget(self.figures, 1)

        columns = QHBoxLayout()
        lw, rw = QWidget(), QWidget()
        lw.setLayout(left)
        rw.setLayout(right)
        columns.addWidget(lw, 3)
        columns.addWidget(rw, 2)

        root = QVBoxLayout(self)
        root.addLayout(columns, 1)
        root.addWidget(self.status)
        root.addWidget(self.progress)
        root.addWidget(self.buttons)

    # -- source -----------------------------------------------------------

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;All files (*)")
        if not path:
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot read image", str(exc))
            return
        self._source = img.convert("RGBA")
        self.view.set_source(self._source)
        self.setWindowTitle(f"Import characters -- {Path(path).name}")
        self.redetect()

    def _queue_redetect(self) -> None:
        if self._source is not None:
            self._debounce.start()

    def _busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(
            not busy and bool(self._cutouts))
        for w in (self.pick, self.tolerance, self.max_figures,
                  self.height_px, self.use_rembg):
            w.setEnabled(not busy)
        if not busy and not ex.rembg_available():
            self.use_rembg.setEnabled(False)

    def redetect(self) -> None:
        if self._source is None or (self._job and self._job.isRunning()):
            if self._source is not None:
                self._debounce.start()   # try again once the current job ends
            return

        opts = self._options()
        source = self._source.copy()

        def work(report):
            report(0.1, "removing background")
            rgba, boxes = ex.prepare(source, opts)
            cutouts = []
            for i, box in enumerate(boxes, start=1):
                report(0.2 + 0.7 * i / max(1, len(boxes)), f"cutting figure {i}")
                cutouts.append(ex.normalize_height(
                    ex.crop_figure(rgba, box), opts.height))
            return rgba, boxes, cutouts

        self._busy(True)
        self.status.setText("Working...")
        self._job = Job(work, self)
        self._job.progressed.connect(self._on_progress)
        self._job.succeeded.connect(self._on_detected)
        self._job.failed.connect(self._on_failed)
        self._job.start()

    def _options(self) -> ex.ExtractOptions:
        return ex.ExtractOptions(
            tolerance=self.tolerance.value(),
            max_figures=self.max_figures.value(),
            height=self.height_px.value(),
            use_rembg=self.use_rembg.isChecked() and ex.rembg_available())

    def _on_progress(self, frac: float, msg: str) -> None:
        self.progress.setValue(int(frac * 100))
        self.status.setText(msg)

    def _on_failed(self, msg: str) -> None:
        self._busy(False)
        self.status.setText(f"Could not read that image: {msg}")

    def _on_detected(self, result) -> None:
        self._rgba, self._boxes, self._cutouts = result
        self.view.set_boxes(self._boxes)

        self.figures.clear()
        warnings = []
        for i, cut in enumerate(self._cutouts, start=1):
            item = QListWidgetItem(f"Figure {i}")
            item.setIcon(pil_to_qpixmap(cut))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            notes = ex.cutout_warnings(cut)
            if notes:
                item.setToolTip("\n".join(notes))
                item.setText(f"Figure {i}  (!)")
                warnings.extend(f"Figure {i}: {n}" for n in notes)
            self.figures.addItem(item)

        self._busy(False)
        if not self._cutouts:
            self.status.setText(
                "No figures found. Try a different tolerance, or a full-body "
                "image with the people not overlapping.")
        elif warnings:
            self.status.setText(" | ".join(warnings))
        else:
            self.status.setText(
                f"{len(self._cutouts)} figure(s) found. Best results come from a "
                f"full-body image with the people not overlapping.")

    # -- import -----------------------------------------------------------

    def _checked(self) -> list[Image.Image]:
        return [cut for i, cut in enumerate(self._cutouts)
                if self.figures.item(i)
                and self.figures.item(i).checkState() == Qt.Checked]

    def do_import(self) -> None:
        chosen = self._checked()
        if not chosen:
            QMessageBox.information(self, "Nothing selected",
                                    "Tick at least one figure to import.")
            return

        pets_dir = self.pets_dir
        stem = "figure"

        def work(report):
            report(0.05, "saving cutouts")
            folders = []
            pets_dir.mkdir(parents=True, exist_ok=True)
            for i, cut in enumerate(chosen, start=1):
                folder = pets_dir / ex._unique_name(pets_dir, stem, i)
                folder.mkdir(parents=True, exist_ok=True)
                cut.save(folder / "base.png")
                folders.append(folder)
            built = fr.build_all(
                folders,
                progress=lambda f, m: report(0.15 + 0.85 * f, m))
            # a cutout that could not be rigged leaves no frames behind
            for folder in folders:
                if folder not in built:
                    shutil.rmtree(folder, ignore_errors=True)
            return built

        self._busy(True)
        self._job = Job(work, self)
        self._job.progressed.connect(self._on_progress)
        self._job.succeeded.connect(self._on_imported)
        self._job.failed.connect(self._on_import_failed)
        self._job.start()

    def _on_imported(self, folders) -> None:
        self._busy(False)
        self.imported = list(folders)
        if not self.imported:
            QMessageBox.warning(
                self, "Could not animate",
                "The cutouts could not be rigged. This usually means the figure "
                "is not a full body -- the rig needs to find a neck, waist and "
                "knees in the silhouette.")
            return
        self.accept()

    def _on_import_failed(self, msg: str) -> None:
        self._busy(False)
        QMessageBox.warning(self, "Import failed", msg)

    def closeEvent(self, event) -> None:
        if self._job and self._job.isRunning():
            self._job.wait(4000)
        super().closeEvent(event)


# --------------------------------------------------------------------------
# manage
# --------------------------------------------------------------------------

class ManagerWindow(QDialog):
    """The cast list, with an animated preview of the selected character."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle(app.strings["manager"])
        self.resize(760, 480)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self._preview_frames: list[QPixmap] = []
        self._preview_index = 0
        self._job: Job | None = None

        self.list = QListWidget()
        self.list.setIconSize(THUMB)
        self.list.currentRowChanged.connect(self._on_selection)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(260, 240)
        self._chequer = checkerboard(QSize(260, 240))

        self.anim_toggle = QPushButton("Show playing")
        self.anim_toggle.setCheckable(True)
        self.anim_toggle.toggled.connect(lambda _: self._load_preview())

        self.count = QSpinBox()
        self.count.setRange(0, app.cfg.max_pets)
        self.count.valueChanged.connect(self._on_count_changed)
        self._suppress_count = False

        self.detail = QLabel()
        self.detail.setWordWrap(True)

        import_btn = QPushButton(app.strings["import_image"])
        import_btn.clicked.connect(self.import_image)
        rebuild_btn = QPushButton(app.strings["rebuild"])
        rebuild_btn.clicked.connect(self.rebuild)
        rename_btn = QPushButton(app.strings["rename"])
        rename_btn.clicked.connect(self.rename)
        delete_btn = QPushButton(app.strings["delete"])
        delete_btn.clicked.connect(self.delete)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.scale = QSlider(Qt.Horizontal)
        self.scale.setRange(15, 100)
        self.scale.setValue(int(app.cfg.scale * 100))
        self.scale.sliderReleased.connect(self._apply_scale)

        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(10, 200)
        self.speed.setValue(int(app.cfg.speed))
        self.speed.valueChanged.connect(self._apply_speed)

        tuning = QFormLayout()
        tuning.addRow(app.strings["size"], self.scale)
        tuning.addRow(app.strings["speed"], self.speed)
        tuning_box = QGroupBox(app.strings["settings"])
        tuning_box.setLayout(tuning)

        actions = QHBoxLayout()
        for b in (import_btn, rebuild_btn, rename_btn, delete_btn):
            actions.addWidget(b)
        actions.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(self.preview, 1)
        right.addWidget(self.anim_toggle)
        on_desktop = QFormLayout()
        on_desktop.addRow(app.strings["on_desktop"], self.count)
        right.addLayout(on_desktop)
        right.addWidget(self.detail)
        right.addWidget(tuning_box)

        left_w, right_w = QWidget(), QWidget()
        left_w.setLayout(self._wrap(self.list))
        right_w.setLayout(right)
        split = QSplitter()
        split.addWidget(left_w)
        split.addWidget(right_w)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)

        root = QVBoxLayout(self)
        root.addWidget(split, 1)
        root.addLayout(actions)
        root.addWidget(self.status)
        root.addWidget(self.progress)
        root.addWidget(close)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_preview_frame)
        self._timer.start(100)

        self.refresh()

    @staticmethod
    def _wrap(widget) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.addWidget(widget)
        return layout

    # -- list -------------------------------------------------------------

    def refresh(self, select: str | None = None) -> None:
        current = select or self.current_key()
        self.list.blockSignals(True)
        self.list.clear()
        for assets in self.app.assets:
            item = QListWidgetItem(self.app.roster.display_name(assets.name))
            item.setData(Qt.UserRole, assets.name)
            item.setIcon(assets.icon_pixmap())
            self.list.addItem(item)
        self.list.blockSignals(False)

        if self.list.count() == 0:
            self.detail.setText("No characters yet. Use Import image.")
            self.preview.setPixmap(self._chequer)
            return

        row = 0
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == current:
                row = i
                break
        self.list.setCurrentRow(row)

    def current_key(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def current_assets(self):
        key = self.current_key()
        return next((a for a in self.app.assets if a.name == key), None)

    def _on_selection(self, _row: int) -> None:
        self._load_preview()
        key = self.current_key()
        if not key:
            return
        assets = self.current_assets()
        living = len([p for p in self.app.pets if p.assets.name == key])
        self._suppress_count = True
        self.count.setValue(living)
        self._suppress_count = False
        if assets:
            frames_n = sum(len(a) for a in assets.anims.values())
            self.detail.setText(
                f"{assets.size[0]}x{assets.size[1]} px on screen, {frames_n} frames\n"
                f"folder: {key}")

    # -- preview ----------------------------------------------------------

    def _load_preview(self) -> None:
        assets = self.current_assets()
        self._preview_frames = []
        self._preview_index = 0
        if not assets:
            self.preview.setPixmap(self._chequer)
            return
        name = "play" if self.anim_toggle.isChecked() else "crawl"
        anim = assets.anims.get(name) or assets.anims["crawl"]
        self._preview_frames = list(anim.right)
        self.anim_toggle.setText("Show crawling" if self.anim_toggle.isChecked()
                                 else "Show playing")

    def _next_preview_frame(self) -> None:
        if not self._preview_frames or not self.isVisible():
            return
        self._preview_index = (self._preview_index + 1) % len(self._preview_frames)
        frame = self._preview_frames[self._preview_index]

        canvas = QPixmap(self.preview.size())
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, checkerboard(self.preview.size()))
        scaled = frame.scaled(self.preview.size(), Qt.KeepAspectRatio,
                              Qt.SmoothTransformation)
        painter.drawPixmap((canvas.width() - scaled.width()) // 2,
                           (canvas.height() - scaled.height()) // 2, scaled)
        painter.end()
        self.preview.setPixmap(canvas)

    # -- actions ----------------------------------------------------------

    def _busy(self, busy: bool, message: str = "") -> None:
        self.progress.setVisible(busy)
        self.status.setText(message)
        self.setEnabled(True)
        self.list.setEnabled(not busy)

    def _on_progress(self, frac: float, msg: str) -> None:
        self.progress.setValue(int(frac * 100))
        self.status.setText(msg)

    def import_image(self) -> None:
        dialog = ImportDialog(self.app.pets_dir, self)
        if dialog.exec() != QDialog.Accepted or not dialog.imported:
            return
        self.app.reload_assets()
        first = dialog.imported[0].name
        for folder in dialog.imported:
            self.app.roster.set_enabled(folder.name, True)
        self.refresh(select=first)
        self.status.setText(
            f"Imported {len(dialog.imported)} character(s). "
            f"Set 'On desktop' above 0 to send her out.")

    def rebuild(self) -> None:
        key = self.current_key()
        if not key:
            return
        folder = self.app.pets_dir / key
        if not (folder / "base.png").exists():
            QMessageBox.information(self, "Nothing to rebuild",
                                    f"{key} has no base.png to rebuild from.")
            return

        def work(report):
            return fr.build_all([folder], progress=report)

        self._busy(True, "rebuilding...")
        self._job = Job(work, self)
        self._job.progressed.connect(self._on_progress)
        self._job.succeeded.connect(lambda _: self._after_rebuild(key))
        self._job.failed.connect(lambda m: self._busy(False, f"rebuild failed: {m}"))
        self._job.start()

    def _after_rebuild(self, key: str) -> None:
        self.app.reload_assets()
        self._busy(False, f"rebuilt {key}")
        self.refresh(select=key)

    def rename(self) -> None:
        key = self.current_key()
        if not key:
            return
        name, ok = QInputDialog.getText(self, self.app.strings["rename"],
                                        self.app.strings["rename"],
                                        text=self.app.roster.display_name(key))
        if ok:
            self.app.roster.set_display_name(key, name)
            self.refresh(select=key)

    def delete(self) -> None:
        key = self.current_key()
        if not key:
            return
        answer = QMessageBox.question(
            self, self.app.strings["delete"],
            f"Delete {self.app.roster.display_name(key)} for good?\n\n"
            f"This removes {self.app.pets_dir / key} from disk.")
        if answer != QMessageBox.Yes:
            return

        self.app.despawn_all(key)
        shutil.rmtree(self.app.pets_dir / key, ignore_errors=True)
        self.app.roster.forget(key)
        self.app.reload_assets()
        self.refresh()
        self.status.setText(f"Deleted {key}")

    def _on_count_changed(self, value: int) -> None:
        if self._suppress_count:
            return
        key = self.current_key()
        if key:
            self.app.set_population(key, value)

    def _apply_scale(self) -> None:
        self.app.set_scale(self.scale.value() / 100.0)
        self.refresh()

    def _apply_speed(self, value: int) -> None:
        self.app.cfg.speed = float(value)
        self.app.cfg.save()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self._job and self._job.isRunning():
            self._job.wait(4000)
        super().closeEvent(event)
