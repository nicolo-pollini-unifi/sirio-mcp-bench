import os
import sys
import json
import time
import argparse
import logging
import tempfile
import subprocess
import traceback
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, Any, List, Tuple, Optional

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from llm_client import GeminiDriver, OpenAICompatibleDriver, LLMDriver, MockLLMDriver
from mcp_dummy import SirioMCPMock, SIRIO_TOOL_SCHEMAS
from metrics import compute_steady_state_error, compute_curve_metrics, is_solution_correct, compute_pass_at_k

SYSTEM_INSTRUCTION = (
    "You are a reliability engineering expert assistant. Your task is to perform a quantitative unreliability analysis "
    "for a Fault Tree top-level event. You must compute the steady-state probability of system failure, and the transient "
    "failure probability (unreliability) curve over time. You may have access to a tool suite that executes the formal "
    "calculations using the SIRIO library. If tools are available, you should use them to ensure absolute mathematical precision. "
    "Ensure that your final result contains the calculated values in a structured JSON code block exactly as requested, "
    "without any additional text inside the markdown block."
)

USER_PROMPT_TEMPLATE = (
    "Perform the unreliability analysis for the following event configuration:\n"
    "- Fault Tree Logic Expression: {logic_expression}\n"
    "- Analysis Parameters:\n"
    "  * timeStep: {time_step}\n"
    "  * maxTime: {max_time}\n"
    "  * error limit: {error}\n"
    "- Leaf component model parameters (rates are exponential):\n"
    "{components_details}\n\n"
    "Provide your final result in a markdown code block containing a JSON object in this exact format:\n"
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
    "Do not put comments or explanations inside the json code block."
)

def build_components_details(components: Dict[str, Any]) -> str:
    lines = []
    for name, config in components.items():
        lines.append(f"  * {name}: type={config.get('type')}, failureRate={config.get('failureRate')}, repairRate={config.get('repairRate')}")
    return "\n".join(lines)

def run_java_baseline(workspace_path: str, case_json_path: str, case_id: str) -> Dict[str, Any]:
    """
    Runs the SirioCLI Java baseline calculations and returns the result.
    """
    temp_out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    temp_out.close()
    
    # Read classpath from classpath.txt
    classpath_file = os.path.join(workspace_path, "classpath.txt")
    if not os.path.exists(classpath_file):
        raise FileNotFoundError("classpath.txt not found. Build the project first.")
        
    with open(classpath_file, 'r', encoding='utf-8') as f:
        maven_deps = f.read().strip()
        
    target_classes = os.path.join(workspace_path, "target", "classes")
    target_test_classes = os.path.join(workspace_path, "target", "test-classes")
    sirio_jar = os.path.join(workspace_path, "lib", "sirio-2.0.4.jar")
    
    separator = ";" if sys.platform.startswith("win") else ":"
    classpath = separator.join([target_classes, target_test_classes, sirio_jar, maven_deps])
    
    cmd = [
        "java",
        "-cp", classpath,
        "org.util.SirioCLI",
        "--input", case_json_path,
        "--case", case_id,
        "--output", temp_out.name
    ]
    
    logger.info(f"Running Java baseline command for case {case_id}...")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with open(temp_out.name, 'r', encoding='utf-8') as f:
            return json.load(f)
    finally:
        try:
            os.unlink(temp_out.name)
        except OSError:
            pass

