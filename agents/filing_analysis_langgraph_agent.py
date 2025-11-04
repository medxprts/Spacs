"""
Filing Analysis LangGraph Agent

Adaptive filing analysis with validation loops and error correction.
Demonstrates LangGraph's advantages over CrewAI:
- Conditional routing (if data is valid → done, else → fix)
- Loops (can re-extract data multiple times until valid)
- State persistence (can pause/resume)
"""

from typing import Dict, Any, Literal
from agents.langgraph_agent_base import LangGraphAgentWrapper, GraphState
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import json
import logging

logger = logging.getLogger(__name__)


class FilingAnalysisLangGraphAgent(LangGraphAgentWrapper):
    """
    Smart filing analysis with self-correction loops.

    Flow:
    1. Extract data from filing
    2. Validate extracted data
    3. If invalid → identify issues → re-extract with guidance → validate again
    4. If valid after 3 attempts → done
    5. If still invalid → flag for human review

    This is HARD to do in CrewAI (linear agents), EASY in LangGraph (state machine).
    """

    def __init__(self, state_manager):
        super().__init__("filing_analysis_langgraph", state_manager)
        self.max_retries = 3

    def _build_graph(self, task_params: Dict[str, Any]) -> StateGraph:
        """
        Build adaptive filing analysis graph.

        Graph structure:
            extract_data
                ↓
            validate_data
                ↓
            [decision point]
                ↓ valid → END
                ↓ invalid + retries < 3 → fix_extraction_errors → extract_data (loop)
                ↓ invalid + retries >= 3 → flag_for_review → END
        """
        graph = StateGraph(GraphState)

        # Add nodes (each is a method below)
        graph.add_node("extract_data", self.extract_data)
        graph.add_node("validate_data", self.validate_data)
        graph.add_node("fix_extraction_errors", self.fix_extraction_errors)
        graph.add_node("flag_for_review", self.flag_for_review)

        # Set entry point
        graph.set_entry_point("extract_data")

        # Linear edges
        graph.add_edge("extract_data", "validate_data")
        graph.add_edge("fix_extraction_errors", "extract_data")  # Loop back!

        # Conditional routing after validation
        graph.add_conditional_edges(
            "validate_data",
            self.decide_next_step,  # Function that returns next node name
            {
                "done": END,
                "fix": "fix_extraction_errors",
                "review": "flag_for_review"
            }
        )

        graph.add_edge("flag_for_review", END)

        # Compile with checkpointer for state persistence
        return graph.compile(checkpointer=self.checkpointer)

    def _create_initial_state(self, task_params: Dict) -> Dict:
        """Initialize state with task parameters"""
        return {
            'ticker': task_params.get('ticker', ''),
            'filing_type': task_params.get('filing_type', ''),
            'filing_text': task_params.get('filing_text', ''),
            'extraction_goals': task_params.get('extraction_goals', []),
            'status': 'started',
            'error': None,
            'messages': [],
            'result': {},
            'extracted_data': {},
            'validation_issues': [],
            'retry_count': 0,
            'extraction_guidance': ''  # Guidance for next extraction attempt
        }

    # === GRAPH NODES (each is a function that transforms state) ===

    def extract_data(self, state: Dict) -> Dict:
        """
        Node: Extract structured data from filing.
        Uses AI with optional guidance from previous validation failures.
        """
        logger.info(f"[extract_data] Extracting data for {state['ticker']}")

        llm = self._get_llm()

        # Build prompt with optional guidance
        guidance = state.get('extraction_guidance', '')
        guidance_text = f"\n\nIMPORTANT GUIDANCE FROM PREVIOUS ATTEMPT:\n{guidance}" if guidance else ""

        filing_text = state['filing_text'][:50000]  # Truncate if too long

        prompt = f"""Extract the following data from this {state['filing_type']} filing for {state['ticker']}:

Fields to extract: {', '.join(state['extraction_goals'])}

Filing content:
{filing_text}

{guidance_text}

RULES:
- Dates: YYYY-MM-DD format ONLY
- Numbers: Numeric values ONLY (e.g., 500000000 not "$500M")
- Company names: Full legal names
- Missing data: Use null (not "N/A" or empty string)

Output ONLY valid JSON (no markdown, no explanations):
{{{', '.join([f'"{goal}": value or null' for goal in state['extraction_goals']])}}}
"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content

            # Extract JSON
            if '{' in response_text and '}' in response_text:
                start_idx = response_text.index('{')
                end_idx = response_text.rindex('}') + 1
                json_str = response_text[start_idx:end_idx]
                extracted_data = json.loads(json_str)
            else:
                raise ValueError("No JSON found in AI response")

            state['extracted_data'] = extracted_data
            state['messages'].append(f"Extracted {len(extracted_data)} fields")
            logger.info(f"[extract_data] Extracted: {list(extracted_data.keys())}")

        except Exception as e:
            logger.error(f"[extract_data] Extraction failed: {e}")
            state['error'] = str(e)
            state['extracted_data'] = {}

        return state

    def validate_data(self, state: Dict) -> Dict:
        """
        Node: Validate extracted data for consistency and correctness.
        Uses AI to find logical issues.
        """
        logger.info(f"[validate_data] Validating data for {state['ticker']}")

        llm = self._get_llm()

        extracted_data = state['extracted_data']

        prompt = f"""Validate this extracted data for {state['ticker']} ({state['filing_type']}):

