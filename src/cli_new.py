"""CLI for pyscf_auto with orca_auto-aligned command names."""

from __future__ import annotations

import argparse
import logging
import sys

from commands._helpers import default_config_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyscf_auto")
    parser.add_argument("--config", default=default_config_path(), help="Path to pyscf_auto.yaml")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Create first-run config/directories and an optional sample reaction folder.",
    )
    init_parser.add_argument(
        "--allowed-root",
        default=None,
        help="Override runtime.allowed_root for the generated config.",
    )
    init_parser.add_argument(
        "--organized-root",
        default=None,
        help="Override runtime.organized_root for the generated config.",
    )
    init_parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Override runtime.default_max_retries for the generated config.",
    )
    init_parser.add_argument(
        "--sample",
        choices=["water_sp", "water_opt", "none"],
        default="water_sp",
        help="Sample reaction template to create under allowed_root.",
    )
    init_parser.add_argument(
        "--reaction-name",
        default="demo_water",
        help="Directory name for the sample reaction under allowed_root.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite config/sample files if they already exist.",
    )
    init_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run-inp", help="Run a PySCF calculation from a .inp file.")
    run_parser.add_argument(
        "--reaction-dir",
        required=True,
        help="Directory under the configured allowed_root containing input files",
    )
    run_parser.add_argument("--max-retries", type=int, default=None)
    run_parser.add_argument("--force", action="store_true", help="Force re-run even if existing output is completed")
    run_mode = run_parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--background",
        action="store_true",
        help="Start run-inp in background and print pid/log path.",
    )
    run_mode.add_argument(
        "--foreground",
        action="store_true",
        help="Force foreground execution (disables background mode).",
    )
    run_parser.add_argument("--json", action="store_true")

    status_parser = subparsers.add_parser("status", help="Check the status of a run.")
    status_parser.add_argument("--reaction-dir", required=True, help="Directory under the configured allowed_root")
    status_parser.add_argument("--json", action="store_true")

    organize_parser = subparsers.add_parser(
        "organize",
        help="Organize completed runs into a clean directory structure.",
    )
    organize_parser.add_argument("--reaction-dir", default=None, help="Single reaction directory to organize")
    organize_parser.add_argument(
        "--root",
        default=None,
        help="Root directory to scan (mutually exclusive with --reaction-dir)",
    )
    organize_parser.add_argument("--apply", action="store_true", default=False, help="Actually move files (default is dry-run)")
    organize_parser.add_argument("--rebuild-index", action="store_true", default=False, help="Rebuild JSONL index from organized directories.")
    organize_parser.add_argument("--find", action="store_true", default=False, help="Search the index")
    organize_parser.add_argument("--run-id", default=None, help="Find by run_id (with --find)")
    organize_parser.add_argument("--job-type", default=None, help="Filter by job_type (with --find)")
    organize_parser.add_argument("--limit", type=int, default=0, help="Limit results (with --find)")
    organize_parser.add_argument("--json", action="store_true")

    check_parser = subparsers.add_parser(
        "check",
        help="Run quality checks against completed runs.",
    )
    check_parser.add_argument("--reaction-dir", default=None, help="Single reaction directory to check")
    check_parser.add_argument(
        "--root",
        default=None,
        help="Root directory to scan (must match allowed_root or organized_root)",
    )
    check_parser.add_argument("--json", action="store_true")

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Monitor disk usage for allowed_root and organized_root.",
    )
    monitor_parser.add_argument("--watch", action="store_true", default=False, help="Continuous monitoring mode")
    monitor_parser.add_argument("--interval-sec", type=int, default=None, help="Scan interval in seconds (watch mode)")
    monitor_parser.add_argument("--threshold-gb", type=float, default=None, help="Disk usage threshold in GB")
    monitor_parser.add_argument("--top-n", type=int, default=None, help="Number of top directories to show")
    monitor_parser.add_argument("--json", action="store_true")

    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument(
        "--reaction-dir",
        default=None,
        help="Single reaction directory under organized_root to clean",
    )
    cleanup_parser.add_argument(
        "--root",
        default=None,
        help="Root directory to scan (must match organized_root)",
    )
    cleanup_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually delete files (default is dry-run)",
    )
    cleanup_parser.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    command_map = {
        "init": _cmd_init,
        "run-inp": _cmd_run_inp,
        "status": _cmd_status,
        "organize": _cmd_organize,
        "check": _cmd_check,
        "monitor": _cmd_monitor,
        "cleanup": _cmd_cleanup,
    }
    try:
        return int(command_map[args.command](args))
    except KeyboardInterrupt:
        return 130
    except ModuleNotFoundError as exc:
        missing = str(getattr(exc, "name", "") or str(exc))
        logging.error(
            "Missing Python dependency: %s. Activate/install pyscf_auto environment first.",
            missing,
        )
        return 1
    except ValueError as exc:
        logging.error("%s", exc)
        return 1
    except Exception:
        logging.exception("Unexpected error")
        return 1


def _cmd_run_inp(args: argparse.Namespace) -> int:
    from commands.run_inp import cmd_run_inp

    return int(cmd_run_inp(args))


def _cmd_init(args: argparse.Namespace) -> int:
    from commands.init import cmd_init

    return int(cmd_init(args))


def _cmd_status(args: argparse.Namespace) -> int:
    from commands.run_inp import cmd_status

    return int(cmd_status(args))


def _cmd_organize(args: argparse.Namespace) -> int:
    from commands.organize import cmd_organize

    return int(cmd_organize(args))


def _cmd_cleanup(args: argparse.Namespace) -> int:
    from commands.cleanup import cmd_cleanup

    return int(cmd_cleanup(args))


def _cmd_check(args: argparse.Namespace) -> int:
    from commands.check import cmd_check

    return int(cmd_check(args))


def _cmd_monitor(args: argparse.Namespace) -> int:
    from commands.monitor import cmd_monitor

    return int(cmd_monitor(args))


if __name__ == "__main__":
    raise SystemExit(main())
