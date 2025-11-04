"""
Filing Analysis Crew Agent

Multi-agent crew for deep SEC filing analysis.
Replaces single AI call in sec_data_scraper.py with collaborative analysis.
"""

from typing import Dict, Any
from agents.crewai_agent_base import CrewAIAgentWrapper
from crewai import Agent, Task, Crew, Process
import json
import logging

logger = logging.getLogger(__name__)


class FilingAnalysisCrewAgent(CrewAIAgentWrapper):
    """
    CrewAI-powered filing analysis with 3 specialized agents:
    1. Analyst - Identifies key sections and filing structure
    2. Extractor - Pulls structured data (dates, numbers, entities)
    3. Validator - Cross-checks extracted data for consistency
    """

    def __init__(self, state_manager):
        super().__init__("filing_analysis_crew", state_manager)

    def _build_crew(self, task_params: Dict[str, Any]) -> Crew:
        """
        Build 3-agent crew for filing analysis.

        Task Parameters:
            - ticker (str): SPAC ticker
            - filing_type (str): 8-K, S-1, 10-Q, etc.
            - filing_text (str): Full filing HTML/text content
            - extraction_goals (list): Fields to extract (e.g., ['ipo_date', 'target', 'deal_value'])
        """
        ticker = task_params.get('ticker')
        filing_type = task_params.get('filing_type')
        filing_text = task_params.get('filing_text', '')
        goals = task_params.get('extraction_goals', [])

        # Truncate filing text if too long (CrewAI context limits)
        max_chars = 50000
        if len(filing_text) > max_chars:
            filing_text = filing_text[:max_chars] + "\n\n[...truncated for length...]"

        # Agent 1: Analyst - Structure identification
        analyst = Agent(
            role="SEC Filing Structure Analyst",
            goal=f"Identify key sections in {filing_type} filing for {ticker} that contain: {', '.join(goals)}",
            backstory="""You are an expert in SEC filing structures. You quickly identify
            where critical information is located (Item numbers, exhibit references, table locations).
            You output a structured map of where to find each data point.""",
            verbose=True,
            llm=self._get_llm()
        )

        # Agent 2: Extractor - Data extraction
        extractor = Agent(
            role="Data Extraction Specialist",
            goal=f"Extract precise values for: {', '.join(goals)}",
            backstory="""You are a meticulous data extractor. Given section locations, you pull
            exact dates, numbers, company names, and terms. You follow these rules:
            - Dates: YYYY-MM-DD format only
            - Numbers: Numeric only (e.g., 275000000 not '275M' or '$275M')
            - Company names: Full legal name, not abbreviations
            - If data not found, return null (not 'N/A' or empty string)""",
            verbose=True,
            llm=self._get_llm()
        )

        # Agent 3: Validator - Consistency checker
        validator = Agent(
            role="Data Validation Specialist",
            goal="Verify extracted data is consistent and passes validation rules",
            backstory="""You are a data quality expert. You check:
            - Date logic (IPO date before deal date, deal date before expected close)
            - Numeric ranges (trust cash shouldn't exceed IPO proceeds by >200%)
            - Entity validation (target shouldn't be a sponsor/trustee entity)
            - Required fields present for filing type
            You flag issues and suggest corrections.""",
            verbose=True,
            llm=self._get_llm()
        )

        # Task 1: Structure analysis
        analysis_task = Task(
            description=f"""Analyze this {filing_type} filing for {ticker} and identify where to find:
{chr(10).join(f'- {goal}' for goal in goals)}

Filing Content (first 50k chars):
{filing_text}

Output a JSON map of section locations:
{{
    "field_name": "Item 1.01, paragraph 3" or "Exhibit 99.1, page 2" or "Table: Trust Account Summary"
}}
""",
            agent=analyst,
            expected_output="JSON mapping of field names to section locations"
        )

        # Task 2: Data extraction
        extraction_task = Task(
            description=f"""Using the section map from the analyst, extract precise values for:
{chr(10).join(f'- {goal}' for goal in goals)}

Filing Content:
{filing_text}

Output strict JSON (no markdown, no explanations):
{{
    "ipo_date": "2024-03-15" or null,
    "target": "Target Company Inc." or null,
    "deal_value": 500000000 or null,
    ...
}}

CRITICAL RULES:
- Dates: YYYY-MM-DD format ONLY
- Numbers: Numeric values ONLY (no strings like "$500M")
- Company names: Full legal names
- Missing data: Use null (not "N/A", "Not found", or empty string)
""",
            agent=extractor,
            expected_output="Strict JSON with extracted field values",
            context=[analysis_task]
        )

        # Task 3: Validation
        validation_task = Task(
            description=f"""Validate the extracted data for {ticker} ({filing_type}):

1. Check date logic:
   - IPO date < announced_date < expected_close
   - All dates are valid calendar dates
   - No dates in future (beyond reasonable IPO timeline)

2. Check numeric ranges:
   - trust_cash shouldn't exceed ipo_proceeds by >200%
   - deal_value should be reasonable for SPAC size
   - Premium calculations make sense

3. Check entity validation:
   - Target shouldn't contain: 'sponsor', 'trustee', 'acquisition corp'
   - Target should be a real operating company name

4. Check required fields for {filing_type}:
   - 8-K: Should have announced_date, target
   - S-1: Should have ipo_date, ipo_proceeds
   - 10-Q: Should have trust_cash, shares_outstanding

Output JSON:
{{
    "validation_passed": true/false,
    "issues": ["Issue 1", "Issue 2", ...],
    "corrections": {{"field": "corrected_value", ...}},
    "final_data": {{...validated/corrected data...}}
}}
""",
            agent=validator,
            expected_output="JSON with validation results and final data",
            context=[extraction_task]
        )

        # Build sequential crew
        return Crew(
            agents=[analyst, extractor, validator],
            tasks=[analysis_task, extraction_task, validation_task],
            process=Process.sequential,
            verbose=True
        )

    def _parse_crew_result(self, crew_result, task_params: Dict) -> Dict:
        """
        Parse CrewAI output into orchestrator result format.
        """
        try:
            # CrewAI returns the final task's output
            # Should be JSON from validator agent
            result_str = str(crew_result)

            # Try to extract JSON from result
            if '{' in result_str and '}' in result_str:
                start_idx = result_str.index('{')
                end_idx = result_str.rindex('}') + 1
                json_str = result_str[start_idx:end_idx]
                result_data = json.loads(json_str)
            else:
                logger.warning("No JSON found in crew result, returning raw output")
                result_data = {'raw_output': result_str}

            return {
                'success': result_data.get('validation_passed', False),
                'extracted_data': result_data.get('final_data', {}),
                'validation_issues': result_data.get('issues', []),
                'corrections_applied': result_data.get('corrections', {}),
                'ticker': task_params.get('ticker'),
                'filing_type': task_params.get('filing_type')
            }

        except Exception as e:
            logger.error(f"Failed to parse crew result: {e}")
            return {
                'success': False,
                'error': str(e),
                'raw_output': str(crew_result)
            }
