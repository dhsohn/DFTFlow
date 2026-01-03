# DFTFlow

DFTFlow is a lightweight workflow wrapper around PySCF (SCF/DFT/gradients/Hessians) and ASE (optimization driver). It runs geometry optimization (min/TS), single-point energy, frequency, IRC, and scans with consistent logging and reproducible metadata.

- CLI entry point: `dftflow` (implementation in `run_opt.py`, core logic under `src/`)
- Default config template: `run_config.json`
- Outputs are organized under `runs/YYYY-MM-DD_HHMMSS/`

## Highlights

- **Reproducible runs**: config, environment, and git metadata captured per run.
- **Interactive and non-interactive modes**: use prompts or explicit configs.
- **Chained workflows**: optimization → frequency → single-point in one execution.
- **Solvent + dispersion support**: PCM/SMD, D3/D4 with guardrails.
- **Queue and status tooling**: background runs and quick status views.

## Capabilities

### Geometry optimization
- Minimum or transition-state (TS) optimization.
- Optimizers: ASE (BFGS, etc.) and Sella for TS (order=1).
- Optional follow-up: frequency, SP, IRC.

### Single-point energy
- Compute energy at the current geometry (standalone or after optimization).

### Frequency analysis
- Hessian via PySCF; harmonic analysis.
- Default: **no dispersion in Hessian** (frequency dispersion mode = `none`).

### IRC
- IRC path from a TS; forward/reverse trajectories with energy profile.

### Scans (1D/2D)
- Scan bond/angle/dihedral grids with optimization or single-point at each point.

## Solvent models

- `vacuum` (default): no solvent.
- `pcm`: dielectric epsilon from `solvent_dielectric.json`.
- `smd`: requires PySCF built with SMD support (see SMD packaging below).

If SMD is not available, DFTFlow falls back to PCM or vacuum depending on context.

## Dispersion

- Supported: `d3bj`, `d3zero`, `d4`.
- Duplicated dispersion is avoided when the XC already embeds it.
- Some XC + D3 parameter combos are unsupported by dftd3; smoke tests skip them.

## Smoke test

`dftflow smoke-test` runs a broad matrix of quick checks (1 SCF cycle and 1-step optimizations).

Default behavior:
- Each case runs in a **separate subprocess** (isolation to avoid cascading crashes).
- Capability check is **skipped** during smoke tests only.
- Unsupported D3/XC combos are marked **skipped** instead of failing.

Useful flags:
- `--resume`: continue in an existing run directory.
- `--stop-on-error`: stop immediately on the first failure.
- `--watch`: monitor and auto-resume when logs stall.
- `--watch-timeout <sec>`: inactivity timeout before restart.
- `--watch-interval <sec>`: polling interval.
- `--watch-max-restarts <n>`: limit restarts (0 = unlimited).
- `--no-isolate`: run all cases in the same process (not recommended).

Smoke-test artifacts (per case):
- `run.log`, `log/run_events.jsonl`
- `smoke_subprocess.out` / `smoke_subprocess.err`
- `smoke_subprocess.status`

## Output layout

Per run directory (example):

```
run.log
log/run_events.jsonl
metadata.json
config_used.json
optimized.xyz
frequency_result.json
irc_result.json
scan_result.json
```

## Installation

Python: **3.12**

### Conda environment

```bash
git clone https://github.com/dhsohn/DFTFlow.git
cd DFTFlow
conda env create -f environment.yml
conda activate DFTFlow
pip install -e .
pip install sella basis-set-exchange
```

### Conda lock (recommended for reproducibility)

```bash
conda install -c conda-forge conda-lock -y
conda-lock lock -f environment.yml -p osx-arm64 -p osx-64 -p linux-64
conda-lock install --name dftflow conda-lock.yml
pip install -e .
```

## SMD-enabled PySCF (conda channel)

A custom PySCF build with SMD enabled can be built and uploaded to your conda channel.

- Recipe location: `packaging/pyscf-smd/`
- Uses `CMAKE_ARGS="-DENABLE_SMD=ON"`
- Output package name: `pyscf` (with build string `smd_...`)

Local build (osx-arm64):

```bash
conda install -n base -c conda-forge conda-build conda-verify anaconda-client
conda build packaging/pyscf-smd -c conda-forge
```

Upload:

```bash
anaconda login
anaconda upload ~/miniconda3/envs/dftflow/conda-bld/osx-arm64/pyscf-2.11.0-smd_py3.12_0.conda --user daehyupsohn
```

Install from channel:

```bash
conda create -n pyscf-smd-test -c daehyupsohn -c conda-forge pyscf
conda activate pyscf-smd-test
python - <<'PY'
import pyscf
import pyscf.solvent.smd
print("SMD enabled OK")
PY
```

Note: `linux-64` and `osx-64` builds must be done on those platforms.

## Usage

### Interactive run (default)

```bash
dftflow run
```

### Non-interactive run

```bash
dftflow run --non-interactive path/to/input.xyz --config run_config.json
```

### Resume a run

```bash
dftflow run --resume runs/2026-01-03_100104/0147_optimization_...
```

### Status and diagnostics

```bash
dftflow status runs/2026-01-03_100104/0147_optimization_...
dftflow status --recent 5
dftflow doctor
dftflow validate-config run_config.json
```

### Queue

```bash
dftflow queue status
dftflow queue cancel <RUN_ID>
dftflow queue retry <RUN_ID>
dftflow queue requeue-failed
dftflow queue prune --keep-days 30
```

## Configuration notes

- Set charge/multiplicity in XYZ comment line:
  - Example: `charge=0 multiplicity=1`
- If omitted, multiplicity is inferred from electron parity.
- `solvent_dielectric.json` provides PCM epsilon map.
- `frequency_dispersion_mode` defaults to `none`.

## Repository structure

```
run_opt.py
src/
  run_opt.py
  run_opt_engine.py
  run_opt_dispersion.py
  run_opt_config.py
  run_opt_logging.py
  run_opt_metadata.py
  run_opt_resources.py
packaging/
  pyscf-smd/
run_config.json
solvent_dielectric.json
runs/
```
