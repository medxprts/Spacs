"""
Deal Investigation LangGraph Agent

Multi-source investigation with human approval workflow.
Demonstrates LangGraph's most powerful features:
- Multi-source research (SEC + news + Reddit)
- Human-in-the-loop (wait for Telegram approval)
- State persistence (can pause/resume)
- Conditional routing based on confidence
"""

from typing import Dict, Any, Literal
from agents.langgraph_agent_base import LangGraphAgentWrapper, GraphState
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DealInvestigationLangGraphAgent(LangGraphAgentWrapper):
    """
    Investigate potential deal signals from multiple sources.

    Flow:
    1. Check SEC filings for deal
    2. Check news articles
    3. Check Reddit sentiment
    4. Synthesize signals → assign confidence
    5. If confidence > 85% → auto-confirm deal
    6. If confidence 70-85% → wait for human approval
    7. If confidence < 70% → reject as noise

    Human-in-the-loop: Graph PAUSES at approval node, waits for Telegram response
    """

    def __init__(self, state_manager):
        super().__init__("deal_investigation_langgraph", state_manager)

    def _build_graph(self, task_params: Dict[str, Any]) -> StateGraph:
        """
        Build multi-source investigation graph with human approval.

        Graph:
            research_sec → research_news → research_reddit
                                              ↓
                                         synthesize_signals
                                              ↓
                                      [decision: confidence?]
                                       ↓       ↓        ↓
                           high (>85%) ↓    medium  low (<70%)
                                       ↓       ↓        ↓
                           confirm_deal  wait_approval  reject_signal
                                       ↓       ↓        ↓
                                      END   [human]    END
                                              ↓
                                       approved? yes → confirm_deal
                                              ↓ no
                                            reject_signal
        """
        graph = StateGraph(GraphState)

        # Research nodes (parallel would be better, but sequential for simplicity)
        graph.add_node("research_sec", self.research_sec)
        graph.add_node("research_news", self.research_news)
        graph.add_node("research_reddit", self.research_reddit)

        # Synthesis node
        graph.add_node("synthesize_signals", self.synthesize_signals)

        # Action nodes
        graph.add_node("confirm_deal", self.confirm_deal)
        graph.add_node("wait_approval", self.wait_approval)
        graph.add_node("reject_signal", self.reject_signal)

        # Entry point
        graph.set_entry_point("research_sec")

        # Research chain
        graph.add_edge("research_sec", "research_news")
        graph.add_edge("research_news", "research_reddit")
        graph.add_edge("research_reddit", "synthesize_signals")

        # Conditional routing based on confidence
        graph.add_conditional_edges(
            "synthesize_signals",
            self.route_by_confidence,
            {
                "high": "confirm_deal",
                "medium": "wait_approval",
                "low": "reject_signal"
            }
        )

        # Terminal edges
        graph.add_edge("confirm_deal", END)
        graph.add_edge("reject_signal", END)

        # Human approval loop
        graph.add_conditional_edges(
            "wait_approval",
            self.check_human_response,
            {
                "approved": "confirm_deal",
                "rejected": "reject_signal",
                "waiting": "wait_approval"  # Loop until response
            }
        )

        return graph.compile(checkpointer=self.checkpointer)

    def _create_initial_state(self, task_params: Dict) -> Dict:
        """Initialize state"""
        return {
            'ticker': task_params.get('ticker', ''),
            'signal_source': task_params.get('signal_source', ''),  # 'reddit', 'news', 'price_spike'
            'signal_data': task_params.get('signal_data', {}),
            'status': 'started',
            'error': None,
            'messages': [],
            'result': {},
            'sec_evidence': {},
            'news_evidence': {},
            'reddit_evidence': {},
            'confidence': 0,
            'recommended_action': '',
            'human_response': None,  # Will be 'approved' or 'rejected' after Telegram
            'wait_start_time': None
        }

    # === RESEARCH NODES ===

    def research_sec(self, state: Dict) -> Dict:
        """Node: Search recent SEC filings for deal evidence"""
        logger.info(f"[research_sec] Checking SEC filings for {state['ticker']}")

        ticker = state['ticker']

        # TODO: Replace with actual SEC API call
        # For now, simulate with AI checking database/recent filings
        llm = self._get_llm()

        prompt = f"""Check recent SEC filings (last 30 days) for {ticker} for deal evidence.

Look for:
- 8-K filings with "business combination" or "merger agreement"
- Item 1.01 (Material Definitive Agreement)
- Target company name mentions

Signal that triggered this: {state['signal_source']} - {state['signal_data']}

Output JSON:
{{
    "found_evidence": true/false,
    "filing_type": "8-K" or null,
    "filing_date": "2024-03-15" or null,
    "target_mentioned": "Company Name" or null,
    "confidence": 0-100
}}
"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            evidence = json.loads(self._extract_json(response.content))
            state['sec_evidence'] = evidence
            state['messages'].append(f"SEC: {evidence.get('confidence', 0)}% confidence")
            logger.info(f"[research_sec] Found evidence: {evidence.get('found_evidence', False)}")
        except Exception as e:
            logger.error(f"[research_sec] Failed: {e}")
            state['sec_evidence'] = {'found_evidence': False, 'confidence': 0}

        return state

    def research_news(self, state: Dict) -> Dict:
        """Node: Search news articles for deal announcements"""
        logger.info(f"[research_news] Checking news for {state['ticker']}")

        ticker = state['ticker']
        llm = self._get_llm()

        # TODO: Replace with actual news API call
        prompt = f"""Search recent news (last 7 days) for {ticker} deal announcements.

