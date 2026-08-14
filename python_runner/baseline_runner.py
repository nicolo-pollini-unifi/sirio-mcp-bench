"""
This module manages the execution and compilation of the Java SIRIO baseline solver.
"""

import os
import sys
import json
import logging
import tempfile
import subprocess
from typing import Dict, Any

logger = logging.getLogger(__name__)

def ensure_project_built(workspace_path: str) -> None:
    """
    Ensures that the Java dependencies are compiled and the classpath file exists.
    If missing, runs Maven commands to compile and build the classpath dynamically.

    Args:
        workspace_path: Path to the root workspace containing pom.xml.
    """
    classpath_file = os.path.join(workspace_path, "classpath.txt")
    should_build = not os.path.exists(classpath_file)
    
    if not should_build:
        try:
            with open(classpath_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if content:
                separator = ";" if sys.platform.startswith("win") else ":"
                parts = content.split(separator)
                if parts and not os.path.exists(parts[0]):
                    logger.info("Detected invalid paths in classpath.txt. Rebuilding...")
                    should_build = True
            else:
                should_build = True
        except Exception:
            should_build = True

    if should_build:
        logger.info("Compiling project and generating classpath.txt automatically via Maven...")
        use_shell = sys.platform.startswith("win")
        try:
            subprocess.run(
                ["mvn", "compile", "dependency:build-classpath", "-Dmdep.outputFile=classpath.txt"],
                cwd=workspace_path,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=use_shell
            )
            subprocess.run(
                ["mvn", "package", "-DskipTests"],
                cwd=workspace_path,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=use_shell
            )
            logger.info("Project built successfully. Generated classpath.txt.")
        except Exception as e:
            logger.warning(
                f"Failed to build the project automatically via Maven: {e}.\n"
                "Please make sure Maven (mvn) and JDK are installed and configured on your PATH,\n"
                "and run: mvn compile dependency:build-classpath \"-Dmdep.outputFile=classpath.txt\" manually."
            )

def run_java_baseline(workspace_path: str, case_json_path: str, case_id: str) -> Dict[str, Any]:
    """
    Executes the Java SirioCLI executable to solve baseline values for a case.

    Args:
        workspace_path: The root project directory.
        case_json_path: Path to the configuration JSON file.
        case_id: The ID of the test case to analyze.

    Returns:
        A dictionary parsed from the Java solver's output JSON.
    """
    temp_out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    temp_out.close()
    
    classpath_file = os.path.join(workspace_path, "classpath.txt")
    if not os.path.exists(classpath_file):
        raise FileNotFoundError("classpath.txt not found. Build the project first.")
        
    with open(classpath_file, 'r', encoding='utf-8') as f:
        maven_deps = f.read().strip()
        
    target_classes = os.path.join(workspace_path, "target", "classes")
    target_test_classes = os.path.join(workspace_path, "target", "test-classes")
    sirio_jar = os.path.join(workspace_path, "lib", "sirio-2.0.4.jar")
    
    separator = ";" if sys.platform.startswith("win") else ":"
    classpath = separator.join([target_classes, target_test_classes, sirio_jar, maven_deps])
    
    cmd = [
        "java",
        "-cp", classpath,
        "org.util.SirioCLI",
        "--input", case_json_path,
        "--case", case_id,
        "--output", temp_out.name
    ]
    
    logger.info(f"Running Java baseline command for case {case_id}...")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with open(temp_out.name, 'r', encoding='utf-8') as f:
            return json.load(f)
    finally:
        try:
            os.unlink(temp_out.name)
        except OSError:
            pass