{json.dumps(extracted_data, indent=2)}

Check for:
1. Date logic (IPO date < deal date < expected close, no future dates)
2. Numeric ranges (trust_cash shouldn't exceed IPO proceeds by >200%)
3. Entity validation (target shouldn't contain "sponsor", "trustee", "acquisition corp")
4. Required fields for {state['filing_type']} are present
5. Data types correct (dates are YYYY-MM-DD, numbers are numeric not strings)

Output JSON:
{{
    "is_valid": true/false,
    "issues": ["Issue 1", "Issue 2", ...],  # Empty list if valid
    "severity": "CRITICAL" or "WARNING" or "OK"
}}
"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content

            # Extract JSON
            if '{' in response_text and '}' in response_text:
                start_idx = response_text.index('{')
                end_idx = response_text.rindex('}') + 1
                json_str = response_text[start_idx:end_idx]
                validation_result = json.loads(json_str)
            else:
                raise ValueError("No JSON found in AI response")

            state['validation_issues'] = validation_result.get('issues', [])
            state['is_valid'] = validation_result.get('is_valid', False)
            state['severity'] = validation_result.get('severity', 'OK')

            if state['is_valid']:
                state['messages'].append("✅ Validation passed")
                state['status'] = 'completed'
            else:
                state['messages'].append(f"❌ Validation failed: {len(state['validation_issues'])} issues")

            logger.info(f"[validate_data] Valid: {state['is_valid']}, Issues: {len(state['validation_issues'])}")

        except Exception as e:
            logger.error(f"[validate_data] Validation failed: {e}")
            state['error'] = str(e)
            state['is_valid'] = False

        return state

    def fix_extraction_errors(self, state: Dict) -> Dict:
        """
        Node: Generate guidance for next extraction attempt based on validation issues.
        This enables the loop: extract → validate → fix guidance → extract again
        """
        logger.info(f"[fix_extraction_errors] Generating fix guidance for {state['ticker']}")

        llm = self._get_llm()

        issues = state['validation_issues']

        prompt = f"""The previous data extraction had these validation issues:

{chr(10).join(f'- {issue}' for issue in issues)}

Extracted data was:
{json.dumps(state['extracted_data'], indent=2)}

Generate SPECIFIC guidance for the next extraction attempt to fix these issues.
Focus on WHERE in the filing to look and WHAT format to use.

Example good guidance:
"For IPO date: Look in Item 8.01 press release, not the filing date at top. Format must be YYYY-MM-DD."

Output 1-3 sentences of guidance:
"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            guidance = response.content.strip()

            state['extraction_guidance'] = guidance
            state['retry_count'] = state.get('retry_count', 0) + 1
            state['messages'].append(f"🔧 Retry {state['retry_count']}: {guidance[:100]}...")

            logger.info(f"[fix_extraction_errors] Generated guidance (retry {state['retry_count']})")

        except Exception as e:
            logger.error(f"[fix_extraction_errors] Failed to generate guidance: {e}")
            state['extraction_guidance'] = "Try extracting data more carefully"
            state['retry_count'] = state.get('retry_count', 0) + 1

        return state

    def flag_for_review(self, state: Dict) -> Dict:
        """
        Node: Flag data for human review after max retries.
        """
        logger.info(f"[flag_for_review] Flagging {state['ticker']} for human review")

        state['status'] = 'needs_review'
        state['messages'].append(f"⚠️ Flagged for review after {state['retry_count']} failed attempts")

        # In real implementation, send Telegram alert
        # orchestrator.agents['telegram'].send_alert(...)

        return state

    # === CONDITIONAL ROUTING ===

    def decide_next_step(self, state: Dict) -> Literal["done", "fix", "review"]:
        """
        Conditional edge function: Decides where to go after validation.

        Returns:
            "done" - Data is valid, finish
            "fix" - Data invalid but retries remaining, fix and loop back
            "review" - Data invalid and max retries reached, flag for human
        """
        if state.get('is_valid', False):
            return "done"
        elif state.get('retry_count', 0) < self.max_retries:
            return "fix"
        else:
            return "review"

    def _parse_graph_result(self, final_state: Dict, task_params: Dict) -> Dict:
        """Parse final state into orchestrator result"""
        return {
            'success': final_state.get('status') == 'completed',
            'extracted_data': final_state.get('extracted_data', {}),
            'validation_issues': final_state.get('validation_issues', []),
            'retry_count': final_state.get('retry_count', 0),
            'needs_review': final_state.get('status') == 'needs_review',
            'messages': final_state.get('messages', []),
            'ticker': final_state.get('ticker'),
            'filing_type': final_state.get('filing_type')
        }
