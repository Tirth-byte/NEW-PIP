"""
Secure isolated Python code runner.
Runs learner code in an isolated subprocess with timeout, dedicated temp dir,
resource limits, and helpful error diagnostics.
"""
import sys
import os
import subprocess
import tempfile
import time
from typing import Dict, Any, Optional

try:
    import resource
except ImportError:  # Windows does not expose POSIX resource limits.
    resource = None

from app.execution.security import validate_code

MAX_OUTPUT_BYTES = 256_000


def _apply_resource_limits() -> None:
    """Apply limits in the child immediately before learner code starts."""
    if resource is None:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))


def _read_capped(path: str) -> str:
    with open(path, "rb") as stream:
        data = stream.read(MAX_OUTPUT_BYTES + 1)
    if len(data) > MAX_OUTPUT_BYTES:
        data = data[:MAX_OUTPUT_BYTES] + b"\n[output truncated]"
    return data.decode("utf-8", errors="replace")

def run_python_code(code: str, timeout_sec: float = 3.5, input_data: str = "") -> Dict[str, Any]:
    """
    Execute user-provided Python code in an isolated subprocess.
    Returns:
        {
            "success": bool,
            "stdout": str,
            "stderr": str,
            "exit_code": int,
            "elapsed_ms": float,
            "timeout": bool,
            "security_violation": bool,
            "explanation": str
        }
    """
    start_time = time.perf_counter()

    violation = validate_code(code)
    if violation:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Security restriction: {violation}",
            "exit_code": -1,
            "elapsed_ms": 0.0,
            "timeout": False,
            "security_violation": True,
            "explanation": "System, process, network, and interpreter-internal operations are restricted."
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        script_file = os.path.join(temp_dir, "learner_script.py")
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Build clean environment
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONUNBUFFERED": "1",
            "LC_ALL": "en_US.UTF-8",
            "LANG": "en_US.UTF-8",
            "HOME": temp_dir,
            "TMPDIR": temp_dir,
            "MPLCONFIGDIR": os.path.join(temp_dir, ".matplotlib"),
        }

        python_bin = sys.executable

        try:
            stdout_path = os.path.join(temp_dir, "stdout.txt")
            stderr_path = os.path.join(temp_dir, "stderr.txt")
            with open(stdout_path, "wb") as stdout_file, open(stderr_path, "wb") as stderr_file:
                process_options = {}
                if os.name == "posix":
                    process_options["preexec_fn"] = _apply_resource_limits
                process = subprocess.Popen(
                    [python_bin, "-I", script_file],
                    stdin=subprocess.PIPE,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=temp_dir,
                    env=env,
                    text=True,
                    **process_options,
                )
                process.communicate(input=input_data, timeout=timeout_sec)
            stdout = _read_capped(stdout_path)
            stderr = _read_capped(stderr_path)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            exit_code = process.returncode
            success = (exit_code == 0)

            explanation = ""
            if not success:
                if "SyntaxError" in stderr:
                    explanation = "Syntax Error detected: Double check colons, parentheses, indentations, and quotation marks."
                elif "NameError" in stderr:
                    explanation = "Name Error: A variable or function was referenced before being defined or is misspelled."
                elif "TypeError" in stderr:
                    explanation = "Type Error: An operation was performed on an inappropriate data type (e.g. adding string and integer)."
                elif "IndexError" in stderr:
                    explanation = "Index Error: Attempted to access a sequence position that does not exist."
                elif "KeyError" in stderr:
                    explanation = "Key Error: The requested dictionary key was not found."
                elif "ZeroDivisionError" in stderr:
                    explanation = "Zero Division Error: Division or modulo by zero is undefined."
                else:
                    explanation = "Execution encountered an error. Review the error details in the console output above."

            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "elapsed_ms": elapsed_ms,
                "timeout": False,
                "security_violation": False,
                "explanation": explanation
            }

        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            stdout = _read_capped(stdout_path)
            stderr = _read_capped(stderr_path)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "success": False,
                "stdout": stdout,
                "stderr": f"Execution Timed Out: Program ran for more than {timeout_sec} seconds. Check for infinite loops (e.g. while True without an exit condition).",
                "exit_code": -9,
                "elapsed_ms": elapsed_ms,
                "timeout": True,
                "security_violation": False,
                "explanation": "Timeout reached. In educational code, long runs usually indicate an uncontrolled loop or blocked input."
            }
        except Exception as e:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution system failure: {str(e)}",
                "exit_code": -1,
                "elapsed_ms": elapsed_ms,
                "timeout": False,
                "security_violation": False,
                "explanation": "System runner encountered an unexpected condition."
            }
