"""Kill-picker window: the top heavy processes with checkboxes.

A thin viewer: it never reads /proc itself and never stops a
process itself. The process list comes from a provider
(callable returning the top processes), the RAM line from a
ram function, and stopping goes through a killer function.
Production passes the real ones (see run_gui); tests pass
fakes, so no test ever touches a real process.

Only processes the user can actually stop are listed: the
provider filters out anything the killer would refuse (system
processes, our own tree, other users' processes).

Importing this module needs PySide6; the guarded entry is
gui_main.py, which prints a plain message when the toolkit is
missing instead of a traceback.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import APP_NAME, killer
from . import processes as proc_mod
from . import ram as ram_mod

MAX_ROWS = 6


def default_provider():
    """The real top 6 stoppable processes, heaviest first."""
    found = proc_mod.collect()
    own_tree = killer.own_tree_pids()
    top = proc_mod.top_conflicts(found, limit=20,
                                 exclude_pids=own_tree)
    stoppable = [info for info in top
                 if killer.refusal_reason(info["pid"],
                                          own_tree=own_tree) is None]
    return stoppable[:MAX_ROWS]


def default_ram():
    """(available bytes, total bytes) for the RAM line."""
    return ram_mod.available_bytes(), ram_mod.total_bytes()


def default_killer(pids, confirm, dry_run):
    """The real kill, through the guarded killer."""
    return killer.kill_pids(pids, confirm=confirm,
                            dry_run=dry_run)


class KillPickerWindow(QWidget):
    """The picker window."""

    def __init__(self, provider=None, killer_fn=None,
                 ram_fn=None, require_bytes=None, dry_run=False,
                 parent=None):
        super().__init__(parent)
        self.provider = provider or default_provider
        self.killer_fn = killer_fn or default_killer
        self.ram_fn = ram_fn or default_ram
        self.require_bytes = require_bytes
        self.dry_run = dry_run
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(560, 320)

        layout = QVBoxLayout(self)

        self.ram_label = QLabel("", self)
        self.ram_label.setObjectName("ram_label")
        layout.addWidget(self.ram_label)

        self.fit_label = QLabel("", self)
        self.fit_label.setObjectName("fit_label")
        layout.addWidget(self.fit_label)

        self.table = QTableWidget(0, 5, self)
        self.table.setObjectName("process_table")
        self.table.setHorizontalHeaderLabels(
            ["", "Process", "PID", "RAM", "CPU"])
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._update_kill_button)
        layout.addWidget(self.table)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("status_label")
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.setObjectName("refresh_button")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)
        self.kill_button = QPushButton("Kill selected", self)
        self.kill_button.setObjectName("kill_button")
        self.kill_button.setEnabled(False)
        self.kill_button.clicked.connect(self._kill_selected)
        buttons.addWidget(self.kill_button)
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName("close_button")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.refresh()

    def _update_kill_button(self, _item=None):
        self.kill_button.setEnabled(bool(self._selected_pids()))

    def _selected_pids(self):
        pids = []
        for row in range(self.table.rowCount()):
            box = self.table.item(row, 0)
            pid_item = self.table.item(row, 2)
            if (box is not None
                    and box.checkState() == Qt.CheckState.Checked
                    and pid_item is not None):
                try:
                    pids.append(int(pid_item.text()))
                except ValueError:
                    continue
        return pids

    def _selected_names(self):
        names = []
        for row in range(self.table.rowCount()):
            box = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            if (box is not None
                    and box.checkState() == Qt.CheckState.Checked
                    and name_item is not None):
                names.append(name_item.text())
        return names

    def refresh(self):
        try:
            available, total = self.ram_fn()
        except OSError:
            available, total = None, None
        if available is None:
            self.ram_label.setText(
                "Free RAM: could not read the memory info.")
        else:
            self.ram_label.setText(
                "Free RAM: %s of %s total."
                % (ram_mod.format_gb(available),
                   ram_mod.format_gb(total)))
        if self.require_bytes is None:
            self.fit_label.setText("")
        elif available is None:
            self.fit_label.setText(
                "Cannot check whether the model fits.")
        else:
            verdict = ram_mod.check(
                self.require_bytes,
                meminfo={"MemAvailable": available // 1024,
                         "MemTotal": total // 1024})
            if verdict["fits"]:
                self.fit_label.setText(
                    "A %s model fits in free RAM."
                    % ram_mod.format_gb(self.require_bytes))
            else:
                self.fit_label.setText(
                    "A %s model does not fit: short %s."
                    % (ram_mod.format_gb(self.require_bytes),
                       ram_mod.format_gb(verdict["shortfall"])))
        try:
            found = self.provider()
        except OSError as exc:
            found = []
            self.status_label.setText(
                "Could not list processes: %s" % exc)
        else:
            self.status_label.setText("")
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for info in found[:MAX_ROWS]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            box = QTableWidgetItem("")
            box.setFlags(box.flags()
                         | Qt.ItemFlag.ItemIsUserCheckable)
            box.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, box)
            self.table.setItem(
                row, 1, QTableWidgetItem(str(info["name"])))
            self.table.setItem(
                row, 2, QTableWidgetItem(str(info["pid"])))
            self.table.setItem(
                row, 3,
                QTableWidgetItem("%.0f MB" % info["rss_mb"]))
            self.table.setItem(
                row, 4,
                QTableWidgetItem("%.0f%%" % info["cpu_percent"]))
        self.table.blockSignals(False)
        if not found:
            # A provider error already wrote its own message;
            # only the genuinely empty case says nothing is heavy.
            if not self.status_label.text():
                self.status_label.setText(
                    "Nothing heavy is running.")
        elif not self.status_label.text():
            self.status_label.setText(
                "Tick the processes you do not need, then press "
                "Kill selected. Only the ticked ones are stopped.")
        self._update_kill_button()

    def _kill_selected(self):
        pids = self._selected_pids()
        names = self._selected_names()
        if not pids:
            return
        listed = "\n".join(
            "  %s (PID %d)" % (name, pid)
            for name, pid in zip(names, pids))
        if self.dry_run:
            question = ("Dry run: stop nothing. These would be "
                        "stopped:\n%s" % listed)
        else:
            question = ("Stop these processes?\n%s\n\n"
                        "They will be stopped for good." % listed)
        answer = QMessageBox.question(
            self, APP_NAME, question,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        results = self.killer_fn(pids, confirm=True,
                                 dry_run=self.dry_run)
        QMessageBox.information(
            self, APP_NAME,
            killer.plain_report(results).rstrip("\n"))
        stopped = sum(1 for r in results
                      if r["outcome"] in ("stopped", "would stop"))
        if self.dry_run:
            message = ("%d process(es) would be stopped." % stopped)
        else:
            message = "%d process(es) stopped." % stopped
        self.refresh()
        # refresh() rewrites the status line, so set the kill
        # result after it.
        self.status_label.setText(message)


def run_gui(argv=None):
    """Open the picker window. Returns the exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    require_bytes = None
    dry_run = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--require" and i + 1 < len(args):
            try:
                require_bytes = ram_mod.parse_size(args[i + 1])
            except ValueError:
                print("That size does not make sense: %r. Try "
                      "something like 4.5GB." % args[i + 1],
                      file=sys.stderr)
                return 2
            i += 1
        elif arg.startswith("--require="):
            try:
                require_bytes = ram_mod.parse_size(
                    arg.split("=", 1)[1])
            except ValueError:
                print("That size does not make sense: %r. Try "
                      "something like 4.5GB."
                      % arg.split("=", 1)[1], file=sys.stderr)
                return 2
        else:
            print("Unknown option: %s (see kill-picker --help)"
                  % arg, file=sys.stderr)
            return 2
        i += 1
    app = QApplication.instance() or QApplication([])
    window = KillPickerWindow(require_bytes=require_bytes,
                              dry_run=dry_run)
    window.show()
    return app.exec()
