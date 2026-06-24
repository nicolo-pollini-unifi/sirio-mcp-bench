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
    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
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
    
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model_name = model_name
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
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
        payload["generationConfig"] = {
            "temperature": 0.0,
            "maxOutputTokens": 8192
        }

        try:
            response = requests.post(self.url, headers=headers, json=payload)
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

class OpenAICompatibleDriver(LLMDriver):
    """
    Driver for OpenAI-compatible local or remote APIs (e.g. Ollama, vLLM, LM Studio).
    """
    
    def __init__(self, base_url: str, model_name: str, api_key: str = "local"):
        self.base_url = base_url.rstrip('/')
        self.model_name = model_name
        self.api_key = api_key
        self.url = f"{self.base_url}/chat/completions"

    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
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
            "temperature": 0.0,
            "max_tokens": 4096
        }

        try:
            response = requests.post(self.url, headers=headers, json=payload)
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

    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        # Returns a JSON block containing baseline data (possibly with slight perturbations)
        data = self.baseline_data or {
            "steadyState": 0.05,
            "transientResult": [
                [0.0, 0.0],
                [50.0, 0.025],
                [100.0, 0.05]
            ]
        }
        return f"Simulated unreliability result:\n```json\n{json.dumps(data, indent=2)}\n```"
