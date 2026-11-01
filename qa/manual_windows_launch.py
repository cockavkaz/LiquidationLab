"""Launch the unchanged PR application and retain local diagnostic evidence."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

SOURCE_COMMIT = "b43f4268a6a7cd46d08ec9d5a9b37da0247c73a6"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--angle", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = ROOT / "qa-output"
    output.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = output / f"run-{stamp}.log"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["KIVY_HOME"] = str(output / "kivy")
    if args.angle:
        env["KIVY_GL_BACKEND"] = "angle_sdl2"
    record = {
        "application_commit": SOURCE_COMMIT,
        "timestamp_utc": stamp,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "kivy": version("Kivy"),
        "requested_graphics_backend": env.get("KIVY_GL_BACKEND", "default"),
        "mode": "setup-check" if args.check else "interactive",
        "manual_visual_check": "pending",
    }
    if args.check:
        code = 0
        print("Подготовка завершена. Этот режим не проверяет окно приложения.", flush=True)
    else:
        print("Открываю приложение. Когда появится окно, пришлите его снимок в чат.", flush=True)
        print("Для этой проверки достаточно демо; данные Bybit загружать не требуется.", flush=True)
        print("Лог запуска:", log_path, flush=True)
        try:
            with log_path.open("w", encoding="utf-8") as log:
                log.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n\n")
                log.flush()
                code = subprocess.call(
                    [sys.executable, "-u", str(ROOT / "main.py")],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                )
        except Exception:
            code = 1
            with log_path.open("a", encoding="utf-8") as log:
                traceback.print_exc(file=log)
        if code:
            print("Не удалось запустить приложение. Пришлите снимок этого окна или указанный лог.")
            print(log_path.read_text(encoding="utf-8", errors="replace")[-5000:])
    record["exit_code"] = code
    (output / f"environment-{stamp}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