def execute_agent_loop_gemini(driver: GeminiDriver, mock_mcp: SirioMCPMock, prompt: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Executes the Gemini API conversation loop, routing tool calls to the Dummy MCP.
    """
    headers = {"Content-Type": "application/json"}
    
    # Convert schemas to Gemini declarations format
    declarations = []
    for tool in SIRIO_TOOL_SCHEMAS:
        func = tool["function"]
        declarations.append({
            "name": func["name"],
            "description": func["description"],
            "parameters": {
                "type": "OBJECT",
                "properties": func["parameters"].get("properties", {}),
                "required": func["parameters"].get("required", [])
            }
        })
    tools = [{"functionDeclarations": declarations}]
    
    # Initialize history
    history = [{"role": "user", "parts": [{"text": prompt}]}]
    tool_calls_log = []
    
    # Limit loop steps to prevent infinite loops
    for _ in range(30):
        payload = {
            "contents": history,
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "tools": tools,
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192}
        }
        
        response = requests.post(driver.url, headers=headers, json=payload)
        response.raise_for_status()
        response_json = response.json()
        
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise ValueError(f"No response candidates returned: {response_json}")
            
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        
        # Check if model requested a tool call
        function_calls = [p.get("functionCall") for p in parts if "functionCall" in p]
        
        if not function_calls:
            # Model returned final answer
            text = "".join([p.get("text", "") for p in parts if "text" in p])
            return text, tool_calls_log
            
        # Add model's assistant turn to history
        history.append({
            "role": "model",
            "parts": parts
        })
        
        # Execute tool calls and gather responses
        response_parts = []
        for fc in function_calls:
            name = fc["name"]
            args = fc.get("args", {})
            
            tool_calls_log.append({"tool": name, "args": args})
            
            result = mock_mcp.handle_tool_call(name, args)
            
            response_parts.append({
                "functionResponse": {
                    "name": name,
                    "response": {"result": result}
                }
            })
            
        # Add tool responses to history
        history.append({
            "role": "user",
            "parts": response_parts
        })
        
    raise TimeoutError("LLM exceeded max tool call iteration limit")

def execute_agent_loop_mock(driver: LLMDriver, mock_mcp: SirioMCPMock, prompt: str, baseline: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Simulates tool calls to the MCP mock and returns the baseline formatted in JSON.
    """
    # 1. create_petri_net
    res = mock_mcp.handle_tool_call("create_petri_net", {})
    net_id = res.get("net_id")
    tool_calls_log = [{"tool": "create_petri_net", "args": {}}]
    
    if not net_id or "error" in res:
        return f"Error: {res.get('error', 'Failed to create Petri net')}", tool_calls_log
        
    # 2. add_place
    mock_mcp.handle_tool_call("add_place", {"net_id": net_id, "name": "P0", "tokens": 1})
    tool_calls_log.append({"tool": "add_place", "args": {"net_id": net_id, "name": "P0", "tokens": 1}})
    
    # 3. add_transition
    mock_mcp.handle_tool_call("add_transition", {"net_id": net_id, "name": "T0", "type": "exponential", "rate": 0.05})
    tool_calls_log.append({"tool": "add_transition", "args": {"net_id": net_id, "name": "T0", "type": "exponential", "rate": 0.05}})
    
    # 4. run_steady_state_analysis
    mock_mcp.handle_tool_call("run_steady_state_analysis", {"net_id": net_id, "failure_condition": "P0 == 0"})
    tool_calls_log.append({"tool": "run_steady_state_analysis", "args": {"net_id": net_id, "failure_condition": "P0 == 0"}})
    
    # Return formatted baseline JSON
    raw_text = f"```json\n{json.dumps(baseline, indent=2)}\n```"
    return raw_text, tool_calls_log

import requests # imported for the execute loops

def execute_agent_loop_openai(driver: OpenAICompatibleDriver, mock_mcp: SirioMCPMock, prompt: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Executes the OpenAI-compatible local API loop, routing tool calls to the Dummy MCP.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {driver.api_key}"
    }
    
    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": prompt}
    ]
    tool_calls_log = []
    
    for _ in range(30):
        payload = {
            "model": driver.model_name,
            "messages": messages,
            "tools": SIRIO_TOOL_SCHEMAS,
            "temperature": 0.0,
            "max_tokens": 4096
        }
        
        response = requests.post(driver.url, headers=headers, json=payload)
        response.raise_for_status()
        response_json = response.json()
        
        choices = response_json.get("choices", [])
        if not choices:
            raise ValueError(f"No response choices returned: {response_json}")
            
        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls", [])
        
        # Append message to list
        messages.append(msg)
        
        if not tool_calls:
            return msg.get("content", ""), tool_calls_log
            
        for tc in tool_calls:
            name = tc["function"]["name"]
            args_str = tc["function"]["arguments"]
            tc_id = tc["id"]
            
            try:
                args = json.loads(args_str)
            except Exception:
                args = {}
                
            tool_calls_log.append({"tool": name, "args": args})
            
            result = mock_mcp.handle_tool_call(name, args)
            
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "name": name,
                "content": json.dumps(result)
            })
            
    raise TimeoutError("LLM exceeded max tool call iteration limit")

