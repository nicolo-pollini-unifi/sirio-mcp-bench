import json
from typing import Dict, Any, List

from llm_client import GeminiDriver, OpenAICompatibleDriver

def _extract_gemini_step(response_json: Dict[str, Any]):
    candidates = response_json.get("candidates", [])
    if not candidates:
        raise ValueError(f"No response candidates returned: {response_json}")
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
    calls = [
        {"id": None, "name": p["functionCall"]["name"], "args": p["functionCall"].get("args", {})}
        for p in parts if "functionCall" in p
    ]
    return text, calls, parts


def _extract_openai_step(response_json: Dict[str, Any]):
    choices = response_json.get("choices", [])
    if not choices:
        raise ValueError(f"No response choices returned: {response_json}")
    msg = choices[0].get("message", {})
    text = (msg.get("content") or "").strip()
    calls = []
    for tc in msg.get("tool_calls", []):
        try:
            args = json.loads(tc["function"]["arguments"])
        except Exception:
            args = {}
        calls.append({"id": tc["id"], "name": tc["function"]["name"], "args": args})
    return text, calls, msg


class GeminiAdapter:
    """Incapsula tutte le specificità del formato Gemini."""

    def __init__(self, driver: GeminiDriver, mcp_tools: List[Dict[str, Any]], system_instruction: str):
        self.driver = driver
        self.system_instruction = system_instruction
        self.headers = {"Content-Type": "application/json"}
        declarations = []
        for tool in mcp_tools:
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
        self.tools = [{"functionDeclarations": declarations}]
        self.history: List[Dict[str, Any]] = []

    def init_conversation(self, prompt: str):
        self.history = [{"role": "user", "parts": [{"text": prompt}]}]

    def build_request(self):
        payload = {
            "contents": self.history,
            "systemInstruction": {"parts": [{"text": self.system_instruction}]},
            "tools": self.tools,
            "generationConfig": {"temperature": self.driver.temperature, "maxOutputTokens": 8192}
        }
        return self.driver.url, self.headers, payload

    def parse_response(self, response_json):
        return _extract_gemini_step(response_json)

    def append_assistant_turn(self, raw_native_content):
        self.history.append({"role": "model", "parts": raw_native_content})

    def append_tool_results(self, calls_with_results):
        response_parts = [
            {"functionResponse": {"name": c["name"], "response": {"result": c["result"]}}}
            for c in calls_with_results
        ]
        self.history.append({"role": "user", "parts": response_parts})

    def append_continuation_request(self):
        self.history.append({
            "role": "user",
            "parts": [{"text": "Your previous response was truncated. Please continue generating the JSON results block exactly from where you left off."}]
        })


class OpenAIAdapter:
    """Incapsula tutte le specificità del formato OpenAI-compatible."""

    def __init__(self, driver: OpenAICompatibleDriver, mcp_tools: List[Dict[str, Any]], system_instruction: str):
        self.driver = driver
        self.system_instruction = system_instruction
        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {driver.api_key}"}
        self.tools = mcp_tools
        self.messages: List[Dict[str, Any]] = []

    def init_conversation(self, prompt: str):
        self.messages = [
            {"role": "system", "content": self.system_instruction},
            {"role": "user", "content": prompt}
        ]

    def build_request(self):
        payload = {
            "model": self.driver.model_name,
            "messages": self.messages,
            "tools": self.tools,
            "temperature": self.driver.temperature,
            "max_tokens": 8192
        }
        return self.driver.url, self.headers, payload

    def parse_response(self, response_json):
        return _extract_openai_step(response_json)

    def append_assistant_turn(self, raw_native_content):
        self.messages.append(raw_native_content)

    def append_tool_results(self, calls_with_results):
        for c in calls_with_results:
            self.messages.append({
                "role": "tool",
                "tool_call_id": c["id"],
                "name": c["name"],
                "content": json.dumps(c["result"])
            })

    def append_continuation_request(self):
        self.messages.append({
            "role": "user",
            "content": "Your previous response was truncated. Please continue generating the JSON results block exactly from where you left off."
        })
