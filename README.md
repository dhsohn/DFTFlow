# pyscf_auto

**Status: Beta**

Local PySCF/ASE retry runner for `.inp`-based reaction directories.
The command style is intentionally aligned with `orca_auto`.

- CLI entry point: `pyscf_auto`
- Main commands: `init`, `run-inp`, `status`, `organize`, `check`, `monitor`, `cleanup`
- App config: `~/.pyscf_auto/config.yaml` (or `PYSCF_AUTO_CONFIG`)
- Default roots: `~/pyscf_runs` (input/runs), `~/pyscf_outputs` (organized outputs)

## Quickstart (First 5 Minutes)

### 1) Install

```bash
conda create -n pyscf_auto -c daehyupsohn -c conda-forge pyscf_auto
conda activate pyscf_auto
```

### 2) One-time initialization

`init` creates runtime directories, a user config, and a runnable sample reaction.

```bash
pyscf_auto init
```

Useful options:

```bash
# custom roots
pyscf_auto init --allowed-root ~/my_runs --organized-root ~/my_outputs

# create optimization sample instead of single-point sample
pyscf_auto init --sample water_opt --reaction-name demo_opt

# overwrite existing config/sample files
pyscf_auto init --force
```

### 3) Run the sample

```bash
pyscf_auto run-inp --reaction-dir ~/pyscf_runs/demo_water
```

Optional: background mode (prints `pid`/`log` and returns immediately):

```bash
pyscf_auto run-inp --reaction-dir ~/pyscf_runs/demo_water --background
```

### 4) Check run status

```bash
pyscf_auto status --reaction-dir ~/pyscf_runs/demo_water
```

### 5) Organize, quality-check, and cleanup (optional)

```bash
# organize dry-run
pyscf_auto organize --root ~/pyscf_runs

# apply organize
pyscf_auto organize --root ~/pyscf_runs --apply

# quality check organized results
pyscf_auto check --root ~/pyscf_outputs --json

# disk usage snapshot
pyscf_auto monitor --json

# cleanup dry-run
pyscf_auto cleanup --root ~/pyscf_outputs

# apply cleanup
pyscf_auto cleanup --root ~/pyscf_outputs --apply
```

Default keep/remove policy is configurable under `cleanup` in config.
`cleanup.remove_overrides_keep` controls whether remove patterns can override keep rules.

## For orca_auto Users

The primary command mapping is intentionally the same:

- `run-inp`: run or resume one reaction directory
- `status`: inspect one reaction directory
- `organize`: move completed runs to organized storage
- `check`: run post-run quality checks
- `monitor`: check/watch disk usage
- `cleanup`: remove non-essential files from organized runs

Main difference:

- Engine is PySCF/ASE based (not ORCA binary execution).
- `run-inp` background mode is explicit (`--background` / `--foreground`) instead of wrapper-only behavior.

## Dependency Profiles

- `core` (default): CLI + state/organize/cleanup paths
- `engine`: adds PySCF/ASE runtime dependencies for `run-inp`
- `dispersion`: optional D3/D4 backends
- `full`: `engine + dispersion`

Example (pip editable/dev environment):

```bash
pip install -e ".[engine]"
pip install -e ".[full]"
```

## Optional Feature Flags

Heavy workflow stages can be disabled explicitly:

- `PYSCF_AUTO_DISABLE_SCAN=1`
- `PYSCF_AUTO_DISABLE_IRC=1`
- `PYSCF_AUTO_DISABLE_FREQUENCY=1`
- `PYSCF_AUTO_DISABLE_QCSCHEMA=1`

## Utility Scripts

```bash
./scripts/preflight_check.sh
./scripts/validate_inp.py path/to/input.inp
./scripts/validate_runtime_config.py --config ~/.pyscf_auto/config.yaml
./scripts/progress_report.py --print-only
./scripts/install_cron.sh
```

## Development Checks

```bash
pip install -r requirements-dev.txt
pytest -q
pytest -q --cov=src --cov-report=term-missing
ruff check src tests
mypy src
```

## Scope

pyscf_auto is a local workstation tool. It does not provide distributed scheduling/orchestration.

## Architecture Guardrails

- Runner/execution boundary is fixed at `execution.entrypoint.execute_attempt`.
- Stage implementations are lazy-loaded via `execution.plugins`.
- Guardrail tests enforce this boundary and block direct stage imports from `execution/__init__.py`.
