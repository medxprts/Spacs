#!/usr/bin/env python3
"""
Test RAG Learning Accuracy

Compares extraction accuracy: Baseline vs RAG semantic search.
Uses vector database for finding similar past corrections.
"""

import os
import sys
from datetime import datetime
from typing import Dict, List
from openai import OpenAI
from dotenv import load_dotenv

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal
from agents.rag_learning_mixin import RAGLearningMixin
from sqlalchemy import text
import json

load_dotenv()

# AI Setup
AI_CLIENT = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


class RAGTester(RAGLearningMixin):
    """Test harness with RAG learning capability"""

    def __init__(self):
        super().__init__()
        self.results = []
        # Initialize RAG
        self.init_rag()

    def extract_field_baseline(self, field: str, filing_text: str) -> str:
        """Baseline extraction (no learning)"""
        prompt = f"""Extract '{field}' from this SEC filing text.

Filing:
{filing_text}

Output ONLY the value (no explanations).
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ Baseline extraction failed: {e}")
            return ""

    def extract_field_with_rag(
        self,
        field: str,
        filing_text: str,
        ticker: str = None
    ) -> str:
        """RAG extraction (with semantic search examples)"""
        prompt = self.build_prompt_with_rag(
            field=field,
            filing_text=filing_text,
            ticker=ticker,
            max_examples=3
        )

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ RAG extraction failed: {e}")
            return ""

    def test_on_correction(self, correction: Dict) -> Dict:
        """Test extraction on a past correction"""
        ticker = correction['ticker']
        field = list(correction['final_fix'].keys())[0]
        correct_value = correction['final_fix'][field]

        filing_text = str(correction.get('original_data', ''))[:2000]

        if not filing_text:
            print(f"⚠️  No original data for {ticker}, skipping")
            return None

        print(f"\n{'='*60}")
        print(f"Testing: {ticker} - Field: {field}")
        print(f"Correct answer: {correct_value}")
        print(f"{'='*60}")

        # Test baseline
        print("🔍 Baseline extraction (no learning)...")
        baseline_result = self.extract_field_baseline(field, filing_text)
        print(f"   Result: {baseline_result}")
        baseline_correct = (str(baseline_result).lower() == str(correct_value).lower())

        # Test with RAG
        print("🧠 RAG extraction (semantic search)...")
        rag_result = self.extract_field_with_rag(field, filing_text, ticker)
        print(f"   Result: {rag_result}")
        rag_correct = (str(rag_result).lower() == str(correct_value).lower())

        # Show what RAG found
        similar = self.get_similar_corrections_rag(
            query=f"Extracting {field} for {ticker}",
            n_results=3
        )
        if similar:
            print(f"\n   📚 RAG found {len(similar)} similar corrections:")
            for i, sim in enumerate(similar, 1):
                print(f"      {i}. {sim['ticker']} - {sim['issue_type']} (similarity: {sim['similarity']:.1%})")

        # Score
        result = {
            'ticker': ticker,
            'field': field,
            'correct_value': correct_value,
            'baseline_result': baseline_result,
            'baseline_correct': baseline_correct,
            'rag_result': rag_result,
            'rag_correct': rag_correct,
            'improvement': rag_correct and not baseline_correct,
            'similar_corrections_found': len(similar)
        }

        if baseline_correct and rag_correct:
            print("   ✅ Both correct")
        elif rag_correct and not baseline_correct:
            print("   🎉 RAG fixed the error!")
        elif baseline_correct and not rag_correct:
            print("   ⚠️  RAG made it worse")
        else:
            print("   ❌ Both wrong")

        return result

    def run_test_suite(self, num_tests: int = 10):
        """Run test on N random corrections"""
        print(f"\n{'='*60}")
        print(f"RAG LEARNING TEST SUITE")
        print(f"{'='*60}")

        # Check RAG stats
        stats = self.get_rag_stats()
        if not stats.get('initialized'):
            print(f"\n❌ RAG not initialized!")
            print(f"   Error: {stats.get('error')}")
            print(f"\n💡 Run: python3 index_corrections_to_vectordb.py")
            return

        print(f"\n📊 RAG Vector Database:")
        print(f"   Total corrections: {stats.get('total_corrections', 0)}")
        print(f"   Embedding model: {stats.get('embedding_model')}")

        # Get random corrections to test on
        db = SessionLocal()
        try:
            query = """
                SELECT
                    ticker,
                    issue_type,
                    original_data,
                    final_fix,
                    learning_notes
                FROM data_quality_conversations
                WHERE
                    original_data IS NOT NULL
                    AND final_fix IS NOT NULL
                    AND learning_notes IS NOT NULL
                    AND issue_type != 'deadline_passed'
                ORDER BY RANDOM()
                LIMIT :limit
            """

            result = db.execute(text(query), {'limit': num_tests})
            corrections = []

            for row in result.fetchall():
                corrections.append({
                    'ticker': row[0],
                    'issue_type': row[1],
                    'original_data': row[2],
                    'final_fix': row[3],
                    'learning_notes': row[4]
                })

            print(f"\n🧪 Testing on {len(corrections)} corrections...")

            # Test each
            results = []
            for correction in corrections:
                result = self.test_on_correction(correction)
                if result:
                    results.append(result)
                    self.results.append(result)

            # Summary
            self.print_summary(results)

        finally:
            db.close()

    def print_summary(self, results: List[Dict]):
        """Print test results summary"""
        if not results:
            print("\n⚠️  No test results")
            return

        total = len(results)
        baseline_correct = sum(1 for r in results if r['baseline_correct'])
        rag_correct = sum(1 for r in results if r['rag_correct'])
        improvements = sum(1 for r in results if r['improvement'])
        avg_similar = sum(r['similar_corrections_found'] for r in results) / total

        print(f"\n{'='*60}")
        print(f"TEST RESULTS SUMMARY")
        print(f"{'='*60}")
        print(f"\n📊 Accuracy:")
        print(f"   Baseline (no learning):    {baseline_correct}/{total} ({baseline_correct/total*100:.1f}%)")
        print(f"   RAG (semantic search):     {rag_correct}/{total} ({rag_correct/total*100:.1f}%)")
        print(f"\n✨ Improvement:")
        print(f"   Fixed by RAG: {improvements}/{total} ({improvements/total*100:.1f}%)")
        print(f"   Avg similar corrections found: {avg_similar:.1f}")

        if rag_correct > baseline_correct:
            improvement_pct = (rag_correct - baseline_correct) / total * 100
            print(f"   📈 Overall improvement: +{improvement_pct:.1f}%")
            print(f"\n✅ RAG learning WORKS! Semantic search improves accuracy.")
        elif rag_correct == baseline_correct:
            print(f"\n⚠️  No improvement over baseline.")
        else:
            print(f"\n❌ RAG made it worse.")

        # Detailed results
        print(f"\n📋 Detailed Results:")
        for i, r in enumerate(results, 1):
            status = "✅" if r['improvement'] else ("✓" if r['rag_correct'] else "❌")
            print(f"   {status} {i}. {r['ticker']} - {r['field']}: {str(r['correct_value'])[:50]}")

    def export_results(self, filename: str = "rag_test_results.json"):
        """Export results to JSON"""
        output = {
            'test_date': datetime.now().isoformat(),
            'method': 'RAG (semantic search)',
            'total_tests': len(self.results),
            'baseline_accuracy': sum(1 for r in self.results if r['baseline_correct']) / len(self.results),
            'rag_accuracy': sum(1 for r in self.results if r['rag_correct']) / len(self.results),
            'improvements': sum(1 for r in self.results if r['improvement']),
            'detailed_results': self.results
        }

        with open(filename, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\n💾 Results exported to {filename}")


def main():
    """Main test runner"""
    import argparse

    parser = argparse.ArgumentParser(description='Test RAG Learning Accuracy')
    parser.add_argument('--tests', type=int, default=10,
                        help='Number of corrections to test (default: 10)')
    parser.add_argument('--export', action='store_true',
                        help='Export results to JSON')

    args = parser.parse_args()

    # Run tests
    tester = RAGTester()
    tester.run_test_suite(num_tests=args.tests)

    # Export if requested
    if args.export:
        tester.export_results()


if __name__ == '__main__':
    main()
