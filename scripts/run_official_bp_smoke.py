#!/usr/bin/env python3
"""Run a very small official EoH online bin packing smoke test.

This wrapper keeps upstream code in EoH/ unchanged while patching the
network client so OpenRouter-style base URLs work.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

TRACE_CONTEXT = threading.local()

PREDEFINED_BASELINES: dict[str, str] = {
    "first_fit": """import numpy as np

def score(item, bins):
    scores = -np.arange(bins.shape[0], dtype=np.float64)
    return scores
""",
    "best_fit": """import numpy as np

def score(item, bins):
    after = bins - item
    return -after.astype(np.float64)
""",
    "tight_fit": """import numpy as np

def score(item, bins):
    after = bins - item
    exact = (after == 0).astype(np.float64) * 1000.0
    return exact - after.astype(np.float64)
""",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base-url",
        default="https://openrouter.ai/api/v1",
        help="Chat completions base URL. Example: https://openrouter.ai/api/v1",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENROUTER_API_KEY",
        help="Environment variable containing the API key.",
    )
    parser.add_argument(
        "--model",
        default="openai/gpt-3.5-turbo",
        help="Model ID for the remote API.",
    )
    parser.add_argument("--pop-size", type=int, default=1)
    parser.add_argument("--n-pop", type=int, default=1)
    parser.add_argument("--n-proc", type=int, default=1)
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Truncate each official bp_online instance to this many items for faster runs.",
    )
    parser.add_argument(
        "--output-dir",
        default="results/official_smoke",
        help="Directory where EoH should write its results/ subfolder.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable upstream debug prints. Avoid for unattended runs.",
    )
    parser.add_argument(
        "--log-responses",
        action="store_true",
        help="Save full parsed response bodies in request trace files.",
    )
    parser.add_argument(
        "--quiet-progress",
        action="store_true",
        help="Reduce wrapper progress logs and rely on upstream output plus JSON traces.",
    )
    parser.add_argument(
        "--no-force-exit",
        action="store_true",
        help="Do not force the process to exit after completion. Useful only for debugging shutdown behavior.",
    )
    return parser.parse_args()


def normalize_chat_url(api_base_url: str) -> str:
    base = api_base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def console_log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[wrapper {stamp}] {message}", flush=True)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def format_objective(value: Any) -> str:
    if value is None:
        return "None"
    try:
        return f"{float(value):.5f}"
    except (TypeError, ValueError):
        return str(value)


def build_trace_paths(out_dir: Path) -> dict[str, Path]:
    trace_dir = out_dir / "llm_traces"
    return {
        "trace_dir": trace_dir,
        "requests_dir": trace_dir / "requests",
        "summary_path": trace_dir / "llm_summary.json",
        "diagnostics_dir": trace_dir / "diagnostics",
    }


def summarize_traces(requests_dir: Path) -> dict[str, Any]:
    files = sorted(requests_dir.glob("*.json"))
    total_requests = 0
    successful_requests = 0
    failed_requests = 0
    total_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    models: dict[str, int] = {}
    latest_request = None

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        total_requests += 1
        model = payload.get("model") or "unknown"
        models[model] = models.get(model, 0) + 1
        if payload.get("ok"):
            successful_requests += 1
        else:
            failed_requests += 1

        usage = payload.get("usage") or {}
        total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
        total_completion_tokens += int(usage.get("completion_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)

        cost = payload.get("cost")
        if cost is not None:
            try:
                total_cost += float(cost)
            except (TypeError, ValueError):
                pass
        latest_request = payload.get("finished_at") or payload.get("started_at") or latest_request

    return {
        "updated_at": utc_now(),
        "request_files": len(files),
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "models": models,
        "latest_request": latest_request,
    }


def summarize_text(text: Any, limit: int = 1200) -> Any:
    if not isinstance(text, str):
        return text
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def persist_event(target_dir: Path, payload: dict[str, Any]) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    unique = f"{stamp}_pid{os.getpid()}_tid{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
    path = target_dir / f"{unique}.json"
    write_json(path, payload)
    return path


def patch_upstream_client(chat_url: str, out_dir: Path, log_responses: bool, quiet_progress: bool) -> None:
    from eoh.llm import api_general
    from eoh.llm import interface_LLM

    trace_paths = build_trace_paths(out_dir)
    trace_paths["requests_dir"].mkdir(parents=True, exist_ok=True)

    def persist_trace(payload: dict[str, Any]) -> None:
        trace_file = persist_event(trace_paths["requests_dir"], payload)
        TRACE_CONTEXT.last_llm_trace_path = str(trace_file)
        TRACE_CONTEXT.last_llm_trace = payload
        write_json(trace_paths["summary_path"], summarize_traces(trace_paths["requests_dir"]))

    class PatchedInterfaceAPI:
        def __init__(self, api_endpoint: str, api_key: str, model_LLM: str, debug_mode: bool):
            self.api_endpoint = api_endpoint
            self.api_key = api_key
            self.model_LLM = model_LLM
            self.debug_mode = debug_mode
            self.n_trial = 5

        def get_response(self, prompt_content: str) -> str | None:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model_LLM,
                "messages": [{"role": "user", "content": prompt_content}],
            }
            response_text = None
            for trial in range(1, self.n_trial + 1):
                started_at = utc_now()
                t0 = time.time()
                if not quiet_progress:
                    console_log(
                        f"LLM request start: trial={trial} prompt_chars={len(prompt_content)}"
                    )
                trace_payload: dict[str, Any] = {
                    "started_at": started_at,
                    "model": self.model_LLM,
                    "api_endpoint": self.api_endpoint,
                    "chat_url": chat_url,
                    "trial": trial,
                    "pid": os.getpid(),
                    "thread_id": threading.get_ident(),
                    "prompt_text": prompt_content,
                    "request": payload,
                }
                try:
                    response = requests.post(
                        chat_url,
                        headers=headers,
                        json=payload,
                        timeout=90,
                    )
                    elapsed_s = time.time() - t0
                    trace_payload["http_status"] = response.status_code
                    trace_payload["elapsed_s"] = round(elapsed_s, 4)
                    trace_payload["finished_at"] = utc_now()
                    trace_payload["response_body_text"] = response.text
                    data = response.json()
                    trace_payload["ok"] = response.ok
                    trace_payload["response_id"] = data.get("id")
                    trace_payload["provider"] = data.get("provider")
                    trace_payload["usage"] = data.get("usage")
                    trace_payload["cost"] = (data.get("usage") or {}).get("cost")
                    trace_payload["choices_count"] = len(data.get("choices") or [])
                    if log_responses:
                        trace_payload["response_json"] = data
                    response.raise_for_status()
                    response_text = data["choices"][0]["message"]["content"]
                    trace_payload["response_text"] = response_text
                    persist_trace(trace_payload)
                    if not quiet_progress:
                        usage = trace_payload.get("usage") or {}
                        cost = trace_payload.get("cost")
                        total_tokens = usage.get("total_tokens")
                        console_log(
                            "LLM request done: "
                            f"status={response.status_code} elapsed={trace_payload['elapsed_s']}s "
                            f"tokens={total_tokens if total_tokens is not None else '?'} "
                            f"cost={float(cost):.4f}" if cost is not None else "cost=?"
                        )
                    break
                except Exception as exc:
                    trace_payload["ok"] = False
                    trace_payload["finished_at"] = utc_now()
                    trace_payload["elapsed_s"] = round(time.time() - t0, 4)
                    trace_payload["error"] = f"{type(exc).__name__}: {exc}"
                    response_obj = locals().get("response")
                    if response_obj is not None:
                        trace_payload["http_status"] = getattr(response_obj, "status_code", None)
                        trace_payload["response_body_text"] = getattr(response_obj, "text", None)
                    persist_trace(trace_payload)
                    if not quiet_progress:
                        console_log(
                            f"LLM request failed: trial={trial} error={type(exc).__name__}: {exc}"
                        )
                    if self.debug_mode:
                        print("Error in API. Restarting the process...")
                    continue
            return response_text

    api_general.InterfaceAPI = PatchedInterfaceAPI
    interface_LLM.InterfaceAPI = PatchedInterfaceAPI


def patch_failure_diagnostics(out_dir: Path, quiet_progress: bool) -> None:
    import concurrent.futures
    import sys
    import types
    import warnings

    import numpy as np

    from eoh.methods.eoh import eoh as eoh_method
    from eoh.methods.eoh import eoh_evolution
    from eoh.methods.eoh import eoh_interface_EC
    from eoh.problems.optimization.bp_online import run as bp_run

    trace_paths = build_trace_paths(out_dir)
    diagnostics_dir = trace_paths["diagnostics_dir"]
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    def persist_diagnostic(payload: dict[str, Any]) -> str:
        path = persist_event(diagnostics_dir, payload)
        return str(path)

    def parse_response(response: str) -> tuple[list[str], list[str]]:
        algorithm = re.findall(r"\{(.*)\}", response, re.DOTALL)
        if len(algorithm) == 0:
            if "python" in response:
                algorithm = re.findall(r"^.*?(?=python)", response, re.DOTALL)
            elif "import" in response:
                algorithm = re.findall(r"^.*?(?=import)", response, re.DOTALL)
            else:
                algorithm = re.findall(r"^.*?(?=def)", response, re.DOTALL)

        code = re.findall(r"import.*return", response, re.DOTALL)
        if len(code) == 0:
            code = re.findall(r"def.*return", response, re.DOTALL)
        return algorithm, code

    def candidate_debug_snapshot(self: Any) -> dict[str, Any] | None:
        value = getattr(self, "_last_candidate_debug", None)
        return value if isinstance(value, dict) else None

    def patched_get_alg(self: Any, prompt_content: str) -> list[str]:
        attempts: list[dict[str, Any]] = []
        response = self.interface_llm.get_response(prompt_content)
        algorithm, code = parse_response(response or "")
        n_retry = 1

        while True:
            attempts.append(
                {
                    "attempt": len(attempts) + 1,
                    "llm_trace_path": getattr(TRACE_CONTEXT, "last_llm_trace_path", None),
                    "algorithm_matches": len(algorithm),
                    "code_matches": len(code),
                    "response_preview": summarize_text(response),
                }
            )
            if len(algorithm) > 0 and len(code) > 0:
                break
            if n_retry > 3:
                break
            n_retry += 1
            response = self.interface_llm.get_response(prompt_content)
            algorithm, code = parse_response(response or "")

        if len(algorithm) == 0 or len(code) == 0:
            diagnostic_path = persist_diagnostic(
                {
                    "timestamp": utc_now(),
                    "stage": "parse_failed",
                    "prompt_preview": summarize_text(prompt_content),
                    "attempts": attempts,
                    "final_response": summarize_text(response),
                }
            )
            if not quiet_progress:
                console_log(f"Parse failed for LLM response. Diagnostic saved to {diagnostic_path}")
            raise ValueError(f"Could not parse algorithm/code from LLM response. Diagnostic: {diagnostic_path}")

        algorithm_text = algorithm[0]
        code_text = code[0]
        code_all = code_text + " " + ", ".join(s for s in self.prompt_func_outputs)
        self._last_candidate_debug = {
            "timestamp": utc_now(),
            "prompt_preview": summarize_text(prompt_content),
            "algorithm_preview": summarize_text(algorithm_text),
            "code_preview": summarize_text(code_all),
            "attempts": attempts,
        }
        return [code_all, algorithm_text]

    def patched_evaluate(self: Any, code_string: str) -> float | None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                heuristic_module = types.ModuleType("heuristic_module")
                exec(code_string, heuristic_module.__dict__)
                sys.modules[heuristic_module.__name__] = heuristic_module
                if not hasattr(heuristic_module, "score"):
                    raise AttributeError("Generated code is missing score()")
                fitness = self.evaluateGreedy(heuristic_module)
                if fitness is None:
                    persist_diagnostic(
                        {
                            "timestamp": utc_now(),
                            "stage": "evaluation_returned_none",
                            "code_preview": summarize_text(code_string),
                        }
                    )
                    if not quiet_progress:
                        console_log("Evaluator returned None for generated heuristic")
                return fitness
        except Exception as exc:
            diagnostic_path = persist_diagnostic(
                {
                    "timestamp": utc_now(),
                    "stage": "evaluation_exception",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                    "code_preview": summarize_text(code_string),
                }
            )
            if not quiet_progress:
                console_log(f"Evaluator crashed on generated heuristic. Diagnostic saved to {diagnostic_path}")
            return None

    def patched_get_offspring(self: Any, pop: list[dict[str, Any]], operator: str) -> tuple[Any, dict[str, Any]]:
        p = None
        offspring = {
            "algorithm": None,
            "code": None,
            "objective": None,
            "other_inf": None,
        }
        diagnostic_base = {
            "timestamp": utc_now(),
            "operator": operator,
            "population_size_seen": len(pop),
        }
        try:
            if not quiet_progress:
                console_log(f"Operator {operator}: generating candidate from population size {len(pop)}")
            p, offspring = self._get_alg(pop, operator)
            candidate_debug = candidate_debug_snapshot(self.evol)

            if self.use_numba:
                pattern = r"def\s+(\w+)\s*\(.*\):"
                match = re.search(pattern, offspring["code"])
                if match is None:
                    diagnostic_path = persist_diagnostic(
                        {
                            **diagnostic_base,
                            "stage": "numba_function_parse_failed",
                            "candidate_debug": candidate_debug,
                            "code_preview": summarize_text(offspring["code"]),
                        }
                    )
                    raise ValueError(f"Could not identify generated function name. Diagnostic: {diagnostic_path}")
                function_name = match.group(1)
                code = eoh_interface_EC.add_numba_decorator(program=offspring["code"], function_name=function_name)
            else:
                code = offspring["code"]

            n_retry = 1
            while self.check_duplicate(pop, offspring["code"]):
                n_retry += 1
                p, offspring = self._get_alg(pop, operator)
                candidate_debug = candidate_debug_snapshot(self.evol)
                if self.use_numba:
                    pattern = r"def\s+(\w+)\s*\(.*\):"
                    match = re.search(pattern, offspring["code"])
                    if match is None:
                        break
                    function_name = match.group(1)
                    code = eoh_interface_EC.add_numba_decorator(program=offspring["code"], function_name=function_name)
                else:
                    code = offspring["code"]
                if n_retry > 1:
                    break

            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(self.interface_eval.evaluate, code)
            try:
                fitness = future.result(timeout=self.timeout)
            except concurrent.futures.TimeoutError:
                diagnostic_path = persist_diagnostic(
                    {
                        **diagnostic_base,
                        "stage": "evaluation_timeout",
                        "timeout_s": self.timeout,
                        "candidate_debug": candidate_debug,
                        "algorithm_preview": summarize_text(offspring.get("algorithm")),
                        "code_preview": summarize_text(offspring.get("code")),
                    }
                )
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                offspring["objective"] = None
                if not quiet_progress:
                    console_log(
                        f"Operator {operator}: evaluation timed out after {self.timeout}s. "
                        f"Diagnostic saved to {diagnostic_path}"
                    )
                return p, offspring
            finally:
                if not future.cancelled():
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)

            if fitness is None:
                diagnostic_path = persist_diagnostic(
                    {
                        **diagnostic_base,
                        "stage": "objective_none",
                        "candidate_debug": candidate_debug,
                        "algorithm_preview": summarize_text(offspring.get("algorithm")),
                        "code_preview": summarize_text(offspring.get("code")),
                    }
                )
                offspring["objective"] = None
                if not quiet_progress:
                    console_log(f"Operator {operator}: objective=None. Diagnostic saved to {diagnostic_path}")
            else:
                offspring["objective"] = np.round(fitness, 5)
                if not quiet_progress:
                    console_log(f"Operator {operator}: objective={offspring['objective']}")

        except Exception as exc:
            diagnostic_path = persist_diagnostic(
                {
                    **diagnostic_base,
                    "stage": "get_offspring_exception",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                    "candidate_debug": candidate_debug_snapshot(self.evol),
                    "algorithm_preview": summarize_text(offspring.get("algorithm")),
                    "code_preview": summarize_text(offspring.get("code")),
                }
            )
            if not quiet_progress:
                console_log(
                    f"Operator {operator}: generation/evaluation failed. Diagnostic saved to {diagnostic_path}"
                )
            offspring = {
                "algorithm": offspring.get("algorithm"),
                "code": offspring.get("code"),
                "objective": None,
                "other_inf": None,
            }
            p = None

        return p, offspring

    def patched_get_algorithm(self: Any, pop: list[dict[str, Any]], operator: str) -> tuple[list[Any], list[dict[str, Any]]]:
        worker_count = max(1, min(int(self.n_p), int(self.pop_size)))
        if not quiet_progress and worker_count > 1:
            console_log(
                f"Operator {operator}: launching {self.pop_size} candidates with {worker_count} worker threads"
            )

        results: list[tuple[Any, dict[str, Any]]] = []
        if worker_count == 1:
            for _ in range(self.pop_size):
                results.append(self.get_offspring(pop, operator))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(self.get_offspring, pop, operator) for _ in range(self.pop_size)]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        diagnostic_path = persist_diagnostic(
                            {
                                "timestamp": utc_now(),
                                "stage": "threaded_get_algorithm_exception",
                                "operator": operator,
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(),
                            }
                        )
                        if not quiet_progress:
                            console_log(
                                f"Operator {operator}: threaded worker failed. Diagnostic saved to {diagnostic_path}"
                            )
                        results.append(
                            (
                                None,
                                {
                                    "algorithm": None,
                                    "code": None,
                                    "objective": None,
                                    "other_inf": None,
                                },
                            )
                        )

        out_p = []
        out_off = []
        for p, off in results:
            out_p.append(p)
            out_off.append(off)
            if self.debug:
                print(f">>> check offsprings: \n {off}")
        return out_p, out_off

    def patched_run(self: Any) -> None:
        try:
            return original_run(self)
        except IndexError as exc:
            population_path = Path(self.output_path) / "results" / "pops"
            latest_population = None
            if population_path.exists():
                candidates = sorted(population_path.glob("population_generation_*.json"))
                latest_population = str(candidates[-1]) if candidates else None
            diagnostic_path = persist_diagnostic(
                {
                    "timestamp": utc_now(),
                    "stage": "population_empty_crash",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                    "latest_population_file": latest_population,
                }
            )
            if not quiet_progress:
                console_log(f"Population became empty. Diagnostic saved to {diagnostic_path}")
            raise RuntimeError(f"Population became empty. Diagnostic: {diagnostic_path}") from exc

    original_run = eoh_method.EOH.run
    eoh_evolution.Evolution._get_alg = patched_get_alg
    bp_run.BPONLINE.evaluate = patched_evaluate
    eoh_interface_EC.InterfaceEC.get_offspring = patched_get_offspring
    eoh_interface_EC.InterfaceEC.get_algorithm = patched_get_algorithm
    eoh_method.EOH.run = patched_run


def patch_bp_dataset(max_items: int | None, quiet_progress: bool) -> None:
    if max_items is None:
        return
    if max_items <= 0:
        raise SystemExit("--max-items must be a positive integer")

    import numpy as np

    from eoh.problems.optimization.bp_online import get_instance as bp_get_instance

    original_get_instances = bp_get_instance.GetData.get_instances

    def patched_get_instances(self: Any) -> tuple[dict[str, Any], dict[str, float]]:
        datasets, _ = original_get_instances(self)
        truncated: dict[str, Any] = {}
        lbs: dict[str, float] = {}
        for dataset_name, dataset in datasets.items():
            truncated[dataset_name] = {}
            lb_values = []
            for instance_name, instance in dataset.items():
                items = list(instance["items"])[:max_items]
                capacity = instance["capacity"]
                truncated_instance = {
                    **instance,
                    "items": items,
                    "num_items": len(items),
                }
                truncated[dataset_name][instance_name] = truncated_instance
                lb_values.append(float(np.ceil(np.sum(items) / capacity)))
            lbs[dataset_name] = float(np.mean(lb_values)) if lb_values else 0.0
        if not quiet_progress:
            console_log(f"Using truncated bp_online instances: max_items={max_items}")
        return truncated, lbs

    bp_get_instance.GetData.get_instances = patched_get_instances


def write_run_metadata(args: argparse.Namespace, out_dir: Path, status: str, extra: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = read_json(out_dir / "run_metadata.json") or {}
    payload = {
        **existing,
        "status": status,
        "api_base_url": args.api_base_url,
        "model": args.model,
        "pop_size": args.pop_size,
        "n_pop": args.n_pop,
        "n_proc": args.n_proc,
        "max_items": args.max_items,
        "log_responses": args.log_responses,
        **extra,
    }
    if "error" not in extra and status != "failed":
        payload.pop("error", None)
    write_json(out_dir / "run_metadata.json", payload)


def evaluate_reference_baselines() -> dict[str, Any]:
    from eoh.problems.optimization.bp_online.run import BPONLINE

    problem = BPONLINE()
    results: list[dict[str, Any]] = []
    for name, code in PREDEFINED_BASELINES.items():
        objective = problem.evaluate(code)
        rounded = None if objective is None else round(float(objective), 5)
        results.append(
            {
                "method": name,
                "objective": rounded,
            }
        )

    results.sort(key=lambda row: float("inf") if row["objective"] is None else float(row["objective"]))
    best = results[0] if results else None
    return {
        "results": results,
        "best": best,
    }


def main() -> int:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Missing API key in ${args.api_key_env}")

    chat_url = normalize_chat_url(args.api_base_url)
    parsed = urlparse(chat_url)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit(f"Unsupported API URL: {chat_url}")

    out_dir = Path(args.output_dir)
    trace_paths = build_trace_paths(out_dir)
    trace_paths["requests_dir"].mkdir(parents=True, exist_ok=True)
    write_json(trace_paths["summary_path"], summarize_traces(trace_paths["requests_dir"]))

    patch_upstream_client(chat_url, out_dir, args.log_responses, args.quiet_progress)

    from eoh import eoh
    from eoh.utils.getParas import Paras

    patch_bp_dataset(args.max_items, args.quiet_progress)
    patch_failure_diagnostics(out_dir, args.quiet_progress)
    baseline_summary = evaluate_reference_baselines()

    paras = Paras()
    paras.set_paras(
        method="eoh",
        problem="bp_online",
        llm_api_endpoint=parsed.netloc,
        llm_api_key=api_key,
        llm_model=args.model,
        ec_pop_size=args.pop_size,
        ec_n_pop=args.n_pop,
        exp_n_proc=args.n_proc,
        exp_debug_mode=args.debug,
        exp_output_path=str(out_dir),
    )

    write_run_metadata(
        args,
        out_dir,
        "started",
        {
            "chat_url": chat_url,
            "started_at": utc_now(),
            "llm_trace_dir": str(trace_paths["trace_dir"]),
            "llm_requests_dir": str(trace_paths["requests_dir"]),
            "llm_summary_path": str(trace_paths["summary_path"]),
            "llm_diagnostics_dir": str(trace_paths["diagnostics_dir"]),
            "baseline_summary": baseline_summary,
        },
    )
    if not args.quiet_progress:
        console_log(
            f"Run start: pop_size={args.pop_size} n_pop={args.n_pop} n_proc={args.n_proc}"
        )
        console_log(f"Trace summary will be written to {trace_paths['summary_path']}")
        best_baseline = baseline_summary.get("best")
        if best_baseline is not None:
            baseline_parts = [
                f"{row['method']}={format_objective(row['objective'])}"
                for row in baseline_summary["results"]
            ]
            console_log(
                "Reference baselines: "
                + ", ".join(baseline_parts)
            )
            console_log(
                "Best baseline: "
                f"{best_baseline['method']} objective={format_objective(best_baseline['objective'])}"
            )

    try:
        evolution = eoh.EVOL(paras)
        evolution.run()
    except Exception as exc:
        write_run_metadata(
            args,
            out_dir,
            "failed",
            {
                "chat_url": chat_url,
                "finished_at": utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
                "llm_summary": summarize_traces(trace_paths["requests_dir"]),
                "baseline_summary": baseline_summary,
            },
        )
        if not args.quiet_progress:
            console_log(f"Run failed: {type(exc).__name__}: {exc}")
        raise

    best_path = out_dir / "results" / "pops_best" / f"population_generation_{args.n_pop}.json"
    best_objective = None
    if best_path.exists():
        best_data = json.loads(best_path.read_text(encoding="utf-8"))
        best_objective = best_data.get("objective")

    write_run_metadata(
        args,
        out_dir,
        "completed",
        {
            "chat_url": chat_url,
            "finished_at": utc_now(),
            "best_path": str(best_path),
            "best_objective": best_objective,
            "llm_summary": summarize_traces(trace_paths["requests_dir"]),
            "baseline_summary": baseline_summary,
        },
    )
    if not args.quiet_progress:
        summary = summarize_traces(trace_paths["requests_dir"])
        best_baseline = baseline_summary.get("best")
        baseline_compare = ""
        if best_baseline is not None and best_objective is not None:
            try:
                delta = float(best_objective) - float(best_baseline["objective"])
                baseline_compare = (
                    f" baseline_best={best_baseline['method']}:{format_objective(best_baseline['objective'])}"
                    f" delta_vs_baseline={delta:+.5f}"
                )
            except (TypeError, ValueError):
                baseline_compare = (
                    f" baseline_best={best_baseline['method']}:{format_objective(best_baseline['objective'])}"
                )
        console_log(
            "Run completed: "
            f"best_objective={format_objective(best_objective)} requests={summary['total_requests']} "
            f"tokens={summary['total_tokens']} cost={summary['total_cost']}{baseline_compare}"
        )
        if not args.no_force_exit:
            console_log("Final results written. Exiting without waiting for leftover worker threads.")
    if not args.no_force_exit:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
