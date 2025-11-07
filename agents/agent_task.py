"""
Agent Task Module
Defines task structures for agent execution
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
import uuid


class TaskPriority(Enum):
    """Task priority levels"""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentTask:
    """Represents a task for an agent to execute"""
    agent_name: str
    task_type: str
    priority: int = 5  # Default priority (1=highest, 10=lowest)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    parameters: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self):
        """Convert task to dictionary"""
        data = {
            'task_id': self.task_id,
            'agent_name': self.agent_name,
            'task_type': self.task_type,
            'priority': self.priority,
            'status': self.status.value if isinstance(self.status, TaskStatus) else self.status,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            'started_at': self.started_at.isoformat() if self.started_at and isinstance(self.started_at, datetime) else self.started_at,
            'completed_at': self.completed_at.isoformat() if self.completed_at and isinstance(self.completed_at, datetime) else self.completed_at,
            'parameters': self.parameters,
            'result': self.result,
            'error': self.error
        }
        return data

    def __str__(self):
        """String representation"""
        return f"AgentTask(id={self.task_id}, agent={self.agent_name}, type={self.task_type}, status={self.status.value if isinstance(self.status, TaskStatus) else self.status})"
