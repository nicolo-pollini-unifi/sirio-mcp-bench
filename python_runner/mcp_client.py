import os
import sys
import uuid
import json
import logging
import tempfile
import subprocess
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from contextlib import AsyncExitStack

logger = logging.getLogger(__name__)

# List of mock tool declarations in OpenAI-compatible format
SIRIO_MOCK_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "create_petri_net",
            "description": "Creates a new Petri net instance and returns its unique net_id identifier.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_place",
            "description": "Adds a place to the specified Petri net.",
            "parameters": {
                "type": "object",
                "properties": {
                    "net_id": {"type": "string", "description": "The target Petri net identifier."},
                    "name": {"type": "string", "description": "Unique name of the place."},
                    "tokens": {"type": "integer", "description": "Initial number of tokens in this place. Defaults to 0.", "default": 0}
                },
                "required": ["net_id", "name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_transition",
            "description": "Adds a transition to the specified Petri net.",
            "parameters": {
                "type": "object",
                "properties": {
                    "net_id": {"type": "string", "description": "The target Petri net identifier."},
                    "name": {"type": "string", "description": "Unique name of the transition."},
                    "type": {"type": "string", "description": "Stochastic type of the transition ('exponential', 'deterministic', 'erlang'). Defaults to 'exponential'.", "enum": ["exponential", "deterministic", "erlang"], "default": "exponential"},
                    "rate": {"type": "number", "description": "The parameter value of the transition (lambda for exponential/erlang, duration value for deterministic)."},
                    "enabling_function": {"type": "string", "description": "Optional logic expression determining when transition is enabled (e.g. 'place1 > 0 && place2 == 0')."},
                    "post_updater": {"type": "string", "description": "Optional marking update statement applied after firing (e.g. 'place1 = 0 ;')."},
                    "priority": {"type": "integer", "description": "Optional integer priority for immediate or deterministic transitions."},
                    "k": {"type": "integer", "description": "Optional stage parameter (k) if the type is 'erlang'."}
                },
                "required": ["net_id", "name", "rate"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_arc",
            "description": "Adds a directed arc between a place and a transition in the specified Petri net.",
            "parameters": {
                "type": "object",
                "properties": {
                    "net_id": {"type": "string", "description": "The target Petri net identifier."},
                    "from_element": {"type": "string", "description": "The name of the source element (place name or transition name)."},
                    "to_element": {"type": "string", "description": "The name of the target element (transition name or place name)."},
                    "type": {"type": "string", "description": "Optional arc type ('precondition' from place to transition, or 'postcondition' from transition to place). If omitted, inferred from the elements.", "enum": ["precondition", "postcondition"]}
                },
                "required": ["net_id", "from_element", "to_element"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_steady_state_analysis",
            "description": "Runs steady-state unreliability analysis on the Petri net to compute the infinite-horizon failure probability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "net_id": {"type": "string", "description": "The target Petri net identifier."},
                    "failure_condition": {"type": "string", "description": "Logical condition indicating failure state (e.g. 'failure > 0')."}
                },
                "required": ["net_id", "failure_condition"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_transient_analysis",
            "description": "Runs transient unreliability analysis to compute the probability of failure over a time series.",
            "parameters": {
                "type": "object",
                "properties": {
                    "net_id": {"type": "string", "description": "The target Petri net identifier."},
                    "failure_condition": {"type": "string", "description": "Logical condition indicating failure state (e.g. 'failure > 0')."},
                    "max_time": {"type": "number", "description": "The upper bound time limit of the transient evaluation."},
                    "time_step": {"type": "number", "description": "The time resolution step size for plotting the unreliability curve."}
                },
                "required": ["net_id", "failure_condition", "max_time", "time_step"]
            }
        }
    }
]


class BaseMCPClient(ABC):
    """
    Abstract Base Class for MCP Clients (SOLID interface).
    """

    @abstractmethod
    def start(self) -> None:
        """Start the MCP connection or subprocess."""
        pass

    @abstractmethod
    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools in OpenAI function calling format."""
        pass

    @abstractmethod
    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a specific tool by name with arguments."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the connection and release resources."""
        pass


class SirioMCPMock(BaseMCPClient):
    """
    Simulates the SIRIO library MCP Server by managing Petri net state and
    running actual calculations via the Java PetriNetEvaluator helper class.
    """
    
    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.abspath(workspace_path)
        self.nets: Dict[str, Dict[str, Any]] = {}
        self._classpath: Optional[str] = None
        
    def start(self) -> None:
        logger.info("Starting SirioMCPMock (no connection required).")

    def list_tools(self) -> List[Dict[str, Any]]:
        return SIRIO_MOCK_TOOL_SCHEMAS

    def _get_classpath(self) -> str:
        if self._classpath:
            return self._classpath
            
        classpath_file = os.path.join(self.workspace_path, "classpath.txt")
        maven_deps = ""
        if os.path.exists(classpath_file):
            try:
                with open(classpath_file, 'r', encoding='utf-8') as f:
                    maven_deps = f.read().strip()
            except Exception as e:
                logger.warning(f"Could not read classpath.txt: {e}")
                
        target_classes = os.path.join(self.workspace_path, "target", "classes")
        target_test_classes = os.path.join(self.workspace_path, "target", "test-classes")
        sirio_jar = os.path.join(self.workspace_path, "lib", "sirio-2.0.4.jar")
        
        separator = ";" if sys.platform.startswith("win") else ":"
        cp_elements = [target_classes, target_test_classes, sirio_jar]
        if maven_deps:
            cp_elements.append(maven_deps)
            
        self._classpath = separator.join(cp_elements)
        return self._classpath

    def execute_evaluator(self, net_config: Dict[str, Any]) -> Dict[str, Any]:
        temp_in = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        temp_out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        
        try:
            temp_in.write(json.dumps(net_config, indent=2).encode('utf-8'))
            temp_in.close()
            temp_out.close()
            
            cp = self._get_classpath()
            cmd = [
                "java",
                "-cp", cp,
                "org.util.PetriNetEvaluator",
                "--input", temp_in.name,
                "--output", temp_out.name
            ]
            
            logger.debug(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            
            if os.path.exists(temp_out.name):
                with open(temp_out.name, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return {"error": "Output file was not generated by Java evaluator."}
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Java evaluator crashed. Stderr: {e.stderr}")
            return {"error": f"Java execution failed: {e.stderr}"}
        except Exception as e:
            logger.error(f"Error executing evaluator: {e}")
            return {"error": str(e)}
        finally:
            try:
                os.unlink(temp_in.name)
                os.unlink(temp_out.name)
            except OSError:
                pass

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Mock MCP Tool call: {name} with args: {arguments}")
        
        try:
            if name == "create_petri_net":
                net_id = str(uuid.uuid4())
                self.nets[net_id] = {
                    "places": [],
                    "transitions": [],
                    "arcs": []
                }
                return {"net_id": net_id, "status": "Petri net created successfully"}
                
            if "net_id" not in arguments:
                return {"error": "Missing required argument 'net_id'"}
                
            net_id = arguments["net_id"]
            if net_id not in self.nets:
                return {"error": f"Petri net with ID {net_id} does not exist"}
                
            net = self.nets[net_id]
            
            if name == "add_place":
                place = {
                    "name": arguments["name"],
                    "tokens": arguments.get("tokens", 0)
                }
                net["places"].append(place)
                return {"status": f"Place '{arguments['name']}' added successfully"}
                
            elif name == "add_transition":
                transition = {
                    "name": arguments["name"],
                    "type": arguments.get("type", "exponential"),
                    "rate": arguments["rate"]
                }
                if "enabling_function" in arguments:
                    transition["enablingFunction"] = arguments["enabling_function"]
                if "post_updater" in arguments:
                    transition["postUpdater"] = arguments["post_updater"]
                if "priority" in arguments:
                    transition["priority"] = arguments["priority"]
                if "k" in arguments:
                    transition["k"] = arguments["k"]
                    
                net["transitions"].append(transition)
                return {"status": f"Transition '{arguments['name']}' added successfully"}
                
            elif name == "add_arc":
                arc = {
                    "from": arguments["from_element"],
                    "to": arguments["to_element"]
                }
                if "type" in arguments:
                    arc["type"] = arguments["type"]
                net["arcs"].append(arc)
                return {"status": f"Arc from '{arguments['from_element']}' to '{arguments['to_element']}' added successfully"}
                
            elif name == "run_steady_state_analysis":
                net_config = {
                    "places": net["places"],
                    "transitions": net["transitions"],
                    "arcs": net["arcs"],
                    "analysis": {
                        "type": "steady",
                        "failureCondition": arguments["failure_condition"]
                    }
                }
                return self.execute_evaluator(net_config)
                
            elif name == "run_transient_analysis":
                net_config = {
                    "places": net["places"],
                    "transitions": net["transitions"],
                    "arcs": net["arcs"],
                    "analysis": {
                        "type": "transient",
                        "failureCondition": arguments["failure_condition"],
                        "maxTime": arguments["max_time"],
                        "timeStep": arguments["time_step"]
                    }
                }
                return self.execute_evaluator(net_config)
                
            else:
                return {"error": f"Unknown tool: {name}"}
                
        except Exception as e:
            logger.error(f"Error handling tool call {name}: {e}")
            return {"error": str(e)}

    def stop(self) -> None:
        logger.info("Stopping SirioMCPMock.")


class SirioMCPRealClient(BaseMCPClient):
    """
    Connects to the actual Java Spring Boot MCP Server.
    Supports both 'stdio' (spawns subprocess) and 'sse' (HTTP server connection) modes.
    """
    
    def __init__(self, mode: str, classpath: str = "", sse_url: str = "http://localhost:8081/mcp/sse"):
        self.mode = mode  # "stdio" or "sse"
        self.classpath = classpath
        self.sse_url = sse_url
        self.loop = asyncio.new_event_loop()
        self.exit_stack: Optional[AsyncExitStack] = None
        self.session: Optional[Any] = None
        self.sse_process = None

    def start(self) -> None:
        logger.info(f"Starting SirioMCPRealClient in '{self.mode}' mode...")
        self.loop.run_until_complete(self._connect())

    async def _connect(self) -> None:
        from mcp import ClientSession
        self.exit_stack = AsyncExitStack()
        try:
            if self.mode == "stdio":
                from mcp.client.stdio import stdio_client
                from mcp import StdioServerParameters
                
                if not self.classpath:
                    raise ValueError("Classpath must be specified for stdio mode.")
                    
                server_params = StdioServerParameters(
                    command="java",
                    args=[
                        "-cp", self.classpath,
                        "org.swam.sirio_mcp_server.SirioMcpServerApplication",
                        "--spring.main.web-application-type=none",
                        "--spring.ai.mcp.server.stdio=true",
                        "--logging.level.root=OFF"
                    ],
                    env=None
                )
                logger.info(f"Launching stdio server with command: java -cp ... org.swam.sirio_mcp_server.SirioMcpServerApplication")
                read_stream, write_stream = await self.exit_stack.enter_async_context(stdio_client(server_params))
            elif self.mode == "sse":
                from mcp.client.sse import sse_client
                import socket
                port = "8081"
                if "localhost:" in self.sse_url:
                    parts = self.sse_url.split("localhost:")
                    if len(parts) > 1:
                        port = parts[1].split("/")[0]
                        
                is_active = False
                try:
                    with socket.create_connection(("localhost", int(port)), timeout=0.5):
                        is_active = True
                        logger.info(f"SSE Java server is already running on port {port}. Connecting directly.")
                except Exception:
                    pass
                    
                if not is_active and self.classpath:
                    import subprocess
                    args = [
                        "java",
                        "-cp", self.classpath,
                        "org.swam.sirio_mcp_server.SirioMcpServerApplication",
                        "--spring.main.web-application-type=servlet",
                        "--spring.ai.mcp.server.stdio=false",
                        f"--server.port={port}"
                    ]
                    logger.info(f"SSE Java server is not running. Launching in background on port {port}...")
                    self.sse_process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    logger.info("Waiting for SSE Java server to boot up and open port...")
                    boot_success = False
                    for attempt in range(20):  # try for up to 10 seconds (20 * 0.5s)
                        try:
                            with socket.create_connection(("localhost", int(port)), timeout=0.5):
                                boot_success = True
                                logger.info("SSE Java server port is open. Proceeding to connect.")
                                break
                        except Exception:
                            await asyncio.sleep(0.5)
                            
                    if not boot_success:
                        logger.warning("SSE Java server did not open port in time. Attempting connection anyway...")
                elif not is_active and not self.classpath:
                    logger.warning("SSE Java server is not running and no classpath was provided to start it.")
                    
                logger.info(f"Connecting to SSE server at: {self.sse_url}")
                read_stream, write_stream = await self.exit_stack.enter_async_context(sse_client(url=self.sse_url))
            else:
                raise ValueError(f"Unsupported MCP mode: {self.mode}")

            self.session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
            await self.session.initialize()
            logger.info("MCP session initialized successfully.")
        except Exception as e:
            await self.exit_stack.aclose()
            logger.error(f"Failed to connect to MCP server: {e}")
            raise e

    def list_tools(self) -> List[Dict[str, Any]]:
        return self.loop.run_until_complete(self._list_tools())

    async def _list_tools(self) -> List[Dict[str, Any]]:
        if not self.session:
            raise RuntimeError("Client session is not initialized. Call start() first.")
            
        mcp_tools_result = await self.session.list_tools()
        openai_tools = []
        for tool in mcp_tools_result.tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            })
        return openai_tools

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.loop.run_until_complete(self._call_tool(name, arguments))

    async def _call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.session:
            raise RuntimeError("Client session is not initialized. Call start() first.")
            
        try:
            logger.info(f"Real MCP Tool call: {name} with args: {arguments}")
            response = await self.session.call_tool(name, arguments)
            
            text_contents = []
            for content in response.content:
                if content.type == "text":
                    text_contents.append(content.text)
                    
            joined_text = "\n".join(text_contents)
            
            try:
                return json.loads(joined_text)
            except Exception:
                return {"result": joined_text}
                
        except Exception as e:
            logger.error(f"Error executing real tool {name}: {e}")
            return {"error": str(e)}

    def stop(self) -> None:
        logger.info("Stopping SirioMCPRealClient.")
        if self.exit_stack:
            try:
                self.loop.run_until_complete(self.exit_stack.aclose())
            except Exception as e:
                logger.debug(f"Exception during exit stack cleanup: {e}")
        try:
            self.loop.close()
        except Exception:
            pass
        if hasattr(self, 'sse_process') and self.sse_process:
            logger.info("Terminating SSE background Java server subprocess.")
            try:
                self.sse_process.terminate()
                self.sse_process.wait(timeout=2)
            except Exception:
                try:
                    self.sse_process.kill()
                except Exception:
                    pass
