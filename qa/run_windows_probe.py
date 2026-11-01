"""Bound the GUI subprocess so Actions uploads logs even if SDL blocks."""
import json
import platform
import subprocess
import sys
from pathlib import Path

output = Path("qa-output")
output.mkdir(exist_ok=True)
log = output / "windows-run.log"
print("Windows probe host:", platform.platform(), flush=True)
with log.open("w", encoding="utf-8") as stream:
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "qa.windows_kivy_probe"],
        stdout=stream, stderr=subprocess.STDOUT)
    try:
        code = process.wait(timeout=130)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        code = 124
        status = output / "status.json"
        if not status.exists():
            status.write_text(
                json.dumps({"success": False, "error": "Windows GUI subprocess exceeded 130 seconds"}),
                encoding="utf-8")
        print("KIVY_PROBE_EXTERNAL_TIMEOUT", flush=True)
print("KIVY_PROBE_EXIT", code, flush=True)
print(log.read_text(encoding="utf-8", errors="replace")[-16000:], flush=True)
sys.exit(code)
