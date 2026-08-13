"""
This module handles JSON result saving, academic summary aggregation, and Markdown reports.
"""

import os
import json
import logging
import numpy as np
from typing import List, Dict, Any, Optional

from metrics import compute_pass_at_k, compute_steady_state_error, compute_curve_metrics
from utils import clean_nan
from llm_client import LLMDriver, MockLLMDriver

logger = logging.getLogger(__name__)

def save_report_summary_json(report_data: List[Dict[str, Any]], report_dir: str) -> None:
    """
    Calculates and saves the aggregated academic summary metrics from the report data.

    Args:
        report_data: The list of test case run results.
        report_dir: The directory where report_summary.json will be saved.
    """
    num_cases = len(report_data)
    if num_cases == 0:
        return

    # Count samples per case
    samples_per_case = len(report_data[0]['no_mcp']['samples'])
    total_samples = num_cases * samples_per_case

    # Arrays for standard deviations across all runs
    no_mcp_run_correctness = []
    mcp_run_correctness = []
    mcp_mod_run_correctness = []

    # Arrays for metrics
    no_mcp_success_count = 0
    no_mcp_maes = []
    no_mcp_rmses = []
    no_mcp_steady_errors = []
    no_mcp_latencies = []
    no_mcp_turns_exceeded_count = 0
    no_mcp_case_pass_rates = []
    no_mcp_p2_cases = []
    no_mcp_p5_cases = []

    mcp_success_count = 0
    mcp_maes = []
    mcp_rmses = []
    mcp_steady_errors = []
    mcp_latencies = []
    mcp_turns_exceeded_count = 0
    mcp_case_pass_rates = []
    mcp_p2_cases = []
    mcp_p5_cases = []

    mcp_mod_success_count = 0
    mcp_mod_maes = []
    mcp_mod_rmses = []
    mcp_mod_steady_errors = []
    mcp_mod_case_pass_rates = []
    mcp_mod_p2_cases = []
    mcp_mod_p5_cases = []

    # MCP structural details
    mcp_isomorphism_count = 0
    mcp_alternative_count = 0
    mcp_tool_ignored_count = 0
    mcp_failure_count = 0

    for c in report_data:
        # --- NO MCP ---
        no_mcp_s = c['no_mcp']['samples']
        c_no_mcp_correct = sum(1 for s in no_mcp_s if s['correct'])
        no_mcp_case_pass_rates.append(c_no_mcp_correct / samples_per_case)
        no_mcp_p2_cases.append(compute_pass_at_k(samples_per_case, c_no_mcp_correct, 2))
        no_mcp_p5_cases.append(compute_pass_at_k(samples_per_case, c_no_mcp_correct, 5))
        
        for s in no_mcp_s:
            no_mcp_run_correctness.append(1.0 if s['correct'] else 0.0)
            no_mcp_latencies.append(s['latency_seconds'])
            if s.get('max_turns_exceeded', False):
                no_mcp_turns_exceeded_count += 1
            if s['success']:
                no_mcp_success_count += 1
                mae = clean_nan(s.get('mae'))
                if mae is not None:
                    no_mcp_maes.append(mae)
                rmse = clean_nan(s.get('rmse'))
                if rmse is not None:
                    no_mcp_rmses.append(rmse)
                ste = clean_nan(s.get('steady_error'))
                if ste is not None:
                    no_mcp_steady_errors.append(ste)

        # --- MCP ---
        mcp_s = c['mcp']['samples']
        c_mcp_correct = sum(1 for s in mcp_s if s['correct'])
        mcp_case_pass_rates.append(c_mcp_correct / samples_per_case)
        mcp_p2_cases.append(compute_pass_at_k(samples_per_case, c_mcp_correct, 2))
        mcp_p5_cases.append(compute_pass_at_k(samples_per_case, c_mcp_correct, 5))

        c_mcp_mod_correct = sum(1 for s in mcp_s if s.get('modeling_correctness', False))
        mcp_mod_case_pass_rates.append(c_mcp_mod_correct / samples_per_case)
        mcp_mod_p2_cases.append(compute_pass_at_k(samples_per_case, c_mcp_mod_correct, 2))
        mcp_mod_p5_cases.append(compute_pass_at_k(samples_per_case, c_mcp_mod_correct, 5))
        
        for s in mcp_s:
            mcp_run_correctness.append(1.0 if s['correct'] else 0.0)
            mcp_mod_run_correctness.append(1.0 if s.get('modeling_correctness', False) else 0.0)
            mcp_latencies.append(s['latency_seconds'])
            if s.get('max_turns_exceeded', False):
                mcp_turns_exceeded_count += 1
                
            # Classify MCP structural results
            mod_correct = s.get('modeling_correctness', False)
            mod_iso = s.get('modeling_isomorphism', False)
            func_correct = s['correct']
            
            if mod_correct:
                if mod_iso:
                    mcp_isomorphism_count += 1
                else:
                    mcp_alternative_count += 1
                if not func_correct:
                    mcp_tool_ignored_count += 1
            else:
                mcp_failure_count += 1

            if s['success']:
                mcp_success_count += 1
                mae = clean_nan(s.get('mae'))
                if mae is not None:
                    mcp_maes.append(mae)
                rmse = clean_nan(s.get('rmse'))
                if rmse is not None:
                    mcp_rmses.append(rmse)
                ste = clean_nan(s.get('steady_error'))
                if ste is not None:
                    mcp_steady_errors.append(ste)

            # Modeling metrics (semantic calculation via direct python call on JVM model)
            sem_ste = clean_nan(s.get('semantic_steady_error'))
            sem_mae = clean_nan(s.get('semantic_mae'))
            sem_rmse = clean_nan(s.get('semantic_rmse'))
            if sem_ste is not None or sem_mae is not None:
                mcp_mod_success_count += 1
                if sem_mae is not None:
                    mcp_mod_maes.append(sem_mae)
                if sem_rmse is not None:
                    mcp_mod_rmses.append(sem_rmse)
                if sem_ste is not None:
                    mcp_mod_steady_errors.append(sem_ste)

    def get_avg_and_std(arr):
        if not arr:
            return 0.0, 0.0
        return float(np.mean(arr)), float(np.std(arr))

    no_mcp_avg_mae, no_mcp_std_mae = get_avg_and_std(no_mcp_maes)
    no_mcp_avg_rmse, no_mcp_std_rmse = get_avg_and_std(no_mcp_rmses)
    no_mcp_avg_ste, no_mcp_std_ste = get_avg_and_std(no_mcp_steady_errors)

    mcp_avg_mae, mcp_std_mae = get_avg_and_std(mcp_maes)
    mcp_avg_rmse, mcp_std_rmse = get_avg_and_std(mcp_rmses)
    mcp_avg_ste, mcp_std_ste = get_avg_and_std(mcp_steady_errors)

    mcp_mod_avg_mae, mcp_mod_std_mae = get_avg_and_std(mcp_mod_maes)
    mcp_mod_avg_rmse, mcp_mod_std_rmse = get_avg_and_std(mcp_mod_rmses)
    mcp_mod_avg_ste, mcp_mod_std_ste = get_avg_and_std(mcp_mod_steady_errors)

    results = {
        "metadata": {
            "num_cases": num_cases,
            "samples_per_case": samples_per_case,
            "total_samples": total_samples
        },
        "no_mcp": {
            "success_rate": no_mcp_success_count / total_samples,
            "pass_1": float(np.mean(no_mcp_run_correctness)),
            "pass_1_std_runs": float(np.std(no_mcp_run_correctness)),
            "pass_1_std_cases": float(np.std(no_mcp_case_pass_rates)),
            "pass_2": float(np.mean(no_mcp_p2_cases)),
            "pass_5": float(np.mean(no_mcp_p5_cases)),
            "avg_mae": no_mcp_avg_mae,
            "std_mae": no_mcp_std_mae,
            "avg_rmse": no_mcp_avg_rmse,
            "std_rmse": no_mcp_std_rmse,
            "avg_steady_error": no_mcp_avg_ste,
            "std_steady_error": no_mcp_std_ste,
            "avg_latency": float(np.mean(no_mcp_latencies)),
            "std_latency": float(np.std(no_mcp_latencies)),
            "max_turns_exceeded_rate": no_mcp_turns_exceeded_count / total_samples
        },
        "mcp_functional": {
            "success_rate": mcp_success_count / total_samples,
            "pass_1": float(np.mean(mcp_run_correctness)),
            "pass_1_std_runs": float(np.std(mcp_run_correctness)),
            "pass_1_std_cases": float(np.std(mcp_case_pass_rates)),
            "pass_2": float(np.mean(mcp_p2_cases)),
            "pass_5": float(np.mean(mcp_p5_cases)),
            "avg_mae": mcp_avg_mae,
            "std_mae": mcp_std_mae,
            "avg_rmse": mcp_avg_rmse,
            "std_rmse": mcp_std_rmse,
            "avg_steady_error": mcp_avg_ste,
            "std_steady_error": mcp_std_ste,
            "avg_latency": float(np.mean(mcp_latencies)),
            "std_latency": float(np.std(mcp_latencies)),
            "max_turns_exceeded_rate": mcp_turns_exceeded_count / total_samples,
            "tool_ignored_error_rate": mcp_tool_ignored_count / total_samples
        },
        "mcp_modeling": {
            "success_rate": mcp_mod_success_count / total_samples,
            "pass_1": float(np.mean(mcp_mod_run_correctness)),
            "pass_1_std_runs": float(np.std(mcp_mod_run_correctness)),
            "pass_1_std_cases": float(np.std(mcp_mod_case_pass_rates)),
            "pass_2": float(np.mean(mcp_mod_p2_cases)),
            "pass_5": float(np.mean(mcp_mod_p5_cases)),
            "avg_mae": mcp_mod_avg_mae,
            "std_mae": mcp_mod_std_mae,
            "avg_rmse": mcp_mod_avg_rmse,
            "std_rmse": mcp_mod_std_rmse,
            "avg_steady_error": mcp_mod_avg_ste,
            "std_steady_error": mcp_mod_std_ste,
            "avg_latency": float(np.mean(mcp_latencies)),
            "std_latency": float(np.std(mcp_latencies)),
            "modeling_isomorphism_rate": mcp_isomorphism_count / total_samples,
            "alternative_modeling_rate": mcp_alternative_count / total_samples,
            "modeling_failure_rate": mcp_failure_count / total_samples
        }
    }

    # Print to console
    logger.info("\n" + "="*95)
    logger.info(" ACADEMIC BENCHMARK SUMMARY")
    logger.info("="*95)
    logger.info(f"Total Cases: {num_cases} | Samples per Case: {samples_per_case} | Total Runs: {total_samples}")
    logger.info("-"*95)
    logger.info(f"{'Metric':<35} | {'No-MCP':<16} | {'MCP (Func)':<16} | {'MCP (Model)':<16}")
    logger.info("-"*95)
    logger.info(f"{'Success/Exec Rate':<35} | {results['no_mcp']['success_rate']:<16.2%} | {results['mcp_functional']['success_rate']:<16.2%} | {results['mcp_modeling']['success_rate']:<16.2%}")
    logger.info(f"{'Pass@1 Accuracy (Mean)':<35} | {results['no_mcp']['pass_1']:<16.2%} | {results['mcp_functional']['pass_1']:<16.2%} | {results['mcp_modeling']['pass_1']:<16.2%}")
    logger.info(f"{'Pass@1 Std Dev (across runs)':<35} | {results['no_mcp']['pass_1_std_runs']:<16.4f} | {results['mcp_functional']['pass_1_std_runs']:<16.4f} | {results['mcp_modeling']['pass_1_std_runs']:<16.4f}")
    logger.info(f"{'Pass@1 Std Dev (across cases)':<35} | {results['no_mcp']['pass_1_std_cases']:<16.4f} | {results['mcp_functional']['pass_1_std_cases']:<16.4f} | {results['mcp_modeling']['pass_1_std_cases']:<16.4f}")
    logger.info(f"{'Pass@2 Accuracy':<35} | {results['no_mcp']['pass_2']:<16.2%} | {results['mcp_functional']['pass_2']:<16.2%} | {results['mcp_modeling']['pass_2']:<16.2%}")
    logger.info(f"{'Pass@5 Accuracy':<35} | {results['no_mcp']['pass_5']:<16.2%} | {results['mcp_functional']['pass_5']:<16.2%} | {results['mcp_modeling']['pass_5']:<16.2%}")
    logger.info(f"{'Average Transient MAE':<35} | {results['no_mcp']['avg_mae']:<16.4e} | {results['mcp_functional']['avg_mae']:<16.4e} | {results['mcp_modeling']['avg_mae']:<16.4e}")
    logger.info(f"{'Average Transient RMSE':<35} | {results['no_mcp']['avg_rmse']:<16.4e} | {results['mcp_functional']['avg_rmse']:<16.4e} | {results['mcp_modeling']['avg_rmse']:<16.4e}")
    logger.info(f"{'Average Steady Error':<35} | {results['no_mcp']['avg_steady_error']:<16.4e} | {results['mcp_functional']['avg_steady_error']:<16.4e} | {results['mcp_modeling']['avg_steady_error']:<16.4e}")
    logger.info(f"{'Average Latency (s)':<35} | {results['no_mcp']['avg_latency']:<16.2f} | {results['mcp_functional']['avg_latency']:<16.2f} | {results['mcp_modeling']['avg_latency']:<16.2f}")
    logger.info(f"{'Max Turns Exceeded Rate':<35} | {results['no_mcp']['max_turns_exceeded_rate']:<16.2%} | {results['mcp_functional']['max_turns_exceeded_rate']:<16.2%} | {'N/A':<16}")
    logger.info(f"{'Tool Ignored Error Rate':<35} | {'N/A':<16} | {results['mcp_functional']['tool_ignored_error_rate']:<16.2%} | {'N/A':<16}")
    logger.info(f"{'Modeling Isomorphism Rate':<35} | {'N/A':<16} | {'N/A':<16} | {results['mcp_modeling']['modeling_isomorphism_rate']:<16.2%}")
    logger.info(f"{'Alternative Modeling Rate':<35} | {'N/A':<16} | {'N/A':<16} | {results['mcp_modeling']['alternative_modeling_rate']:<16.2%}")
    logger.info(f"{'Modeling Failure Rate':<35} | {'N/A':<16} | {'N/A':<16} | {results['mcp_modeling']['modeling_failure_rate']:<16.2%}")
    logger.info("="*95)

    summary_path = os.path.join(report_dir, "report_summary.json")
    with open(summary_path, "w", encoding="utf-8") as sf:
        json.dump(results, sf, indent=2)
    logger.info(f"Summary JSON automatically saved to: {summary_path}")

