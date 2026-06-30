import os
import sys
import logging
import json

logging.basicConfig(level=logging.INFO)

# Add parent directory (python_runner/) to path to resolve mcp_client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_client import SirioMCPRealClient

def main():
    # Resolve workspace root (parent of python_runner/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_path = os.path.dirname(os.path.dirname(script_dir))
    
    # Read classpath
    classpath_file = os.path.join(workspace_path, "classpath.txt")
    with open(classpath_file, 'r', encoding='utf-8') as f:
        maven_deps = f.read().strip()
    target_classes = os.path.join(workspace_path, "target", "classes")
    sirio_jar = os.path.join(workspace_path, "lib", "sirio-2.0.4.jar")
    classpath = ";".join([target_classes, sirio_jar, maven_deps])

    client = SirioMCPRealClient(mode="stdio", classpath=classpath)
    print("Starting client...")
    client.start()
    
    try:
        print("\nListing tools:")
        tools = client.list_tools()
        for t in tools:
            func = t["function"]
            print(f"- {func['name']}: {func['description']}")
            
        print("\nExecuting tool calls:")
        # 1. create
        res = client.handle_tool_call("create", {})
        print("create result:", res)
        
        # 2. add_places
        res = client.handle_tool_call("add_places", {"node_names": ["P0", "P1"]})
        print("add_places result:", res)
        
        # 3. add_tokens
        res = client.handle_tool_call("add_tokens", {"name": "P0", "num": 1})
        print("add_tokens result:", res)
        
        # 4. add_transitions
        res = client.handle_tool_call("add_transitions", {"transition_names": ["T0"]})
        print("add_transitions result:", res)
        
        # 5. add_precondition
        res = client.handle_tool_call("add_precondition", {"place_name": "P0", "transition_name": "T0"})
        print("add_precondition result:", res)
        
        # 6. add_postcondition
        res = client.handle_tool_call("add_postcondition", {"place_name": "P1", "transition_name": "T0"})
        print("add_postcondition result:", res)
        
        # 7. add_EXP
        res = client.handle_tool_call("add_EXP", {"transition_name": "T0", "rate": 0.05})
        print("add_EXP result:", res)
        
        # 8. show_net
        res = client.handle_tool_call("show_net", {})
        if isinstance(res, dict):
            print("show_net result:", res.get("result"))
        else:
            print("show_net result:", res)
        
        # 9. execute_steady_state_analysis
        res = client.handle_tool_call("execute_steady_state_analysis", {})
        print("execute_steady_state_analysis result:", res)
        
    finally:
        print("Stopping client...")
        client.stop()

if __name__ == "__main__":
    main()
