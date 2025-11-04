#!/usr/bin/env python3
"""
Test Few-Shot Learning Accuracy

Compares extraction accuracy with and without few-shot learning examples.
Uses real corrections from database to validate improvements.
"""

import os
import sys
from datetime import datetime
from typing import Dict, List
from openai import OpenAI
from dotenv import load_dotenv

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from agents.self_learning_mixin import SelfLearningMixin
from sqlalchemy import text
import json

load_dotenv()

# AI Setup
AI_CLIENT = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


class FewShotTester(SelfLearningMixin):
    """Test harness with self-learning capability"""

    def __init__(self):
        self.results = []

    def extract_field_baseline(self, field: str, filing_text: str) -> str:
        """
        Baseline extraction (no learning examples).

        This is how your system currently works.
        """
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

    def extract_field_with_learning(
        self,
        field: str,
        filing_text: str,
        ticker: str = None
    ) -> str:
        """
        Few-shot extraction (with learning examples).

        This uses your 414 corrections to improve accuracy.
        """
        prompt = self.build_prompt_with_learning(
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
            print(f"❌ Learning extraction failed: {e}")
            return ""

    def test_on_correction(self, correction: Dict) -> Dict:
        """
        Test extraction on a past correction.

        We know the correct answer (final_fix), so we can measure accuracy.
        """
        ticker = correction['ticker']
        field = list(correction['final_fix'].keys())[0]  # First field in fix
        correct_value = correction['final_fix'][field]

        # Simulate filing text (use original_data if available)
        filing_text = str(correction.get('original_data', ''))[:2000]

        if not filing_text:
            print(f"⚠️  No original data for {ticker}, skipping")
            return None

        print(f"\n{'='*60}")
        print(f"Testing: {ticker} - Field: {field}")
        print(f"Correct answer: {correct_value}")
        print(f"{'='*60}")

        # Test baseline (no learning)
        print("🔍 Baseline extraction (no learning)...")
        baseline_result = self.extract_field_baseline(field, filing_text)
        print(f"   Result: {baseline_result}")
        baseline_correct = (str(baseline_result).lower() == str(correct_value).lower())

        # Test with learning
        print("🧠 Few-shot extraction (with learning)...")
        learning_result = self.extract_field_with_learning(field, filing_text, ticker)
        print(f"   Result: {learning_result}")
        learning_correct = (str(learning_result).lower() == str(correct_value).lower())

        # Score
        result = {
            'ticker': ticker,
            'field': field,
            'correct_value': correct_value,
            'baseline_result': baseline_result,
            'baseline_correct': baseline_correct,
            'learning_result': learning_result,
            'learning_correct': learning_correct,
            'improvement': learning_correct and not baseline_correct
        }

        if baseline_correct and learning_correct:
            print("   ✅ Both correct")
        elif learning_correct and not baseline_correct:
            print("   🎉 Learning fixed the error!")
        elif baseline_correct and not learning_correct:
            print("   ⚠️  Learning made it worse")
        else:
            print("   ❌ Both wrong")

        return result

    def run_test_suite(self, num_tests: int = 5):
        """
        Run test on N random corrections from database.

        Args:
            num_tests: Number of corrections to test
        """
        print(f"\n{'='*60}")
        print(f"FEW-SHOT LEARNING TEST SUITE")
        print(f"{'='*60}")

        # Get learning stats
        stats = self.get_learning_stats()
        print(f"\n📊 Available Learning Data:")
        print(f"   Total corrections: {stats.get('total_corrections', 0)}")
        print(f"   Top corrected fields: {list(stats.get('top_corrected_fields', {}).keys())[:5]}")

        # Get random corrections to test on
        db = SessionLocal()
        try:
            # Get corrections with original_data (so we can re-test)
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
                    AND issue_type != 'deadline_passed'  -- Skip deadline corrections
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

            # Test each correction
            results = []
            for correction in corrections:
                result = self.test_on_correction(correction)
                if result:
                    results.append(result)
                    self.results.append(result)

            # Print summary
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
        learning_correct = sum(1 for r in results if r['learning_correct'])
        improvements = sum(1 for r in results if r['improvement'])

        print(f"\n{'='*60}")
        print(f"TEST RESULTS SUMMARY")
        print(f"{'='*60}")
        print(f"\n📊 Accuracy:")
        print(f"   Baseline (no learning):  {baseline_correct}/{total} ({baseline_correct/total*100:.1f}%)")
        print(f"   Few-shot (with learning): {learning_correct}/{total} ({learning_correct/total*100:.1f}%)")
        print(f"\n✨ Improvement:")
        print(f"   Fixed by learning: {improvements}/{total} ({improvements/total*100:.1f}%)")

        if learning_correct > baseline_correct:
            improvement_pct = (learning_correct - baseline_correct) / total * 100
            print(f"   📈 Overall improvement: +{improvement_pct:.1f}%")
            print(f"\n✅ Few-shot learning WORKS! Consider deploying.")
        elif learning_correct == baseline_correct:
            print(f"\n⚠️  No improvement. May need more/better examples.")
        else:
            print(f"\n❌ Learning made it worse. Check examples quality.")

        # Detailed results
        print(f"\n📋 Detailed Results:")
        for i, r in enumerate(results, 1):
            status = "✅" if r['improvement'] else ("✓" if r['learning_correct'] else "❌")
            print(f"   {status} {i}. {r['ticker']} - {r['field']}: {r['correct_value']}")

    def export_results(self, filename: str = "few_shot_test_results.json"):
        """Export results to JSON for analysis"""
        output = {
            'test_date': datetime.now().isoformat(),
            'total_tests': len(self.results),
            'baseline_accuracy': sum(1 for r in self.results if r['baseline_correct']) / len(self.results),
            'learning_accuracy': sum(1 for r in self.results if r['learning_correct']) / len(self.results),
            'improvements': sum(1 for r in self.results if r['improvement']),
            'detailed_results': self.results
        }

        with open(filename, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\n💾 Results exported to {filename}")


def main():
    """Main test runner"""
    import argparse

    parser = argparse.ArgumentParser(description='Test Few-Shot Learning Accuracy')
    parser.add_argument('--tests', type=int, default=5,
                        help='Number of corrections to test (default: 5)')
    parser.add_argument('--export', action='store_true',
                        help='Export results to JSON')

    args = parser.parse_args()

    # Run tests
    tester = FewShotTester()
    tester.run_test_suite(num_tests=args.tests)

    # Export if requested
    if args.export:
        tester.export_results()


if __name__ == '__main__':
    main()
