"""
This module provides shared helper and data formatting utility functions.
"""

import json
import numpy as np
from typing import Dict, Any, Optional

def clean_nan(val: Any) -> Any:
    """
    Cleans floating point NaN values, converting them to None for JSON serialization.

    Args:
        val: The input value to clean.

    Returns:
        None if val is a NaN float, otherwise the original value.
    """
    if isinstance(val, (int, float)) and np.isnan(val):
        return None
    return val

def build_components_details(components: Dict[str, Any]) -> str:
    """
    Formats the component list config into a markdown list for prompt insertion.

    Args:
        components: A dictionary mapping component names to their config parameters.

    Returns:
        A formatted markdown string detailing each component's attributes.
    """
    lines = []
    for name, config in components.items():
        lines.append(
            f"  * {name}: type={config.get('type')}, "
            f"failureRate={config.get('failureRate')}, "
            f"repairRate={config.get('repairRate')}"
        )
    return "\n".join(lines)

def parse_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extracts and parses the JSON markdown block from an LLM response.

    Args:
        text: The raw LLM response text containing potential JSON blocks.

    Returns:
        The parsed dictionary if JSON extraction is successful, otherwise None.
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
            
    try:
        return json.loads(text.strip())
    except Exception:
        pass
        
    return None
