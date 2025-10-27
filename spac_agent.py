# spac_agent.py - AI Agent for LEVP SPAC Platform using DeepSeek
from dotenv import load_dotenv
load_dotenv()

import os
import json
from openai import OpenAI
from database import SessionLocal, SPAC
from sqlalchemy import and_, or_, func

class SPACAIAgent:
    def __init__(self, api_key: str = None):
        """Initialize the SPAC AI Agent with DeepSeek"""
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment")
        
        # DeepSeek uses OpenAI-compatible API
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )
        self.db = SessionLocal()
        
        # Define available functions for the agent
        self.functions = [
            {
                "name": "search_spacs",
                "description": "Search for SPACs based on various criteria like premium, banker, deal status, ticker, or company name. Returns a list of matching SPACs with their details.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "min_premium": {
                            "type": "number",
                            "description": "Minimum premium percentage (e.g., 10 for 10%)"
                        },
                        "max_premium": {
                            "type": "number",
                            "description": "Maximum premium percentage"
                        },
                        "banker": {
                            "type": "string",
                            "description": "Investment banker name (e.g., 'Goldman Sachs', 'JPMorgan Chase')"
                        },
                        "deal_status": {
                            "type": "string",
                            "enum": ["ANNOUNCED", "SEARCHING"],
                            "description": "Deal status filter"
                        },
                        "risk_level": {
                            "type": "string",
                            "enum": ["deal", "safe", "urgent", "expired"],
                            "description": "Risk level classification"
                        },
                        "sector": {
                            "type": "string",
                            "description": "Sector/industry (e.g., 'Technology', 'Healthcare', 'Bitcoin/Crypto')"
                        },
                        "ticker": {
                            "type": "string",
                            "description": "Specific ticker symbol to search for"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 10)",
                            "default": 10
                        }
                    }
                }
            },
            {
                "name": "get_market_stats",
                "description": "Get overall market statistics and analytics for all SPACs, including total count, average premium, total market cap, and top bankers.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_top_spacs",
                "description": "Get top SPACs by a specific metric like premium, market cap, or days to deadline.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sort_by": {
                            "type": "string",
                            "enum": ["premium", "market_cap", "days_to_deadline"],
                            "description": "Metric to sort by",
                            "default": "premium"
                        },
                        "order": {
                            "type": "string",
                            "enum": ["desc", "asc"],
                            "description": "Sort order",
                            "default": "desc"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of results",
                            "default": 5
                        }
                    },
                    "required": ["sort_by"]
                }
            },
            {
                "name": "compare_bankers",
                "description": "Compare investment bankers by their SPAC count, average premium, and total market cap.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "banker_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of banker names to compare (e.g., ['Goldman Sachs', 'JPMorgan Chase'])"
                        }
                    },
                    "required": ["banker_names"]
                }
            },
            {
                "name": "get_urgent_deadlines",
                "description": "Get SPACs with urgent deadlines (less than specified days remaining).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days_threshold": {
                            "type": "integer",
                            "description": "Number of days threshold (default 90)",
                            "default": 90
                        }
                    }
                }
            }
        ]
    
    def search_spacs(self, **kwargs):
        """Search SPACs with various filters"""
        query = self.db.query(SPAC)
        
        if kwargs.get('min_premium') is not None:
            query = query.filter(SPAC.premium >= kwargs['min_premium'])
        if kwargs.get('max_premium') is not None:
            query = query.filter(SPAC.premium <= kwargs['max_premium'])
        if kwargs.get('banker'):
            query = query.filter(SPAC.banker.ilike(f"%{kwargs['banker']}%"))
        if kwargs.get('deal_status'):
            query = query.filter(SPAC.deal_status == kwargs['deal_status'])
        if kwargs.get('risk_level'):
            query = query.filter(SPAC.risk_level == kwargs['risk_level'])
        if kwargs.get('sector'):
            query = query.filter(SPAC.sector.ilike(f"%{kwargs['sector']}%"))
        if kwargs.get('ticker'):
            query = query.filter(SPAC.ticker.ilike(f"%{kwargs['ticker']}%"))
        
        limit = kwargs.get('limit', 10)
        results = query.limit(limit).all()
        
        return [
            {
                "ticker": s.ticker,
                "company": s.company,
                "price": s.price,
                "premium": s.premium,
                "deal_status": s.deal_status,
                "target": s.target,
                "expected_close": s.expected_close,
                "days_to_deadline": s.days_to_deadline,
                "market_cap": s.market_cap,
                "risk_level": s.risk_level,
                "sector": s.sector,
                "banker": s.banker,
                "pipe_size": s.pipe_size,
                "pipe_price": s.pipe_price,
                "min_cash": s.min_cash,
                "deal_value": s.deal_value
            }
            for s in results
        ]
    
    def get_market_stats(self):
        """Get overall market statistics"""
        all_spacs = self.db.query(SPAC).all()
        
        total = len(all_spacs)
        announced = len([s for s in all_spacs if s.deal_status == "ANNOUNCED"])
        searching = len([s for s in all_spacs if s.deal_status == "SEARCHING"])
        
        premiums = [s.premium for s in all_spacs if s.premium is not None]
        avg_premium = sum(premiums) / len(premiums) if premiums else 0
        median_premium = sorted(premiums)[len(premiums)//2] if premiums else 0
        
        total_market_cap = sum([s.market_cap for s in all_spacs if s.market_cap])
        
        # Top bankers
        from collections import Counter
        banker_counts = Counter([s.banker for s in all_spacs])
        top_bankers = dict(banker_counts.most_common(10))
        
        return {
            "total_spacs": total,
            "announced_deals": announced,
            "searching_spacs": searching,
            "average_premium": round(avg_premium, 2),
            "median_premium": round(median_premium, 2),
            "total_market_cap_millions": round(total_market_cap, 2),
            "top_bankers": top_bankers
        }
    
    def get_top_spacs(self, sort_by="premium", order="desc", limit=5):
        """Get top SPACs by a metric"""
        query = self.db.query(SPAC)
        
        if sort_by == "premium":
            query = query.order_by(SPAC.premium.desc() if order == "desc" else SPAC.premium.asc())
        elif sort_by == "market_cap":
            query = query.order_by(SPAC.market_cap.desc() if order == "desc" else SPAC.market_cap.asc())
        elif sort_by == "days_to_deadline":
            query = query.filter(SPAC.days_to_deadline.isnot(None))
            query = query.order_by(SPAC.days_to_deadline.asc() if order == "asc" else SPAC.days_to_deadline.desc())
        
        results = query.limit(limit).all()
        
        return [
            {
                "ticker": s.ticker,
                "company": s.company,
                "price": s.price,
                "premium": s.premium,
                "market_cap": s.market_cap,
                "days_to_deadline": s.days_to_deadline,
                "banker": s.banker,
                "deal_status": s.deal_status
            }
            for s in results
        ]
    
    def compare_bankers(self, banker_names):
        """Compare investment bankers"""
        results = {}
        
        for banker in banker_names:
            spacs = self.db.query(SPAC).filter(SPAC.banker.ilike(f"%{banker}%")).all()
            
            if spacs:
                premiums = [s.premium for s in spacs if s.premium is not None]
                results[banker] = {
                    "count": len(spacs),
                    "average_premium": round(sum(premiums) / len(premiums), 2) if premiums else 0,
                    "total_market_cap": round(sum([s.market_cap for s in spacs if s.market_cap]), 2),
                    "announced_deals": len([s for s in spacs if s.deal_status == "ANNOUNCED"])
                }
        
        return results
    
    def get_urgent_deadlines(self, days_threshold=90):
        """Get SPACs with urgent deadlines"""
        results = self.db.query(SPAC).filter(
            and_(
                SPAC.days_to_deadline.isnot(None),
                SPAC.days_to_deadline > 0,
                SPAC.days_to_deadline < days_threshold
            )
        ).order_by(SPAC.days_to_deadline.asc()).all()
        
        return [
            {
                "ticker": s.ticker,
                "company": s.company,
                "days_to_deadline": s.days_to_deadline,
                "deal_status": s.deal_status,
                "premium": s.premium,
                "banker": s.banker
            }
            for s in results
        ]
    
    def execute_function(self, function_name, arguments):
        """Execute a function call"""
        if function_name == "search_spacs":
            return self.search_spacs(**arguments)
        elif function_name == "get_market_stats":
            return self.get_market_stats()
        elif function_name == "get_top_spacs":
            return self.get_top_spacs(**arguments)
        elif function_name == "compare_bankers":
            return self.compare_bankers(**arguments)
        elif function_name == "get_urgent_deadlines":
            return self.get_urgent_deadlines(**arguments)
        else:
            return {"error": f"Unknown function: {function_name}"}
    
    def chat(self, user_message, conversation_history=None):
        """
        Main chat interface for the AI agent.
        Handles multi-turn conversations with function calling.
        """
        if conversation_history is None:
            conversation_history = []
        
        # Add user message to history
        conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        # System prompt for the agent
        system_message = {
            "role": "system",
            "content": """You are a SPAC (Special Purpose Acquisition Company) research assistant with access to a comprehensive database of 154 publicly traded SPACs.

You can help users:
- Find SPACs by premium, banker, sector, deal status
- Analyze market trends and statistics
- Compare investment bankers
- Identify urgent deadlines and opportunities
- Get details on specific SPACs or deals

When users ask questions, use the available functions to query the database and provide accurate, data-driven answers. Always cite specific numbers and SPACs when relevant.

Be conversational but professional. Format your responses clearly with bullet points or tables when showing multiple SPACs."""
        }
        
        messages = [system_message] + conversation_history
        
        # Make initial API call with function calling
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            functions=self.functions,
            function_call="auto",
            temperature=0.7,
            max_tokens=2000
        )
        
        # Process function calls if any
        while response.choices[0].finish_reason == "function_call":
            function_call = response.choices[0].message.function_call
            function_name = function_call.name
            function_args = json.loads(function_call.arguments)
            
            print(f"🔧 Agent using function: {function_name}")
            print(f"   Arguments: {function_args}")
            
            # Execute the function
            function_result = self.execute_function(function_name, function_args)
            
            # Add function call and result to conversation
            conversation_history.append({
                "role": "assistant",
                "content": None,
                "function_call": {
                    "name": function_name,
                    "arguments": function_call.arguments
                }
            })
            
            conversation_history.append({
                "role": "function",
                "name": function_name,
                "content": json.dumps(function_result)
            })
            
            # Get next response
            messages = [system_message] + conversation_history
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                functions=self.functions,
                function_call="auto",
                temperature=0.7,
                max_tokens=2000
            )
        
        # Get final response
        final_response = response.choices[0].message.content
        
        # Add final response to history
        conversation_history.append({
            "role": "assistant",
            "content": final_response
        })
        
        return {
            "response": final_response,
            "conversation_history": conversation_history
        }
    
    def close(self):
        """Close database connection"""
        self.db.close()


