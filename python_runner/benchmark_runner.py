"""
Fault Tree Quantitative Analysis Benchmarking Orchestrator.
Orchestrates the evaluation of LLM models with and without MCP connection.
"""

import os
import sys
import json
import time
import argparse
import logging
import traceback
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("mcp.client.sse").setLevel(logging.CRITICAL)

from llm_client import GeminiDriver, OpenAICompatibleDriver, MockLLMDriver
from mcp_client import SirioMCPMock, SirioMCPRealClient
from metrics import compute_pass_at_k, compute_steady_state_error, compute_curve_metrics

from utils import build_components_details, clean_nan
from progress_tracker import ProgressTracker
from baseline_runner import ensure_project_built, run_java_baseline
from plotter import generate_comparative_plots
from report_generator import save_report_data_json, write_markdown_report
from agent_loop import run_evaluation_for_mode

USER_PROMPT_TEMPLATE = (
    "Perform both the steady-state unavailability analysis and the transient unreliability analysis for the following event configuration:\n"
    "- Fault Tree Logic Expression: {logic_expression}\n"
    "- Transient Analysis Parameters:\n"
    "  * timeStep: {time_step}\n"
    "  * maxTime: {max_time}\n"
    "  * error limit: {error}\n"
    "- Leaf component model parameters (rates are exponential):\n"
    "{components_details}\n\n"
    "Show your step-by-step reasoning or tool interaction history first. "
    "At the very end of your response, provide your final results in a markdown JSON block "
    "with the following exact format:\n\n"
    "```json\n"
    "{{\n"
    "  \"steadyState\": <steady_state_probability_double>,\n"
    "  \"transientResult\": [\n"
    "    [0.0, 0.0],\n"
    "    [<t1>, <prob1>],\n"
    "    ...\n"
    "    [<max_time>, <prob_max>]\n"
    "  ]\n"
    "}}\n"
    "```\n"
    "Ensure the JSON is well-formed and do not put comments or explanations inside the json code block."
)

