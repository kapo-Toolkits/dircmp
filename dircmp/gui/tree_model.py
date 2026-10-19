"""Qt tree model over a Comparison: one column per folder, cells coloured by group."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QApplication, QStyle

from ..core.compare import Comparison
from ..core.fields import STATUS_NAMES, group_notation
from ..core.model import Kind, Row, Status

ROW_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1

STATUS_COLORS = {
    Status.IDENTICAL: "#43a047",
    Status.CONTENT_DIFFERS: "#e53935",
    Status.METADATA_DIFFERS: "#fb8c00",
    Status.PARTIAL: "#1e88e5",
    Status.MOVED: "#8e24aa",
    Status.ERROR: "#d32f2f",
}
GROUP_COLORS = ["#43a047", "#e53935", "#1e88e5", "#fb8c00", "#8e24aa", "#00897b", "#6d4c41", "#3949ab",
                "#c0ca33", "#d81b60"]
STATUS_ORDER = {s: i for i, s in enumerate(Status)}
INNER_DIFF = "შიგნით განსხვავებებია"


def group_brush(g: int, alpha: int = 90) -> QBrush:
    c = QColor(GROUP_COLORS[g % len(GROUP_COLORS)])
    c.setAlpha(alpha)
    return QBrush(c)


class Node:
    __slots__ = ("name", "row", "parent", "children", "pos", "has_diff")

    def __init__(self, name: str, row: Row | None, parent: Node | None):
        self.name = name
        self.row = row
        self.parent = parent
        self.children: list[Node] = []
        self.pos = 0
        self.has_diff = False
        if parent is not None:
            self.pos = len(parent.children)
            parent.children.append(self)


def build_tree(comp: Comparison) -> Node:
    root = Node("", None, None)
    by_key: dict[str, Node] = {"": root}
    order: list[Node] = []
    for r in comp.rows:  # sorted so parents precede children
        parent_key = r.key.rpartition("/")[0]
        parent = by_key.get(parent_key)
        if parent is None:  # shouldn't happen; keep the row visible anyway
            parent = root
        node = Node(r.name, r, parent)
        by_key[r.key] = node
        order.append(node)
    for node in reversed(order):  # children before parents
        node.has_diff = node.has_diff or node.row.status is not Status.IDENTICAL
        if node.has_diff and node.parent is not None:
            node.parent.has_diff = True
    return root


class CompareModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.comp: Comparison | None = None
        self.root = Node("", None, None)
        self.labels: list[str] = []
        style = QApplication.style()
        self._icons = {
            Kind.DIR: style.standardIcon(QStyle.StandardPixmap.SP_DirIcon),
            Kind.FILE: style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            Kind.SYMLINK: style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon),
            Kind.OTHER: style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            None: style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning),
        }

    def set_comparison(self, comp: Comparison | None) -> None:
        self.beginResetModel()
        self.comp = comp
        self.root = build_tree(comp) if comp else Node("", None, None)
        self.labels = comp.labels if comp else []
        self.endResetModel()

    # --- structure ---

    def index(self, row, column, parent=QModelIndex()):
        pnode = parent.internalPointer() if parent.isValid() else self.root
        if 0 <= row < len(pnode.children) and 0 <= column < self.columnCount():
            return self.createIndex(row, column, pnode.children[row])
        return QModelIndex()

    def parent(self, index=QModelIndex()):
        if not index.isValid():
            return QModelIndex()
        p = index.internalPointer().parent
        if p is None or p is self.root:
            return QModelIndex()
        return self.createIndex(p.pos, 0, p)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 2 + len(self.labels)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return ["სახელი", "სტატუსი"][section] if section < 2 else self.labels[section - 2]
        if role == Qt.ItemDataRole.ToolTipRole and section >= 2 and self.comp:
            return self.comp.roots[section - 2]
        return None

    # --- data ---

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: Node = index.internalPointer()
        r = node.row
        col = index.column()
        if role == ROW_ROLE:
            return r
        if col == 0:
            return self._name_data(node, role)
        if col == 1:
            return self._status_data(node, role)
        return self._folder_data(r, col - 2, role)

    def _name_data(self, node: Node, role):
        r = node.row
        if role == Qt.ItemDataRole.DisplayRole:
            return node.name
        if role == Qt.ItemDataRole.DecorationRole:
            return self._icons.get(r.kind)
        if role == Qt.ItemDataRole.ForegroundRole and r.status is not Status.IDENTICAL:
            return QBrush(QColor(STATUS_COLORS[r.status]))
        if role == Qt.ItemDataRole.ToolTipRole:
            return r.rel
        if role == SORT_ROLE:
            return ("0" if r.kind is Kind.DIR else "1") + node.name.casefold()
        return None

    def _status_data(self, node: Node, role):
        r = node.row
        inner = r.status is Status.IDENTICAL and node.has_diff
        if role == Qt.ItemDataRole.DisplayRole:
            return INNER_DIFF if inner else STATUS_NAMES[r.status]
        if role == Qt.ItemDataRole.ForegroundRole:
            if inner:
                return QBrush(QColor(STATUS_COLORS[Status.METADATA_DIFFERS]))
            return QBrush(QColor(STATUS_COLORS[r.status]))
        if role == Qt.ItemDataRole.ToolTipRole:
            text = group_notation(r.overall, self.labels)
            if r.differing:
                text += "\n" + ", ".join(r.differing)
            return text
        if role == SORT_ROLE:
            return STATUS_ORDER[r.status]
        return None

    def _folder_data(self, r: Row, i: int, role):
        e = r.entries[i]
        g = r.overall[i]
        multi = len({x for x in r.overall if x is not None}) > 1
        if role == Qt.ItemDataRole.DisplayRole or role == SORT_ROLE:
            if e is None:
                return "↪" if i in r.moved else "∅"
            if e.error:
                return "⚠"
            return str(g + 1) if multi else "✓"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.BackgroundRole and e is not None and multi:
            return group_brush(g)
        if role == Qt.ItemDataRole.ForegroundRole and e is None:
            return QBrush(QColor("#9e9e9e"))
        if role == Qt.ItemDataRole.ToolTipRole:
            if e is None:
                return f"→ {r.moved[i]}" if i in r.moved else "აკლია"
            return e.error or f"ჯგუფი {g + 1}"
        return None


class FilterProxy(QSortFilterProxyModel):
    """Status/text filter; parents of matching rows stay visible."""

    MODES = {
        "all": ("ყველა", None),
        "diff": ("მხოლოდ განსხვავებები", lambda s: s is not Status.IDENTICAL),
        "content": ("შიგთავსი განსხვავდება", lambda s: s is Status.CONTENT_DIFFERS),
        "metadata": ("მეტამონაცემები განსხვავდება", lambda s: s is Status.METADATA_DIFFERS),
        "partial": ("ზოგან აკლია / გადატანილი", lambda s: s in (Status.PARTIAL, Status.MOVED)),
        "error": ("შეცდომები", lambda s: s is Status.ERROR),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRecursiveFilteringEnabled(True)
        self.setSortRole(SORT_ROLE)
        self._mode = "diff"
        self._text = ""

    def set_mode(self, mode: str) -> None:
        self._refilter("_mode", mode)

    def set_text(self, text: str) -> None:
        self._refilter("_text", text.casefold())

    def _refilter(self, attr: str, value) -> None:
        if getattr(self, attr) == value:
            return
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.10; invalidateFilter() is deprecated there
            self.beginFilterChange()
            setattr(self, attr, value)
            self.endFilterChange()
        else:
            setattr(self, attr, value)
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        idx = self.sourceModel().index(source_row, 0, source_parent)
        node: Node = idx.internalPointer()
        r = node.row
        if r is None:
            return False
        if self._text and self._text not in r.rel.casefold():
            return False
        pred = self.MODES[self._mode][1]
        return pred is None or pred(r.status)
