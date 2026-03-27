"""Task dispatcher — spawns claude -p processes and tracks PIDs."""

import os
import signal
import subprocess
import time
from datetime import datetime

from .session import get_tasks_dir


def spawn_task(
    agent_file_name: str,
    session_id: str,
    project_dir: str,
    prompt: str,
    task_id: int,
    model: str | None = None,
) -> int:
    """Spawn claude -p as background process.

    Returns PID of spawned process.
    """
    tasks_dir = get_tasks_dir(session_id)
    os.makedirs(tasks_dir, exist_ok=True)

    result_file = os.path.join(tasks_dir, f"task-{task_id}-result.json")
    stderr_file = os.path.join(tasks_dir, f"task-{task_id}-stderr.log")

    expanded_dir = os.path.expanduser(project_dir)

    cmd = [
        "claude",
        "--agent", agent_file_name,
        "--session-id", session_id,
        "--output-format", "json",
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["-p", prompt])

    with open(result_file, "w") as out_f, open(stderr_file, "w") as err_f:
        process = subprocess.Popen(
            cmd,
            stdout=out_f,
            stderr=err_f,
            cwd=expanded_dir,
            start_new_session=True,
        )

    return process.pid


def get_result_file(session_id: str, task_id: int) -> str:
    """Get the result file path for a task."""
    return os.path.join(get_tasks_dir(session_id), f"task-{task_id}-result.json")


def get_stderr_file(session_id: str, task_id: int) -> str:
    """Get the stderr file path for a task."""
    return os.path.join(get_tasks_dir(session_id), f"task-{task_id}-stderr.log")


def pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


def kill_process(pid: int, graceful: bool = True) -> bool:
    """Kill a process. Returns True if process was killed."""
    try:
        if graceful:
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                time.sleep(1)
                if not pid_alive(pid):
                    return True
        os.kill(pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False