Signal context: {state['signal_source']} - {state['signal_data']}

Check for:
- Press releases from reputable sources (Reuters, Bloomberg, PRNewswire)
- Specific deal details (target name, deal value)
- Language confidence ("announces deal" vs "rumored to be considering")

Output JSON:
{{
    "found_articles": true/false,
    "source": "Reuters" or null,
    "target_mentioned": "Company Name" or null,
    "deal_value_mentioned": 500000000 or null,
    "confidence": 0-100
}}
"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            evidence = json.loads(self._extract_json(response.content))
            state['news_evidence'] = evidence
            state['messages'].append(f"News: {evidence.get('confidence', 0)}% confidence")
            logger.info(f"[research_news] Found articles: {evidence.get('found_articles', False)}")
        except Exception as e:
            logger.error(f"[research_news] Failed: {e}")
            state['news_evidence'] = {'found_articles': False, 'confidence': 0}

        return state

    def research_reddit(self, state: Dict) -> Dict:
        """Node: Check Reddit sentiment and mentions"""
        logger.info(f"[research_reddit] Checking Reddit for {state['ticker']}")

        ticker = state['ticker']
        llm = self._get_llm()

        # TODO: Replace with actual Reddit API call
        prompt = f"""Check Reddit r/SPACs (last 24 hours) for {ticker} mentions.

Signal context: {state['signal_source']} - {state['signal_data']}

Analyze:
- Number of mentions (1 vs 50+)
- User credibility (new accounts vs trusted users)
- Specificity ("heard rumor" vs "SEC filing tomorrow")
- Bullish vs bearish sentiment

Output JSON:
{{
    "mention_count": 0,
    "avg_sentiment": 0-100,
    "specific_details": ["detail1", "detail2"] or [],
    "confidence": 0-100
}}
"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            evidence = json.loads(self._extract_json(response.content))
            state['reddit_evidence'] = evidence
            state['messages'].append(f"Reddit: {evidence.get('confidence', 0)}% confidence")
            logger.info(f"[research_reddit] Mentions: {evidence.get('mention_count', 0)}")
        except Exception as e:
            logger.error(f"[research_reddit] Failed: {e}")
            state['reddit_evidence'] = {'mention_count': 0, 'confidence': 0}

        return state

    def synthesize_signals(self, state: Dict) -> Dict:
        """Node: Combine all evidence and assign final confidence"""
        logger.info(f"[synthesize_signals] Synthesizing evidence for {state['ticker']}")

        llm = self._get_llm()

        prompt = f"""Combine these signals for {state['ticker']} and assign final confidence:

SEC Evidence: {json.dumps(state['sec_evidence'], indent=2)}
News Evidence: {json.dumps(state['news_evidence'], indent=2)}
Reddit Evidence: {json.dumps(state['reddit_evidence'], indent=2)}

Weighting rules:
- SEC filing with deal = 90%+ confidence (most authoritative)
- Reputable news + SEC mention = 85%+ confidence
- Reputable news alone = 70-84% confidence (rumor)
- Reddit alone = <50% confidence (noise)
- Conflicting signals = explain why

