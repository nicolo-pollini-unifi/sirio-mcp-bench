import os
import sys
import uuid
import json
import logging
import tempfile
import subprocess
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# List of tool declarations in OpenAI-compatible format
SIRIO_TOOL_SCHEMAS = [
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

class SirioMCPMock:
    """
    Simulates the SIRIO library MCP Server by managing Petri net state and
    running actual calculations via the Java PetriNetEvaluator helper class.
    """
    
    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.abspath(workspace_path)
        self.nets: Dict[str, Dict[str, Any]] = {}
        self._classpath: Optional[str] = None
        
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
                
        # Include local project target/classes, target/test-classes and local lib jar
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
        """
        Calls the Java PetriNetEvaluator subprocess with the given net configuration.
        """
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
            # Cleanup temp files
            try:
                os.unlink(temp_in.name)
                os.unlink(temp_out.name)
            except OSError:
                pass

    def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Routes the tool invocation to the correct handler.
        """
        logger.info(f"MCP Tool call: {name} with args: {arguments}")
        
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
