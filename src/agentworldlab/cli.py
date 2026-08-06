"""AgentWorldLab command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any

from agentworldlab.config import AppConfig, load_config
from agentworldlab.controller import WorkerClient
from agentworldlab.errors import AgentWorldLabError, ConfigurationError, RequestTimeoutError
from agentworldlab.evaluation import evaluate_trajectory, evaluate_transition
from agentworldlab.fixtures import load_fixture, render_prompt
from agentworldlab.inspection import inspect_host, inspect_model_metadata, tokenizer_probe
from agentworldlab.metrics import GIB, memory_sample
from agentworldlab.records import new_record, parse_observation, write_record


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "default.toml"
DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "terminal" / "single-transition-v1.json"


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _config(args: argparse.Namespace) -> AppConfig:
    return load_config(args.config)


def command_inspect_host(args: argparse.Namespace) -> int:
    config = _config(args)
    _json(inspect_host(config.thermal))
    return 0


def command_inspect_model(args: argparse.Namespace) -> int:
    config = _config(args)
    _json(inspect_model_metadata(config.model(args.model)))
    return 0


def command_tokenizer(args: argparse.Namespace) -> int:
    config = _config(args)
    fixture = load_fixture(args.fixture)
    prompt = render_prompt(fixture, args.action)
    _json(tokenizer_probe(config.model(args.model), prompt))
    return 0


def _wait_until_idle(client: WorkerClient, config: AppConfig) -> bool:
    deadline = time.monotonic() + config.runtime.unload_timeout_seconds
    while time.monotonic() < deadline:
        try:
            health = client.request("health", {}, config.runtime.request_timeout_seconds)
            if health.get("state") != "busy":
                return True
        except AgentWorldLabError:
            return False
        time.sleep(0.25)
    return False


def command_run(args: argparse.Namespace) -> int:
    config = _config(args)
    model = config.model(args.model)
    fixture = load_fixture(args.fixture)
    prompt = render_prompt(fixture, args.action)
    record = new_record(model=model, fixture=fixture, cold_run=not args.warm)
    record["memory"]["initial"] = memory_sample().to_dict()
    client = WorkerClient(config)
    exit_code = 1
    load_result: dict[str, Any] | None = None
    try:
        client.start()
        load_result = client.request(
            "load", {"model": args.model}, config.runtime.load_timeout_seconds
        )
        record["run"]["load_seconds"] = load_result.get("total_load_seconds")
        load_thermal = load_result.get("thermal", {})
        record["thermal"].update({
            "peak_celsius": load_thermal.get("peak_celsius"),
            "caution_observed": load_thermal.get("caution_observed", False),
            "cancelled": load_thermal.get("cancellation_requested", False),
            "hard_termination": load_thermal.get("hard_termination_requested", False),
            "telemetry_available": load_thermal.get("telemetry_available", False),
        })
        run_result = client.request(
            "run",
            {
                "prompt": prompt,
                "max_input_tokens": args.max_input_tokens or model.max_context_tokens,
                "max_output_tokens": args.max_output_tokens or model.max_output_tokens,
                "temperature": args.temperature,
                "seed": args.seed,
            },
            config.runtime.generation_timeout_seconds,
        )
        run = record["run"]
        run["input_tokens"] = run_result.get("input_tokens")
        run["generated_tokens"] = run_result.get("output_tokens")
        run["tokenizer_preprocessing_seconds"] = run_result.get("preprocessing_seconds")
        run["prompt_prefill_seconds"] = run_result.get("prefill_seconds")
        run["text_generation_seconds"] = run_result.get("decode_seconds")
        run["total_seconds"] = run_result.get("total_seconds")
        decode_for_rate = run["text_generation_seconds"] or run_result.get("generation_seconds")
        if run["generated_tokens"] and decode_for_rate:
            run["tokens_per_second"] = run["generated_tokens"] / decode_for_rate
        thermal = run_result.get("thermal", {})
        generation_peak = thermal.get("peak_celsius")
        load_peak = record["thermal"].get("peak_celsius")
        peaks = [value for value in (load_peak, generation_peak) if isinstance(value, (int, float))]
        record["thermal"].update({
            "peak_celsius": max(peaks) if peaks else None,
            "caution_observed": record["thermal"]["caution_observed"] or thermal.get("caution_observed", False),
            "cancelled": record["thermal"]["cancelled"] or thermal.get("cancellation_requested", False),
            "hard_termination": record["thermal"]["hard_termination"] or thermal.get("hard_termination_requested", False),
            "telemetry_available": record["thermal"]["telemetry_available"] or thermal.get("telemetry_available", False),
        })
        record["memory"]["peak"] = {
            "minimum_system_available_bytes": thermal.get("minimum_system_available_bytes"),
            "maximum_gpu_used_bytes": thermal.get("maximum_gpu_used_bytes"),
            "maximum_process_rss_bytes": thermal.get("maximum_process_rss_bytes"),
        }
        raw = run_result.get("raw_output", "")
        record["outcome"].update({
            "completion_status": "cancelled" if run_result.get("cancelled") else "completed",
            "raw_output": raw,
            "parsed_observation": parse_observation(raw),
        })
        record["evaluation"] = evaluate_transition(fixture, raw)
        exit_code = (
            0
            if raw and not run_result.get("cancelled") and record["evaluation"]["automated_pass"]
            else 1
        )
    except RequestTimeoutError as exc:
        record["outcome"].update({
            "completion_status": "timeout",
            "timeout": True,
            "error_category": exc.category,
            "error_message": str(exc),
        })
        try:
            client.cancel()
            if not _wait_until_idle(client, config):
                client.terminate()
        except AgentWorldLabError:
            client.terminate()
    except AgentWorldLabError as exc:
        details = exc.details()
        if details["category"] == "thermal_hard_stop":
            record["thermal"].update({"hard_termination": True, "cancelled": True})
        record["outcome"].update({
            "completion_status": "failed",
            "error_category": details["category"],
            "error_message": details["message"],
        })
    except KeyboardInterrupt:
        exit_code = 130
        record["outcome"].update({
            "completion_status": "cancelled",
            "error_category": "cancelled",
            "error_message": "interrupted by user",
        })
        try:
            client.cancel()
            if not _wait_until_idle(client, config):
                client.terminate()
        except AgentWorldLabError:
            client.terminate()
    except Exception as exc:
        record["outcome"].update({
            "completion_status": "failed",
            "error_category": "internal_error",
            "error_message": f"{type(exc).__name__}: {exc}",
        })
    finally:
        if client.process is not None and client.process.poll() is None:
            try:
                unload = client.request("unload", {}, config.runtime.unload_timeout_seconds)
                record["memory"]["after_unload"] = unload.get("memory_after")
            except AgentWorldLabError:
                client.terminate()
        client.stop()
        initial = record["memory"].get("initial") or {}
        after = record["memory"].get("after_unload") or {}
        initial_available = initial.get("system_available_bytes")
        after_available = after.get("system_available_bytes")
        if isinstance(initial_available, int) and isinstance(after_available, int):
            tolerance = config.runtime.memory_recovery_tolerance_gib * GIB
            record["memory"]["recovered_within_tolerance"] = after_available + tolerance >= initial_available
        paths = write_record(record, config.runtime.records_directory)
    _json({"record": str(paths[0]), "summary": str(paths[1]), "outcome": record["outcome"]})
    return exit_code


def command_trajectory(args: argparse.Namespace) -> int:
    config = _config(args)
    model = config.model(args.model)
    fixture = load_fixture(args.fixture)
    actions = fixture.get("actions")
    if not isinstance(actions, list) or not 5 <= len(actions) <= 10 or not all(
        isinstance(action, str) and action.strip() for action in actions
    ):
        raise ConfigurationError("trajectory fixture must contain five to ten non-empty actions")
    record = new_record(model=model, fixture=fixture, cold_run=not args.warm)
    record["memory"]["initial"] = memory_sample().to_dict()
    record["trajectory"] = []
    client = WorkerClient(config)
    exit_code = 1
    try:
        client.start()
        loaded = client.request("load", {"model": args.model}, config.runtime.load_timeout_seconds)
        record["run"]["load_seconds"] = loaded.get("total_load_seconds")
        history: list[dict[str, str]] = []
        raw_outputs: list[str] = []
        total_input = total_output = 0
        total_time = total_generation = total_prefill = total_preprocessing = 0.0
        peak_temperatures: list[float] = []
        load_peak = loaded.get("thermal", {}).get("peak_celsius")
        if isinstance(load_peak, (int, float)):
            peak_temperatures.append(float(load_peak))
        for index, action in enumerate(actions, start=1):
            transition_fixture = dict(fixture)
            transition_fixture["history"] = list(history)
            prompt = render_prompt(transition_fixture, action)
            result = client.request(
                "run",
                {
                    "prompt": prompt,
                    "max_input_tokens": args.max_input_tokens or model.max_context_tokens,
                    "max_output_tokens": args.max_output_tokens or model.max_output_tokens,
                    "temperature": args.temperature,
                    "seed": args.seed,
                },
                config.runtime.generation_timeout_seconds,
            )
            raw = str(result.get("raw_output", ""))
            raw_outputs.append(raw)
            parsed = parse_observation(raw)
            record["trajectory"].append({
                "turn": index,
                "action": action,
                "raw_output": raw,
                "parsed_observation": parsed,
                "input_tokens": result.get("input_tokens"),
                "generated_tokens": result.get("output_tokens"),
                "total_seconds": result.get("total_seconds"),
            })
            history.extend([
                {"role": "agent", "content": action},
                {"role": "environment", "content": raw},
            ])
            total_input += int(result.get("input_tokens") or 0)
            total_output += int(result.get("output_tokens") or 0)
            total_time += float(result.get("total_seconds") or 0)
            total_generation += float(result.get("decode_seconds") or result.get("generation_seconds") or 0)
            total_prefill += float(result.get("prefill_seconds") or 0)
            total_preprocessing += float(result.get("preprocessing_seconds") or 0)
            peak = result.get("thermal", {}).get("peak_celsius")
            if isinstance(peak, (int, float)):
                peak_temperatures.append(float(peak))
            if result.get("cancelled"):
                raise AgentWorldLabError(f"trajectory was cancelled at turn {index}")
        record["run"].update({
            "input_tokens": total_input,
            "generated_tokens": total_output,
            "tokenizer_preprocessing_seconds": total_preprocessing,
            "prompt_prefill_seconds": total_prefill,
            "text_generation_seconds": total_generation,
            "total_seconds": total_time,
            "tokens_per_second": total_output / total_generation if total_generation else None,
        })
        record["thermal"]["peak_celsius"] = max(peak_temperatures) if peak_temperatures else None
        record["outcome"].update({
            "completion_status": "completed",
            "raw_output": raw_outputs,
            "parsed_observation": [parse_observation(output) for output in raw_outputs],
        })
        record["evaluation"] = evaluate_trajectory(fixture, raw_outputs)
        exit_code = 0 if record["evaluation"]["automated_pass"] else 1
    except RequestTimeoutError as exc:
        record["outcome"].update({
            "completion_status": "timeout", "timeout": True,
            "error_category": exc.category, "error_message": str(exc),
        })
        try:
            client.cancel()
            if not _wait_until_idle(client, config):
                client.terminate()
        except AgentWorldLabError:
            client.terminate()
    except AgentWorldLabError as exc:
        details = exc.details()
        if details["category"] == "thermal_hard_stop":
            record["thermal"].update({"hard_termination": True, "cancelled": True})
        record["outcome"].update({
            "completion_status": "failed",
            "error_category": details["category"],
            "error_message": details["message"],
        })
    except KeyboardInterrupt:
        exit_code = 130
        record["outcome"].update({
            "completion_status": "cancelled",
            "error_category": "cancelled",
            "error_message": "interrupted by user",
        })
        try:
            client.cancel()
            if not _wait_until_idle(client, config):
                client.terminate()
        except AgentWorldLabError:
            client.terminate()
    except Exception as exc:
        record["outcome"].update({
            "completion_status": "failed",
            "error_category": "internal_error",
            "error_message": f"{type(exc).__name__}: {exc}",
        })
    finally:
        if client.process is not None and client.process.poll() is None:
            try:
                unloaded = client.request("unload", {}, config.runtime.unload_timeout_seconds)
                record["memory"]["after_unload"] = unloaded.get("memory_after")
            except AgentWorldLabError:
                client.terminate()
        client.stop()
        initial = record["memory"].get("initial") or {}
        after = record["memory"].get("after_unload") or {}
        if isinstance(initial.get("system_available_bytes"), int) and isinstance(
            after.get("system_available_bytes"), int
        ):
            record["memory"]["recovered_within_tolerance"] = (
                after["system_available_bytes"]
                + config.runtime.memory_recovery_tolerance_gib * GIB
                >= initial["system_available_bytes"]
            )
        paths = write_record(record, config.runtime.records_directory)
    _json({"record": str(paths[0]), "summary": str(paths[1]), "outcome": record["outcome"]})
    return exit_code


def command_worker(args: argparse.Namespace) -> int:
    from agentworldlab.worker import serve

    return serve(_config(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentworldlab",
        description="Safely evaluate a model as an environment simulator",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to the TOML configuration")
    commands = parser.add_subparsers(dest="command", required=True)

    host = commands.add_parser("inspect-host", help="report read-only host compatibility data")
    host.set_defaults(function=command_inspect_host)

    model = commands.add_parser("inspect-model", help="inspect a pinned local snapshot without loading weights")
    model.add_argument("--model", default="agentworld")
    model.set_defaults(function=command_inspect_model)

    tokenizer = commands.add_parser("probe-tokenizer", help="load only the processor and render a fixture")
    tokenizer.add_argument("--model", default="agentworld")
    tokenizer.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    tokenizer.add_argument("--action")
    tokenizer.set_defaults(function=command_tokenizer)

    run = commands.add_parser("run", help="load, run one synthetic transition, record, and unload")
    run.add_argument("--model", default="mock")
    run.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    run.add_argument("--action")
    run.add_argument("--max-input-tokens", type=int)
    run.add_argument("--max-output-tokens", type=int)
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--warm", action="store_true", help="label this as a warm run")
    run.set_defaults(function=command_run)

    trajectory = commands.add_parser(
        "run-trajectory", help="run a fixed five-to-ten-turn synthetic trajectory"
    )
    trajectory.add_argument("--model", default="mock")
    trajectory.add_argument(
        "--fixture", default=str(DEFAULT_FIXTURE.parent / "stateful-trajectory-v1.json")
    )
    trajectory.add_argument("--max-input-tokens", type=int)
    trajectory.add_argument("--max-output-tokens", type=int)
    trajectory.add_argument("--temperature", type=float, default=0.0)
    trajectory.add_argument("--seed", type=int, default=0)
    trajectory.add_argument("--warm", action="store_true")
    trajectory.set_defaults(function=command_trajectory)

    worker = commands.add_parser("worker", help="serve the JSON Lines protocol on stdin/stdout")
    worker.set_defaults(function=command_worker)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.function(args))
    except AgentWorldLabError as exc:
        _json({"error": exc.details()})
        return 2
    except KeyboardInterrupt:
        _json({"error": {"category": "cancelled", "message": "interrupted by user"}})
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