def save_report_data_json(report_data: List[Dict[str, Any]], output_root: str, timestamp: str) -> str:
    """
    Saves the main detailed results JSON to output/experiments/experiment_[timestamp].

    Args:
        report_data: List of detailed results for each case.
        output_root: The target directory for experiment runs.
        timestamp: The timestamp unique to this run.

    Returns:
        The file path where report_data.json was saved.
    """
    report_dir = os.path.join(output_root, f"experiments/experiment_{timestamp}")
    if not os.path.exists(report_dir):
        os.makedirs(report_dir, exist_ok=True)

    report_path = os.path.join(report_dir, "report_data.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    logger.info("Saved report_data JSON to %s", report_path)
    
    try:
        save_report_summary_json(report_data, report_dir)
    except Exception as e:
        logger.error(f"Failed to generate automatic report summary: {e}")
        
    return report_path

def write_local_report_fallback(data: List[Dict[str, Any]], report_path: str, samples: int, k: int) -> None:
    """
    Writes a deterministic, programmatic evaluation report to disk as a fallback.

    Args:
        data: Evaluated test case results.
        report_path: Destination path for the report.
        samples: Samples per case.
        k: k value for Pass@k calculations.
    """
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Quantitative Benchmark Report: LLM vs LLM+MCP on Fault Tree Unreliability (Deterministic Report)\n\n")
        f.write("## 1. Executive Summary\n")
        f.write(
            "This report documents the comparative performance evaluation of a Large Language Model (LLM) "
            "configured with and without Model Context Protocol (MCP) connection to the SIRIO formal method library. "
            "The benchmark tasks involve analyzing complex Fault Trees with AND/OR/KOFN gates and Gilbert-Elliot leaf nodes, "
            "computing infinite-horizon steady-state unreliability, and transient probability distributions.\n\n"
        )
        
        f.write("## 2. Experimental Setup\n")
        f.write(f"- **Evaluated Model**: {samples} samples per case (Pass@{k} configured)\n")
        f.write("- **Baseline (Ground Truth)**: Petri Net formal execution via SIRIO library (Java)\n")
        f.write("- **Tool Availability for LLM+MCP**: Low-level Petri Net primitives (places, transitions, markings, analysis executions) without Fault Tree modeling abstraction.\n\n")
        
        f.write("## 3. Comparative Performance Metrics\n\n")
        f.write("| Case ID | Config | Steady-State Prob | SS Abs Error | Curve MAE | Curve RMSE | Executable Rate | Pass@k |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
        
        for case in data:
            cid = case["case_id"]
            base_ss = case["baseline"]["steadyState"]
            f.write(f"| {cid} | Baseline | {base_ss:.8f} | 0.00000000 | 0.00000000 | 0.00000000 | 100.0% | N/A |\n")
            
            nm_agg = case["no_mcp"]["aggregated"]
            nm_success_samples = [s for s in case["no_mcp"]["samples"] if s["success"]]
            nm_ss_avg = np.mean([s["steady_state"] for s in nm_success_samples]) if nm_success_samples else float('nan')
            
            ss_str = f"{nm_ss_avg:.8f}" if not np.isnan(nm_ss_avg) else "N/A"
            se_str = f"{nm_agg['avg_steady_error']:.8f}" if nm_agg['avg_steady_error'] is not None and not np.isnan(nm_agg['avg_steady_error']) else "N/A"
            mae_str = f"{nm_agg['avg_mae']:.8f}" if nm_agg['avg_mae'] is not None and not np.isnan(nm_agg['avg_mae']) else "N/A"
            rmse_str = f"{nm_agg['avg_rmse']:.8f}" if nm_agg['avg_rmse'] is not None and not np.isnan(nm_agg['avg_rmse']) else "N/A"
            f.write(f"| | LLM (No MCP) | {ss_str} | {se_str} | {mae_str} | {rmse_str} | {nm_agg['executable_rate']:.1%} | {nm_agg['pass_k']:.1%} |\n")
            
            m_agg = case["mcp"]["aggregated"]
            m_success_samples = [s for s in case["mcp"]["samples"] if s["success"]]
            m_ss_avg = np.mean([s["steady_state"] for s in m_success_samples]) if m_success_samples else float('nan')
            
            m_ss_str = f"{m_ss_avg:.8f}" if not np.isnan(m_ss_avg) else "N/A"
            m_se_str = f"{m_agg['avg_steady_error']:.8f}" if m_agg['avg_steady_error'] is not None and not np.isnan(m_agg['avg_steady_error']) else "N/A"
            m_mae_str = f"{m_agg['avg_mae']:.8f}" if m_agg['avg_mae'] is not None and not np.isnan(m_agg['avg_mae']) else "N/A"
            m_rmse_str = f"{m_agg['avg_rmse']:.8f}" if m_agg['avg_rmse'] is not None and not np.isnan(m_agg['avg_rmse']) else "N/A"
            f.write(f"| | LLM+MCP | {m_ss_str} | {m_se_str} | {m_mae_str} | {m_rmse_str} | {m_agg['executable_rate']:.1%} | {m_agg['pass_k']:.1%} |\n")
            
        f.write("\n\n## 4. Evaluation and Transient Curves\n\n")
        for case in data:
            cid = case["case_id"]
            plot_relative = f"{cid}_curve_comparison.png"
            f.write(f"### Case: {cid}\n\n")
            f.write(f"![Transient Curve comparison]({plot_relative})\n\n")
            
        f.write("## 5. Architectural Findings\n")
        f.write(
            "- **LLM+MCP Behavior**: When provided with low-level SIRIO capabilities, the LLM attempts to construct "
            "the corresponding state space or Petri Net structure manually. This leverages formal verification methods "
            "but requires the LLM to successfully translate the Fault Tree logic gates into places, transitions, and enabling functions.\n"
            "- **LLM Direct Prompt Behavior**: When denied tool access, the LLM either uses textbook formula approximations or "
            "hallucinates mathematical probability calculations, leading to higher curve MAE/RMSE.\n"
        )

def write_markdown_report(
    driver: LLMDriver, 
    data: List[Dict[str, Any]], 
    output_dir: str, 
    samples: int, 
    k: int, 
    interaction_history: Optional[List[Dict[str, Any]]] = None
) -> None:
    """
    Generates a formal, dynamic evaluation report using the LLM.

    Args:
        driver: LLM connection manager.
        data: Evaluated test case results.
        output_dir: Target output directory path.
        samples: Samples per case.
        k: k value for Pass@k.
        interaction_history: Optional run logs.
    """
    report_path = os.path.join(output_dir, "benchmark_report.md")
    
    if isinstance(driver, MockLLMDriver):
        logger.info("Using deterministic fallback report writer for dry-run/mock mode.")
        write_local_report_fallback(data, report_path, samples, k)
        return
        
    interactions_summary = ""
    if interaction_history:
        interactions_summary = "\nHere is a summary of the LLM interactions during the experiment:\n"
        for item in interaction_history:
            interactions_summary += f"\n- Case: {item['case_id']}\n"
            interactions_summary += "  * Direct Prompt (No MCP) samples:\n"
            for run in item["no_mcp_runs"]:
                interactions_summary += f"    - Run {run['run_index']}: Latency={run['latency_seconds']:.2f}s, Success={run['success']}, Correct={run['correct']}, Error={run['error']}\n"
            interactions_summary += "  * Tool Calling (MCP) samples:\n"
            for run in item["mcp_runs"]:
                tcs = [f"{tc.get('tool')}({json.dumps(tc.get('args'))}) -> {json.dumps(tc.get('result'))}" for tc in run["tool_calls"]]
                tcs_str = " | ".join(tcs) if tcs else "None"
                interactions_summary += f"    - Run {run['run_index']}: Latency={run['latency_seconds']:.2f}s, Success={run['success']}, Correct={run['correct']}, ToolCalls=[{tcs_str}], Error={run['error']}\n"

    prompt = f"""You are a reliability engineering and academic writing expert. Your task is to write a formal, technical evaluation report summarizing the findings of a benchmarking experiment.
 
The experiment compared:
1. Baseline (Ground Truth): Petri Net formal execution via the SIRIO library (Java).
2. LLM without MCP: Direct prompting of the model.
3. LLM+MCP: The model with low-level Petri Net tool access (places, transitions, markings, analysis executions).
 
Here is the structured data collected from the experiment:
{json.dumps(data, indent=2)}

Here is the detailed trace of the LLM interaction history (prompts, tool calls, results):
{interactions_summary}
 
Parameters:
- Samples per case: {samples}
- Pass@k (k): {k}
 
Please generate the report in raw Markdown. Follow this structure strictly:
 
# Quantitative Benchmark Report: LLM vs LLM+MCP on Fault Tree Unreliability
 
## 1. Executive Summary
[Summarize the goal of comparing LLM vs LLM+MCP on quantitative fault tree analysis, the findings, and the main conclusions.]
 
## 2. Experimental Setup
[Detail the methodology, model used, baseline solver (SIRIO), and the tools made available to LLM+MCP (low-level Petri net building blocks without higher-level fault tree concepts).]
 
## 3. Comparative Performance Metrics
[Provide a markdown table summarizing the performance metrics. You MUST build the table based on the provided JSON data. Include columns for Case ID, Config, Steady-State Prob, SS Abs Error, Curve MAE, Curve RMSE, Executable Rate, and Pass@k.]
 
## 4. Evaluation and Transient Curves
[For each case, include a sub-section with the comparison plot. Example format:
### Case: <case_id>
![Transient Curve comparison](<plot_relative_path>)
Add some brief observations on the curve alignments.]
 
## 5. Architectural Findings & Discussion
[Provide a detailed and rigorous technical analysis. Discuss:
- The challenge of translating a Fault Tree logic expression into low-level Petri Net components (places, transitions, enabling functions).
- Why the LLM+MCP configuration might fail or succeed depending on the model's capability to structure state spaces.
  Make specific observations on what actually happened during the MCP calls (which tools were launched, what results or errors they produced) by referencing the interaction trace details.
- Why the LLM without MCP is prone to mathematical approximations or hallucinations, leading to higher transient curve errors.
- Recommendations for future MCP tool designs (e.g., higher-level fault tree gates vs low-level Petri net primitives).]
 
Do not wrap the output in markdown code blocks (e.g. do not start with ```markdown and do not end with ```). Return only the raw markdown content itself.
"""
 
    logger.info("Invoking LLM to generate formal benchmark report...")
    try:
        report_content = driver.generate(prompt, "You are a technical report writing assistant. You must produce output in raw Markdown format.")
        
        if report_content.startswith("```markdown"):
            report_content = report_content.split("```markdown", 1)[1]
        elif report_content.startswith("```"):
            report_content = report_content.split("```", 1)[1]
        if report_content.endswith("```"):
            report_content = report_content.rsplit("```", 1)[0]
        report_content = report_content.strip()
 
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Dynamic LLM benchmark report generated successfully at: {report_path}")
    except Exception as e:
        logger.error(f"Failed to generate benchmark report via LLM: {e}")
        logger.warning("Falling back to local report generation due to LLM error.")
        write_local_report_fallback(data, report_path, samples, k)
        logger.info(f"Fallback benchmark report generated successfully at: {report_path}")