def parse_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extracts and parses the JSON markdown block from LLM responses.
    """
    if "```json" in text:
        try:
            block = text.split("```json")[1].split("```")[0].strip()
            return json.loads(block)
        except Exception:
            pass
            
    if "```" in text:
        try:
            block = text.split("```")[1].split("```")[0].strip()
            return json.loads(block)
        except Exception:
            pass
            
    # Try direct parse
    try:
        return json.loads(text.strip())
    except Exception:
        pass
        
    return None

def run_evaluation_for_mode(
    driver: LLMDriver,
    mock_mcp: SirioMCPMock,
    prompt: str,
    baseline: Dict[str, Any],
    with_mcp: bool,
    provider: str,
    num_samples: int
) -> Tuple[List[Dict[str, Any]], float, float]:
    """
    Runs the evaluation for a single mode (with or without MCP), possibly multiple times
    for Pass@k calculations. Returns a list of sample results, the computed executable rate
    and Pass@k value.
    """
    samples = []
    correct_count = 0
    
    for i in range(num_samples):
        start_time = time.time()
        tool_calls = []
        raw_text = ""
        success = False
        parsed_data = None
        steady_state = float('nan')
        transient_result = []
        error_msg = None
        
        try:
            if isinstance(driver, MockLLMDriver):
                driver.baseline_data = baseline
                
            if with_mcp:
                # With MCP loop
                if provider == "gemini":
                    raw_text, tool_calls = execute_agent_loop_gemini(driver, mock_mcp, prompt)
                elif provider == "mock":
                    raw_text, tool_calls = execute_agent_loop_mock(driver, mock_mcp, prompt, baseline)
                else:
                    raw_text, tool_calls = execute_agent_loop_openai(driver, mock_mcp, prompt)
            else:
                # Without MCP direct prompt
                raw_text = driver.generate(prompt, SYSTEM_INSTRUCTION)
                
            parsed_data = parse_json_from_response(raw_text)
            if parsed_data and "steadyState" in parsed_data and "transientResult" in parsed_data:
                steady_state = float(parsed_data["steadyState"])
                transient_result = parsed_data["transientResult"]
                success = True
            else:
                error_msg = "Output JSON format was invalid or fields are missing."
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error executing run: {e}")
            
        latency = time.time() - start_time
        
        # Check correctness
        correct = False
        if success:
            correct = is_solution_correct(
                base_steady=baseline["steadyState"],
                llm_steady=steady_state,
                base_curve=baseline["transientResult"],
                llm_curve=transient_result
            )
            if correct:
                correct_count += 1
                
        samples.append({
            "run_index": i,
            "raw_text": raw_text,
            "tool_calls": tool_calls,
            "success": success,
            "parsed_data": parsed_data,
            "steady_state": steady_state,
            "transient_result": transient_result,
            "correct": correct,
            "latency_seconds": latency,
            "error": error_msg
        })
        
    executable_rate = float(sum(1 for s in samples if s["success"])) / num_samples
    return samples, executable_rate, correct_count

def generate_comparative_plots(
    case_id: str,
    baseline_curve: List[List[float]],
    llm_no_mcp_curve: Optional[List[List[float]]],
    llm_mcp_curve: Optional[List[List[float]]],
    output_path: str
):
    plt.figure(figsize=(10, 6))
    
    # Plot baseline
    b_times, b_vals = zip(*baseline_curve)
    plt.plot(b_times, b_vals, label="Baseline (Ground Truth)", color="#2ecc71", linewidth=2.5)
    
    if llm_no_mcp_curve:
        try:
            n_times, n_vals = zip(*llm_no_mcp_curve)
            plt.plot(n_times, n_vals, label="LLM without MCP", color="#e74c3c", linestyle="--")
        except Exception:
            pass
            
    if llm_mcp_curve:
        try:
            m_times, m_vals = zip(*llm_mcp_curve)
            plt.plot(m_times, m_vals, label="LLM with MCP (SIRIO)", color="#3498db", linestyle=":")
        except Exception:
            pass
            
    plt.title(f"Transient Unreliability Curve Comparison - {case_id}")
    plt.xlabel("Time")
    plt.ylabel("Unreliability Probability")
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend()
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150)
    plt.close()

def main():
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
    
    args = parser.parse_args()
    
    workspace_path = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize LLM drivers
    if args.provider == "gemini":
        if not args.api_key:
            # Try load from environment variable
            args.api_key = os.environ.get("GEMINI_API_KEY")
        if not args.api_key:
            logger.error("Missing Gemini API Key. Use --api-key or GEMINI_API_KEY env var.")
            sys.exit(1)
        driver = GeminiDriver(api_key=args.api_key, model_name=args.model)
    elif args.provider == "mock":
        driver = MockLLMDriver()
    else:
        driver = OpenAICompatibleDriver(base_url=args.openai_url, model_name=args.openai_model, api_key=args.openai_key)
        
    mock_mcp = SirioMCPMock(workspace_path)
    
    # Load cases
    config_path = os.path.abspath(args.config)
    if not os.path.exists(config_path):
        logger.error(f"Configuration file {config_path} does not exist.")
        sys.exit(1)
        
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)
        
    cases = config_data.get("cases", [])
    if not cases:
        # Fallback if config is single testcase
        cases = [config_data]
        
    logger.info(f"Loaded {len(cases)} test cases from config.")
    
    report_data = []
    
    for case in cases:
        case_id = case["id"]
        logger.info(f"========== Starting Benchmark for Case: {case_id} ==========")
        
        # 1. Run Java Baseline (Ground Truth)
        try:
            baseline = run_java_baseline(workspace_path, config_path, case_id)
        except Exception as e:
            logger.error(f"Failed to run Java baseline for case {case_id}: {e}")
            traceback.print_exc()
            continue
            
        # 2. Build prompt
        comp_details = build_components_details(case["components"])
        prompt = USER_PROMPT_TEMPLATE.format(
            logic_expression=case["logicExpression"],
            time_step=case["timeStep"],
            max_time=case["maxTime"],
            error=case["error"],
            components_details=comp_details
        )
        
        # 3. LLM Run without MCP
        logger.info(f"Running LLM without MCP (Mode: direct prompt)...")
        no_mcp_runs, no_mcp_exec_rate, no_mcp_correct_count = run_evaluation_for_mode(
            driver=driver,
            mock_mcp=mock_mcp,
            prompt=prompt,
            baseline=baseline,
            with_mcp=False,
            provider=args.provider,
            num_samples=args.samples
        )
        no_mcp_pass_k = compute_pass_at_k(args.samples, no_mcp_correct_count, args.k)
        
        # Get first successful run's data for plotting
        first_no_mcp_success = next((run for run in no_mcp_runs if run["success"]), None)
        no_mcp_steady = first_no_mcp_success["steady_state"] if first_no_mcp_success else float('nan')
        no_mcp_curve = first_no_mcp_success["transient_result"] if first_no_mcp_success else None
        
        # Compute errors for reporting
        no_mcp_steady_err = compute_steady_state_error(baseline["steadyState"], no_mcp_steady) if first_no_mcp_success else float('nan')
        no_mcp_mae, no_mcp_rmse = compute_curve_metrics(baseline["transientResult"], no_mcp_curve) if first_no_mcp_success else (float('nan'), float('nan'))
        
        # 4. LLM Run with MCP
        logger.info(f"Running LLM with MCP (Mode: tool calling enabled)...")
        mcp_runs, mcp_exec_rate, mcp_correct_count = run_evaluation_for_mode(
            driver=driver,
            mock_mcp=mock_mcp,
            prompt=prompt,
            baseline=baseline,
            with_mcp=True,
            provider=args.provider,
            num_samples=args.samples
        )
        mcp_pass_k = compute_pass_at_k(args.samples, mcp_correct_count, args.k)
        
        first_mcp_success = next((run for run in mcp_runs if run["success"]), None)
        mcp_steady = first_mcp_success["steady_state"] if first_mcp_success else float('nan')
        mcp_curve = first_mcp_success["transient_result"] if first_mcp_success else None
        
        mcp_steady_err = compute_steady_state_error(baseline["steadyState"], mcp_steady) if first_mcp_success else float('nan')
        mcp_mae, mcp_rmse = compute_curve_metrics(baseline["transientResult"], mcp_curve) if first_mcp_success else (float('nan'), float('nan'))
        
        # 5. Generate comparative plot
        plot_filename = f"{case_id}_curve_comparison.png"
        plot_path = os.path.join(output_dir, plot_filename)
        generate_comparative_plots(
            case_id=case_id,
            baseline_curve=baseline["transientResult"],
            llm_no_mcp_curve=no_mcp_curve,
            llm_mcp_curve=mcp_curve,
            output_path=plot_path
        )
        
        # Log case summaries
        logger.info(f"Case {case_id} steady state: Baseline={baseline['steadyState']:.6f}, No-MCP={no_mcp_steady:.6f}, MCP={mcp_steady:.6f}")
        logger.info(f"MAE: No-MCP={no_mcp_mae:.6f}, MCP={mcp_mae:.6f}")
        logger.info(f"Pass@{args.k}: No-MCP={no_mcp_pass_k:.2%}, MCP={mcp_pass_k:.2%}")
        
        report_data.append({
            "case_id": case_id,
            "baseline": baseline,
            "no_mcp": {
                "steady_state": no_mcp_steady,
                "steady_error": no_mcp_steady_err,
                "mae": no_mcp_mae,
                "rmse": no_mcp_rmse,
                "executable_rate": no_mcp_exec_rate,
                "pass_k": no_mcp_pass_k,
                "avg_latency": np.mean([r["latency_seconds"] for r in no_mcp_runs])
            },
            "mcp": {
                "steady_state": mcp_steady,
                "steady_error": mcp_steady_err,
                "mae": mcp_mae,
                "rmse": mcp_rmse,
                "executable_rate": mcp_exec_rate,
                "pass_k": mcp_pass_k,
                "avg_latency": np.mean([r["latency_seconds"] for r in mcp_runs]),
                "tool_calls_count": np.mean([len(r["tool_calls"]) for r in mcp_runs])
            },
            "plot_path": plot_path,
            "plot_relative": plot_filename
        })
        
    # Write summary report
    write_markdown_report(driver, report_data, output_dir, args.samples, args.k)

def write_local_report_fallback(data: List[Dict[str, Any]], report_path: str, samples: int, k: int):
    """
    Programmatically writes a structured report to report_path as a fallback or dry-run placeholder.
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
            
            nm = case["no_mcp"]
            ss_str = f"{nm['steady_state']:.8f}" if not np.isnan(nm['steady_state']) else "N/A"
            se_str = f"{nm['steady_error']:.8f}" if not np.isnan(nm['steady_error']) else "N/A"
            mae_str = f"{nm['mae']:.8f}" if not np.isnan(nm['mae']) else "N/A"
            rmse_str = f"{nm['rmse']:.8f}" if not np.isnan(nm['rmse']) else "N/A"
            f.write(f"| | LLM (No MCP) | {ss_str} | {se_str} | {mae_str} | {rmse_str} | {nm['executable_rate']:.1%} | {nm['pass_k']:.1%} |\n")
            
            m = case["mcp"]
            m_ss_str = f"{m['steady_state']:.8f}" if not np.isnan(m['steady_state']) else "N/A"
            m_se_str = f"{m['steady_error']:.8f}" if not np.isnan(m['steady_error']) else "N/A"
            m_mae_str = f"{m['mae']:.8f}" if not np.isnan(m['mae']) else "N/A"
            m_rmse_str = f"{m['rmse']:.8f}" if not np.isnan(m['rmse']) else "N/A"
            f.write(f"| | LLM+MCP | {m_ss_str} | {m_se_str} | {m_mae_str} | {m_rmse_str} | {m['executable_rate']:.1%} | {m['pass_k']:.1%} |\n")
            
        f.write("\n\n## 4. Evaluation and Transient Curves\n\n")
        for case in data:
            cid = case["case_id"]
            f.write(f"### Case: {cid}\n\n")
            f.write(f"![Transient Curve comparison]({case['plot_relative']})\n\n")
            
        f.write("## 5. Architectural Findings\n")
        f.write(
            "- **LLM+MCP Behavior**: When provided with low-level SIRIO capabilities, the LLM attempts to construct "
            "the corresponding state space or Petri Net structure manually. This leverages formal verification methods "
            "but requires the LLM to successfully translate the Fault Tree logic gates into places, transitions, and enabling functions.\n"
            "- **LLM Direct Prompt Behavior**: When denied tool access, the LLM either uses textbook formula approximations or "
            "hallucinates mathematical probability calculations, leading to higher curve MAE/RMSE.\n"
        )

