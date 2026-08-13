"""
This module encapsulates the core agent execution loops and LLM orchestration logic.
"""

import os
import sys
import json
import time
import logging
import requests
import traceback
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from llm_client import GeminiDriver, OpenAICompatibleDriver, LLMDriver, MockLLMDriver
from llm_adapters import GeminiAdapter, OpenAIAdapter
from mcp_client import BaseMCPClient
from metrics import compute_steady_state_error, compute_curve_metrics, is_solution_correct
from graph_isomorphism import are_petri_nets_isomorphic
from exceptions import SemanticLoopError, MaxTurnsExceededError, NetworkError
from utils import clean_nan, parse_json_from_response
from progress_tracker import ProgressTracker

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are a reliability engineering expert specializing in quantitative fault tree analysis.\n\n"
    "## Objective\n"
    "Compute, for a given Fault Tree top-level event:\n"
    "1. **Steady-state failure probability** (limiting unreliability): the steady-state analysis must "
    "provide the asymptotic unreliability of the system model (i.e., the steady-state probability of the "
    "TOP event condition being active at regime, evaluated under the top-event absorption configuration).\n"
    "    *Note: Do not assume that the request is a mistake or a trivial result. Even if the limiting "
    "unreliability is known to converge to a certain value, you must not skip the derivation steps to "
    "formally obtain the result rather than stating it without analysis.*\n"
    "2. **Transient unreliability curve** Q(t) over time: the cumulative probability of system failure over "
    "the time horizon $[0, T]$, sampled at discrete time steps $t_k$ according to the specified analysis "
    "parameters, evaluated with top-event absorption active.\n\n"
    "## Petri Net Modeling Rules\n"
    "- Model each component as a Gilbert-Elliot net: the transition rates must be as specified in the prompt. "
    "Use enabling conditions as a link between nets of different levels.\n"
    "- Implement **repair arcs**: remove a gate's token when its activating condition no longer holds "
    "(i.e., one or more inputs are repaired).\n"
    "- **Single-fire gates (MANDATORY structural guard)**: every gate-fail transition MUST have an explicit input "
    "arc from a dedicated \"armed\" place (initial marking 1). This arc is a hard precondition for firing, separate "
    "from the enabling-function, a transition without this input arc is an invalid construction and must be "
    "corrected immediately before proceeding. Firing the gate-fail transition consumes the armed token, disabling "
    "the transition until the paired repair transition restores it. The repair transition fires only when its "
    "repair enabling-function holds and consumes only its own gate's token, never a sibling gate's.\n"
    "- **Top-event absorption**: the top-event place has no repair arc — system failure is absorbing. The "
    "top-event transition's `marking-update` must explicitly zero every place in the net except the top-event place "
    "(syntax: \"p<i> 0\" for each place), and it must have priority higher than any other immediate transition so it "
    "preempts intermediate gate updates.\n"
    "- Use `&&` for AND and `||` for OR in all enabling functions.\n\n"
    "## Execution & Tool Guidelines\n"
    "- If external tools are available in your environment, you MUST use them as early as possible to construct "
    "the model and delegate all formal computations to maintain mathematical precision.\n"
    "- Validate your model structure (e.g., confirm armed input arcs exist) before executing solvers.\n"
    "- Do **not** approximate math manually if formal tool execution is available.\n\n"
    "## Output Format\n"
    "Your final quantitative result MUST be provided as a JSON block matching this exact structure:\n\n"
    "```json\n"
    "{\n"
    "    \"steadyState\": <number>,\n"
    "    \"transientResult\": [\n"
    "        [0.0, 0.0],\n"
    "        [<t1>, <prob1>],\n"
    "        ...\n"
    "    ]\n"
    "}\n"
    "```\n"
)

def is_top_failure_marking(marking_str: str) -> bool:
    """
    Checks if a marking string matches the system failure state.

    Args:
        marking_str: The Petri Net state marking description.

    Returns:
        True if TOP_fail contains a token, False otherwise.
    """
    return (
        "TOP_fail = 1" in marking_str or 
        "TOP_fail=1" in marking_str or 
        "TOP_fail: 1" in marking_str or 
        "TOP_fail : 1" in marking_str
    )

