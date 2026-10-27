import subprocess
import sys
import tempfile
from pathlib import Path

from brain.tools_executor import register_tool


@register_tool("run_python_code")
def _run_python_code(code: str, description: str = "") -> dict:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path.home()),
        )

        Path(tmp_path).unlink(missing_ok=True)

        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode != 0:
            return {"error": f"Error: {error or 'Codigo falló'}", "output": output}

        return {
            "status": "success",
            "output": output[:3000] if output else "(sin salida)",
            "description": description,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Código tardó más de 30 segundos. Detenido."}
    except Exception as e:
        return {"error": f"Error ejecutando código: {e}"}
