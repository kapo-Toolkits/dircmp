"""Folder list, details table, matrix dialog and the background compare worker."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHeaderView, QListWidget, QListWidgetItem, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QLabel,
)

from ..core import ALL_FIELDS, Cancelled, Comparison, Options, Row, compare, label
from ..core.fields import FIELD_NAMES, value_text
from .tree_model import group_brush

PATH_ROLE = Qt.ItemDataRole.UserRole


class FolderList(QListWidget):
    """Reorderable list of folders; accepts directories dropped from the file manager."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.model().rowsMoved.connect(self._relabel)

    def folders(self) -> list[str]:
        return [self.item(i).data(PATH_ROLE) for i in range(self.count())]

    def add_folder(self, path: str) -> bool:
        path = os.path.normpath(os.path.abspath(path))
        if not os.path.isdir(path) or path in self.folders():
            return False
        item = QListWidgetItem()
        item.setData(PATH_ROLE, path)
        self.addItem(item)
        self._relabel()
        return True

    def remove_selected(self) -> None:
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self._relabel()

    def move_selected(self, delta: int) -> None:
        row = self.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.count():
            return
        item = self.takeItem(row)
        self.insertItem(target, item)
        self.setCurrentRow(target)
        self._relabel()

    def clear_all(self) -> None:
        self.clear()
        self._relabel()

    def _relabel(self, *_) -> None:
        for i in range(self.count()):
            item = self.item(i)
            item.setText(f"{label(i)}    {item.data(PATH_ROLE)}")
        self.changed.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.add_folder(url.toLocalFile())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            self._relabel()


class DetailsTable(QTableWidget):
    """Every field of the selected path, folders side by side; differing values coloured by group."""

    ROWS = ("path",) + ALL_FIELDS

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.setRowCount(len(self.ROWS))
        self.setVerticalHeaderLabels(["ბილიკი"] + [FIELD_NAMES[f] for f in ALL_FIELDS])

    def show_row(self, comp: Comparison | None, r: Row | None) -> None:
        self.clearContents()
        if comp is None or r is None:
            return
        labels = comp.labels
        self.setColumnCount(len(labels))
        self.setHorizontalHeaderLabels(labels)
        for i, e in enumerate(r.entries):
            if e is None:
                text = f"∅  (გადატანილია → {r.moved[i]})" if i in r.moved else "∅"
            else:
                text = os.path.join(comp.roots[i], *e.rel.split("/"))
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            self.setItem(0, i, item)

        for fi, f in enumerate(ALL_FIELDS, start=1):
            groups = r.groups.get(f, [])
            member = {i: gi for gi, g in enumerate(groups) for i in g}
            differs = len(groups) > 1
            header = QTableWidgetItem(FIELD_NAMES[f])
            if f in r.differing:
                font = QFont()
                font.setBold(True)
                header.setFont(font)
                header.setForeground(QBrush(QColor("#e53935")))
            self.setVerticalHeaderItem(fi, header)
            for i, e in enumerate(r.entries):
                item = QTableWidgetItem(value_text(f, e))
                item.setToolTip(item.text())
                if differs and e is not None:
                    item.setBackground(group_brush(member[i], 70 if f in r.differing else 35))
                self.setItem(fi, i, item)
        header = self.horizontalHeader()
        if len(labels) <= 4:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            for i in range(len(labels)):
                self.setColumnWidth(i, 280)


class MatrixDialog(QDialog):
    def __init__(self, comp: Comparison, parent=None):
        super().__init__(parent)
        self.setWindowTitle("განსხვავებების მატრიცა")
        labels = comp.labels
        m = comp.distance_matrix()
        peak = max((v for row in m for v in row), default=0) or 1
        table = QTableWidget(len(labels), len(labels))
        table.setHorizontalHeaderLabels(labels)
        table.setVerticalHeaderLabels(labels)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, row in enumerate(m):
            for j, v in enumerate(row):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(f"{labels[i]}: {comp.roots[i]}\n{labels[j]}: {comp.roots[j]}")
                if i != j:
                    c = QColor("#e53935")
                    c.setAlpha(int(20 + 180 * v / peak) if v else 0)
                    item.setBackground(QBrush(c))
                table.setItem(i, j, item)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("რამდენ გზაზე არ ემთხვევა ორი საქაღალდე ერთმანეთს:"))
        layout.addWidget(table)
        self.resize(120 + 60 * len(labels), 120 + 32 * len(labels))


class CompareWorker(QObject):
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, roots: list[str], options: Options):
        super().__init__()
        self.roots = roots
        self.options = options
        self.cancel = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            comp = compare(self.roots, self.options, progress=self.progress.emit, cancel=self.cancel)
        except Cancelled:
            self.failed.emit("შედარება გაუქმდა")
        except Exception as exc:  # surfaced in the status bar, never crash the GUI
            self.failed.emit(str(exc))
        else:
            self.done.emit(comp)