def parse_mcp_transient_result(tool_result: Any) -> List[List[float]]:
    """
    Parses the transient analysis tool result from the Petri Net solver.

    Args:
        tool_result: The raw tool output mapping time points to marking distributions.

    Returns:
        A sorted list of time-unreliability coordinate pairs.
    """
    curve = []
    if not isinstance(tool_result, dict):
        return []
    for time_str, distribution in tool_result.items():
        try:
            t_val = float(time_str)
            p_val = 0.0
            if isinstance(distribution, dict):
                found_top = False
                for marking_str, prob in distribution.items():
                    if is_top_failure_marking(str(marking_str)):
                        try:
                            p_val += float(prob)
                            found_top = True
                        except Exception:
                            pass
                if found_top:
                    curve.append([t_val, p_val])
                elif len(distribution) == 1:
                    val = next(iter(distribution.values()))
                    try:
                        curve.append([t_val, float(val)])
                    except Exception:
                        pass
        except ValueError:
            pass
    return sorted(curve, key=lambda x: x[0])

def parse_mcp_steady_result(tool_result: Any) -> float:
    """
    Parses the steady-state analysis tool output from the Petri Net solver.

    Args:
        tool_result: The raw tool output representing state probabilities.

    Returns:
        The computed steady-state unreliability probability, or NaN if unavailable.
    """
    if isinstance(tool_result, dict):
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

