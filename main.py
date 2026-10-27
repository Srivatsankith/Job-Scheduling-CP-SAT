import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
VENV_DIR = BACKEND_DIR / ".venv"


def run_npm(npm_path, arguments, frontend_env):
    if os.name == "nt":
        command = subprocess.list2cmdline([str(npm_path), *arguments])
        return subprocess.run(
            command, cwd=FRONTEND_DIR, env=frontend_env, check=True, shell=True
        )
    return subprocess.run(
        [str(npm_path), *arguments], cwd=FRONTEND_DIR, env=frontend_env, check=True
    )


def stop_process(process):
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    python_path = (
        VENV_DIR / "Scripts" / "python.exe"
        if os.name == "nt"
        else VENV_DIR / "bin" / "python"
    )
    if not python_path.exists():
        print("Creating the backend virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    print("Checking backend requirements...")
    subprocess.run(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            "-r",
            str(BACKEND_DIR / "requirements.txt"),
        ],
        check=True,
    )

    frontend_env = os.environ.copy()
    bundled_node = ROOT / "node-v24.22.0-win-x64"
    if os.name == "nt" and (bundled_node / "npm.cmd").exists():
        frontend_env["PATH"] = str(bundled_node) + os.pathsep + frontend_env["PATH"]
        npm_path = bundled_node / "npm.cmd"
    else:
        npm_command = shutil.which("npm.cmd") or shutil.which("npm")
        if npm_command is None:
            raise RuntimeError(
                "Node.js and npm were not found. Install Node.js or add npm to PATH."
            )
        npm_path = Path(npm_command)

    if not (FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js").exists():
        print("Installing frontend packages...")
        run_npm(npm_path, ["ci"], frontend_env)

    backend_command = [
        str(python_path),
        "-m",
        "uvicorn",
        "api:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    processes = []
    try:
        processes.append(
            subprocess.Popen(
                backend_command,
                cwd=BACKEND_DIR,
                creationflags=creation_flags,
            )
        )
        processes.append(
            subprocess.Popen(
                subprocess.list2cmdline([str(npm_path), "run", "dev"])
                if os.name == "nt"
                else [str(npm_path), "run", "dev"],
                cwd=FRONTEND_DIR,
                env=frontend_env,
                shell=os.name == "nt",
                creationflags=creation_flags,
            )
        )
        print("\nBackend: http://127.0.0.1:8000")
        print("Open the Local URL printed by Vite (usually http://localhost:5173).")
        print("Press Ctrl+C to stop both services.")

        while True:
            for process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    raise RuntimeError(
                        f"A service stopped unexpectedly (exit code {exit_code})."
                    )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping backend and frontend...")
    finally:
        for process in reversed(processes):
            stop_process(process)


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
