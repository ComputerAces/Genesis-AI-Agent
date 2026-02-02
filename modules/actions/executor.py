import os
import json
import subprocess
import sys
import logging
import venv
from typing import Dict, Any, Optional, List

class ActionExecutor:
    def __init__(self):
        self.logger = logging.getLogger("ActionExecutor")

    def _ensure_plugin_venv(self, plugin_path: str) -> Optional[str]:
        """
        Checks if plugin has requirements.txt. If so, ensures venv exists
        and dependencies are installed. Returns path to venv python executable.
        """
        requirements_path = os.path.join(plugin_path, "requirements.txt")
        venv_path = os.path.join(plugin_path, ".venv")
        
        if not os.path.exists(requirements_path):
            return None  # No special requirements, use system Python
        
        # Check if venv already exists
        if os.name == 'nt':
            venv_python = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            venv_python = os.path.join(venv_path, "bin", "python")
        
        installed_marker = os.path.join(venv_path, ".deps_installed")
        
        if not os.path.exists(venv_python):
            self.logger.info(f"Creating venv for plugin at {plugin_path}")
            try:
                venv.create(venv_path, with_pip=True)
            except Exception as e:
                self.logger.error(f"Failed to create venv: {e}")
                return None
        
        # Install dependencies if not already done
        if not os.path.exists(installed_marker):
            self.logger.info(f"Installing dependencies for plugin at {plugin_path}")
            try:
                subprocess.run(
                    [venv_python, "-m", "pip", "install", "-r", requirements_path, "-q"],
                    check=True,
                    capture_output=True,
                    timeout=120  # 2 min timeout for pip
                )
                # Create marker file
                with open(installed_marker, 'w') as f:
                    f.write("installed")
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to install dependencies: {e.stderr}")
                return None
            except Exception as e:
                self.logger.error(f"Failed to install dependencies: {e}")
                return None
        
        return venv_python

    def execute(self, action_def: Dict, args: Dict, context: Dict, progress_callback=None) -> Dict:
        """
        Executes an action based on its definition.
        
        Args:
            action_def: The metadata from registry (path, role, spec, etc.)
            args: Arguments passed to the action
            context: Context info (user_id, chat_id, etc.)
        
        Returns:
            Dict containing 'status', 'output', 'error'
        """
        action_type = action_def["spec"].get("type", "python")
        script_path = action_def["script"]
        plugin_path = action_def["path"]
        role = action_def["role"]
        
        # 1. Setup Environment
        env = os.environ.copy()
        
        # Determine GENESIS_HOME based on role and user
        user_id = context.get("user_id")
        if role == "system":
            genesis_home = os.path.abspath(os.path.join("bot_data", "_system"))
        elif role == "user" and user_id:
            genesis_home = os.path.abspath(os.path.join("bot_data", "users", user_id))
        else:
            genesis_home = os.path.abspath(os.path.join("data", "tmp"))

        if not os.path.exists(genesis_home):
            os.makedirs(genesis_home, exist_ok=True)

        env["GENESIS_HOME"] = genesis_home
        env["GENESIS_PLUGIN_PATH"] = plugin_path
        
        # Pass arguments as JSON string
        args_json = json.dumps(args)
        env["ACTION_ARGS"] = args_json

        self.logger.info(f"Executing {action_def['spec']['name']} ({action_type})")

        try:
            if action_type == "python":
                # Check for plugin-specific venv
                venv_python = self._ensure_plugin_venv(plugin_path)
                python_exe = venv_python if venv_python else sys.executable
                return self._execute_python_internal(script_path, args, env, python_exe, progress_callback)
            elif action_type == "python_inproc":
                 return self._execute_python_inproc(script_path, args, context) # In-proc needs update too?
            elif action_type == "process":
                return self._execute_process(script_path, args_json, env, progress_callback)
            else:
                return {"status": "error", "error": f"Unknown action type: {action_type}"}

        except Exception as e:
            self.logger.error(f"Execution failed: {e}")
            return {"status": "error", "error": str(e)}

    def _execute_python_inproc(self, script_path: str, args: Dict, context: Dict) -> Dict:
        """
        Executes a python script INSIDE the current process.
        This allows caching of heavy resources (like ML models) in global variables.
        WARNING: Plugin crashes can crash the main server.
        """
        import importlib.util
        import hashlib
        
        try:
            # Generate a consistent module name based on path
            module_name = "plugin_" + hashlib.md5(script_path.encode()).hexdigest()
            
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, script_path)
                if spec is None:
                     return {"status": "error", "error": f"Could not load spec for {script_path}"}
                
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            
            # Check for execute function
            if hasattr(module, "execute"):
                # We expect execute(args: Dict, context: Dict) -> Dict
                return module.execute(args, context)
            else:
                return {"status": "error", "error": "Plugin script missing 'execute(args, context)' function"}
                
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.logger.error(f"In-process execution failed: {tb}")
            return {"status": "error", "error": f"In-process execution failed: {str(e)}"}

    def _execute_python_internal(self, script_path: str, args: Dict, env: Dict, python_exe: str = None, progress_callback=None) -> Dict:
        """
        Executes a python script as a subprocess.
        Uses provided python_exe (from venv) or falls back to sys.executable.
        """
        if python_exe is None:
            python_exe = sys.executable
        cmd = [python_exe, script_path]
        return self._run_subprocess(cmd, args_json=json.dumps(args), env=env, progress_callback=progress_callback)

    def _execute_process(self, script_path: str, args_json: str, env: Dict, progress_callback=None) -> Dict:
        """Executes an arbitrary executable."""
        cmd = [script_path]
        return self._run_subprocess(cmd, args_json, env, progress_callback)

    def _run_subprocess(self, cmd: List[str], args_json: str, env: Dict, progress_callback=None) -> Dict:
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                cwd=env.get("GENESIS_PLUGIN_PATH", os.getcwd()),
                bufsize=1 # Line buffered
            )
            
            # Send input
            if args_json:
                process.stdin.write(args_json)
                process.stdin.close()
            
            stdout_lines = []
            stderr_lines = []
            
            # Read stdout line by line
            while True:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                
                stdout_lines.append(line)
                
                # Check for progress
                if progress_callback and line.strip().startswith("{"):
                    try:
                        data = json.loads(line)
                        if data.get("status") == "progress":
                            progress_callback(data)
                    except:
                        pass
            
            # Capture stderr
            stderr_output = process.stderr.read()
            
            return_code = process.wait()
            full_stdout = "".join(stdout_lines)
            
            if return_code == 0:
                try:
                    # Try to find the last JSON line as the result
                    # Or parse the whole thing if it's one JSON
                    output_data = None
                    for line in reversed(stdout_lines):
                        if line.strip().startswith("{"):
                            try:
                                output_data = json.loads(line)
                                if output_data.get("status") != "progress":
                                    break
                            except:
                                continue
                    
                    if not output_data:
                        output_data = json.loads(full_stdout)
                        
                    return {"status": "success", "output": output_data}
                except json.JSONDecodeError:
                    return {"status": "success", "output": full_stdout}
            else:
                return {"status": "error", "error": stderr_output or "Unknown Error", "exit_code": return_code}

        except subprocess.TimeoutExpired:
            process.kill()
            return {"status": "error", "error": "Execution timed out"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
