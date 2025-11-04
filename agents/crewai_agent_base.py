"""
CrewAI Agent Wrapper for Orchestrator Integration

Wraps CrewAI crews as orchestrator-compatible agents.
"""

from typing import Dict, Optional, Any
from datetime import datetime
from agents.orchestrator_agent_base import OrchestratorAgentBase
from crewai import Agent, Task, Crew, Process
import logging

logger = logging.getLogger(__name__)


class CrewAIAgentWrapper(OrchestratorAgentBase):
    """
    Base class for wrapping CrewAI crews as orchestrator agents.

    Subclasses define the crew (agents + tasks) and implement execute().
    """

    def __init__(self, agent_name: str, state_manager):
        super().__init__(agent_name, state_manager)
        self.crew: Optional[Crew] = None

    def _build_crew(self, task_params: Dict[str, Any]) -> Crew:
        """
        Override this method to build your CrewAI crew based on task parameters.

        Example:
            analyst = Agent(
                role="SEC Filing Analyst",
                goal="Extract deal data from 8-K filings",
                backstory="Expert in SEC filings...",
                llm=self._get_llm()
            )

            task = Task(
                description=f"Analyze filing for {task_params['ticker']}",
                agent=analyst,
                expected_output="JSON with deal data"
            )

            return Crew(
                agents=[analyst],
                tasks=[task],
                process=Process.sequential
            )
        """
        raise NotImplementedError("Subclasses must implement _build_crew()")

    def _get_llm(self):
        """
        Get LLM configuration for CrewAI agents.
        Can use OpenAI-compatible endpoints (DeepSeek, etc.)
        """
        from langchain_openai import ChatOpenAI
        import os

        return ChatOpenAI(
            model="deepseek-chat",
            openai_api_base="https://api.deepseek.com/v1",
            openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
            temperature=0.1
        )

    def execute(self, task):
        """
        Execute CrewAI crew and return result in orchestrator format.
        """
        self._start_task(task)

        try:
            logger.info(f"[{self.agent_name}] Building CrewAI crew for task {task.task_id}")

            # Build crew based on task parameters
            self.crew = self._build_crew(task.parameters)

            logger.info(f"[{self.agent_name}] Starting CrewAI execution")

            # Execute crew
            crew_result = self.crew.kickoff()

            # Parse crew output
            result = self._parse_crew_result(crew_result, task.parameters)

            logger.info(f"[{self.agent_name}] CrewAI execution complete")

            self._complete_task(task, result)

        except Exception as e:
            logger.error(f"[{self.agent_name}] CrewAI execution failed: {e}")
            self._fail_task(task, str(e))

        return task

    def _parse_crew_result(self, crew_result, task_params: Dict) -> Dict:
        """
        Override to parse CrewAI output into orchestrator result format.

        Default: Returns crew output as-is
        """
        return {
            'success': True,
            'crew_output': str(crew_result),
            'timestamp': datetime.now().isoformat()
        }
