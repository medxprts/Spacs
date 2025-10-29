"""
Feedback System - Refactored
Version: 2.0.0

Simplified, modular feedback mechanism for SPAC data quality.

Components:
- validation_queue.py: Queue management (database-backed)
- telegram_interface.py: Conversational approval workflow
- investigation_engine.py: AI-powered root cause analysis
- fix_applier.py: Execute approved fixes
- learning_log.py: Track learnings and effectiveness
- self_improvement.py: Propose code fixes for repeated errors
"""

__version__ = "2.0.0"
__all__ = [
    "ValidationQueue",
    "TelegramInterface",
    "InvestigationEngine",
    "FixApplier",
    "LearningLog",
    "SelfImprovementAgent"
]

from .validation_queue import ValidationQueue
from .telegram_interface import TelegramInterface
from .investigation_engine import InvestigationEngine
from .fix_applier import FixApplier
from .learning_log import LearningLog
from .self_improvement import SelfImprovementAgent
