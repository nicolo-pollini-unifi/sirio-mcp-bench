import math
import numpy as np
from typing import List, Tuple

def compute_steady_state_error(base_steady: float, llm_steady: float) -> float:
    """
    Computes the absolute error for the steady state probability.
    """
    return abs(base_steady - llm_steady)

def compute_curve_metrics(base_curve: List[Tuple[float, float]], llm_curve: List[Tuple[float, float]]) -> Tuple[float, float]:
    """
    Computes Mean Absolute Error (MAE) and Root Mean Square Error (RMSE)
    between the baseline transient curve and the LLM transient curve.
    
    Assumes curves are lists of (time, probability) tuples, possibly at different alignments.
    We align them by interpolating the LLM curve at baseline time points.
    
    Returns:
        A tuple of (mae, rmse).
    """
    if not base_curve or not llm_curve:
        return float('inf'), float('inf')
        
    base_times, base_vals = zip(*base_curve)
    llm_times, llm_vals = zip(*llm_curve)
    
    # Interpolate LLM values at baseline time points to align them
    try:
        interpolated_llm_vals = np.interp(base_times, llm_times, llm_vals)
    except Exception:
        return float('inf'), float('inf')
        
    errors = np.array(base_vals) - np.array(interpolated_llm_vals)
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    
    return mae, rmse

def is_solution_correct(
    base_steady: float, 
    llm_steady: float, 
    base_curve: List[Tuple[float, float]], 
    llm_curve: List[Tuple[float, float]], 
    steady_tol: float = 0.01, 
    transient_mae_tol: float = 0.05
) -> bool:
    """
    Determines if an LLM solution is 'correct' (within a defined tolerance of the baseline).
    """
    if math.isnan(llm_steady) or llm_steady == float('inf'):
        return False
        
    steady_err = compute_steady_state_error(base_steady, llm_steady)
    if steady_err > steady_tol:
        return False
        
    mae, _ = compute_curve_metrics(base_curve, llm_curve)
    if mae > transient_mae_tol:
        return False
        
    return True

def compute_pass_at_k(n: int, c: int, k: int) -> float:
    """
    Computes the Pass@k metric.
    
    Formula:
        Pass@k = 1 - choose(n - c, k) / choose(n, k)
        
    If n - c < k, returns 1.0.
    """
    if k <= 0:
        return 0.0
    if n < k:
        # If we have fewer samples than k, we estimate pass@k as the success rate
        return float(c) / float(n) if n > 0 else 0.0
    if n - c < k:
        return 1.0
        
    # Compute using combinations to avoid overflow
    def choose(n_val, k_val):
        if k_val < 0 or k_val > n_val:
            return 0
        if k_val == 0 or k_val == n_val:
            return 1
        k_val = min(k_val, n_val - k_val)
        c_val = 1
        for i in range(k_val):
            c_val = c_val * (n_val - i) // (i + 1)
        return c_val

    total_combinations = choose(n, k)
    fail_combinations = choose(n - c, k)
    
    if total_combinations == 0:
        return 0.0
        
    return 1.0 - (float(fail_combinations) / float(total_combinations))
