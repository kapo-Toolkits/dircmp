import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dircmp.core import compare  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    QCoreApplication.setOrganizationName("dircmp-tests")
    QCoreApplication.setApplicationName("dircmp-tests")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    yield app
    # Tear Qt down while Python still owns everything; otherwise PySide6 can
    # segfault at interpreter exit on Linux CI.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if hasattr(app, "shutdown"):
        app.shutdown()


def test_model_and_window(app, make):
    from dircmp.gui.main_window import MainWindow
    from dircmp.gui.tree_model import ROW_ROLE

    a = make({"same": "x", "d": {"diff": "one", "only_a": "1"}})
    b = make({"same": "x", "d": {"diff": "two"}})
    c = make({"same": "x", "d": {"diff": "one"}})
    w = MainWindow([a, b, c])
    assert w.folder_list.folders() == [a, b, c]
    w._on_done(compare([a, b, c]))

    proxy = w.proxy
    # "differences only": the identical file is hidden, the dir with changes stays
    names = [proxy.index(i, 0).data() for i in range(proxy.rowCount())]
    assert names == ["d"]
    d = proxy.index(0, 0)
    child_names = sorted(proxy.index(i, 0, d).data() for i in range(proxy.rowCount(d)))
    assert child_names == ["diff", "only_a"]

    diff_idx = next(proxy.index(i, 0, d) for i in range(proxy.rowCount(d)) if proxy.index(i, 0, d).data() == "diff")
    assert [proxy.index(diff_idx.row(), col, d).data() for col in (2, 3, 4)] == ["1", "2", "1"]
    w.details.show_row(w.comp, diff_idx.data(ROW_ROLE))
    assert w.details.columnCount() == 3

    w.filter_combo.setCurrentIndex(0)  # all
    assert proxy.rowCount() == 2
    w.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
