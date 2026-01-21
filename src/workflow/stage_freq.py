import json
import logging
import time
import traceback

from run_opt_engine import (
    compute_frequencies,
    compute_imaginary_mode,
    compute_single_point_energy,
)
from qcschema_export import export_qcschema_result
from .stage_irc import run_irc_stage
from .events import finalize_metadata
from .utils import (
    _frequency_units,
    _frequency_versions,
    _resolve_d3_params,
    _thermochemistry_payload,
    _update_checkpoint_scf,
)


def _is_ts_quality_enforced(ts_quality) -> bool:
    if ts_quality is None:
        return False
    if hasattr(ts_quality, "enforce"):
        enforce_value = ts_quality.enforce
        if enforce_value is not None:
            return bool(enforce_value)
    if hasattr(ts_quality, "to_dict"):
        try:
            ts_quality_dict = ts_quality.to_dict()
        except Exception:
            ts_quality_dict = None
        if isinstance(ts_quality_dict, dict):
            enforce_value = ts_quality_dict.get("enforce")
            if enforce_value is not None:
                return bool(enforce_value)
    if isinstance(ts_quality, dict):
        enforce_value = ts_quality.get("enforce")
        if enforce_value is not None:
            return bool(enforce_value)
    return False


def run_frequency_stage(stage_context, queue_update_fn):
    logging.info("Starting frequency calculation...")
    run_start = stage_context["run_start"]
    calculation_metadata = stage_context["metadata"]
    profiling_enabled = bool(stage_context.get("profiling_enabled"))
    irc_enabled = bool(stage_context.get("irc_enabled"))
    single_point_enabled = bool(stage_context.get("single_point_enabled"))
    irc_payload = None
    sp_result = None
    try:
        frequency_result = compute_frequencies(
            stage_context["mol"],
            stage_context["calc_basis"],
            stage_context["calc_xc"],
            stage_context["calc_scf_config"],
            stage_context["calc_solvent_model"],
            stage_context["calc_solvent_name"],
            stage_context["calc_eps"],
            stage_context["calc_dispersion_model"],
            stage_context["freq_dispersion_mode"],
            stage_context.get("freq_dispersion_step"),
            _resolve_d3_params(stage_context.get("optimizer_ase_config")),
            stage_context["thermo"],
            stage_context["verbose"],
            stage_context["memory_mb"],
            stage_context.get("constraints"),
            run_dir=stage_context["run_dir"],
            optimizer_mode=stage_context["optimizer_mode"],
            multiplicity=stage_context["multiplicity"],
            ts_quality=stage_context.get("ts_quality"),
            profiling_enabled=profiling_enabled,
            log_override=False,
        )
        imaginary_check = frequency_result.get("imaginary_check") or {}
        imaginary_status = imaginary_check.get("status")
        imaginary_message = imaginary_check.get("message")
        ts_quality_result = frequency_result.get("ts_quality") or {}
        ts_quality_status = ts_quality_result.get("status")
        ts_quality_message = ts_quality_result.get("message")
        if imaginary_message:
            if imaginary_status == "one_imaginary":
                logging.info("Imaginary frequency check: %s", imaginary_message)
            else:
                logging.warning("Imaginary frequency check: %s", imaginary_message)
        if ts_quality_message:
            if ts_quality_status in ("pass", "warn"):
                logging.info("TS quality check: %s", ts_quality_message)
            else:
                logging.warning("TS quality check: %s", ts_quality_message)
        frequency_payload = {
            "status": "completed",
            "output_file": stage_context["frequency_output_path"],
            "units": _frequency_units(),
            "versions": _frequency_versions(),
            "basis": stage_context["calc_basis"],
            "xc": stage_context["calc_xc"],
            "scf": stage_context["calc_scf_config"],
            "solvent": stage_context["calc_solvent_name"],
            "solvent_model": stage_context["calc_solvent_model"]
            if stage_context["calc_solvent_name"]
            else None,
            "solvent_eps": stage_context["calc_eps"],
            "dispersion": stage_context["calc_dispersion_model"],
            "dispersion_mode": stage_context["freq_dispersion_mode"],
            "dispersion_step": stage_context.get("freq_dispersion_step"),
            "profiling": frequency_result.get("profiling"),
            "thermochemistry": _thermochemistry_payload(
                stage_context["thermo"], frequency_result.get("thermochemistry")
            ),
            "results": frequency_result,
        }
        with open(
            stage_context["frequency_output_path"], "w", encoding="utf-8"
        ) as handle:
            json.dump(frequency_payload, handle, indent=2)
        calculation_metadata["frequency"] = frequency_payload
        calculation_metadata["dispersion_info"] = frequency_result.get("dispersion")
        if frequency_result.get("profiling") is not None:
            calculation_metadata.setdefault("profiling", {})["frequency"] = frequency_result.get(
                "profiling"
            )
        energy = frequency_result.get("energy")
        sp_converged = frequency_result.get("converged")
        sp_cycles = frequency_result.get("cycles")
        _update_checkpoint_scf(
            stage_context.get("checkpoint_path"),
            pyscf_chkfile=stage_context.get("pyscf_chkfile"),
            scf_energy=energy,
            scf_converged=sp_converged,
        )

        imaginary_count = frequency_result.get("imaginary_count")
        ts_quality_enforced = _is_ts_quality_enforced(stage_context.get("ts_quality"))
        irc_status = "skipped"
        irc_skip_reason = None
        if irc_enabled:
            expected_imaginary = (
                1 if stage_context["optimizer_mode"] == "transition_state" else 0
            )
            if imaginary_count is None:
                if ts_quality_enforced:
                    irc_skip_reason = (
                        "Imaginary frequency count unavailable; skipping IRC."
                    )
                    logging.warning("Skipping IRC: %s", irc_skip_reason)
                else:
                    logging.warning(
                        "Imaginary frequency count unavailable; proceeding with IRC "
                        "because ts_quality.enforce is false."
                    )
                    irc_status = "pending"
            else:
                allow_irc = ts_quality_result.get("allow_irc")
                if (
                    stage_context["optimizer_mode"] == "transition_state"
                    and allow_irc is not None
                ):
                    if not allow_irc:
                        message = ts_quality_result.get("message") or (
                            "TS quality checks did not pass."
                        )
                        if ts_quality_enforced:
                            irc_skip_reason = message
                            logging.warning("Skipping IRC: %s", irc_skip_reason)
                        else:
                            logging.warning(
                                "TS quality checks did not pass; proceeding with IRC "
                                "because ts_quality.enforce is false. %s",
                                message,
                            )
                            irc_status = "pending"
                    else:
                        irc_status = "pending"
                elif imaginary_count != expected_imaginary:
                    if ts_quality_enforced:
                        irc_skip_reason = (
                            "Imaginary frequency count does not match expected "
                            f"{expected_imaginary}."
                        )
                        logging.warning("Skipping IRC: %s", irc_skip_reason)
                    else:
                        logging.warning(
                            "Imaginary frequency count does not match expected %s; "
                            "proceeding with IRC because ts_quality.enforce is false.",
                            expected_imaginary,
                        )
                        irc_status = "pending"
                else:
                    irc_status = "pending"
        else:
            irc_skip_reason = "IRC calculation disabled."

        run_single_point = False
        sp_status = "skipped"
        sp_skip_reason = None
        if single_point_enabled:
            expected_imaginary = (
                1 if stage_context["optimizer_mode"] == "transition_state" else 0
            )
            if imaginary_count is None:
                if ts_quality_enforced:
                    logging.warning(
                        "Skipping single-point calculation because imaginary "
                        "frequency count is unavailable."
                    )
                    sp_skip_reason = "Imaginary frequency count unavailable."
                else:
                    logging.warning(
                        "Imaginary frequency count unavailable; proceeding with "
                        "single-point because ts_quality.enforce is false."
                    )
                    run_single_point = True
            elif stage_context["optimizer_mode"] == "transition_state":
                allow_sp = ts_quality_result.get("allow_single_point")
                if allow_sp is None:
                    allow_sp = imaginary_count == expected_imaginary
                if allow_sp:
                    run_single_point = True
                else:
                    message = ts_quality_result.get("message") or (
                        "TS quality checks did not pass."
                    )
                    if ts_quality_enforced:
                        logging.warning(
                            "Skipping single-point calculation due to TS quality checks."
                        )
                        sp_skip_reason = message
                    else:
                        logging.warning(
                            "TS quality checks did not pass; proceeding with "
                            "single-point because ts_quality.enforce is false. %s",
                            message,
                        )
                        run_single_point = True
            elif imaginary_count == expected_imaginary:
                run_single_point = True
            else:
                if ts_quality_enforced:
                    logging.warning(
                        "Skipping single-point calculation because imaginary "
                        "frequency count %s does not match expected %s.",
                        imaginary_count,
                        expected_imaginary,
                    )
                    sp_skip_reason = (
                        "Imaginary frequency count does not match expected "
                        f"{expected_imaginary}."
                    )
                else:
                    logging.warning(
                        "Imaginary frequency count %s does not match expected %s; "
                        "proceeding with single-point because ts_quality.enforce is "
                        "false.",
                        imaginary_count,
                        expected_imaginary,
                    )
                    run_single_point = True
        else:
            logging.info("Skipping single-point energy calculation (disabled).")
            sp_skip_reason = "Single-point calculation disabled."

        if run_single_point:
            sp_status = "executed"
            sp_skip_reason = None

        if isinstance(calculation_metadata.get("single_point"), dict):
            calculation_metadata["single_point"]["status"] = sp_status
            calculation_metadata["single_point"]["skip_reason"] = sp_skip_reason
        calculation_metadata["irc"] = {
            "status": irc_status,
            "skip_reason": irc_skip_reason,
            "output_file": stage_context.get("irc_output_path"),
        }
        frequency_payload["single_point"] = {
            "status": sp_status,
            "skip_reason": sp_skip_reason,
        }
        with open(
            stage_context["frequency_output_path"], "w", encoding="utf-8"
        ) as handle:
            json.dump(frequency_payload, handle, indent=2)

        if irc_status == "pending":
            logging.info("Running IRC for frequency geometry...")
            irc_steps = 10
            irc_step_size = 0.05
            irc_force_threshold = 0.01
            irc_config = stage_context.get("irc_config")
            if irc_config:
                if irc_config.steps is not None:
                    irc_steps = irc_config.steps
                if irc_config.step_size is not None:
                    irc_step_size = irc_config.step_size
                if irc_config.force_threshold is not None:
                    irc_force_threshold = irc_config.force_threshold
            try:
                mode_result = compute_imaginary_mode(
                    stage_context["mol"],
                    stage_context["calc_basis"],
                    stage_context["calc_xc"],
                    stage_context["calc_scf_config"],
                    stage_context["calc_solvent_model"]
                    if stage_context["calc_solvent_name"]
                    else None,
                    stage_context["calc_solvent_name"],
                    stage_context["calc_eps"],
                    stage_context["verbose"],
                    stage_context["memory_mb"],
                    dispersion=stage_context["calc_dispersion_model"],
                    dispersion_hessian_step=stage_context.get("freq_dispersion_step"),
                    constraints=stage_context.get("constraints"),
                    dispersion_params=_resolve_d3_params(
                        stage_context.get("optimizer_ase_config")
                    ),
                    run_dir=stage_context["run_dir"],
                    optimizer_mode=stage_context["optimizer_mode"],
                    multiplicity=stage_context["multiplicity"],
                    profiling_enabled=profiling_enabled,
                    return_hessian=True,
                )
                if mode_result.get("eigenvalue", 0.0) >= 0:
                    logging.warning(
                        "IRC mode eigenvalue is non-negative (%.6f); "
                        "structure may not be a first-order saddle point.",
                        mode_result.get("eigenvalue", 0.0),
                    )
                irc_stage_context = dict(stage_context)
                irc_stage_context.update(
                    {
                        "mode_vector": mode_result["mode"],
                        "mode_hessian": mode_result.get("hessian"),
                        "mode_eigenvalue": mode_result.get("eigenvalue"),
                        "mode_profiling": mode_result.get("profiling")
                        if profiling_enabled
                        else None,
                        "irc_steps": irc_steps,
                        "irc_step_size": irc_step_size,
                        "irc_force_threshold": irc_force_threshold,
                    }
                )
                irc_payload = run_irc_stage(
                    irc_stage_context,
                    queue_update_fn,
                    finalize=False,
                    update_summary=False,
                )
                if irc_payload is not None:
                    calculation_metadata["irc"] = irc_payload
            except Exception as exc:
                logging.exception("IRC calculation failed.")
                irc_payload = {
                    "status": "failed",
                    "output_file": stage_context.get("irc_output_path"),
                    "steps": irc_steps,
                    "step_size": irc_step_size,
                    "force_threshold": irc_force_threshold,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                calculation_metadata["irc"] = irc_payload
                if stage_context.get("irc_output_path"):
                    with open(
                        stage_context["irc_output_path"], "w", encoding="utf-8"
                    ) as handle:
                        json.dump(irc_payload, handle, indent=2)
        elif irc_status == "skipped":
            logging.info("Skipping IRC calculation.")

        if run_single_point:
            logging.info("Calculating single-point energy after frequency...")
            try:
                sp_result = compute_single_point_energy(
                    stage_context["mol"],
                    stage_context["calc_basis"],
                    stage_context["calc_xc"],
                    stage_context["calc_scf_config"],
                    stage_context["calc_solvent_model"],
                    stage_context["calc_solvent_name"],
                    stage_context["calc_eps"],
                    stage_context["calc_dispersion_model"],
                    _resolve_d3_params(stage_context.get("optimizer_ase_config")),
                    stage_context["verbose"],
                    stage_context["memory_mb"],
                    run_dir=stage_context["run_dir"],
                    optimizer_mode=stage_context["optimizer_mode"],
                    multiplicity=stage_context["multiplicity"],
                    log_override=False,
                    profiling_enabled=profiling_enabled,
                )
                if isinstance(calculation_metadata.get("single_point"), dict):
                    calculation_metadata["single_point"][
                        "dispersion_info"
                    ] = sp_result.get("dispersion")
                    if profiling_enabled and sp_result.get("profiling") is not None:
                        calculation_metadata["single_point"]["profiling"] = sp_result.get(
                            "profiling"
                        )
                _update_checkpoint_scf(
                    stage_context.get("checkpoint_path"),
                    pyscf_chkfile=stage_context.get("pyscf_chkfile"),
                    scf_energy=sp_result.get("energy"),
                    scf_converged=sp_result.get("converged"),
                )
            except Exception:
                logging.exception("Single-point calculation failed.")
                sp_result = None
        elif single_point_enabled:
            logging.info("Skipping single-point energy calculation.")

        final_energy = energy
        final_sp_energy = energy
        final_sp_converged = sp_converged
        final_sp_cycles = sp_cycles
        scf_converged = sp_converged
        if sp_result:
            final_sp_energy = sp_result.get("energy")
            final_sp_converged = sp_result.get("converged")
            final_sp_cycles = sp_result.get("cycles") or sp_cycles
            if final_sp_energy is not None:
                final_energy = final_sp_energy
            scf_converged = final_sp_converged
        summary = {
            "elapsed_seconds": time.perf_counter() - run_start,
            "n_steps": sp_cycles,
            "final_energy": final_energy,
            "opt_final_energy": energy,
            "final_sp_energy": final_sp_energy,
            "final_sp_converged": final_sp_converged,
            "final_sp_cycles": final_sp_cycles,
            "scf_converged": scf_converged,
            "opt_converged": None,
            "converged": bool(scf_converged) if scf_converged is not None else True,
        }
        calculation_metadata["summary"] = summary
        calculation_metadata["summary"]["memory_limit_enforced"] = stage_context[
            "memory_limit_enforced"
        ]
        export_qcschema_result(
            stage_context.get("qcschema_output_path"),
            calculation_metadata,
            stage_context.get("input_xyz"),
            geometry_xyz=stage_context.get("input_xyz"),
            frequency_payload=frequency_payload,
            irc_payload=irc_payload,
            sp_result=sp_result,
        )
        finalize_metadata(
            stage_context["run_metadata_path"],
            stage_context["event_log_path"],
            stage_context["run_id"],
            stage_context["run_dir"],
            calculation_metadata,
            status="completed",
            previous_status="running",
            queue_update_fn=queue_update_fn,
            exit_code=0,
        )
    except Exception as exc:
        logging.exception("Calculation failed.")
        finalize_metadata(
            stage_context["run_metadata_path"],
            stage_context["event_log_path"],
            stage_context["run_id"],
            stage_context["run_dir"],
            calculation_metadata,
            status="failed",
            previous_status="running",
            queue_update_fn=queue_update_fn,
            exit_code=1,
            details={"error": str(exc)},
            error=exc,
        )
        raise
