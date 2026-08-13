"""
This module provides plotting utilities for comparing LLM curves with GSPN baselines.
"""

import matplotlib.pyplot as plt
from typing import List, Optional

def generate_comparative_plots(
    case_id: str,
    baseline_curve: List[List[float]],
    llm_no_mcp_curve: Optional[List[List[float]]],
    llm_mcp_curve: Optional[List[List[float]]],
    output_path: str
) -> None:
    """
    Generates and saves a transient unreliability curve comparison plot.

    Args:
        case_id: The test case identifier.
        baseline_curve: Ground truth curve values.
        llm_no_mcp_curve: Curve values predicted in No-MCP mode.
        llm_mcp_curve: Curve values predicted in MCP mode.
        output_path: Destination path for the generated PNG image.
    """
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
    
    plt.savefig(output_path, bbox_inches='tight')
    plt.close()
