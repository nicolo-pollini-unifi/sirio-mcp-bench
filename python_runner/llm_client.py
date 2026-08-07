import abc
import json
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class LLMDriver(abc.ABC):
    """
    Abstract interface for LLM providers.
    """

    @abc.abstractmethod
    def generate(self, prompt: str, system_instruction: Optional[str] = None, seed: Optional[int] = None) -> str:
        """
        Sends a prompt to the LLM and returns the generated string response.
        
        Args:
            prompt: The user query prompt.
            system_instruction: Optional developer system instruction.
            
        Returns:
            The text response from the model.
        """
        pass

class GeminiDriver(LLMDriver):
    """
    Driver for Google Gemini API via HTTP POST.
    """
    
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", temperature: float = 0.0, timeout: float = 600):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.timeout = timeout
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    def generate(self, prompt: str, system_instruction: Optional[str] = None, seed: Optional[int] = None) -> str:
        headers = {"Content-Type": "application/json"}
        
        contents = [
            {
                "parts": [{"text": prompt}]
            }
        ]
        
        payload: Dict[str, Any] = {"contents": contents}
        
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
            
        # Standard configuration for deterministic outputs in benchmarking
        gen_config: Dict[str, Any] = {
            "temperature": self.temperature,
            "maxOutputTokens": 8192
        }
        if seed is not None:
            gen_config["seed"] = seed
            
        payload["generationConfig"] = gen_config

        try:
            response = requests.post(self.url, headers=headers, json=payload, timeout = self.timeout)
            response.raise_for_status()
            response_json = response.json()
            
            # Extract text from standard Gemini API response structure
            candidates = response_json.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            
            raise ValueError(f"Unexpected response structure from Gemini API: {response_json}")
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}")
            raise e

REASONING_EFFORT_TOKEN_BUDGETS = {
    "low": 512,
    "medium": 2048,
    "high": 4096,
    "xhigh": 8192,
    "max": -1,  # -1 = nessun limite (thinking libero)
}

class OpenAICompatibleDriver(LLMDriver):
    """
    Driver for OpenAI-compatible local or remote APIs (e.g. Ollama, vLLM, LM Studio).
    """
    
    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str = "local",
        temperature: float = 0.0,
        timeout: float = 600,
        reasoning: str = "medium",
        enable_thinking: bool = True,
    ):
        self.base_url = base_url.rstrip('/')
        self.model_name = model_name
        self.api_key = api_key
        self.temperature = temperature
        self.reasoning = reasoning
        self.reasoning_budget = REASONING_EFFORT_TOKEN_BUDGETS.get(reasoning, 2048)
        self.enable_thinking = enable_thinking
        self.timeout = timeout
        self.url = f"{self.base_url}/chat/completions"

    def generate(self, prompt: str, system_instruction: Optional[str] = None, seed: Optional[int] = None) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
            
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 4096,
            "reasoning_effort": self.reasoning,
            "chat_template_kwargs": {
                "enable_thinking": self.enable_thinking
            }
        }
        if seed is not None:
            payload["seed"] = seed

        try:
            response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            response_json = response.json()
            
            choices = response_json.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
                
            raise ValueError(f"Unexpected response structure from OpenAI-compatible API: {response_json}")
        except Exception as e:
            logger.error(f"Error calling OpenAI-compatible API: {e}")
            raise e

class MockLLMDriver(LLMDriver):
    """
    Mock LLM driver that simulates response generation without calling external APIs.
    Useful for testing and verification of the benchmarking workflow.
    """
    def __init__(self, baseline_data: Optional[Dict[str, Any]] = None):
        self.baseline_data = baseline_data

    def generate(self, prompt: str, system_instruction: Optional[str] = None, seed: Optional[int] = None) -> str:
        # Returns a simulated chain of thought followed by the JSON block containing baseline data
        data = self.baseline_data or {
            "steadyState": 0.05,
            "transientResult": [
                [0.0, 0.0],
                [50.0, 0.025],
                [100.0, 0.05]
            ]
        }
        
        cot_explanation = (
            "/* DISCLAIMER: This is a simulated/mock LLM response for dry-run testing. */\n\n"
            "To perform the unreliability analysis of the given event configuration, we follow these steps:\n"
            "1. Identify the logic gates and leaf events. The logic expression is (GE1 & GE2 & GE3) | (GE4 & GE5).\n"
            "2. Under steady state, since all components are repairable (modeled as two-state Markov chains with failure and repair rates), the system unreliability converges to a steady state probability. We compute this by solving the steady state vector of the GSPN.\n"
            "3. Under transient analysis, we solve the differential equations of state probability transition over the specified time range [0, maxTime] with timeStep step size.\n\n"
            "Below is the calculated steady-state and transient unreliability results:\n"
            f"```json\n{json.dumps(data, indent=2)}\n```"
        )
        return cot_explanation