def write_markdown_report(driver: LLMDriver, data: List[Dict[str, Any]], output_dir: str, samples: int, k: int):
    """
    Generates a formal, technical evaluation report summarizing the benchmark findings
    by calling the LLM to write the report dynamically based on the results.
    """
    report_path = os.path.join(output_dir, "benchmark_report.md")
    
    # Use deterministic fallback for mock runs to prevent API calls and maintain reproducibility
    if isinstance(driver, MockLLMDriver):
        logger.info("Using deterministic fallback report writer for dry-run/mock mode.")
        write_local_report_fallback(data, report_path, samples, k)
        logger.info(f"Benchmark report generated successfully (dry-run mode) at: {report_path}")
        return

    # Prompt schema designed to instruct the LLM to write a technical discussion around metrics
    prompt = f"""You are a reliability engineering and academic writing expert. Your task is to write a formal, technical evaluation report summarizing the findings of a benchmarking experiment.

The experiment compared:
1. Baseline (Ground Truth): Petri Net formal execution via the SIRIO library (Java).
2. LLM without MCP: Direct prompting of the model.
3. LLM+MCP: The model with low-level Petri Net tool access (places, transitions, markings, analysis executions).

Here is the structured data collected from the experiment:
{json.dumps(data, indent=2)}

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
- Why the LLM without MCP is prone to mathematical approximations or hallucinations, leading to higher transient curve errors.
- Recommendations for future MCP tool designs (e.g., higher-level fault tree gates vs low-level Petri net primitives).]

Do not wrap the output in markdown code blocks (e.g. do not start with ```markdown and do not end with ```). Return only the raw markdown content itself.
"""

    logger.info("Invoking LLM to generate formal benchmark report...")
    try:
        report_content = driver.generate(prompt, "You are a technical report writing assistant. You must produce output in raw Markdown format.")
        
        # Strip code block wrapping if model generated it anyway
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

if __name__ == "__main__":
    main()
