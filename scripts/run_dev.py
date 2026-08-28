from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def wait_for_url(
    url: str,
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited during startup with code {process.returncode}")
        if url_is_available(url):
            return
        time.sleep(0.25)
    raise RuntimeError(f"Service did not become ready at {url}")


def url_is_available(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as response:
            return response.status < 500
    except (OSError, URLError):
        return False


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return

    if os.name == "nt":
        try:
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        except OSError:
            process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)

    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def process_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def install_stop_handlers(stop_requested: threading.Event) -> None:
    def request_stop(_signum: int, _frame: object) -> None:
        stop_requested.set()

    signal_names = ["SIGINT", "SIGTERM"]
    if os.name == "nt":
        signal_names.append("SIGBREAK")
    for signal_name in signal_names:
        signal.signal(getattr(signal, signal_name), request_stop)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-port", type=int, default=18001)
    parser.add_argument("--frontend-port", type=int, default=3000)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    stop_requested = threading.Event()
    install_stop_handlers(stop_requested)
    project_root = Path(__file__).resolve().parents[1]
    frontend_root = project_root / "frontend"
    next_cli = frontend_root / "node_modules" / "next" / "dist" / "bin" / "next"
    if not next_cli.is_file():
        raise RuntimeError("Next.js is not installed; run npm ci in frontend first")

    environment = os.environ.copy()
    environment["FRONTEND_ORIGINS"] = (
        f"http://localhost:{arguments.frontend_port},"
        f"http://127.0.0.1:{arguments.frontend_port}"
    )
    environment["NEXT_PUBLIC_API_URL"] = (
        f"http://127.0.0.1:{arguments.backend_port}"
    )

    backend_log = Path(tempfile.gettempdir()) / (
        f"jobflow-agent-backend-{arguments.backend_port}.log"
    )
    backend_error_log = Path(tempfile.gettempdir()) / (
        f"jobflow-agent-backend-{arguments.backend_port}.error.log"
    )
    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None

    try:
        with backend_log.open("wb") as stdout, backend_error_log.open("wb") as stderr:
            backend = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "src.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(arguments.backend_port),
                ],
                cwd=project_root,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                **process_options(),
            )

        wait_for_url(
            f"http://127.0.0.1:{arguments.backend_port}/health",
            backend,
            15,
        )
        frontend = subprocess.Popen(
            [
                "node",
                str(next_cli),
                "dev",
                "--hostname",
                "localhost",
                "--port",
                str(arguments.frontend_port),
            ],
            cwd=frontend_root,
            env=environment,
            **process_options(),
        )
        wait_for_url(
            f"http://localhost:{arguments.frontend_port}",
            frontend,
            60,
        )

        print(f"Backend: http://127.0.0.1:{arguments.backend_port}", flush=True)
        print(f"Frontend: http://localhost:{arguments.frontend_port}", flush=True)
        print("Press Ctrl+C to stop both services.", flush=True)

        while backend.poll() is None and frontend.poll() is None:
            if stop_requested.wait(0.5):
                print("\nStopping development services...", flush=True)
                return 0
        if backend.returncode not in (None, 0):
            raise RuntimeError(f"Backend exited with code {backend.returncode}")
        if frontend.returncode not in (None, 0):
            raise RuntimeError(f"Frontend exited with code {frontend.returncode}")
        return 0
    except KeyboardInterrupt:
        print("\nStopping development services...", flush=True)
        return 0
    finally:
        stop_process(frontend)
        stop_process(backend)


if __name__ == "__main__":
    raise SystemExit(main())