# ============================================================================
# CLI Interface for testing the agent
# ============================================================================

def main():
    """Interactive CLI for the SPAC AI Agent"""
    import sys
    
    print("=" * 60)
    print("SPAC AI Agent - Powered by DeepSeek")
    print("=" * 60)
    print()
    
    # Check for API key
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ Error: DEEPSEEK_API_KEY not found in environment")
        print("   Set it in your .env file:")
        print("   DEEPSEEK_API_KEY='your-key-here'")
        print()
        print("   Get your key at: https://platform.deepseek.com/")
        sys.exit(1)
    
    # Initialize agent
    print("🤖 Initializing SPAC AI Agent...")
    try:
        agent = SPACAIAgent(api_key=api_key)
        print("✅ Agent ready! Ask me anything about SPACs.\n")
    except Exception as e:
        print(f"❌ Error initializing agent: {e}")
        sys.exit(1)
    
    print("Examples:")
    print("  - Show me high premium SPACs with Goldman Sachs")
    print("  - What are the top 5 SPACs by market cap?")
    print("  - Compare Goldman Sachs and JPMorgan Chase")
    print("  - Which deals are closing in Q4 2025?")
    print("  - What SPACs have urgent deadlines?")
    print()
    print("Type 'quit' or 'exit' to stop.\n")
    
    conversation_history = None
    
    try:
        while True:
            user_input = input("You: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                break
            
            if not user_input:
                continue
            
            print("\n🤔 Thinking...\n")
            
            # Get response from agent
            try:
                result = agent.chat(user_input, conversation_history)
                conversation_history = result["conversation_history"]
                
                print(f"Agent: {result['response']}\n")
            except Exception as e:
                print(f"❌ Error: {e}\n")
    
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    
    finally:
        agent.close()


if __name__ == "__main__":
    main()