def execute_agent_loop_mock(
    driver: LLMDriver, 
    mcp_client: BaseMCPClient, 
    prompt: str, 
    baseline: Dict[str, Any]
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Simulates tool calls to the MCP client and returns mock Petri Net calculations.

    Args:
        driver: LLM connection driver.
        mcp_client: Petri Net solver MCP client.
        prompt: Initial request prompt.
        baseline: The ground truth baseline dictionary.

    Returns:
        A tuple of (generated_text, tool_calls_log, interactions_trace).
    """
    tools = mcp_client.list_tools()
    has_real_tools = any(t.get("function", {}).get("name") == "create" for t in tools)
    
    tool_calls_log = []
    interactions_trace = []
    
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
    interactions_trace.append({
        "type": "text", 
        "content": f"{disclaimer}\nInitial prompt received. Constructing unreliability analysis Petri net structure..."
    })
    
    if has_real_tools:
        call_tool("create", {})
        call_tool("add_places", map_args("add_places", {"node_names": ["P0", "P1"]}))
        call_tool("add_tokens", map_args("add_tokens", {"name": "P0", "num": 1}))
        call_tool("add_transitions", map_args("add_transitions", {"transition_names": ["T0"]}))
        call_tool("add_precondition", map_args("add_precondition", {"place_name": "P0", "transition_name": "T0"}))
        call_tool("add_postcondition", map_args("add_postcondition", {"place_name": "P1", "transition_name": "T0"}))
        call_tool("add_EXP", map_args("add_EXP", {"transition_name": "T0", "rate": 0.05}))
        call_tool("execute_steady_state_analysis", {})
    else:
        res = call_tool("create_petri_net", {})
        net_id = res.get("net_id")
        if net_id and "error" not in res:
            call_tool("add_place", {"net_id": net_id, "name": "P0", "tokens": 1})
            call_tool("add_transition", {"net_id": net_id, "name": "T0", "type": "exponential", "rate": 0.05})
            call_tool("run_steady_state_analysis", {"net_id": net_id, "failure_condition": "P0 == 0"})

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

def execute_agent_loop(
    driver: LLMDriver, 
    mcp_client: BaseMCPClient, 
    prompt: str, 
    max_turns: int = 100, 
    seed: Optional[int] = None, 
    stream: bool = False
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Executes the main agent-loop interacting with the LLM driver and MCP tools.

    Args:
        driver: The target LLM connection.
        mcp_client: The connected Petri Net MCP client.
        prompt: User reliability analysis configuration prompt.
        max_turns: Maximum reasoning/interaction loop steps.
        seed: Deterministic random seed for LLM generation.
        stream: Enables server-sent events token streaming if supported.

    Returns:
        A tuple of (full_generated_response, list_of_tool_calls_run, full_interaction_trace).
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
                logger.info(f"  [MCP] Turn {turn+1}/{max_turns}: Requesting LLM...")
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
                interactions_trace.append({
                    "type": "tool_call", 
                    "name": call["name"], 
                    "args": call["args"], 
                    "result": result
                })
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
                        reasoning_str = (
                            raw_native_content.get("reasoning") or 
                            raw_native_content.get("reasoning_content") or 
                            "_empty_"
                        )

                    f.write("## Content\n\n")
                    f.write(content_str)
                    f.write("\n\n")

                    f.write("## Reasoning\n\n")
                    f.write(reasoning_str)
                    f.write("\n\n")

                    f.write("## Tool Calls\n\n")
                    if calls_with_results:
                        for i, cl in enumerate(calls_with_results, 1):
                            f.write(f"### Tool Call {i}\n")
                            f.write(f"- Name: `{cl.get('name', '_unknown_')}`\n")
                            f.write(f"- Args: `{cl.get('args', '')}`\n")
                            f.write(f"- Result: `{cl.get('result', '')}`\n\n")
                    elif calls:
                        for i, cl in enumerate(calls, 1):
                            f.write(f"### Tool Call {i}\n")
                            f.write(f"- Name: `{cl.get('name', '_unknown_')}`\n")
                            f.write(f"- Args: `{cl.get('args', '')}`\n")
                            f.write("- Result: `_not executed_`\n\n")
                    else:
                        f.write("_No tool calls_\n\n")
            except Exception:
                logger.exception("Could not save dump of turn %d", turn + 1)

    raise MaxTurnsExceededError("LLM exceeded max tool call iteration limit")

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
    Executes multiple run iterations for a single configuration (No-MCP or MCP).

    Args:
        driver: LLM connection manager.
        mcp_client: Connected Petri Net MCP client.
        prompt: Prompt explaining the analysis requirements.
        baseline: Ground truth results for validation.
        with_mcp: Enabled MCP tool-calling when True.
        provider: API endpoint provider (gemini, openai, mock).
        num_samples: Number of sampling runs to execute (Pass@k calculation).
        verbose_interactions: Logs full raw responses when True.
        max_turns: Iteration limit inside the agent loop.
        base_seed: Master random seed.
        tracker: Active progress display tracking execution metrics.
        case_id: The identifier of the case.
        stream: Enables streaming API responses when supported.

    Returns:
        A tuple of (list_of_sample_metrics_dictionaries, executable_success_ratio, correct_runs_count).
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
                if provider == "mock":
                    raw_text, tool_calls, interactions_trace = execute_agent_loop_mock(
                        driver, mcp_client, prompt, baseline
                    )
                else:
                    raw_text, tool_calls, interactions_trace = execute_agent_loop(
                        driver, mcp_client, prompt, max_turns, seed=sample_seed, stream=stream
                    )
            else:
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
                            break
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        text = "".join([p.get("text", "") for p in parts if "text" in p])
                        raw_text += text
                        interactions_trace.append({"type": "text", "content": text})
                        
                        if "```json" in raw_text and parse_json_from_response(raw_text):
                            break
                        history.append({"role": "model", "parts": parts})
                        history.append({
                            "role": "user", 
                            "parts": [{
                                "text": "Your previous response was truncated. "
                                        "Please continue generating the JSON results block "
                                        "exactly from where you left off."
                            }]
                        })
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
                            driver.add_thinking_params(payload)
                            if sample_seed is not None:
                                payload["seed"] = sample_seed
                            response = requests.post(
                                driver.url, headers=headers, json=payload, timeout=120, stream=True
                            )
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
                            
                            if "```json" in raw_text and parse_json_from_response(raw_text):
                                break
                            messages.append({"role": "assistant", "content": chunk_text})
                            messages.append({
                                "role": "user", 
                                "content": "Your previous response was truncated. "
                                           "Please continue generating the JSON results block "
                                           "exactly from where you left off."
                            })
                        else:
                            logger.info(f"  [No-MCP] Turn {turn+1}/5: Requesting LLM...")
                            payload = {
                                "model": driver.model_name,
                                "messages": messages,
                                "temperature": driver.temperature,
                                "max_tokens": 8192
                            }
                            driver.add_thinking_params(payload)
                            if sample_seed is not None:
                                payload["seed"] = sample_seed
                            response = requests.post(driver.url, headers=headers, json=payload, timeout=120)
                            response.raise_for_status()
                            response_json = response.json()
                            choices = response_json.get("choices", [])
                            if not choices:
                                break
                            msg = choices[0].get("message", {})
                            text = msg.get("content", "") or ""
                            raw_text += text
                            interactions_trace.append({"type": "text", "content": text})
                            
                            if "```json" in raw_text and parse_json_from_response(raw_text):
                                break
                            messages.append(msg)
                            messages.append({
                                "role": "user", 
                                "content": "Your previous response was truncated. "
                                           "Please continue generating the JSON results block "
                                           "exactly from where you left off."
                            })
                else:
                    raw_text = driver.generate(prompt, SYSTEM_INSTRUCTION, seed=sample_seed)
                    interactions_trace.append({"type": "text", "content": raw_text})
                
            if verbose_interactions:
                logger.info(f"\n==================== [VERBOSE] Prompt (MCP={with_mcp}, Sample={i}) ====================\n{prompt}\n========================================================================================\n")
                logger.info(f"\n==================== [VERBOSE] Response (MCP={with_mcp}, Sample={i}) ====================\n{raw_text}\n=======================================================================================\n")
                
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
                direct_transient_res = mcp_client.handle_tool_call(
                    "execute_transient_analysis", {"timePoints": time_points}
                )
                direct_steady_res = mcp_client.handle_tool_call("execute_steady_state_analysis", {})
                direct_graph_res = mcp_client.handle_tool_call("export_petri_net_graph", {})
                
                mcp_curve_direct = parse_mcp_transient_result(direct_transient_res)
                mcp_steady_direct = parse_mcp_steady_result(direct_steady_res)
                mcp_graph_direct = direct_graph_res if isinstance(direct_graph_res, dict) else None
                
                if mcp_curve_direct:
                    semantic_steady_error = compute_steady_state_error(
                        baseline["steadyState"], mcp_steady_direct
                    )
                    semantic_mae, semantic_rmse = compute_curve_metrics(
                        baseline["transientResult"], mcp_curve_direct
                    )
                    
                    semantic_modeling_correct = is_solution_correct(
                        base_steady=baseline["steadyState"],
                        llm_steady=mcp_steady_direct,
                        base_curve=baseline["transientResult"],
                        llm_curve=mcp_curve_direct
                    )
                
                # Check for Petri Net graph structural isomorphism
                if mcp_graph_direct and baseline.get("petriNetGraph"):
                    structural_modeling_correct = are_petri_nets_isomorphic(
                        baseline["petriNetGraph"], mcp_graph_direct
                    )
            except Exception as e:
                logger.error(f"Error checking semantic/structural modeling correctness: {e}")
                
        sample_dict = {
            "run_index": i,
            "success": success,
            "correct": correct,
            "steady_state": clean_nan(steady_state),
            "steady_error": clean_nan(steady_error),
            "mae": clean_nan(mae),
            "rmse": clean_nan(rmse),
            "transient_result": transient_result,
            "latency_seconds": latency,
            "error": error_msg,
            "error_type": error_type,
            "max_turns_exceeded": (error_type == "MaxTurnsExceededError"),
            "tool_calls": tool_calls,
            "raw_text": raw_text,
            "interactions_trace": interactions_trace
        }

        if with_mcp:
            sample_dict["modeling_correctness"] = semantic_modeling_correct
            sample_dict["modeling_isomorphism"] = structural_modeling_correct
            sample_dict["semantic_steady_error"] = clean_nan(semantic_steady_error)
            sample_dict["semantic_mae"] = clean_nan(semantic_mae)
            sample_dict["semantic_rmse"] = clean_nan(semantic_rmse)
            sample_dict["mcp_steady_direct"] = clean_nan(mcp_steady_direct)
            sample_dict["mcp_curve_direct"] = mcp_curve_direct

        samples.append(sample_dict)
        if tracker:
            tracker.complete_sample()
        
    executable_rate = float(sum(1 for s in samples if s["success"])) / num_samples
    return samples, executable_rate, correct_count
