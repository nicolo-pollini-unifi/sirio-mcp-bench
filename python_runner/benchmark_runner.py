import os
import sys
import json
import time
import argparse
import logging
import tempfile
import subprocess
import traceback
import requests
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, Any, List, Tuple, Optional
from dotenv import load_dotenv
from pathlib import Path
from difflib import SequenceMatcher

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from llm_client import GeminiDriver, OpenAICompatibleDriver, LLMDriver, MockLLMDriver
from llm_adapters import GeminiAdapter, OpenAIAdapter
from mcp_client import BaseMCPClient, SirioMCPMock, SirioMCPRealClient
from metrics import compute_steady_state_error, compute_curve_metrics, is_solution_correct, compute_pass_at_k
from graph_isomorphism import are_petri_nets_isomorphic

class AgentLoopError(Exception):
    """Base exception per tutti i fallimenti del loop agentico."""
    pass

class SemanticLoopError(AgentLoopError):
    """Il modello ripete reasoning o tool call quasi identici senza progresso."""
    pass

class MaxTurnsExceededError(AgentLoopError):
    """Limite massimo di turni raggiunto senza output valido."""
    pass

class ToolCallBudgetExceededError(AgentLoopError):
    """Numero totale di tool call ha superato il budget consentito."""
    pass

class NetworkError(AgentLoopError):
    """Errore di rete/timeout durante la chiamata all'endpoint LLM."""
    pass

SYSTEM_INSTRUCTION = (
    '''You are a reliability engineering expert specializing in quantitative fault tree analysis.

    ## Objective
    Compute, for a given Fault Tree top-level event:
    1. **Steady-state failure probability** (limiting unreliability): the steady-state analysis must provide the asymptotic unreliability of the system model (i.e., the steady-state probability of the TOP event condition being active at regime, evaluated under the top-event absorption configuration).
        *Note: Do not assume that the request is a mistake or a trivial result. Even if the limiting unreliability is known to converge to a certain value, you must not skip the derivation steps to formally obtain the result rather than stating it without analysis.*
    2. **Transient unreliability curve** Q(t) over time: the cumulative probability of system failure over the time horizon $[0, T]$, sampled at discrete time steps $t_k$ according to the specified analysis parameters, evaluated with top-event absorption active.

    ## Petri Net Modeling Rules
    - Model each component as a Gilbert-Elliot net: the transition rates must be as specified in the prompt. Use enabling conditions as a link between nets of different levels.
    - Implement **repair arcs**: remove a gate's token when its activating condition no longer holds (i.e., one or more inputs are repaired).
    - **Single-fire gates (MANDATORY structural guard)**: every gate-fail transition MUST have an explicit input arc from a dedicated "armed" place (initial marking 1). This arc is a hard precondition for firing, separate from the enabling-function, a transition without this input arc is an invalid construction and must be corrected immediately before proceeding. Firing the gate-fail transition consumes the armed token, disabling the transition until the paired repair transition restores it. The repair transition fires only when its repair enabling-function holds and consumes only its own gate's token, never a sibling gate's.
    - **Top-event absorption**: the top-event place has no repair arc — system failure is absorbing. The top-event transition's `marking-update` must explicitly zero every place in the net except the top-event place (syntax: "p<i> 0" for each place), and it must have priority higher than any other immediate transition so it preempts intermediate gate updates.
    - Use `&&` for AND and `||` for OR in all enabling functions.

    ## Execution & Tool Guidelines
    - If external tools are available in your environment, you MUST use them as early as possible to construct the model and delegate all formal computations to maintain mathematical precision.
    - Validate your model structure (e.g., confirm armed input arcs exist) before executing solvers.
    - Do **not** approximate math manually if formal tool execution is available.

    ## Output Format
    Your final quantitative result MUST be provided as a JSON block matching this exact structure:

    ```json
    {
        "steadyState": <number>,
        "transientResult": [
            [0.0, 0.0],
            [<t1>, <prob1>],
            ...
        ]
    }
    ```
    '''   
)


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

def build_components_details(components: Dict[str, Any]) -> str:
    lines = []
    for name, config in components.items():
        lines.append(f"  * {name}: type={config.get('type')}, failureRate={config.get('failureRate')}, repairRate={config.get('repairRate')}")
    return "\n".join(lines)

