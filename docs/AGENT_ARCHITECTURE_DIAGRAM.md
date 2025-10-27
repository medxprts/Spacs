# Agent Architecture - Before vs. After

## BEFORE: Monolithic Structure

```
┌─────────────────────────────────────────────────────────┐
│          agent_orchestrator.py (4,086 lines)            │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  • StateManager class                                    │
│  • TaskPriority enum                                     │
│  • TaskStatus enum                                       │
│  • AgentTask dataclass                                   │
│                                                           │
│  ┌─────────────────────────────────────────────┐        │
│  │      BaseAgent (for task agents)            │        │
│  │  ┌────────────────────────────────────┐     │        │
│  │  │  DealHunterAgent                   │     │        │
│  │  │  VoteTrackerAgent                  │     │        │
│  │  │  PriceMonitorAgent                 │  ◄──┼────────┼── 🎯 Moving out!
│  │  │  RiskAnalysisAgent                 │     │        │
│  │  │  DeadlineExtensionAgent            │     │        │
│  │  │  DataValidatorAgent                │     │        │
│  │  │  PreIPODuplicateCheckerAgent       │     │        │
│  │  │  PremiumAlertAgent                 │     │        │
│  │  │  DataQualityFixerAgent             │     │        │
│  │  │  FilingProcessorWrapper            │     │        │
│  │  │  SignalMonitorAgentWrapper         │     │        │
│  │  │  TelegramAgentWrapper              │     │        │
│  │  │  ... 6 more wrappers ...           │     │        │
│  │  └────────────────────────────────────┘     │        │
│  └─────────────────────────────────────────────┘        │
│                                                           │
│  • Orchestrator class                                    │
│  • Main loop and scheduling logic                        │
│                                                           │
└─────────────────────────────────────────────────────────┘

Problems:
❌ Hard to test individual agents
❌ Hard to understand (too much in one file)
❌ Hard to collaborate (merge conflicts)
❌ Hard to reuse agents elsewhere
```

## AFTER: Modular Structure

```
┌────────────────────────────────┐
│  agent_orchestrator.py (~500)  │
├────────────────────────────────┤
│ • StateManager                 │
│ • TaskPriority                 │
│ • TaskStatus                   │
│ • AgentTask                    │
│ • Orchestrator class           │
│ • Main loop logic              │
└────────────────────────────────┘
           │
           │ imports
           ▼
┌────────────────────────────────────────────────────────────┐
│                    /agents/ folder                         │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌────────────────────────────────────┐                   │
│  │  orchestrator_agent_base.py        │  ◄───┐            │
│  │  (Base class for task agents)      │      │            │
│  └────────────────────────────────────┘      │            │
│                                               │ inherits   │
│  ┌────────────────────────────────────┐      │            │
│  │  price_monitor_agent.py            │  ────┘  ✅ DONE   │
│  └────────────────────────────────────┘                   │
│                                                            │
│  ┌────────────────────────────────────┐                   │
│  │  deal_hunter_agent.py              │  ←── 📋 TODO      │
│  └────────────────────────────────────┘                   │
│                                                            │
│  ┌────────────────────────────────────┐                   │
│  │  vote_tracker_agent.py             │  ←── 📋 TODO      │
│  └────────────────────────────────────┘                   │
│                                                            │
│  ┌────────────────────────────────────┐                   │
│  │  risk_analysis_agent.py            │  ←── 📋 TODO      │
│  └────────────────────────────────────┘                   │
│                                                            │
│  ... 10 more agents ...                                   │
│                                                            │
│  ┌────────────────────────────────────┐                   │
│  │  base_agent.py                     │  ◄───┐            │
│  │  (Base class for filing agents)    │      │            │
│  └────────────────────────────────────┘      │            │
│                                               │ inherits   │
│  ┌────────────────────────────────────┐      │            │
│  │  deal_detector_agent.py            │  ────┘  (existing)│
│  │  extension_monitor_agent.py        │                   │
│  │  ipo_detector_agent.py             │                   │
│  │  redemption_extractor.py           │                   │
│  │  ... more filing agents ...        │                   │
│  └────────────────────────────────────┘                   │
│                                                            │
└────────────────────────────────────────────────────────────┘

Benefits:
✅ Easy to test (import individual agents)
✅ Easy to understand (clear file names)
✅ Easy to collaborate (separate files)
✅ Easy to reuse (import anywhere)
```

## Two Base Classes (Clarified)

### 1. `agents/orchestrator_agent_base.py`
**Purpose**: Base class for scheduled task agents  
**Pattern**: Synchronous  
**Method**: `execute(task: AgentTask) -> AgentTask`  
**Used by**: PriceMonitor, DealHunter, VoteTracker, etc.

```python
class OrchestratorAgentBase:
    def execute(self, task):
        # Run scheduled task
        ...
```

### 2. `agents/base_agent.py`
**Purpose**: Base class for filing processor agents  
**Pattern**: Async/await  
**Methods**: `can_process(filing)`, `process(filing)`  
**Used by**: DealDetector, ExtensionMonitor, IPODetector, etc.

```python
class BaseAgent(ABC):
    async def can_process(self, filing):
        # Can this agent handle this filing?
        ...
    
    async def process(self, filing):
        # Extract data from filing
        ...
```

## Progress Tracker

| Agent | Lines | Status | Module |
|-------|-------|--------|--------|
| PriceMonitorAgent | 78 | ✅ Done | `agents.price_monitor_agent` |
| DealHunterAgent | ~150 | 📋 TODO | - |
| VoteTrackerAgent | ~100 | 📋 TODO | - |
| RiskAnalysisAgent | ~80 | 📋 TODO | - |
| DeadlineExtensionAgent | ~250 | 📋 TODO | - |
| DataValidatorAgent | ~1000 | 📋 TODO | - |
| PreIPODuplicateCheckerAgent | ~150 | 📋 TODO | - |
| PremiumAlertAgent | ~200 | 📋 TODO | - |
| DataQualityFixerAgent | ~100 | 📋 TODO | - |
| All wrappers (6) | ~200 | 📋 TODO | - |

**Total**: 1 of 14 agents migrated (7% complete)

## Example Usage

### Before (embedded agent)
```python
# Had to dig through 4,000+ lines to find PriceMonitorAgent
# Defined on line 272 of agent_orchestrator.py
class PriceMonitorAgent(BaseAgent):
    ...
```

### After (modular agent)
```python
# Clear, focused file
from agents.price_monitor_agent import PriceMonitorAgent

# Can test independently
agent = PriceMonitorAgent('test', None)

# Can use in other scripts
from agents.price_monitor_agent import PriceMonitorAgent
```

---

**Visual Summary**: We're moving from a 4,086-line monolith to a clean modular architecture where each agent is a separate file in `/agents/`, making the codebase easier to maintain, test, and extend.