Output JSON:
{{
    "confidence": 0-100,
    "deal_status": "CONFIRMED" or "RUMORED" or "NOISE",
    "target": "Company Name" or null,
    "reasoning": "Why this confidence level",
    "recommended_action": "confirm_deal" or "flag_rumor" or "ignore"
}}
"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            synthesis = json.loads(self._extract_json(response.content))

            state['confidence'] = synthesis.get('confidence', 0)
            state['deal_status'] = synthesis.get('deal_status', 'NOISE')
            state['target'] = synthesis.get('target')
            state['recommended_action'] = synthesis.get('recommended_action', 'ignore')
            state['reasoning'] = synthesis.get('reasoning', '')

            state['messages'].append(f"📊 Final confidence: {state['confidence']}%")
            logger.info(f"[synthesize_signals] Confidence: {state['confidence']}%")

        except Exception as e:
            logger.error(f"[synthesize_signals] Failed: {e}")
            state['confidence'] = 0
            state['recommended_action'] = 'ignore'

        return state

    # === ACTION NODES ===

    def confirm_deal(self, state: Dict) -> Dict:
        """Node: Auto-confirm high-confidence deal"""
        logger.info(f"[confirm_deal] Auto-confirming deal for {state['ticker']}")

        state['status'] = 'completed'
        state['result'] = {
            'action': 'CONFIRMED_DEAL',
            'ticker': state['ticker'],
            'target': state.get('target'),
            'confidence': state['confidence'],
            'reasoning': state.get('reasoning')
        }
        state['messages'].append(f"✅ Deal confirmed (confidence: {state['confidence']}%)")

        # TODO: Trigger orchestrator_trigger.trigger_confirmed_deal()

        return state

    def wait_approval(self, state: Dict) -> Dict:
        """
        Node: Wait for human approval via Telegram.

        This is LangGraph's killer feature:
        - Graph PAUSES here
        - State persists to disk (checkpointer)
        - Telegram bot sends alert with graph state
        - User responds "approve" or "reject"
        - Graph RESUMES from this exact node
        """
        logger.info(f"[wait_approval] Waiting for human approval for {state['ticker']}")

        # First time hitting this node
        if state.get('wait_start_time') is None:
            state['wait_start_time'] = datetime.now().isoformat()
            state['messages'].append(f"⏸️  Waiting for human approval (confidence: {state['confidence']}%)")

            # TODO: Send Telegram alert with state
            # telegram.send_alert(f"""
            # 🔍 Deal Investigation: {state['ticker']}
            #
            # Confidence: {state['confidence']}%
            # Target: {state.get('target', 'Unknown')}
            # Reasoning: {state.get('reasoning', '')}
            #
            # Reply:
            # - "approve {state['ticker']}" to confirm deal
            # - "reject {state['ticker']}" to ignore signal
            # """)

            logger.info(f"[wait_approval] Sent Telegram alert, graph will pause")

        # Check if human has responded
        # (In real implementation, Telegram listener would update state['human_response'])
        # For now, simulate timeout after 60 seconds
        wait_start = datetime.fromisoformat(state['wait_start_time'])
        wait_duration = (datetime.now() - wait_start).total_seconds()

        if wait_duration > 3600:  # 1 hour timeout
            state['human_response'] = 'rejected'
            state['messages'].append("⏱️ Approval timeout, rejecting signal")
            logger.info(f"[wait_approval] Timeout reached, auto-rejecting")

        return state

    def reject_signal(self, state: Dict) -> Dict:
        """Node: Reject low-confidence signal"""
        logger.info(f"[reject_signal] Rejecting signal for {state['ticker']}")

        state['status'] = 'completed'
        state['result'] = {
            'action': 'REJECTED',
            'ticker': state['ticker'],
            'confidence': state['confidence'],
            'reasoning': state.get('reasoning')
        }
        state['messages'].append(f"❌ Signal rejected (confidence: {state['confidence']}%)")

        return state

    # === CONDITIONAL ROUTING ===

    def route_by_confidence(self, state: Dict) -> Literal["high", "medium", "low"]:
        """Route based on confidence threshold"""
        confidence = state.get('confidence', 0)

        if confidence >= 85:
            return "high"
        elif confidence >= 70:
            return "medium"
        else:
            return "low"

    def check_human_response(self, state: Dict) -> Literal["approved", "rejected", "waiting"]:
        """Check if human has approved/rejected"""
        response = state.get('human_response')

        if response == 'approved':
            return "approved"
        elif response == 'rejected':
            return "rejected"
        else:
            return "waiting"  # Loop back to wait_approval

    # === HELPERS ===

    def _extract_json(self, text: str) -> str:
        """Extract JSON from AI response"""
        if '{' in text and '}' in text:
            start_idx = text.index('{')
            end_idx = text.rindex('}') + 1
            return text[start_idx:end_idx]
        return '{}'
