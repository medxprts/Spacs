"""
Orchestrator Agent Base Class
Base class for task-based agents that are scheduled and executed by the orchestrator
"""

from datetime import datetime
from typing import Dict
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrchestratorAgentBase:
    """Base class for orchestrator task agents"""

    def __init__(self, name: str, state_manager=None):
        self.name = name
        self.state_manager = state_manager

    def execute(self, task) -> 'AgentTask':
        """Execute a task - to be implemented by subclasses"""
        raise NotImplementedError

    def _start_task(self, task):
        """Mark task as started"""
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now()
        print(f"[{self.name}] Starting: {task.task_type}")

    def _complete_task(self, task, result: Dict):
        """Mark task as completed"""
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.result = result

        if self.state_manager:
            self.state_manager.record_task(task)
            self.state_manager.set_last_run(self.name, task.task_type, task.completed_at)

        duration = (task.completed_at - task.started_at).total_seconds()
        print(f"[{self.name}] ✓ Completed in {duration:.1f}s")

    def _fail_task(self, task, error: str):
        """Mark task as failed"""
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now()
        task.error = error

        if self.state_manager:
            self.state_manager.record_task(task)

        print(f"[{self.name}] ✗ Failed: {error}")
