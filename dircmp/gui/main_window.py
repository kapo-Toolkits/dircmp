"""Main window: folder list, options, result tree, details panel, export."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QThread
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter, QTreeView, QVBoxLayout,
    QWidget,
)

from ..core import Comparison, Mode, Options
from ..core.fields import STATUS_NAMES
from ..report import render_text, write_csv, write_json
from .tree_model import STATUS_COLORS, CompareModel, FilterProxy, ROW_ROLE
from .widgets import CompareWorker, DetailsTable, FolderList, MatrixDialog

MODES = [(Mode.QUICK, "სწრაფი"), (Mode.STANDARD, "სტანდარტული"), (Mode.DEEP, "ღრმა")]
PHASES = {"scan": "სკანირება", "hash": "ჰეშირება", "diff": "შედარება"}
EXPAND_ALL_LIMIT = 3000


class MainWindow(QMainWindow):
    def __init__(self, folders: list[str] | None = None):
        super().__init__()
        self.setWindowTitle("dircmp — საქაღალდეების შედარება")
        self.comp: Comparison | None = None
        self.thread: QThread | None = None
        self.worker: CompareWorker | None = None
        self.settings = QSettings()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_folders())
        layout.addLayout(self._build_options())
        layout.addLayout(self._build_actions())
        layout.addLayout(self._build_filter())
        layout.addWidget(self._build_results(), 1)
        self.setCentralWidget(central)

        self._load_settings(restore_folders=not folders)
        for f in folders or []:
            self.folder_list.add_folder(f)
        self._update_buttons()

    # --- layout ---

    def _build_folders(self) -> QGroupBox:
        box = QGroupBox("საქაღალდეები (გადმოათრიეთ აქ ან დაამატეთ; რიგი ცვლის ეტიკეტებს A, B, C…)")
        self.folder_list = FolderList()
        self.folder_list.setMaximumHeight(140)
        self.folder_list.changed.connect(self._update_buttons)
        buttons = QVBoxLayout()
        for text, slot in (
            ("დამატება…", self._add_folder),
            ("წაშლა", self.folder_list.remove_selected),
            ("▲", lambda: self.folder_list.move_selected(-1)),
            ("▼", lambda: self.folder_list.move_selected(1)),
            ("გასუფთავება", self.folder_list.clear_all),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()
        row = QHBoxLayout(box)
        row.addWidget(self.folder_list, 1)
        row.addLayout(buttons)
        return box

    def _build_options(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.mode_combo = QComboBox()
        for mode, name in MODES:
            self.mode_combo.addItem(name, mode)
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.setToolTip("სწრაფი: ზომა + mtime\nსტანდარტული: + შიგთავსი (საჭიროებისას), უფლებები\n"
                                   "ღრმა: + ყველა ფაილის სრული ჰეში, xattr")
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0, 86400)
        self.tolerance.setDecimals(1)
        self.tolerance.setSuffix(" წმ")
        self.tolerance.setToolTip("ამ ფარგლებში განსხვავებული დროები ტოლად ითვლება (FAT-ისთვის 2 წმ)")
        self.ignore = QLineEdit()
        self.ignore.setPlaceholderText("იგნორირება: .git; node_modules; *.tmp")
        self.case_insensitive = QCheckBox("რეგისტრის უგულებელყოფა")
        self.exclude_hidden = QCheckBox("დამალულების გამოტოვება")
        self.follow_symlinks = QCheckBox("symlink-ებს მიყევი")
        row.addWidget(QLabel("რეჟიმი:"))
        row.addWidget(self.mode_combo)
        row.addWidget(QLabel("დროის ტოლერანტობა:"))
        row.addWidget(self.tolerance)
        row.addWidget(self.ignore, 1)
        row.addWidget(self.case_insensitive)
        row.addWidget(self.exclude_hidden)
        row.addWidget(self.follow_symlinks)
        return row

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.compare_btn = QPushButton("შედარება")
        self.compare_btn.setDefault(True)
        self.compare_btn.clicked.connect(self._compare_or_cancel)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.status_label = QLabel("დაამატეთ მინიმუმ ორი საქაღალდე.")
        row.addWidget(self.compare_btn)
        row.addWidget(self.progress)
        row.addWidget(self.status_label, 1)
        return row

    def _build_filter(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.filter_combo = QComboBox()
        for key, (name, _) in FilterProxy.MODES.items():
            self.filter_combo.addItem(name, key)
        self.filter_combo.setCurrentIndex(1)
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("ძებნა გზაში…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.matrix_btn = QPushButton("მატრიცა")
        self.matrix_btn.clicked.connect(self._show_matrix)
        self.export_btn = QPushButton("ექსპორტი…")
        self.export_btn.clicked.connect(self._export)
        row.addWidget(QLabel("ჩვენება:"))
        row.addWidget(self.filter_combo)
        row.addWidget(self.search, 1)
        row.addWidget(self.summary_label)
        row.addWidget(self.matrix_btn)
        row.addWidget(self.export_btn)
        return row

    def _build_results(self) -> QSplitter:
        self.model = CompareModel(self)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setAlternatingRowColors(True)
        self.tree.selectionModel().currentChanged.connect(self._on_current)
        self.details = DetailsTable()
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        return splitter

    # --- actions ---

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "საქაღალდის არჩევა")
        if path:
            self.folder_list.add_folder(path)

    def options(self) -> Options:
        ignore = [p.strip() for p in self.ignore.text().replace(",", ";").split(";") if p.strip()]
        return Options(
            mode=self.mode_combo.currentData(),
            ignore=ignore,
            exclude_hidden=self.exclude_hidden.isChecked(),
            follow_symlinks=self.follow_symlinks.isChecked(),
            case_insensitive=self.case_insensitive.isChecked(),
            time_tolerance=self.tolerance.value(),
        )

    def _compare_or_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.compare_btn.setEnabled(False)
            return
        folders = self.folder_list.folders()
        if len(folders) < 2:
            return
        self.worker = CompareWorker(folders, self.options())
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.done.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._on_thread_finished)
        self.compare_btn.setText("გაუქმება")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status_label.setText("მიმდინარეობს…")
        self.thread.start()

    def _on_progress(self, phase: str, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)
        self.status_label.setText(f"{PHASES.get(phase, phase)}: {done}" + (f" / {total}" if total else ""))

    def _on_done(self, comp: Comparison) -> None:
        self.comp = comp
        self.model.set_comparison(comp)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, self.model.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._apply_filter()
        self.details.show_row(None, None)
        self._show_summary(comp)
        self._update_buttons()

    def _on_failed(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_thread_finished(self) -> None:
        self.thread.deleteLater()
        self.worker.deleteLater()
        self.thread = self.worker = None
        self.compare_btn.setText("შედარება")
        self.compare_btn.setEnabled(True)
        self.progress.setVisible(False)
        self._update_buttons()

    def _show_summary(self, comp: Comparison) -> None:
        s = comp.summary()
        parts = []
        for status, name in STATUS_NAMES.items():
            if s[status.value]:
                parts.append(f'<span style="color:{STATUS_COLORS[status]}">{name}: {s[status.value]}</span>')
        self.summary_label.setText(" · ".join(parts))
        verdict = "ყველაფერი იდენტურია ✓" if comp.all_identical else f"{len(comp.differences())} განსხვავება"
        errors = f", {len(comp.errors)} შეცდომა" if comp.errors else ""
        self.status_label.setText(f"{verdict}{errors} — {s['total']} ჩანაწერი, {comp.elapsed:.2f} წმ")

    def _apply_filter(self) -> None:
        self.proxy.set_mode(self.filter_combo.currentData())
        self.proxy.set_text(self.search.text())
        if self.proxy.rowCount() and self.comp and len(self.comp.rows) <= EXPAND_ALL_LIMIT:
            self.tree.expandAll()

    def _on_current(self, current, _previous) -> None:
        r = current.data(ROW_ROLE) if current.isValid() else None
        self.details.show_row(self.comp, r)

    def _show_matrix(self) -> None:
        if self.comp:
            MatrixDialog(self.comp, self).exec()

    def _export(self) -> None:
        if not self.comp:
            return
        path, chosen = QFileDialog.getSaveFileName(
            self, "ექსპორტი", "dircmp-report.json", "JSON (*.json);;CSV (*.csv);;ტექსტი (*.txt)")
        if not path:
            return
        all_rows = self.filter_combo.currentData() == "all"
        try:
            with open(path, "w", encoding="utf-8", newline="") as fp:
                if path.endswith(".csv") or chosen.startswith("CSV"):
                    write_csv(self.comp, fp, all_rows=all_rows)
                elif path.endswith(".txt") or chosen.startswith("ტექსტი"):
                    fp.write(render_text(self.comp, all_rows=all_rows, verbose=True))
                else:
                    write_json(self.comp, fp, all_rows=all_rows)
        except OSError as exc:
            QMessageBox.critical(self, "ექსპორტი", str(exc))
            return
        self.status_label.setText(f"შენახულია: {path}")

    def _update_buttons(self) -> None:
        running = self.worker is not None
        self.compare_btn.setEnabled(running or len(self.folder_list.folders()) >= 2)
        has = self.comp is not None
        self.matrix_btn.setEnabled(has)
        self.export_btn.setEnabled(has)

    # --- persistence ---

    def _load_settings(self, restore_folders: bool) -> None:
        s = self.settings
        if geo := s.value("geometry"):
            self.restoreGeometry(geo)
        else:
            self.resize(1200, 800)
        if restore_folders:
            for f in s.value("folders", []) or []:
                self.folder_list.add_folder(f)
        self.mode_combo.setCurrentIndex(int(s.value("mode_index", 1)))
        self.tolerance.setValue(float(s.value("tolerance", 0.0)))
        self.ignore.setText(s.value("ignore", "") or "")
        for box, key in ((self.case_insensitive, "case_insensitive"), (self.exclude_hidden, "exclude_hidden"),
                         (self.follow_symlinks, "follow_symlinks")):
            box.setChecked(s.value(key, "false") in (True, "true"))

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.cancel.set()
            self.thread.quit()
            self.thread.wait(5000)
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("folders", self.folder_list.folders())
        s.setValue("mode_index", self.mode_combo.currentIndex())
        s.setValue("tolerance", self.tolerance.value())
        s.setValue("ignore", self.ignore.text())
        s.setValue("case_insensitive", self.case_insensitive.isChecked())
        s.setValue("exclude_hidden", self.exclude_hidden.isChecked())
        s.setValue("follow_symlinks", self.follow_symlinks.isChecked())
        super().closeEvent(event)