def save_report_data_json(report_data: List[Dict[str, Any]], output_root: str, timestamp: str) -> str:
    """Save the collected benchmark report data as JSON under output/experiment_[timestamp]."""
    report_dir = os.path.join(output_root, f"experiments/experiment_{timestamp}")
    if not os.path.exists(report_dir):
        os.makedirs(report_dir, exist_ok=True)

    report_path = os.path.join(report_dir, "report_data.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    logger.info("Saved report_data JSON to %s", report_path)
    return report_path

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

def execute_agent_loop_mock(driver: LLMDriver, mcp_client: BaseMCPClient, prompt: str, baseline: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Simulates tool calls to the MCP mock or real client and returns the baseline formatted in JSON.
    """
    tools = mcp_client.list_tools()
    has_real_tools = any(t.get("function", {}).get("name") == "create" for t in tools)
    
    tool_calls_log = []
    interactions_trace = []
    
    # Helper to map arguments based on what parameter names the MCP server/mock expects
    def map_args(tool_name: str, args_dict: Dict[str, Any]) -> Dict[str, Any]:
        tool_schema = next((t for t in tools if t.get("function", {}).get("name") == tool_name), None)
        if not tool_schema:
            return args_dict
        properties = tool_schema.get("function", {}).get("parameters", {}).get("properties", {})
        if "arg0" in properties:
            mapped = {}
            order_map = {
                "add_places": ["node_names"],
                "add_tokens": ["name", "num"],
                "add_transitions": ["transition_names"],
                "add_precondition": ["place_name", "transition_name"],
                "add_postcondition": ["place_name", "transition_name"],
                "add_EXP": ["transition_name", "rate"]
            }
            if tool_name in order_map:
                param_names = order_map[tool_name]
                for idx, orig_name in enumerate(param_names):
                    if orig_name in args_dict:
                        mapped[f"arg{idx}"] = args_dict[orig_name]
                return mapped
        return args_dict

    def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        res = mcp_client.handle_tool_call(name, args)
        tool_calls_log.append({"tool": name, "args": args, "result": res})
        interactions_trace.append({
            "type": "tool_call",
            "name": name,
            "args": args,
            "result": res
        })
        return res
        
    disclaimer = "/* DISCLAIMER: This is a simulated/mock agent tool-use workflow. */"
    interactions_trace.append({"type": "text", "content": f"{disclaimer}\nInitial prompt received. Constructing unreliability analysis Petri net structure..."})
    
    if has_real_tools:
        # 1. create
        interactions_trace.append({"type": "text", "content": "Creating new empty Petri net..."})
        call_tool("create", {})
        
        # 2. add_places
        interactions_trace.append({"type": "text", "content": "Adding state places (P0, P1)..."})
        call_tool("add_places", map_args("add_places", {"node_names": ["P0", "P1"]}))
        
        # 3. add_tokens
        interactions_trace.append({"type": "text", "content": "Setting initial tokens count..."})
        call_tool("add_tokens", map_args("add_tokens", {"name": "P0", "num": 1}))
        
        # 4. add_transitions
        interactions_trace.append({"type": "text", "content": "Adding transitions..."})
        call_tool("add_transitions", map_args("add_transitions", {"transition_names": ["T0"]}))
        
        # 5. add_precondition
        interactions_trace.append({"type": "text", "content": "Connecting places to transitions (preconditions)..."})
        call_tool("add_precondition", map_args("add_precondition", {"place_name": "P0", "transition_name": "T0"}))
        
        # 6. add_postcondition
        interactions_trace.append({"type": "text", "content": "Connecting transitions to places (postconditions)..."})
        call_tool("add_postcondition", map_args("add_postcondition", {"place_name": "P1", "transition_name": "T0"}))
        
        # 7. add_EXP
        interactions_trace.append({"type": "text", "content": "Configuring transition stochastic parameters..."})
        call_tool("add_EXP", map_args("add_EXP", {"transition_name": "T0", "rate": 0.05}))
        
        # 8. execute_steady_state_analysis
        interactions_trace.append({"type": "text", "content": "Executing steady state analysis on the network..."})
        call_tool("execute_steady_state_analysis", {})
        
    else:
        # Fallback to fittizio mock tool sequence
        interactions_trace.append({"type": "text", "content": "Initializing mock Petri net instance..."})
        res = call_tool("create_petri_net", {})
        net_id = res.get("net_id")
        
        if net_id and "error" not in res:
            interactions_trace.append({"type": "text", "content": "Adding place P0 with 1 token..."})
            call_tool("add_place", {"net_id": net_id, "name": "P0", "tokens": 1})
            
            interactions_trace.append({"type": "text", "content": "Adding transition T0..."})
            call_tool("add_transition", {"net_id": net_id, "name": "T0", "type": "exponential", "rate": 0.05})
            
            interactions_trace.append({"type": "text", "content": "Executing unreliability analysis on P0..."})
            call_tool("run_steady_state_analysis", {"net_id": net_id, "failure_condition": "P0 == 0"})

    # Return formatted baseline JSON with explanation and disclaimer
    reasoning = (
        f"{disclaimer}\n\n"
        "Using the MCP tool suite to analyze the Fault Tree unreliability:\n"
        "1. Created a new Petri net instance.\n"
        "2. Added places and initial tokens for the component states.\n"
        "3. Added transitions and set their exponential failure/repair rates.\n"
        "4. Connected places and transitions using preconditions and postconditions.\n"
        "5. Executed steady state and transient analysis tools to retrieve accurate numerical results.\n\n"
        f"```json\n{json.dumps(baseline, indent=2)}\n```"
    )
    interactions_trace.append({"type": "text", "content": reasoning})
    return reasoning, tool_calls_log, interactions_trace


# TODO aggiungere reasoning impostabile da CLI
# TODO vogliamo aggiungere una gestione del caso context length exceeded?
def execute_agent_loop(driver: LLMDriver, mcp_client: BaseMCPClient, prompt: str, max_turns: int = 100, seed: Optional[int] = None, stream: bool = False) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Unico entry point del loop agente. Seleziona l'adapter corretto in base
    al tipo di driver ricevuto e delega ad esso tutte le specificità del
    formato API, mentre l'algoritmo del loop (richiesta, parsing, tool calls,
    gestione troncamenti, timeout) resta condiviso e scritto una sola volta.
    """
    mcp_tools = mcp_client.list_tools()

    if isinstance(driver, GeminiDriver):
        adapter = GeminiAdapter(driver, mcp_tools, SYSTEM_INSTRUCTION, seed=seed)
    elif isinstance(driver, OpenAICompatibleDriver):
        adapter = OpenAIAdapter(driver, mcp_tools, SYSTEM_INSTRUCTION, seed=seed)
    else:
        raise ValueError(f"Unsupported driver type for execute_agent_loop: {type(driver).__name__}")

    adapter.init_conversation(prompt)

    tool_calls_log: List[Dict[str, Any]] = []
    interactions_trace: List[Dict[str, Any]] = []
    full_text = ""

    for turn in range(max_turns):

        logger.info("\n\n================================= AGENT TURN %d/%d =================================", turn + 1, max_turns)

        if turn == 0:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            msg_path = os.path.join("output", "messages", timestamp)
            if not os.path.exists(msg_path):
                os.makedirs(msg_path)

        out_path = Path(msg_path) / f"Turn{turn+1}.md"

        response_json = None
        text = ""
        calls = []
        raw_native_content = {}
        calls_with_results = []
        error_msg = None

        try:
            try:
                url, headers, payload = adapter.build_request()
                if stream and isinstance(driver, OpenAICompatibleDriver):
                    payload["stream"] = True
                    response = requests.post(url, headers=headers, json=payload, timeout=600, stream=True)
                    response.raise_for_status()
                    
                    accumulated_content = ""
                    accumulated_reasoning = ""
                    accumulated_tool_calls = {}
                    
                    has_started_reasoning = False
                    has_started_content = False
                    
                    for line in response.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode("utf-8").strip()
                        if line_str.startswith("data: "):
                            data_content = line_str[6:]
                            if data_content == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_content)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    
                                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                    if reasoning:
                                        if not has_started_reasoning:
                                            sys.stdout.write("\n[LLM Reasoning]: ")
                                            sys.stdout.flush()
                                            has_started_reasoning = True
                                        accumulated_reasoning += reasoning
                                        sys.stdout.write(reasoning)
                                        sys.stdout.flush()
                                        
                                    content = delta.get("content") or ""
                                    if content:
                                        if not has_started_content:
                                            sys.stdout.write("\n[LLM Response]: ")
                                            sys.stdout.flush()
                                            has_started_content = True
                                        accumulated_content += content
                                        sys.stdout.write(content)
                                        sys.stdout.flush()
                                        
                                    tool_calls_list = delta.get("tool_calls", [])
                                    for tc in tool_calls_list:
                                        idx = tc.get("index")
                                        if idx is None:
                                            continue
                                        if idx not in accumulated_tool_calls:
                                            accumulated_tool_calls[idx] = {
                                                "id": tc.get("id"),
                                                "type": "function",
                                                "function": {
                                                    "name": tc.get("function", {}).get("name") or "",
                                                    "arguments": tc.get("function", {}).get("arguments") or ""
                                                }
                                            }
                                        else:
                                            existing = accumulated_tool_calls[idx]
                                            if tc.get("id"):
                                                existing["id"] = tc.get("id")
                                            if tc.get("function", {}).get("name"):
                                                existing["function"]["name"] = tc["function"]["name"]
                                            if tc.get("function", {}).get("arguments"):
                                                existing["function"]["arguments"] += tc["function"]["arguments"]
                            except Exception:
                                pass
                    print()
                    
                    message_dict = {
                        "role": "assistant",
                        "content": accumulated_content
                    }
                    if accumulated_reasoning:
                        message_dict["reasoning_content"] = accumulated_reasoning
                    if accumulated_tool_calls:
                        message_dict["tool_calls"] = [
                            accumulated_tool_calls[k] for k in sorted(accumulated_tool_calls.keys())
                        ]
                    response_json = {
                        "choices": [
                            {
                                "message": message_dict
                            }
                        ]
                    }
                else:
                    response = requests.post(url, headers=headers, json=payload, timeout=600)
                    response.raise_for_status()
                    response_json = response.json()
            except requests.exceptions.RequestException as e:
                body = getattr(e.response, "text", "")[:1000] if getattr(e, "response", None) else ""
                raise NetworkError(f"HTTP request failed at turn {turn+1}: {e} | Response body: {body}") from e
            text, calls, raw_native_content = adapter.parse_response(response_json)
            
            if text:
                interactions_trace.append({"type": "text", "content": text})

            if not calls:
                full_text += text

                if "```json" in full_text and not parse_json_from_response(full_text):
                    adapter.append_assistant_turn(raw_native_content)
                    adapter.append_continuation_request()
                    continue

                return full_text, tool_calls_log, interactions_trace

            adapter.append_assistant_turn(raw_native_content)

            for call in calls:
                result = mcp_client.handle_tool_call(call["name"], call["args"])
                tool_calls_log.append({"tool": call["name"], "args": call["args"], "result": result})
                interactions_trace.append({"type": "tool_call", "name": call["name"], "args": call["args"], "result": result})
                calls_with_results.append({**call, "result": result})

            adapter.append_tool_results(calls_with_results)

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.exception("Error in turn %d", turn + 1)
            raise

        finally:
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(f"# Turn {turn+1}\n\n")

                    if error_msg:
                        f.write(f"Error: `{error_msg}`\n\n")

                    content_str = text or "_empty_"
                    reasoning_str = "_empty_"
                    if isinstance(raw_native_content, dict):
                        reasoning_str = raw_native_content.get("reasoning") or raw_native_content.get("reasoning_content") or "_empty_"

                    f.write("## Content\n\n")
                    f.write(content_str)
                    f.write("\n\n")

                    f.write("## Reasoning\n\n")
                    f.write(reasoning_str)
                    f.write("\n\n")

                    f.write("## Tool Calls\n\n")
                    if calls_with_results:
                        for i, call in enumerate(calls_with_results, 1):
                            f.write(f"### Tool Call {i}\n")
                            f.write(f"- Name: `{call.get('name', '_unknown_')}`\n")
                            f.write(f"- Args: `{call.get('args', '')}`\n")
                            f.write(f"- Result: `{call.get('result', '')}`\n\n")
                    elif calls:
                        for i, call in enumerate(calls, 1):
                            f.write(f"### Tool Call {i}\n")
                            f.write(f"- Name: `{call.get('name', '_unknown_')}`\n")
                            f.write(f"- Args: `{call.get('args', '')}`\n")
                            f.write("- Result: `_not executed_`\n\n")
                    else:
                        f.write("_No tool calls_\n\n")
            except Exception:
                logger.exception("Could not save dump of turn %d", turn + 1)

    raise MaxTurnsExceededError("LLM exceeded max tool call iteration limit")

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
        
def is_top_failure_marking(marking_str: str) -> bool:
    places = [p.strip().lower() for p in marking_str.split() if p.strip()]
    for p in places:
        if "top" in p and "armed" not in p and "ok" not in p and "work" not in p:
            return True
    return False

def parse_mcp_transient_result(tool_result: Any) -> List[Tuple[float, float]]:
    """
    Parses the transient analysis tool result into a sorted list of (time, probability) tuples.
    Handles both direct (time -> prob) dicts and full SIRIO marking dicts (time -> {Marking: prob}).
    """
    curve = []
    if isinstance(tool_result, dict):
        data_dict = tool_result.get("result") if isinstance(tool_result.get("result"), dict) else tool_result
        if isinstance(data_dict, dict):
            for k, v in data_dict.items():
                try:
                    t = float(k)
                    if isinstance(v, (int, float)):
                        p = float(v)
                        curve.append((t, p))
                    elif isinstance(v, dict):
                        p_val = 0.0
                        found_top = False
                        for marking_str, prob in v.items():
                            if is_top_failure_marking(str(marking_str)):
                                try:
                                    p_val += float(prob)
                                    found_top = True
                                except Exception:
                                    pass
                        if found_top:
                            curve.append((t, p_val))
                        elif len(v) == 1:
                            try:
                                curve.append((t, float(next(iter(v.values())))))
                            except Exception:
                                pass
                except (ValueError, TypeError):
                    continue
    elif isinstance(tool_result, list):
        for item in tool_result:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                try:
                    curve.append((float(item[0]), float(item[1])))
                except (ValueError, TypeError):
                    continue
    curve.sort(key=lambda x: x[0])
    return curve

def parse_mcp_steady_result(tool_result: Any) -> float:
    """
    Parses steady-state analysis tool result into a float for the top event.
    """
    if isinstance(tool_result, dict):
        for key in ["steady_state", "steadyState", "result"]:
            if key in tool_result:
                val = tool_result[key]
                if isinstance(val, (int, float)):
                    return float(val)
                try:
                    return float(val)
                except Exception:
                    pass
        p_val = 0.0
        found_top = False
        for marking_str, prob in tool_result.items():
            if is_top_failure_marking(str(marking_str)):
                try:
                    p_val += float(prob)
                    found_top = True
                except Exception:
                    pass
        if found_top:
            return p_val
        if len(tool_result) == 1:
            val = next(iter(tool_result.values()))
            try:
                return float(val)
            except Exception:
                pass
    elif isinstance(tool_result, (int, float)):
        return float(tool_result)
    return float('nan')

def clean_nan(val):
    if isinstance(val, (int, float)) and np.isnan(val):
        return None
    return val

class ProgressTracker:
    def __init__(self, total_evals: int):
        self.total_evals = total_evals
        self.completed_evals = 0
        self.start_time = time.time()

    def start_sample(self, case_id: str, with_mcp: bool, sample_index: int, total_samples: int):
        mode_str = "With MCP" if with_mcp else "No MCP"
        logger.info(
            f"\n>>> [Progress] Running evaluation {self.completed_evals + 1}/{self.total_evals} "
            f"(Case: {case_id}, Mode: {mode_str}, Sample: {sample_index + 1}/{total_samples})..."
        )

    def complete_sample(self):
        self.completed_evals += 1
        elapsed = time.time() - self.start_time
        avg_time = elapsed / self.completed_evals
        remaining = self.total_evals - self.completed_evals
        eta = avg_time * remaining
        
        eta_str = time.strftime('%H:%M:%S', time.localtime(time.time() + eta))
        logger.info(
            f">>> [Progress] Completed {self.completed_evals}/{self.total_evals}. "
            f"Elapsed: {elapsed:.1f}s, Avg: {avg_time:.1f}s/sample, "
            f"Est. Remaining: {eta:.1f}s (ETA: {eta_str})"
        )

def run_evaluation_for_mode(
    driver: LLMDriver,
    mcp_client: BaseMCPClient,
    prompt: str,
    baseline: Dict[str, Any],
    with_mcp: bool,
    provider: str,
    num_samples: int,
    verbose_interactions: bool = False,
    max_turns: int = 100,
    base_seed: Optional[int] = None,
    tracker: Optional[ProgressTracker] = None,
    case_id: str = "",
    stream: bool = False
) -> Tuple[List[Dict[str, Any]], float, float]:
    """
    Runs the evaluation for a single mode (with or without MCP), possibly multiple times
    for Pass@k calculations. Returns a list of sample results, the computed executable rate
    and Pass@k value.
    """
    samples = []
    correct_count = 0
    
    for i in range(num_samples):
        if tracker:
            tracker.start_sample(case_id, with_mcp, i, num_samples)
            
        start_time = time.time()
        tool_calls = []
        raw_text = ""
        success = False
        parsed_data = None
        steady_state = float('nan')
        transient_result = []
        error_msg = None
        error_type = None
        interactions_trace = []
        
        sample_seed = base_seed + i if base_seed is not None else None
        
        try:
            if isinstance(driver, MockLLMDriver):
                driver.baseline_data = baseline
                
            if with_mcp:
                # With MCP loop
                if provider == "mock":
                    raw_text, tool_calls, interactions_trace = execute_agent_loop_mock(driver, mcp_client, prompt, baseline)
                else:
                    raw_text, tool_calls, interactions_trace = execute_agent_loop(driver, mcp_client, prompt, max_turns, seed=sample_seed, stream=stream)
            else:
                # Without MCP direct prompt with continuation support
                if provider == "gemini":
                    headers = {"Content-Type": "application/json"}
                    history = [{"role": "user", "parts": [{"text": prompt}]}]
                    raw_text = ""
                    for turn in range(5):
                        logger.info(f"  [No-MCP] Turn {turn+1}/5: Requesting LLM...")
                        gen_config = {"temperature": driver.temperature, "maxOutputTokens": 8192}
                        if sample_seed is not None:
                            gen_config["seed"] = sample_seed
                        payload = {
                            "contents": history,
                            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
                            "generationConfig": gen_config
                        }
                        response = requests.post(driver.url, headers=headers, json=payload, timeout=120)
                        response.raise_for_status()
                        response_json = response.json()
                        candidates = response_json.get("candidates", [])
                        if not candidates:
                            logger.info(f"  [No-MCP] Turn {turn+1}/5: No candidates returned.")
                            break
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        text = "".join([p.get("text", "") for p in parts if "text" in p])
                        raw_text += text
                        interactions_trace.append({"type": "text", "content": text})
                        logger.info(f"  [No-MCP] Turn {turn+1}/5: Received response ({len(text)} chars).")
                        
                        if "```json" in raw_text and parse_json_from_response(raw_text):
                            logger.info("  [No-MCP] Found valid JSON results block. Ending early.")
                            break
                            
                        # If incomplete, append turns to history and continue
                        history.append({"role": "model", "parts": parts})
                        history.append({"role": "user", "parts": [{"text": "Your previous response was truncated. Please continue generating the JSON results block exactly from where you left off."}]})
                elif provider == "openai":
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {driver.api_key}"
                    }
                    messages = [
                        {"role": "system", "content": SYSTEM_INSTRUCTION},
                        {"role": "user", "content": prompt}
                    ]
                    raw_text = ""
                    for turn in range(5):
                        if stream:
                            logger.info(f"  [No-MCP] Turn {turn+1}/5: Requesting LLM (with streaming)...")
                            payload = {
                                "model": driver.model_name,
                                "messages": messages,
                                "temperature": driver.temperature,
                                "max_tokens": 8192,
                                "stream": True
                            }
                            if sample_seed is not None:
                                payload["seed"] = sample_seed
                            response = requests.post(driver.url, headers=headers, json=payload, timeout=120, stream=True)
                            response.raise_for_status()
                            
                            has_started_reasoning = False
                            has_started_content = False
                            chunk_text = ""
                            
                            for line in response.iter_lines():
                                if not line:
                                    continue
                                line_str = line.decode("utf-8").strip()
                                if line_str.startswith("data: "):
                                    data_content = line_str[6:]
                                    if data_content == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(data_content)
                                        choices = chunk.get("choices", [])
                                        if choices:
                                            delta = choices[0].get("delta", {})
                                            
                                            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                            if reasoning:
                                                if not has_started_reasoning:
                                                    sys.stdout.write("\n[LLM Reasoning]: ")
                                                    sys.stdout.flush()
                                                    has_started_reasoning = True
                                                sys.stdout.write(reasoning)
                                                sys.stdout.flush()
                                                
                                            content = delta.get("content") or ""
                                            if content:
                                                if not has_started_content:
                                                    sys.stdout.write("\n[LLM Response]: ")
                                                    sys.stdout.flush()
                                                    has_started_content = True
                                                chunk_text += content
                                                sys.stdout.write(content)
                                                sys.stdout.flush()
                                    except Exception:
                                        pass
                            print()
                            raw_text += chunk_text
                            interactions_trace.append({"type": "text", "content": chunk_text})
                            logger.info(f"  [No-MCP] Turn {turn+1}/5: Received response ({len(chunk_text)} chars).")
                            
                            if "```json" in raw_text and parse_json_from_response(raw_text):
                                logger.info("  [No-MCP] Found valid JSON results block. Ending early.")
                                break
                                
                            msg = {"role": "assistant", "content": chunk_text}
                            messages.append(msg)
                            messages.append({"role": "user", "content": "Your previous response was truncated. Please continue generating the JSON results block exactly from where you left off."})
                        else:
                            logger.info(f"  [No-MCP] Turn {turn+1}/5: Requesting LLM...")
                            payload = {
                                "model": driver.model_name,
                                "messages": messages,
                                "temperature": driver.temperature,
                                "max_tokens": 8192
                            }
                            if sample_seed is not None:
                                payload["seed"] = sample_seed
                            response = requests.post(driver.url, headers=headers, json=payload, timeout=120)
                            response.raise_for_status()
                            response_json = response.json()
                            choices = response_json.get("choices", [])
                            if not choices:
                                logger.info(f"  [No-MCP] Turn {turn+1}/5: No choices returned.")
                                break
                            msg = choices[0].get("message", {})
                            text = msg.get("content", "") or ""
                            raw_text += text
                            interactions_trace.append({"type": "text", "content": text})
                            logger.info(f"  [No-MCP] Turn {turn+1}/5: Received response ({len(text)} chars).")
                            
                            if "```json" in raw_text and parse_json_from_response(raw_text):
                                logger.info("  [No-MCP] Found valid JSON results block. Ending early.")
                                break
                                
                            messages.append(msg)
                            messages.append({"role": "user", "content": "Your previous response was truncated. Please continue generating the JSON results block exactly from where you left off."})
                else:
                    # Mock driver fallback
                    raw_text = driver.generate(prompt, SYSTEM_INSTRUCTION, seed=sample_seed)
                    interactions_trace.append({"type": "text", "content": raw_text})
                
            if verbose_interactions:
                logger.info(f"\n==================== [VERBOSE] Prompt Sent to LLM (MCP={with_mcp}, Sample={i}) ====================\n{prompt}\n========================================================================================\n")
                logger.info(f"\n==================== [VERBOSE] Raw LLM Response (MCP={with_mcp}, Sample={i}) ====================\n{raw_text}\n=======================================================================================\n")
                if tool_calls:
                    logger.info(f"\n==================== [VERBOSE] MCP Tool Call Trace (MCP={with_mcp}, Sample={i}) ====================\n{json.dumps(tool_calls, indent=2)}\n=======================================================================================\n")
                
            parsed_data = parse_json_from_response(raw_text)
            if parsed_data:
                steady_state = clean_nan(parsed_data.get("steadyState", float('nan')))
                transient_result = parsed_data.get("transientResult", [])
                success = True
                
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            logger.error(f"Error executing run: {e}")
            traceback.print_exc()
            
        latency = time.time() - start_time
        
        # Check correctness on LLM-reported metrics (Functional correctness)
        correct = False
        steady_error = float('nan')
        mae, rmse = float('nan'), float('nan')
        if success:
            correct = is_solution_correct(
                base_steady=baseline["steadyState"],
                llm_steady=steady_state,
                base_curve=baseline["transientResult"],
                llm_curve=transient_result
            )
            if correct:
                correct_count += 1
            
            steady_error = compute_steady_state_error(baseline["steadyState"], steady_state)
            mae, rmse = compute_curve_metrics(baseline["transientResult"], transient_result)
                
        # Evaluated on active STPN model directly via MCP solver (Semantic & Structural Modeling Correctness)
        semantic_modeling_correct = False
        structural_modeling_correct = False
        semantic_steady_error = float('nan')
        semantic_mae = float('nan')
        semantic_rmse = float('nan')
        mcp_steady_direct = float('nan')
        mcp_curve_direct = []
        mcp_graph_direct = None

        if with_mcp and mcp_client and provider != "mock":
            try:
                time_points = [pt[0] for pt in baseline["transientResult"]]
                direct_transient_res = mcp_client.handle_tool_call("execute_transient_analysis", {"timePoints": time_points})
                direct_steady_res = mcp_client.handle_tool_call("execute_steady_state_analysis", {})
                direct_graph_res = mcp_client.handle_tool_call("export_petri_net_graph", {})
                
                mcp_curve_direct = parse_mcp_transient_result(direct_transient_res)
                mcp_steady_direct = parse_mcp_steady_result(direct_steady_res)
                mcp_graph_direct = direct_graph_res if isinstance(direct_graph_res, dict) else None
                
                if mcp_curve_direct:
                     semantic_mae, semantic_rmse = compute_curve_metrics(baseline["transientResult"], mcp_curve_direct)
                if not np.isnan(mcp_steady_direct):
                     semantic_steady_error = compute_steady_state_error(baseline["steadyState"], mcp_steady_direct)
                    
                semantic_modeling_correct = is_solution_correct(
                    base_steady=baseline["steadyState"],
                    llm_steady=mcp_steady_direct,
                    base_curve=baseline["transientResult"],
                    llm_curve=mcp_curve_direct
                )

                if mcp_graph_direct and baseline.get("groundTruthGraph"):
                    structural_modeling_correct = are_petri_nets_isomorphic(mcp_graph_direct, baseline["groundTruthGraph"])
            except Exception as e:
                logger.error(f"Error extracting metrics directly from STPN model: {e}")
                
        sample_dict = {
            "run_index": i,
            "raw_text": raw_text,
            "tool_calls": tool_calls,
            "interactions_trace": interactions_trace,
            "success": success,
            "parsed_data": parsed_data,
            "steady_state": steady_state,
            "steady_error": steady_error if success else float('nan'),
            "mae": mae if success else float('nan'),
            "rmse": rmse if success else float('nan'),
            "transient_result": transient_result,
            "correct": correct,
            "latency_seconds": latency,
            "error": error_msg,
            "error_type": error_type,
            "max_turns_exceeded": (error_type == "MaxTurnsExceededError")
        }

        if with_mcp:
            sample_dict["modeling_correctness"] = semantic_modeling_correct
            sample_dict["modeling_isomorphism"] = structural_modeling_correct
            sample_dict["semantic_steady_error"] = semantic_steady_error
            sample_dict["semantic_mae"] = semantic_mae
            sample_dict["semantic_rmse"] = semantic_rmse
            sample_dict["mcp_steady_direct"] = mcp_steady_direct
            sample_dict["mcp_curve_direct"] = mcp_curve_direct

        samples.append(sample_dict)
        if tracker:
            tracker.complete_sample()
        
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
    