def main() -> None:
    """
    Main orchestrator execution loop. Parses command-line inputs, configures LLM drivers,
    builds the baseline, and loops through the test cases in sequence.
    """
    parser = argparse.ArgumentParser(description="Fault Tree Quantitative Analysis Benchmarking Orchestrator")
    parser.add_argument("--config", default="test_cases_example.json", help="Path to input test cases configuration JSON")
    parser.add_argument("--api-key", default=None, help="Gemini API Key (Google AI Studio)")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name")
    parser.add_argument("--provider", default="gemini", choices=["gemini", "openai", "mock"], help="Model provider endpoint")
    parser.add_argument("--openai-url", default="http://localhost:8000/v1", help="OpenAI-compatible endpoint url")
    parser.add_argument("--openai-model", default="qwen-2.5-coder-32b", help="Model name for OpenAI endpoint")
    parser.add_argument("--openai-key", default="local", help="OpenAI API Key (defaults to 'local')")
    parser.add_argument("--samples", type=int, default=1, help="Number of sampling generation passes per case")
    parser.add_argument("--k", type=int, default=1, help="k value for Pass@k estimation")
    parser.add_argument("--output-dir", default="output/benchmark", help="Output directory for plots and reports")
    parser.add_argument("--mcp-mode", default="mock", choices=["mock", "stdio", "sse"], help="MCP server connection mode")
    parser.add_argument("--sse-url", default="http://localhost:8081/sse", help="MCP server SSE URL (when mcp-mode is sse)")
    parser.add_argument("--verbose-interactions", action="store_true", help="Print detailed LLM logs during execution")
    parser.add_argument("--stream", action="store_true", help="Enable real-time streaming of LLM response to stdout")
    parser.add_argument("--temperature", type=float, default=0.0, help="Temperature for LLM generation")
    parser.add_argument("--reasoning-effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-agentic-turn", type=int, default=100, help="Maximum number of turns for the agent loop")
    parser.add_argument("--case", default=None, help="Filter to run only a single case by ID")
    parser.add_argument(
        "--enable-thinking",
        dest="thinking",
        action="store_true",
        help="Enable thinking in chat_template_kwargs for OpenAI-compatible requests"
    )
    parser.add_argument(
        "--disable-thinking",
        dest="thinking",
        action="store_false",
        help="Disable thinking in chat_template_kwargs for OpenAI-compatible requests"
    )
    parser.set_defaults(thinking=True)
    
    args = parser.parse_args()
    
    workspace_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    ensure_project_built(workspace_path)
    
    # Initialize LLM drivers
    if args.provider == "gemini":
        if not args.api_key:
            args.api_key = os.environ.get("GEMINI_API_KEY")
        if not args.api_key:
            logger.error("Missing Gemini API Key. Use --api-key or GEMINI_API_KEY env var.")
            sys.exit(1)
        driver = GeminiDriver(api_key=args.api_key, model_name=args.model, temperature=args.temperature)
    elif args.provider == "mock":
        driver = MockLLMDriver(temperature=args.temperature)
    else:
        openai_key = args.openai_key
        if openai_key == "local" or not openai_key:
            openai_key = os.environ.get("OPENAI_API_KEY") or "local"
        driver = OpenAICompatibleDriver(
            base_url=args.openai_url, 
            model_name=args.openai_model, 
            api_key=openai_key, 
            temperature=args.temperature, 
            reasoning=args.reasoning_effort, 
            enable_thinking=args.thinking
        )
        
    # Build classpath for stdio/sse real client
    classpath = ""
    if args.mcp_mode in ("stdio", "sse"):
        classpath_file = os.path.join(workspace_path, "classpath.txt")
        maven_deps = ""
        if os.path.exists(classpath_file):
            try:
                with open(classpath_file, 'r', encoding='utf-8') as f:
                    maven_deps = f.read().strip()
            except Exception as e:
                logger.warning(f"Could not read classpath.txt: {e}")
        target_classes = os.path.join(workspace_path, "target", "classes")
        target_test_classes = os.path.join(workspace_path, "target", "test-classes")
        sirio_jar = os.path.join(workspace_path, "lib", "sirio-2.0.4.jar")
        separator = ";" if sys.platform.startswith("win") else ":"
        cp_elements = [target_classes, target_test_classes, sirio_jar]
        if maven_deps:
            cp_elements.append(maven_deps)
        classpath = separator.join(cp_elements)

    if args.mcp_mode == "mock":
        mcp_client = SirioMCPMock(workspace_path)
    else:
        mcp_client = SirioMCPRealClient(mode=args.mcp_mode, classpath=classpath, sse_url=args.sse_url)

    mcp_client.start()
    try:
        config_path = os.path.abspath(args.config)
        if not os.path.exists(config_path):
            logger.error(f"Configuration file {config_path} does not exist.")
            sys.exit(1)
            
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            
        cases = config_data.get("cases", [])
        if not cases:
            cases = [config_data]
            
        if args.case:
            cases = [c for c in cases if c.get("id") == args.case]
            if not cases:
                logger.error(f"Case '{args.case}' not found in configuration.")
                sys.exit(1)
            
        logger.info(f"Loaded {len(cases)} test cases from config.")
        
        total_evals = len(cases) * args.samples * 2
        tracker = ProgressTracker(total_evals)
        
        report_data = []
        interaction_history = []
        
        for case in cases:
            case_id = case["id"]
            logger.info(f"========== Starting Benchmark for Case: {case_id} ==========")
            
            try:
                baseline = run_java_baseline(workspace_path, config_path, case_id)
            except Exception as e:
                logger.error(f"Failed to run Java baseline for case {case_id}: {e}")
                traceback.print_exc()
                continue
                
            comp_details = build_components_details(case["components"])
            prompt = USER_PROMPT_TEMPLATE.format(
                logic_expression=case["logicExpression"],
                time_step=case["timeStep"],
                max_time=case["maxTime"],
                error=case["error"],
                components_details=comp_details
            )
            
            # Direct prompt mode
            logger.info("Running LLM without MCP (Mode: direct prompt)...")
            no_mcp_runs, no_mcp_exec_rate, no_mcp_correct_count = run_evaluation_for_mode(
                driver=driver,
                mcp_client=mcp_client,
                prompt=prompt,
                baseline=baseline,
                with_mcp=False,
                provider=args.provider,
                num_samples=args.samples,
                verbose_interactions=args.verbose_interactions,
                max_turns=args.max_agentic_turn,
                base_seed=config_data.get("seed"),
                tracker=tracker,
                case_id=case_id,
                stream=args.stream
            )
            no_mcp_pass_k = compute_pass_at_k(args.samples, no_mcp_correct_count, args.k)
            
            first_no_mcp_success = next((run for run in no_mcp_runs if run["success"]), None)
            no_mcp_steady = first_no_mcp_success["steady_state"] if first_no_mcp_success else float('nan')
            no_mcp_curve = first_no_mcp_success["transient_result"] if first_no_mcp_success else None
            
            no_mcp_steady_err = compute_steady_state_error(baseline["steadyState"], no_mcp_steady) if first_no_mcp_success else float('nan')
            no_mcp_mae, no_mcp_rmse = compute_curve_metrics(baseline["transientResult"], no_mcp_curve) if first_no_mcp_success else (float('nan'), float('nan'))
            
            # Tool calling mode
            logger.info("Running LLM with MCP (Mode: tool calling enabled)...")
            mcp_client.disconnect()
            mcp_client.start()
            mcp_runs, mcp_exec_rate, mcp_correct_count = run_evaluation_for_mode(
                driver=driver,
                mcp_client=mcp_client,
                prompt=prompt,
                baseline=baseline,
                with_mcp=True,
                provider=args.provider,
                num_samples=args.samples,
                verbose_interactions=args.verbose_interactions,
                max_turns=args.max_agentic_turn,
                base_seed=config_data.get("seed"),
                tracker=tracker,
                case_id=case_id,
                stream=args.stream
            )
            mcp_pass_k = compute_pass_at_k(args.samples, mcp_correct_count, args.k)
            
            first_mcp_success = next((run for run in mcp_runs if run["success"]), None)
            mcp_steady = first_mcp_success["steady_state"] if first_mcp_success else float('nan')
            mcp_curve = first_mcp_success["transient_result"] if first_mcp_success else None
            
            mcp_steady_err = compute_steady_state_error(baseline["steadyState"], mcp_steady) if first_mcp_success else float('nan')
            mcp_mae, mcp_rmse = compute_curve_metrics(baseline["transientResult"], mcp_curve) if first_mcp_success else (float('nan'), float('nan'))
            
            # Generate plots
            plot_filename = f"{case_id}_curve_comparison.png"
            plot_path = os.path.join(output_dir, plot_filename)
            generate_comparative_plots(
                case_id=case_id,
                baseline_curve=baseline["transientResult"],
                llm_no_mcp_curve=no_mcp_curve,
                llm_mcp_curve=mcp_curve,
                output_path=plot_path
            )
            
            logger.info(f"Case {case_id} steady state: Baseline={baseline['steadyState']:.6f}, No-MCP={no_mcp_steady:.6f}, MCP={mcp_steady:.6f}")
            logger.info(f"MAE: No-MCP={no_mcp_mae:.6f}, MCP={mcp_mae:.6f}")
            logger.info(f"Pass@{args.k}: No-MCP={no_mcp_pass_k:.2%}, MCP={mcp_pass_k:.2%}")
            
            # Format results
            no_mcp_samples_data = []
            no_mcp_pass_1_list = []
            for run in no_mcp_runs:
                p1_val = 1.0 if run["correct"] else 0.0
                no_mcp_pass_1_list.append(p1_val)
                no_mcp_samples_data.append({
                    "run_index": run["run_index"],
                    "success": run["success"],
                    "correct": run["correct"],
                    "pass_1": p1_val,
                    "steady_state": clean_nan(run["steady_state"]),
                    "steady_error": clean_nan(run["steady_error"]),
                    "mae": clean_nan(run["mae"]),
                    "rmse": clean_nan(run["rmse"]),
                    "transient_result": run["transient_result"],
                    "latency_seconds": run["latency_seconds"],
                    "max_turns_exceeded": run.get("max_turns_exceeded", False)
                })
            
            no_mcp_success_runs = [r for r in no_mcp_runs if r["success"]]
            no_mcp_avg_steady_error = float(np.mean([r["steady_error"] for r in no_mcp_success_runs])) if no_mcp_success_runs else float('nan')
            no_mcp_avg_mae = float(np.mean([r["mae"] for r in no_mcp_success_runs])) if no_mcp_success_runs else float('nan')
            no_mcp_avg_rmse = float(np.mean([r["rmse"] for r in no_mcp_success_runs])) if no_mcp_success_runs else float('nan')
            
            no_mcp_agg = {
                "samples_count": args.samples,
                "k": args.k,
                "executable_rate": no_mcp_exec_rate,
                "pass_k": no_mcp_pass_k,
                "pass_at_samples": compute_pass_at_k(args.samples, no_mcp_correct_count, args.samples),
                "avg_latency": float(np.mean([r["latency_seconds"] for r in no_mcp_runs])),
                "avg_steady_error": clean_nan(no_mcp_avg_steady_error),
                "avg_mae": clean_nan(no_mcp_avg_mae),
                "avg_rmse": clean_nan(no_mcp_avg_rmse),
                "pass_1_mean": float(np.mean(no_mcp_pass_1_list)),
                "pass_1_std": float(np.std(no_mcp_pass_1_list)),
                "max_turns_exceeded_rate": float(sum(1 for r in no_mcp_runs if r.get("max_turns_exceeded"))) / args.samples
            }
            if args.samples // 2 > 0:
                no_mcp_agg["pass_at_half_samples"] = compute_pass_at_k(args.samples, no_mcp_correct_count, args.samples // 2)

            mcp_samples_data = []
            mcp_pass_1_list = []
            for run in mcp_runs:
                p1_val = 1.0 if run["correct"] else 0.0
                mcp_pass_1_list.append(p1_val)
                mcp_samples_data.append({
                    "run_index": run["run_index"],
                    "success": run["success"],
                    "correct": run["correct"],
                    "modeling_correctness": run.get("modeling_correctness", False),
                    "modeling_isomorphism": run.get("modeling_isomorphism", False),
                    "pass_1": p1_val,
                    "steady_state": clean_nan(run["steady_state"]),
                    "steady_error": clean_nan(run["steady_error"]),
                    "mae": clean_nan(run["mae"]),
                    "rmse": clean_nan(run["rmse"]),
                    "semantic_steady_error": clean_nan(run.get("semantic_steady_error")),
                    "semantic_mae": clean_nan(run.get("semantic_mae")),
                    "semantic_rmse": clean_nan(run.get("semantic_rmse")),
                    "transient_result": run["transient_result"],
                    "latency_seconds": run["latency_seconds"],
                    "tool_calls_count": len(run["tool_calls"]),
                    "max_turns_exceeded": run.get("max_turns_exceeded", False)
                })
            
            mcp_success_runs = [r for r in mcp_runs if r["success"]]
            mcp_avg_steady_error = float(np.mean([r["steady_error"] for r in mcp_success_runs])) if mcp_success_runs else float('nan')
            mcp_avg_mae = float(np.mean([r["mae"] for r in mcp_success_runs])) if mcp_success_runs else float('nan')
            mcp_avg_rmse = float(np.mean([r["rmse"] for r in mcp_success_runs])) if mcp_success_runs else float('nan')
            
            mcp_correctness_count = sum(1 for r in mcp_runs if r.get("modeling_correctness"))
            mcp_isomorphism_count = sum(1 for r in mcp_runs if r.get("modeling_isomorphism"))
            mcp_alternative_count = sum(1 for r in mcp_runs if r.get("modeling_correctness") and not r.get("modeling_isomorphism"))
            mcp_tool_ignored_count = sum(1 for r in mcp_runs if r.get("modeling_correctness") and not r.get("correct"))
            mcp_failure_count = sum(1 for r in mcp_runs if not r.get("modeling_correctness"))

            mcp_agg = {
                "samples_count": args.samples,
                "k": args.k,
                "executable_rate": mcp_exec_rate,
                "pass_k": mcp_pass_k,
                "pass_at_samples": compute_pass_at_k(args.samples, mcp_correct_count, args.samples),
                "modeling_correctness_rate": float(mcp_correctness_count) / args.samples,
                "modeling_isomorphism_rate": float(mcp_isomorphism_count) / args.samples,
                "alternative_modeling_rate": float(mcp_alternative_count) / args.samples,
                "tool_ignored_error_rate": float(mcp_tool_ignored_count) / args.samples,
                "modeling_failure_rate": float(mcp_failure_count) / args.samples,
                "avg_latency": float(np.mean([r["latency_seconds"] for r in mcp_runs])),
                "avg_steady_error": clean_nan(mcp_avg_steady_error),
                "avg_mae": clean_nan(mcp_avg_mae),
                "avg_rmse": clean_nan(mcp_avg_rmse),
                "avg_tool_calls_count": float(np.mean([len(r["tool_calls"]) for r in mcp_runs])),
                "pass_1_mean": float(np.mean(mcp_pass_1_list)),
                "pass_1_std": float(np.std(mcp_pass_1_list)),
                "max_turns_exceeded_rate": float(sum(1 for r in mcp_runs if r.get("max_turns_exceeded"))) / args.samples
            }
            if args.samples // 2 > 0:
                mcp_agg["pass_at_half_samples"] = compute_pass_at_k(args.samples, mcp_correct_count, args.samples // 2)

            report_data.append({
                "model": driver.model_name,
                "case_id": case_id,
                "logic_expression": case.get("logicExpression"),
                "seed": config_data.get("seed"),
                "baseline": baseline,
                "no_mcp": {
                    "samples": no_mcp_samples_data,
                    "aggregated": no_mcp_agg
                },
                "mcp": {
                    "samples": mcp_samples_data,
                    "aggregated": mcp_agg
                }
            })
            
            interaction_history.append({
                "case_id": case_id,
                "prompt": prompt,
                "no_mcp_runs": no_mcp_runs,
                "mcp_runs": mcp_runs
            })

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")    
        save_report_data_json(report_data, os.path.dirname(output_dir), timestamp)
        
        # Write interactions log
        if interaction_history:
            log_filename = f"interactions_{timestamp}.md"
            log_path = os.path.join(output_dir, log_filename)
            try:
                logger.info(f"Saving detailed LLM interactions log to {log_path}...")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"# LLM Interaction Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write("This file contains the detailed prompts, raw LLM responses, and MCP tool call sequences for each evaluated case.\n\n")
                    
                    for item in interaction_history:
                        cid = item["case_id"]
                        f.write(f"---\n\n## Case: {cid}\n\n")
                        
                        f.write("### 1. Direct Prompt (Without MCP)\n\n")
                        for run in item["no_mcp_runs"]:
                            idx = run["run_index"]
                            latency = run["latency_seconds"]
                            success = run["success"]
                            correct = run["correct"]
                            error = run["error"]
                            trace = run.get("interactions_trace", [])
                            
                            f.write(f"#### Run {idx} (Latency: {latency:.2f}s, Success: {success}, Correct: {correct})\n\n")
                            f.write("**Prompt Sent to LLM:**\n")
                            f.write(f"```\n{item['prompt']}\n```\n\n")
                            
                            f.write("**Chronological Interaction Trace:**\n\n")
                            if trace:
                                for step_idx, step in enumerate(trace):
                                    if step["type"] == "text":
                                        f.write(f"##### Turn {step_idx + 1} - LLM Response:\n{step['content']}\n\n")
                                    elif step["type"] == "tool_call":
                                        f.write(f"##### Turn {step_idx + 1} - MCP Tool Call:\n`{step['name']}({json.dumps(step['args'])})` -> `{json.dumps(step['result'])}`\n\n")
                            else:
                                f.write("**LLM Response:**\n")
                                f.write(f"```\n{run['raw_text']}\n```\n\n")
                                
                            if error:
                                f.write(f"**Error:** `{error}`\n\n")
                                
                        f.write("### 2. Tool Calling (With MCP)\n\n")
                        for run in item["mcp_runs"]:
                            idx = run["run_index"]
                            latency = run["latency_seconds"]
                            success = run["success"]
                            correct = run["correct"]
                            error = run["error"]
                            trace = run.get("interactions_trace", [])
                            
                            f.write(f"#### Run {idx} (Latency: {latency:.2f}s, Success: {success}, Correct: {correct})\n\n")
                            f.write("**Initial Prompt Sent to LLM:**\n")
                            f.write(f"```\n{item['prompt']}\n```\n\n")
                            
                            f.write("**Chronological Interaction Trace:**\n\n")
                            if trace:
                                for step_idx, step in enumerate(trace):
                                    if step["type"] == "text":
                                        f.write(f"##### Turn {step_idx + 1} - LLM Response:\n{step['content']}\n\n")
                                    elif step["type"] == "tool_call":
                                        f.write(f"##### Turn {step_idx + 1} - MCP Tool Call:\n`{step['name']}({json.dumps(step['args'])})` -> `{json.dumps(step['result'])}`\n\n")
                            else:
                                tool_calls = run.get("tool_calls", [])
                                if tool_calls:
                                    f.write("| Step | Tool Called | Arguments | Result |\n")
                                    f.write("|---|---|---|---|\n")
                                    for tc_idx, tc in enumerate(tool_calls):
                                        f.write(f"| {tc_idx + 1} | `{tc.get('tool')}` | `{json.dumps(tc.get('args'))}` | `{json.dumps(tc.get('result'))}` |\n")
                                    f.write("\n")
                                f.write("**Final LLM Response:**\n")
                                f.write(f"```\n{run['raw_text']}\n```\n\n")
                                
                            if error:
                                f.write(f"**Error:** `{error}`\n\n")
                logger.info(f"LLM interactions log successfully saved to {log_path}.")
            except Exception as e:
                logger.error(f"Failed to save LLM interactions log: {e}")
    finally:
        mcp_client.stop()

if __name__ == "__main__":
    main()
