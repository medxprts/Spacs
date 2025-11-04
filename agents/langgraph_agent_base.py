"""
LangGraph Agent Wrapper for Orchestrator Integration

Wraps LangGraph state machines as orchestrator-compatible agents.
"""

from typing import Dict, Optional, Any, TypedDict, Annotated
from datetime import datetime
from agents.orchestrator_agent_base import OrchestratorAgentBase
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import operator
import logging

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    """
    Base state for LangGraph agents.
    Each agent can extend this with custom fields.
    """
    ticker: str
    status: str
    error: Optional[str]
    messages: Annotated[list, operator.add]  # Accumulates messages
    result: Dict[str, Any]


class LangGraphAgentWrapper(OrchestratorAgentBase):
    """
    Base class for wrapping LangGraph state machines as orchestrator agents.

    LangGraph advantages over CrewAI:
    - Conditional routing (if/else logic)
    - Loops and cycles (agents can revisit steps)
    - State persistence (survives restarts)
    - Human-in-the-loop (wait for approval, then continue)
    """

    def __init__(self, agent_name: str, state_manager):
        super().__init__(agent_name, state_manager)
        self.graph = None
        self.checkpointer = None

    def _build_graph(self, task_params: Dict[str, Any]) -> StateGraph:
        """
        Override this method to build your LangGraph state machine.

        Example:
            graph = StateGraph(GraphState)

            # Add nodes (each is a function)
            graph.add_node("analyze", self.analyze_filing)
            graph.add_node("validate", self.validate_data)
            graph.add_node("fix_errors", self.fix_errors)

            # Add edges (routing logic)
            graph.set_entry_point("analyze")
            graph.add_edge("analyze", "validate")
            graph.add_conditional_edges(
                "validate",
                self.should_fix_errors,  # Function returns next node
                {
                    "fix": "fix_errors",
                    "done": END
                }
            )
            graph.add_edge("fix_errors", "validate")  # Loop back

            return graph.compile(checkpointer=self.checkpointer)
        """
        raise NotImplementedError("Subclasses must implement _build_graph()")

    def _get_llm(self):
        """Get LLM for agent nodes"""
        from langchain_openai import ChatOpenAI
        import os

        return ChatOpenAI(
            model="deepseek-chat",
            openai_api_base="https://api.deepseek.com/v1",
            openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
            temperature=0.1
        )

    def _init_checkpointer(self):
        """
        Initialize state persistence (optional but powerful).
        Allows graph to survive restarts and resume from last checkpoint.
        """
        return SqliteSaver.from_conn_string("/home/ubuntu/spac-research/langgraph_checkpoints.db")

    def execute(self, task):
        """Execute LangGraph state machine"""
        self._start_task(task)

        try:
            logger.info(f"[{self.agent_name}] Building LangGraph for task {task.task_id}")

            # Initialize checkpointer for state persistence
            self.checkpointer = self._init_checkpointer()

            # Build graph based on task parameters
            self.graph = self._build_graph(task.parameters)

            logger.info(f"[{self.agent_name}] Starting LangGraph execution")

            # Initialize state
            initial_state = self._create_initial_state(task.parameters)

            # Execute graph with thread_id for state persistence
            thread_config = {"configurable": {"thread_id": task.task_id}}

            # Run graph (can be paused/resumed with checkpointer)
            final_state = self.graph.invoke(initial_state, thread_config)

            # Parse result
            result = self._parse_graph_result(final_state, task.parameters)

            logger.info(f"[{self.agent_name}] LangGraph execution complete")

            self._complete_task(task, result)

        except Exception as e:
            logger.error(f"[{self.agent_name}] LangGraph execution failed: {e}")
            self._fail_task(task, str(e))

        return task

    def _create_initial_state(self, task_params: Dict) -> Dict:
        """
        Create initial state for graph.
        Override to customize starting state.
        """
        return {
            'ticker': task_params.get('ticker', ''),
            'status': 'started',
            'error': None,
            'messages': [],
            'result': {}
        }

    def _parse_graph_result(self, final_state: Dict, task_params: Dict) -> Dict:
        """
        Parse LangGraph final state into orchestrator result format.
        Override to customize result parsing.
        """
        return {
            'success': final_state.get('status') == 'completed',
            'result': final_state.get('result', {}),
            'messages': final_state.get('messages', []),
            'error': final_state.get('error'),
            'timestamp': datetime.now().isoformat()
        }
