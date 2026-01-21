# Configuration

DFTFlow configuration supports `.json`, `.yaml/.yml`, and `.toml`.

## Key Fields

| Field | Description |
| --- | --- |
| `calculation_mode` | `optimization`, `single_point`, `frequency`, `irc`, `scan` |
| `basis`, `xc` | Base basis/functional |
| `solvent`, `solvent_model` | Solvent settings (`pcm`/`smd`, vacuum can omit model) |
| `dispersion` | Dispersion correction (`d3bj`, `d3zero`, `d4`, etc.) |
| `scf` | SCF settings (`max_cycle`, `conv_tol`, `chkfile`, `extra`) |
| `optimizer` | Optimization settings (`mode`, `ase`) |
| `single_point` | Single-point override settings |
| `frequency_enabled` | Run frequency after optimization |
| `single_point_enabled` | Run single-point after optimization or frequency |
| `irc_enabled` | Run IRC after optimization or frequency |
| `scan` / `scan2d` | Scan settings (`dimensions`, `mode`, `executor`) |
| `ts_quality` | TS quality checks (`enforce`, etc.) |
| `threads`, `memory_gb` | Resource settings |
| `io` | Write intervals (`scan_write_interval_points`, etc.) |

With `calculation_mode: frequency`, `irc_enabled` and `single_point_enabled` trigger
optional follow-up steps after the frequency calculation.

## Basic Example (Optimization + Frequency + Single-Point)

```yaml
calculation_mode: optimization
basis: def2-svp
xc: b3lyp
solvent: vacuum
optimizer:
  mode: minimum
scf:
  max_cycle: 200
single_point_enabled: true
frequency_enabled: true
```

## Scan Example

```yaml
calculation_mode: scan
scan:
  mode: optimization
  executor: local
  dimensions:
    - type: bond
      i: 0
      j: 1
      start: 1.0
      end: 1.4
      step: 0.2
```

## Validation

```bash
dftflow validate-config run_config.yaml
```
