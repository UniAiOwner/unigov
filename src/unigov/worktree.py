"""Ephemeral Git Worktree Sandboxing for Task Execution in UniGov."""

import subprocess
import shutil
from pathlib import Path
from typing import Optional


def is_git_repo(root_dir: Path = Path(".")) -> bool:
    """Checks whether root_dir is inside a valid git working tree with a HEAD commit."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root_dir,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0 or res.stdout.strip() != "true":
            return False

        head_res = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root_dir,
            capture_output=True,
            text=True,
        )
        return head_res.returncode == 0
    except Exception:
        return False


def get_task_branch_name(task_id: str) -> str:
    """Standardizes git branch name for a task."""
    clean_id = task_id.lower().replace(":", "-").replace("/", "-")
    return f"unigov/task/{clean_id}"


def get_task_worktree_path(root_dir: Path, task_id: str) -> Path:
    """Returns the filesystem path for the ephemeral task worktree."""
    clean_id = task_id.lower().replace(":", "-").replace("/", "-")
    return root_dir / ".unigov" / "worktrees" / clean_id


def create_task_worktree(root_dir: Path, task_id: str) -> Path:
    """Creates an isolated git worktree for executing a task without dirtying main."""
    if not is_git_repo(root_dir):
        raise RuntimeError("Ephemeral worktree execution requires an active Git repository with at least one commit.")

    worktree_path = get_task_worktree_path(root_dir, task_id)
    branch_name = get_task_branch_name(task_id)

    # Clean up stale worktree or branch if exists
    cleanup_task_worktree(root_dir, task_id)

    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"]
    res = subprocess.run(cmd, cwd=root_dir, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to create git worktree: {res.stderr.strip()}")

    return worktree_path


def cleanup_task_worktree(root_dir: Path, task_id: str, delete_branch: bool = True) -> None:
    """Removes the ephemeral git worktree and optionally deletes the task branch."""
    worktree_path = get_task_worktree_path(root_dir, task_id)
    branch_name = get_task_branch_name(task_id)

    if worktree_path.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=root_dir,
            capture_output=True,
        )
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

    subprocess.run(["git", "worktree", "prune"], cwd=root_dir, capture_output=True)

    if delete_branch:
        subprocess.run(["git", "branch", "-D", branch_name], cwd=root_dir, capture_output=True)


def merge_task_worktree(root_dir: Path, task_id: str) -> bool:
    """Merges the verified task branch into the current Git branch and cleans up worktree."""
    branch_name = get_task_branch_name(task_id)

    # First prune the worktree to release the branch
    cleanup_task_worktree(root_dir, task_id, delete_branch=False)

    merge_res = subprocess.run(
        ["git", "merge", "--no-ff", branch_name, "-m", f"feat(unigov): complete task {task_id}"],
        cwd=root_dir,
        capture_output=True,
        text=True,
    )

    # Delete branch after merge
    subprocess.run(["git", "branch", "-D", branch_name], cwd=root_dir, capture_output=True)
    return merge_res.returncode == 0
