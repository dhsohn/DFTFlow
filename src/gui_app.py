import json
import os
import signal
import subprocess
import sys
import traceback
from datetime import datetime
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QScatterSeries, QValueAxis

from run_opt_config import validate_run_config
from run_opt_paths import get_app_base_dir, get_runs_base_dir


REFRESH_INTERVAL_MS = 2000
LOG_TAIL_LINES = 2000


@dataclass
class RunEntry:
    run_dir: str
    metadata_path: str
    status: str
    started_at: str | None
    calculation_mode: str | None
    basis: str | None
    xc: str | None


def _ensure_runs_dir() -> Path:
    runs_dir = Path(get_runs_base_dir())
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir


def _read_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return list(deque(handle, maxlen=max_lines))
    except OSError:
        return []


def _axis_range(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 1.0)
    vmin = min(values)
    vmax = max(values)
    if vmin == vmax:
        pad = 1.0 if vmin == 0 else abs(vmin) * 0.1
        return (vmin - pad, vmax + pad)
    pad = (vmax - vmin) * 0.05
    return (vmin - pad, vmax + pad)


def _safe_results(payload: dict | None) -> dict:
    if not payload:
        return {}
    results = payload.get("results")
    if isinstance(results, dict):
        return results
    return {}


def _iter_metadata_files(base_dir: Path, max_depth: int = 2):
    base_depth = len(base_dir.parts)
    for root, dirs, files in os.walk(base_dir):
        depth = len(Path(root).parts) - base_depth
        if depth > max_depth:
            dirs[:] = []
            continue
        if "metadata.json" in files:
            yield Path(root) / "metadata.json"


def _load_run_entries(base_dir: Path) -> list[RunEntry]:
    entries: list[RunEntry] = []
    for metadata_path in _iter_metadata_files(base_dir):
        metadata = _read_json(metadata_path)
        if not metadata:
            continue
        run_dir = metadata.get("run_directory") or str(metadata_path.parent)
        entries.append(
            RunEntry(
                run_dir=run_dir,
                metadata_path=str(metadata_path),
                status=metadata.get("status", "unknown"),
                started_at=metadata.get("run_started_at"),
                calculation_mode=metadata.get("calculation_mode"),
                basis=metadata.get("basis"),
                xc=metadata.get("xc"),
            )
        )
    entries.sort(
        key=lambda item: os.path.getmtime(item.metadata_path)
        if os.path.exists(item.metadata_path)
        else 0,
        reverse=True,
    )
    return entries


class RunSubmitDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Run")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._atom_labels: list[str] = []

        form = QtWidgets.QFormLayout()
        self.xyz_path = QtWidgets.QLineEdit()
        xyz_button = QtWidgets.QPushButton("Browse...")
        xyz_button.clicked.connect(self._pick_xyz)
        form.addRow("XYZ file", self._wrap_picker(self.xyz_path, xyz_button))

        self.calc_mode = QtWidgets.QComboBox()
        self.calc_mode.addItems(
            [
                "Optimization",
                "Constrained relaxation",
                "Frequency",
                "Single point",
                "Scan",
            ]
        )
        self.calc_mode.currentIndexChanged.connect(self._update_mode_panel)
        form.addRow("Simulation", self.calc_mode)

        self.basis_box = QtWidgets.QComboBox()
        self.basis_box.setEditable(True)
        basis_values = [
            "sto-3g",
            "3-21g",
            "6-31g",
            "6-31g*",
            "6-31g**",
            "6-31+g",
            "6-31+g*",
            "6-31+g**",
            "6-31g(d)",
            "6-31g(d,p)",
            "6-31+g(d)",
            "6-31+g(d,p)",
            "6-311g",
            "6-311g*",
            "6-311g**",
            "6-311+g",
            "6-311+g*",
            "6-311+g**",
            "6-311++g",
            "6-311++g**",
            "def2-svp",
            "def2-svpd",
            "def2-tzvp",
            "def2-tzvpd",
            "def2-tzvpp",
            "def2-qzvp",
            "def2-qzvpd",
            "def2-qzvpp",
            "cc-pvdz",
            "cc-pvtz",
            "cc-pvqz",
            "aug-cc-pvdz",
            "aug-cc-pvtz",
            "aug-cc-pvqz",
            "cc-pcvdz",
            "cc-pcvtz",
            "def2-svp-jkfit",
            "def2-tzvp-jkfit",
            "def2-svp-ri",
            "def2-tzvp-ri",
        ]
        self.basis_box.addItems(basis_values)
        basis_completer = QtWidgets.QCompleter(basis_values, self)
        basis_completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        basis_completer.setFilterMode(QtCore.Qt.MatchContains)
        self.basis_box.setCompleter(basis_completer)
        form.addRow("Basis", self.basis_box)

        self.xc_box = QtWidgets.QComboBox()
        self.xc_box.setEditable(True)
        xc_values = [
            "b3lyp",
            "pbe0",
            "pbe",
            "bp86",
            "blyp",
            "tpss",
            "rev-tpss",
            "m06",
            "m06-2x",
            "m06-l",
            "wb97x-d",
            "wb97m-v",
            "cam-b3lyp",
            "b97-d",
            "b97-3c",
            "b97x-d",
            "pbe-d3bj",
            "pbe0-d3bj",
            "b3lyp-d3bj",
            "scan",
            "r2scan",
            "r2scan-3c",
        ]
        self.xc_box.addItems(xc_values)
        xc_completer = QtWidgets.QCompleter(xc_values, self)
        xc_completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        xc_completer.setFilterMode(QtCore.Qt.MatchContains)
        self.xc_box.setCompleter(xc_completer)
        form.addRow("XC", self.xc_box)

        self.solvent_box = QtWidgets.QComboBox()
        self.solvent_box.setEditable(True)
        self.solvent_box.addItems(
            [
                "water",
                "acetonitrile",
                "methanol",
                "ethanol",
                "acetone",
                "dichloromethane",
            ]
        )
        form.addRow("Solvent", self.solvent_box)

        self.solvent_model_box = QtWidgets.QComboBox()
        self.solvent_model_box.addItems(["none", "pcm", "smd"])
        form.addRow("Solvent model", self.solvent_model_box)

        self.dispersion_box = QtWidgets.QComboBox()
        self.dispersion_box.addItems(["none", "d3bj", "d3zero", "d4"])
        form.addRow("Dispersion", self.dispersion_box)

        self.mode_panel = QtWidgets.QStackedWidget()
        self.mode_panel.addWidget(self._build_empty_panel())
        self.mode_panel.addWidget(self._build_optimization_panel())
        self.mode_panel.addWidget(self._build_constraint_panel())
        self.mode_panel.addWidget(self._build_scan_panel())
        form.addRow("Options", self.mode_panel)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self._update_mode_panel()

    def _wrap_picker(self, line_edit, button):
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        container.setLayout(layout)
        return container

    def _pick_file(self, target: QtWidgets.QLineEdit):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file")
        if path:
            target.setText(path)

    def _pick_xyz(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select XYZ file")
        if not path:
            return
        self.xyz_path.setText(path)
        self._load_xyz_atoms(path)

    def _load_xyz_atoms(self, path: str):
        labels: list[str] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                first = handle.readline().strip()
                count = int(first)
                handle.readline()
                for idx in range(count):
                    line = handle.readline()
                    if not line:
                        break
                    parts = line.split()
                    symbol = parts[0] if parts else "X"
                    labels.append(f"{idx}: {symbol}")
        except (OSError, ValueError):
            labels = []
        self._atom_labels = labels
        self._refresh_atom_combos()

    def _refresh_atom_combos(self):
        combos = [
            self.constraint_i,
            self.constraint_j,
            self.constraint_k,
            self.constraint_l,
            self.scan_i,
            self.scan_j,
            self.scan_k,
            self.scan_l,
        ]
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self._atom_labels)
            combo.blockSignals(False)

    def _build_empty_panel(self):
        panel = QtWidgets.QWidget()
        panel.setLayout(QtWidgets.QVBoxLayout())
        panel.layout().addWidget(QtWidgets.QLabel("No additional options."))
        return panel

    def _build_optimization_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()
        self.opt_optimizer = QtWidgets.QComboBox()
        self.opt_optimizer.addItems(["bfgs", "lbfgs", "fire", "gpmin", "mdmin", "sella"])
        self.opt_fmax = QtWidgets.QDoubleSpinBox()
        self.opt_fmax.setRange(0.0001, 10.0)
        self.opt_fmax.setDecimals(4)
        self.opt_fmax.setSingleStep(0.01)
        self.opt_fmax.setValue(0.05)
        self.opt_steps = QtWidgets.QSpinBox()
        self.opt_steps.setRange(1, 5000)
        self.opt_steps.setValue(200)
        layout.addRow("Optimizer", self.opt_optimizer)
        layout.addRow("Fmax", self.opt_fmax)
        layout.addRow("Max steps", self.opt_steps)
        panel.setLayout(layout)
        return panel

    def _build_constraint_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()
        self.constraint_type = QtWidgets.QComboBox()
        self.constraint_type.addItems(["bond", "angle", "dihedral"])
        self.constraint_type.currentIndexChanged.connect(self._update_constraint_fields)
        self.constraint_i = QtWidgets.QComboBox()
        self.constraint_j = QtWidgets.QComboBox()
        self.constraint_k = QtWidgets.QComboBox()
        self.constraint_l = QtWidgets.QComboBox()
        self.constraint_value = QtWidgets.QDoubleSpinBox()
        self.constraint_value.setRange(-360.0, 360.0)
        self.constraint_value.setDecimals(4)
        self.constraint_value.setSingleStep(0.1)
        layout.addRow("Constraint type", self.constraint_type)
        layout.addRow("Atom i", self.constraint_i)
        layout.addRow("Atom j", self.constraint_j)
        layout.addRow("Atom k", self.constraint_k)
        layout.addRow("Atom l", self.constraint_l)
        layout.addRow("Target value", self.constraint_value)
        self.constraint_optimizer = QtWidgets.QComboBox()
        self.constraint_optimizer.addItems(["bfgs", "lbfgs", "fire", "gpmin", "mdmin", "sella"])
        self.constraint_fmax = QtWidgets.QDoubleSpinBox()
        self.constraint_fmax.setRange(0.0001, 10.0)
        self.constraint_fmax.setDecimals(4)
        self.constraint_fmax.setSingleStep(0.01)
        self.constraint_fmax.setValue(0.05)
        self.constraint_steps = QtWidgets.QSpinBox()
        self.constraint_steps.setRange(1, 5000)
        self.constraint_steps.setValue(200)
        layout.addRow("Optimizer", self.constraint_optimizer)
        layout.addRow("Fmax", self.constraint_fmax)
        layout.addRow("Max steps", self.constraint_steps)
        panel.setLayout(layout)
        self._update_constraint_fields()
        return panel

    def _build_scan_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()
        self.scan_type = QtWidgets.QComboBox()
        self.scan_type.addItems(["bond", "angle", "dihedral"])
        self.scan_type.currentIndexChanged.connect(self._update_scan_fields)
        self.scan_mode = QtWidgets.QComboBox()
        self.scan_mode.addItems(["optimization", "single_point"])
        self.scan_i = QtWidgets.QComboBox()
        self.scan_j = QtWidgets.QComboBox()
        self.scan_k = QtWidgets.QComboBox()
        self.scan_l = QtWidgets.QComboBox()
        self.scan_start = QtWidgets.QDoubleSpinBox()
        self.scan_start.setRange(-360.0, 360.0)
        self.scan_start.setDecimals(4)
        self.scan_start.setSingleStep(0.1)
        self.scan_end = QtWidgets.QDoubleSpinBox()
        self.scan_end.setRange(-360.0, 360.0)
        self.scan_end.setDecimals(4)
        self.scan_end.setSingleStep(0.1)
        self.scan_step = QtWidgets.QDoubleSpinBox()
        self.scan_step.setRange(0.0001, 360.0)
        self.scan_step.setDecimals(4)
        self.scan_step.setSingleStep(0.1)
        layout.addRow("Scan type", self.scan_type)
        layout.addRow("Scan mode", self.scan_mode)
        layout.addRow("Atom i", self.scan_i)
        layout.addRow("Atom j", self.scan_j)
        layout.addRow("Atom k", self.scan_k)
        layout.addRow("Atom l", self.scan_l)
        layout.addRow("Start", self.scan_start)
        layout.addRow("End", self.scan_end)
        layout.addRow("Step", self.scan_step)
        panel.setLayout(layout)
        self._update_scan_fields()
        return panel

    def _update_constraint_fields(self):
        constraint_type = self.constraint_type.currentText()
        needs_k = constraint_type in ("angle", "dihedral")
        needs_l = constraint_type == "dihedral"
        self.constraint_k.setEnabled(needs_k)
        self.constraint_l.setEnabled(needs_l)
        if constraint_type == "bond":
            self.constraint_value.setRange(0.0, 10.0)
            self.constraint_value.setSingleStep(0.01)
        elif constraint_type == "angle":
            self.constraint_value.setRange(0.0, 180.0)
            self.constraint_value.setSingleStep(1.0)
        else:
            self.constraint_value.setRange(-180.0, 180.0)
            self.constraint_value.setSingleStep(1.0)

    def _update_scan_fields(self):
        scan_type = self.scan_type.currentText()
        needs_k = scan_type in ("angle", "dihedral")
        needs_l = scan_type == "dihedral"
        self.scan_k.setEnabled(needs_k)
        self.scan_l.setEnabled(needs_l)

    def _update_mode_panel(self):
        mode = self.calc_mode.currentText()
        if mode == "Optimization":
            self.mode_panel.setCurrentIndex(1)
        elif mode == "Constrained relaxation":
            self.mode_panel.setCurrentIndex(2)
        elif mode == "Scan":
            self.mode_panel.setCurrentIndex(3)
        else:
            self.mode_panel.setCurrentIndex(0)

    def get_values(self):
        if not self.xyz_path.text().strip():
            return {"xyz": None}
        basis = self.basis_box.currentText().strip()
        xc = self.xc_box.currentText().strip()
        solvent = self.solvent_box.currentText().strip()
        solvent_model = self.solvent_model_box.currentText()
        if solvent_model == "none":
            solvent_model = None
        dispersion = self.dispersion_box.currentText()
        if dispersion == "none":
            dispersion = None
        mode_text = self.calc_mode.currentText()
        calculation_mode = {
            "Optimization": "optimization",
            "Constrained relaxation": "optimization",
            "Frequency": "frequency",
            "Single point": "single_point",
            "Scan": "scan",
        }[mode_text]

        if mode_text in ("Constrained relaxation", "Scan") and not self._atom_labels:
            return {"xyz": None, "error": "Unable to read atoms from XYZ file."}

        def _combo_index(combo):
            index = combo.currentIndex()
            return index if index >= 0 else None

        config = {
            "basis": basis,
            "xc": xc,
            "solvent": solvent,
            "solvent_model": solvent_model,
            "dispersion": dispersion,
            "calculation_mode": calculation_mode,
        }

        if mode_text == "Optimization":
            optimizer_block = {
                "optimizer": self.opt_optimizer.currentText().strip(),
                "fmax": float(self.opt_fmax.value()),
                "steps": int(self.opt_steps.value()),
            }
            config["optimizer"] = {"mode": "minimum", "ase": optimizer_block}

        if mode_text == "Constrained relaxation":
            optimizer_block = {
                "optimizer": self.constraint_optimizer.currentText().strip(),
                "fmax": float(self.constraint_fmax.value()),
                "steps": int(self.constraint_steps.value()),
            }
            config["optimizer"] = {"mode": "minimum", "ase": optimizer_block}
            constraint_type = self.constraint_type.currentText()
            constraint = {
                "i": _combo_index(self.constraint_i),
                "j": _combo_index(self.constraint_j),
            }
            if constraint_type in ("angle", "dihedral"):
                constraint["k"] = _combo_index(self.constraint_k)
            if constraint_type == "dihedral":
                constraint["l"] = _combo_index(self.constraint_l)
            if any(value is None for value in constraint.values()):
                return {"xyz": None, "error": "Select all constraint atom indices."}
            value = float(self.constraint_value.value())
            if constraint_type == "bond":
                constraint["length"] = value
                config["constraints"] = {"bonds": [constraint]}
            elif constraint_type == "angle":
                constraint["angle"] = value
                config["constraints"] = {"angles": [constraint]}
            else:
                constraint["dihedral"] = value
                config["constraints"] = {"dihedrals": [constraint]}

        if mode_text == "Scan":
            scan_type = self.scan_type.currentText()
            scan_config = {
                "type": scan_type,
                "i": _combo_index(self.scan_i),
                "j": _combo_index(self.scan_j),
                "start": float(self.scan_start.value()),
                "end": float(self.scan_end.value()),
                "step": float(self.scan_step.value()),
                "mode": self.scan_mode.currentText(),
            }
            if scan_type in ("angle", "dihedral"):
                scan_config["k"] = _combo_index(self.scan_k)
            if scan_type == "dihedral":
                scan_config["l"] = _combo_index(self.scan_l)
            if any(value is None for key, value in scan_config.items() if key in {"i", "j", "k", "l"}):
                return {"xyz": None, "error": "Select all scan atom indices."}
            config["scan"] = scan_config

        return {
            "xyz": self.xyz_path.text().strip() or None,
            "config": config,
        }


class DFTFlowWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DFTFlow")
        self.resize(1200, 800)

        self.runs_dir = _ensure_runs_dir()
        self.current_run: RunEntry | None = None
        self.current_log_lines: list[str] = []
        self.current_query = ""

        self._build_ui()
        self._refresh_runs()

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_runs)
        self.refresh_timer.start(REFRESH_INTERVAL_MS)

    def _log_gui_error(self, label, exc):
        error_path = Path(get_app_base_dir()) / "gui_errors.log"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        with error_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{label}] {exc}\n")
            handle.write(traceback.format_exc())
            handle.write("\n")

    def _build_ui(self):
        toolbar = QtWidgets.QToolBar()
        self.addToolBar(toolbar)

        new_run_action = QtGui.QAction("New Run", self)
        new_run_action.triggered.connect(self._new_run)
        toolbar.addAction(new_run_action)

        stop_action = QtGui.QAction("Stop Run", self)
        stop_action.triggered.connect(self._stop_run)
        toolbar.addAction(stop_action)

        open_runs_action = QtGui.QAction("Open Runs Folder", self)
        open_runs_action.triggered.connect(self._open_runs_folder)
        toolbar.addAction(open_runs_action)

        splitter = QtWidgets.QSplitter()

        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.addWidget(QtWidgets.QLabel("Runs"))
        self.run_list = QtWidgets.QListWidget()
        self.run_list.itemSelectionChanged.connect(self._select_run)
        left_layout.addWidget(self.run_list)
        left_panel.setLayout(left_layout)

        self.tabs = QtWidgets.QTabWidget()
        self.summary_view = QtWidgets.QPlainTextEdit()
        self.summary_view.setReadOnly(True)
        self.summary_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)

        log_tab = QtWidgets.QWidget()
        log_layout = QtWidgets.QVBoxLayout()
        self.log_search = QtWidgets.QLineEdit()
        self.log_search.setPlaceholderText("Filter log...")
        self.log_search.textChanged.connect(self._update_log_view)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        log_layout.addWidget(self.log_search)
        log_layout.addWidget(self.log_view)
        log_tab.setLayout(log_layout)

        results_tab = QtWidgets.QWidget()
        results_layout = QtWidgets.QVBoxLayout()
        self.results_info = QtWidgets.QLabel("No results available.")
        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QtGui.QPainter.Antialiasing)
        results_layout.addWidget(self.results_info)
        results_layout.addWidget(self.chart_view, 1)
        results_tab.setLayout(results_layout)

        self.tabs.addTab(self.summary_view, "Summary")
        self.tabs.addTab(log_tab, "Logs")
        self.tabs.addTab(results_tab, "Results")

        splitter.addWidget(left_panel)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

    def _new_run(self):
        dialog = RunSubmitDialog(self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        values = dialog.get_values()
        if values.get("error"):
            QtWidgets.QMessageBox.warning(self, "Invalid input", values["error"])
            return
        if not values.get("xyz") or not values.get("config"):
            QtWidgets.QMessageBox.warning(
                self, "Missing input", "XYZ and simulation settings are required."
            )
            return
        config = values["config"]
        try:
            validate_run_config(config)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Invalid settings", f"Config validation failed: {exc}"
            )
            return
        config_dir = Path(self.runs_dir) / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        config_path = config_dir / f"run_config_{timestamp}.json"
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
        command = [
            sys.executable,
            "-m",
            "run_opt",
            "run",
            values["xyz"],
            "--config",
            str(config_path),
        ]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        subprocess.Popen(
            command,
            cwd=str(Path(get_app_base_dir())),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )

    def _open_runs_folder(self):
        url = QtCore.QUrl.fromLocalFile(str(self.runs_dir))
        QtGui.QDesktopServices.openUrl(url)

    def _stop_run(self):
        if not self.current_run:
            return
        metadata = _read_json(Path(self.current_run.metadata_path))
        if not metadata:
            return
        pid = metadata.get("pid")
        if not pid:
            QtWidgets.QMessageBox.information(
                self, "Stop Run", "No PID recorded for this run."
            )
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Stop Run", f"Unable to stop process {pid}: {exc}"
            )

    def _refresh_runs(self):
        selected = self.current_run.run_dir if self.current_run else None
        entries = _load_run_entries(self.runs_dir)
        self.run_list.blockSignals(True)
        self.run_list.clear()
        for entry in entries:
            label_parts = [
                entry.status,
                entry.calculation_mode or "unknown",
                entry.basis or "-",
                entry.xc or "-",
                Path(entry.run_dir).name,
            ]
            item = QtWidgets.QListWidgetItem(" | ".join(label_parts))
            item.setData(QtCore.Qt.UserRole, entry)
            self.run_list.addItem(item)
            if selected and entry.run_dir == selected:
                item.setSelected(True)
        self.run_list.blockSignals(False)
        if selected:
            self._select_run()

    def _select_run(self):
        selected_items = self.run_list.selectedItems()
        if not selected_items:
            self.current_run = None
            return
        entry = selected_items[0].data(QtCore.Qt.UserRole)
        self.current_run = entry
        self._update_summary_view()
        self._update_log_view()
        self._update_results_view()

    def _update_summary_view(self):
        if not self.current_run:
            self.summary_view.setPlainText("")
            return
        metadata = _read_json(Path(self.current_run.metadata_path))
        if not metadata:
            self.summary_view.setPlainText("Unable to load metadata.")
            return
        summary_lines = [
            f"Run dir: {metadata.get('run_directory')}",
            f"Status: {metadata.get('status')}",
            f"Started: {metadata.get('run_started_at')}",
            f"Ended: {metadata.get('run_ended_at')}",
            f"Mode: {metadata.get('calculation_mode')}",
            f"Basis: {metadata.get('basis')}",
            f"XC: {metadata.get('xc')}",
            f"Solvent: {metadata.get('solvent')}",
            f"Solvent model: {metadata.get('solvent_model')}",
            f"Dispersion: {metadata.get('dispersion')}",
            "",
            "Metadata JSON:",
            json.dumps(metadata, indent=2, ensure_ascii=False),
        ]
        self.summary_view.setPlainText("\n".join(summary_lines))

    def _update_log_view(self):
        if not self.current_run:
            self.log_view.setPlainText("")
            return
        metadata = _read_json(Path(self.current_run.metadata_path))
        if not metadata:
            return
        log_path = metadata.get("log_file") or str(Path(self.current_run.run_dir) / "run.log")
        lines = _tail_lines(Path(log_path), LOG_TAIL_LINES)
        query = self.log_search.text().strip().lower()
        if query:
            lines = [line for line in lines if query in line.lower()]
        self.log_view.setPlainText("".join(lines))

    def _update_results_view(self):
        try:
            if not self.current_run:
                self.results_info.setText("No run selected.")
                self.chart_view.setChart(QChart())
                return
            run_dir = Path(self.current_run.run_dir)
            opt_log = run_dir / "ase_opt.log"
            irc_csv = run_dir / "irc_profile.csv"
            scan_csv = run_dir / "scan_result.csv"
            freq_json = run_dir / "frequency_result.json"
            sp_json = run_dir / "qcschema_result.json"

            if opt_log.exists():
                step_index = None
                energy_index = None
                x_values = []
                y_values = []
                line_series = QLineSeries()
                with opt_log.open("r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        parts = line.strip().split()
                        if not parts:
                            continue
                        if parts[0] == "Step" and "Energy" in parts:
                            step_index = parts.index("Step")
                            energy_index = parts.index("Energy")
                            continue
                        if parts[0].endswith(":"):
                            parts = parts[1:]
                        if step_index is not None and energy_index is not None:
                            if len(parts) <= max(step_index, energy_index):
                                continue
                            step_token = parts[step_index]
                            energy_token = parts[energy_index]
                        else:
                            if len(parts) < 3:
                                continue
                            step_token = parts[0]
                            energy_token = parts[2]
                        try:
                            step = float(step_token)
                            energy = float(energy_token)
                        except ValueError:
                            continue
                        x_values.append(step)
                        y_values.append(energy)
                        line_series.append(step, energy)
                if x_values:
                    chart = QChart()
                    chart.addSeries(line_series)
                    axis_x = QValueAxis()
                    axis_x.setTitleText("Step")
                    axis_y = QValueAxis()
                    axis_y.setTitleText("Energy (Hartree)")
                    x_min, x_max = _axis_range(x_values)
                    y_min, y_max = _axis_range(y_values)
                    axis_x.setRange(x_min, x_max)
                    axis_y.setRange(y_min, y_max)
                    chart.addAxis(axis_x, QtCore.Qt.AlignBottom)
                    chart.addAxis(axis_y, QtCore.Qt.AlignLeft)
                    line_series.attachAxis(axis_x)
                    line_series.attachAxis(axis_y)
                    self.results_info.setText("Optimization energy profile.")
                    self.chart_view.setChart(chart)
                    return

            if irc_csv.exists():
                series = {}
                x_values = []
                y_values = []
                with irc_csv.open("r", encoding="utf-8", errors="replace") as handle:
                    header = handle.readline().strip().split(",")
                    try:
                        direction_index = header.index("direction")
                        step_index = header.index("step")
                        energy_index = header.index("energy_ev")
                    except ValueError:
                        self.results_info.setText("IRC profile format not recognized.")
                        self.chart_view.setChart(QChart())
                        return
                    for line in handle:
                        parts = [item.strip() for item in line.split(",")]
                        if len(parts) <= energy_index:
                            continue
                        direction = parts[direction_index]
                        try:
                            step = float(parts[step_index])
                            energy = float(parts[energy_index])
                        except ValueError:
                            continue
                        x_values.append(step)
                        y_values.append(energy)
                        series.setdefault(direction, []).append((step, energy))
                chart = QChart()
                for direction, points in series.items():
                    line_series = QLineSeries()
                    line_series.setName(direction)
                    for step, energy in points:
                        line_series.append(step, energy)
                    chart.addSeries(line_series)
                axis_x = QValueAxis()
                axis_x.setTitleText("Step")
                axis_y = QValueAxis()
                axis_y.setTitleText("Energy (eV)")
                x_min, x_max = _axis_range(x_values)
                y_min, y_max = _axis_range(y_values)
                axis_x.setRange(x_min, x_max)
                axis_y.setRange(y_min, y_max)
                chart.addAxis(axis_x, QtCore.Qt.AlignBottom)
                chart.addAxis(axis_y, QtCore.Qt.AlignLeft)
                for s in chart.series():
                    s.attachAxis(axis_x)
                    s.attachAxis(axis_y)
                chart.legend().setVisible(True)
                self.results_info.setText("IRC energy profile.")
                self.chart_view.setChart(chart)
                return

            if scan_csv.exists():
                x_values = []
                y_values = []
                with scan_csv.open("r", encoding="utf-8", errors="replace") as handle:
                    header = handle.readline().strip().split(",")
                    if len(header) < 3:
                        self.results_info.setText("Scan result format not recognized.")
                        self.chart_view.setChart(QChart())
                        return
                    energy_index = header.index("energy") if "energy" in header else None
                    coord_index = None
                    for idx, name in enumerate(header):
                        if name.startswith("bond_") or name.startswith("angle_") or name.startswith("dihedral_"):
                            coord_index = idx
                            break
                    if energy_index is None or coord_index is None:
                        self.results_info.setText("Scan result format not recognized.")
                        self.chart_view.setChart(QChart())
                        return
                    line_series = QLineSeries()
                    for line in handle:
                        parts = [item.strip() for item in line.split(",")]
                        if len(parts) <= energy_index:
                            continue
                        try:
                            coord = float(parts[coord_index])
                            energy = float(parts[energy_index])
                        except ValueError:
                            continue
                        x_values.append(coord)
                        y_values.append(energy)
                        line_series.append(coord, energy)
                chart = QChart()
                chart.addSeries(line_series)
                axis_x = QValueAxis()
                axis_x.setTitleText(header[coord_index])
                axis_y = QValueAxis()
                axis_y.setTitleText("Energy (Hartree)")
                x_min, x_max = _axis_range(x_values)
                y_min, y_max = _axis_range(y_values)
                axis_x.setRange(x_min, x_max)
                axis_y.setRange(y_min, y_max)
                chart.addAxis(axis_x, QtCore.Qt.AlignBottom)
                chart.addAxis(axis_y, QtCore.Qt.AlignLeft)
                line_series.attachAxis(axis_x)
                line_series.attachAxis(axis_y)
                self.results_info.setText("Scan energy profile.")
                self.chart_view.setChart(chart)
                return

            if freq_json.exists():
                payload = _read_json(freq_json)
                if not payload:
                    self.results_info.setText("Frequency result unavailable.")
                    self.chart_view.setChart(QChart())
                    return
                results = _safe_results(payload)
                frequencies = results.get("frequencies_wavenumber") or []
                line_series = QLineSeries()
                x_values = []
                y_values = []
                for idx, value in enumerate(frequencies, start=1):
                    try:
                        freq = float(value)
                    except (TypeError, ValueError):
                        continue
                    x_values.append(float(idx))
                    y_values.append(freq)
                    line_series.append(idx, freq)
                chart = QChart()
                chart.addSeries(line_series)
                axis_x = QValueAxis()
                axis_x.setTitleText("Mode index")
                axis_y = QValueAxis()
                axis_y.setTitleText("Frequency (cm^-1)")
                x_min, x_max = _axis_range(x_values)
                y_min, y_max = _axis_range(y_values)
                axis_x.setRange(x_min, x_max)
                axis_y.setRange(y_min, y_max)
                chart.addAxis(axis_x, QtCore.Qt.AlignBottom)
                chart.addAxis(axis_y, QtCore.Qt.AlignLeft)
                line_series.attachAxis(axis_x)
                line_series.attachAxis(axis_y)
                self.results_info.setText("Frequency spectrum.")
                self.chart_view.setChart(chart)
                return

            if sp_json.exists():
                payload = _read_json(sp_json)
                energy = None
                if payload:
                    energy = payload.get("return_result")
                    if energy is None:
                        energy = payload.get("properties", {}).get("return_energy")
                if energy is not None:
                    self.results_info.setText(f"Single-point energy: {energy:.6f} Hartree")
                    scatter = QScatterSeries()
                    scatter.append(1.0, float(energy))
                    chart = QChart()
                    chart.addSeries(scatter)
                    axis_x = QValueAxis()
                    axis_x.setTitleText("Point")
                    axis_y = QValueAxis()
                    axis_y.setTitleText("Energy (Hartree)")
                    x_min, x_max = _axis_range([1.0])
                    y_min, y_max = _axis_range([float(energy)])
                    axis_x.setRange(x_min, x_max)
                    axis_y.setRange(y_min, y_max)
                    chart.addAxis(axis_x, QtCore.Qt.AlignBottom)
                    chart.addAxis(axis_y, QtCore.Qt.AlignLeft)
                    scatter.attachAxis(axis_x)
                    scatter.attachAxis(axis_y)
                    self.chart_view.setChart(chart)
                else:
                    self.results_info.setText("Single-point result available.")
                    self.chart_view.setChart(QChart())
                return

            self.results_info.setText("No results available.")
            self.chart_view.setChart(QChart())
        except Exception as exc:
            self._log_gui_error("results_view", exc)
            self.results_info.setText(
                "Error loading results (see ~/DFTFlow/gui_errors.log)."
            )
            self.chart_view.setChart(QChart())


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = DFTFlowWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