def ensure_project_built(workspace_path: str) -> None:
    """
    Checks if classpath.txt exists and contains valid paths.
    If not, compiles the project and generates classpath.txt automatically via Maven.
    """
    classpath_file = os.path.join(workspace_path, "classpath.txt")
    should_build = not os.path.exists(classpath_file)
    
    if not should_build:
        try:
            with open(classpath_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if content:
                # Check if the first dependency path in the classpath actually exists
                parts = content.split(";" if sys.platform.startswith("win") else ":")
                if parts and not os.path.exists(parts[0]):
                    logger.info("Detected invalid paths in classpath.txt (likely generated on a different machine).")
                    should_build = True
            else:
                should_build = True
        except Exception:
            should_build = True

    if should_build:
        logger.info("Compiling project and generating classpath.txt automatically via Maven...")
        import subprocess
        try:
            # Compile target classes and generate classpath.txt
            subprocess.run(
                ["mvn", "compile", "dependency:build-classpath", "-Dmdep.outputFile=classpath.txt"],
                cwd=workspace_path,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Build TestCaseGenerator assembly package
            subprocess.run(
                ["mvn", "package", "-DskipTests"],
                cwd=workspace_path,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info("Project built successfully. Generated classpath.txt.")
        except Exception as e:
            logger.warning(
                f"Failed to build the project automatically via Maven: {e}.\n"
                "Please make sure Maven (mvn) and Java Development Kit (JDK) are installed and configured on your PATH,\n"
                "and run 'mvn compile dependency:build-classpath -Dmdep.outputFile=classpath.txt' manually."
            )

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
    parser.add_argument("--mcp-mode", default="mock", choices=["mock", "stdio", "sse"], help="MCP server connection mode")
    parser.add_argument("--sse-url", default="http://localhost:8081/sse", help="MCP server SSE URL (when mcp-mode is sse)")
    parser.add_argument("--verbose-interactions", action="store_true", help="Print detailed LLM prompts, responses, and tool calls to console during execution")
    parser.add_argument("--stream", action="store_true", help="Enable real-time streaming of LLM reasoning and content response to stdout")
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
            # Try load from environment variable
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
        driver = OpenAICompatibleDriver(base_url=args.openai_url, model_name=args.openai_model, api_key=openai_key, temperature=args.temperature, reasoning=args.reasoning_effort, enable_thinking=args.thinking)
        
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
            
            # Get first successful run's data for plotting
            first_no_mcp_success = next((run for run in no_mcp_runs if run["success"]), None)
            no_mcp_steady = first_no_mcp_success["steady_state"] if first_no_mcp_success else float('nan')
            no_mcp_curve = first_no_mcp_success["transient_result"] if first_no_mcp_success else None
            
            # Compute errors for reporting
            no_mcp_steady_err = compute_steady_state_error(baseline["steadyState"], no_mcp_steady) if first_no_mcp_success else float('nan')
            no_mcp_mae, no_mcp_rmse = compute_curve_metrics(baseline["transientResult"], no_mcp_curve) if first_no_mcp_success else (float('nan'), float('nan'))
            
            # 4. LLM Run with MCP
            logger.info(f"Running LLM with MCP (Mode: tool calling enabled)...")
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
            
            # Calculate metrics for no_mcp
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

            # Calculate metrics for mcp
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

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")    
        save_report_data_json(report_data, os.path.dirname(output_dir), timestamp)
        # Write summary report
        # write_markdown_report(driver, report_data, output_dir, args.samples, args.k, interaction_history)
        
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

def write_markdown_report(driver: LLMDriver, data: List[Dict[str, Any]], output_dir: str, samples: int, k: int, interaction_history: Optional[List[Dict[str, Any]]] = None):
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

    # Prompt schema designed to instruct the LLM to write a technical discussion around metrics
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
