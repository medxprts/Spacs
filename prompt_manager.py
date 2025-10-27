#!/usr/bin/env python3
"""
Prompt Management System
Loads AI prompts from YAML files, tracks performance, enables versioning

Usage:
    from prompt_manager import get_prompt, log_prompt_result

    # Get a prompt
    prompt_text = get_prompt('deal_target_extraction', filing_text=text)

    # After using prompt, log the result
    log_prompt_result('deal_target_extraction', success=True, extracted_data={'target': 'Acme Corp'})

    # If prompt repeatedly fails, system auto-improves it
"""

import yaml
import os
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime
from database import SessionLocal
from sqlalchemy import text


class PromptManager:
    """Manages AI prompts with versioning and performance tracking"""

    def __init__(self, prompts_dir: str = '/home/ubuntu/spac-research/prompts'):
        self.prompts_dir = Path(prompts_dir)
        self._prompt_cache: Dict[str, Dict] = {}

    def get_prompt(self, prompt_id: str, **variables) -> Dict[str, str]:
        """
        Load a prompt and interpolate variables

        Args:
            prompt_id: Prompt identifier (e.g., 'deal_target_extraction')
            **variables: Variables to interpolate into prompt template

        Returns:
            Dict with 'system_prompt' and 'user_prompt' keys
        """
        # Load from cache or file
        if prompt_id not in self._prompt_cache:
            self._load_prompt(prompt_id)

        prompt_data = self._prompt_cache.get(prompt_id)
        if not prompt_data:
            raise ValueError(f"Prompt not found: {prompt_id}")

        # Interpolate variables into user prompt
        user_prompt = prompt_data['user_prompt'].format(**variables)
        system_prompt = prompt_data.get('system_prompt', '')

        return {
            'system_prompt': system_prompt,
            'user_prompt': user_prompt,
            'metadata': prompt_data.get('metadata', {})
        }

    def _load_prompt(self, prompt_id: str):
        """Load prompt from YAML file"""
        # Search for prompt file
        for yaml_file in self.prompts_dir.rglob('*.yaml'):
            try:
                with open(yaml_file, 'r') as f:
                    data = yaml.safe_load(f)

                metadata = data.get('metadata', {})
                if metadata.get('prompt_id') == prompt_id:
                    self._prompt_cache[prompt_id] = data
                    return
            except Exception as e:
                print(f"⚠️  Error loading {yaml_file}: {e}")

        # If not found, raise error
        raise FileNotFoundError(f"Prompt file not found for: {prompt_id}")

    def log_result(self, prompt_id: str, success: bool,
                   extracted_data: Optional[Dict] = None,
                   error: Optional[str] = None,
                   spac_ticker: Optional[str] = None):
        """
        Log the result of using a prompt

        This data is used to track prompt effectiveness and trigger improvements
        """
        db = SessionLocal()
        try:
            db.execute(text("""
                INSERT INTO prompt_usage_log
                (prompt_id, success, extracted_data, error_message, spac_ticker, used_at)
                VALUES
                (:prompt_id, :success, :extracted_data, :error, :ticker, NOW())
            """), {
                'prompt_id': prompt_id,
                'success': success,
                'extracted_data': str(extracted_data) if extracted_data else None,
                'error': error,
                'ticker': spac_ticker
            })
            db.commit()
        except Exception as e:
            # Table may not exist yet - silent fail
            pass
        finally:
            db.close()

    def get_prompt_stats(self, prompt_id: str, lookback_days: int = 30) -> Dict:
        """Get performance statistics for a prompt"""
        db = SessionLocal()
        try:
            result = db.execute(text("""
                SELECT
                    COUNT(*) as total_uses,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                    CAST(SUM(CASE WHEN success THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) * 100 as success_rate,
                    array_agg(DISTINCT error_message) FILTER (WHERE error_message IS NOT NULL) as common_errors
                FROM prompt_usage_log
                WHERE prompt_id = :prompt_id
                  AND used_at >= NOW() - INTERVAL '{} days'
            """.format(lookback_days)), {
                'prompt_id': prompt_id
            }).fetchone()

            if result and result[0] > 0:
                return {
                    'total_uses': result[0],
                    'successes': result[1],
                    'success_rate': round(result[2], 2) if result[2] else 0,
                    'common_errors': result[3] or []
                }

            return {'total_uses': 0, 'successes': 0, 'success_rate': 0, 'common_errors': []}

        except Exception as e:
            return {'total_uses': 0, 'successes': 0, 'success_rate': 0, 'common_errors': []}
        finally:
            db.close()

    def suggest_improvement(self, prompt_id: str) -> Optional[str]:
        """
        Analyze prompt performance and suggest improvements

        Returns:
            Improvement suggestion or None if prompt is performing well
        """
        stats = self.get_prompt_stats(prompt_id)

        if stats['total_uses'] < 10:
            return None  # Not enough data

        if stats['success_rate'] < 70:
            return f"Prompt '{prompt_id}' has low success rate ({stats['success_rate']}%). Common errors: {stats['common_errors'][:3]}"

        return None


# Singleton instance
_prompt_manager = PromptManager()


def get_prompt(prompt_id: str, **variables) -> Dict[str, str]:
    """Get a prompt with interpolated variables"""
    return _prompt_manager.get_prompt(prompt_id, **variables)


def log_prompt_result(prompt_id: str, success: bool, **kwargs):
    """Log the result of using a prompt"""
    return _prompt_manager.log_result(prompt_id, success, **kwargs)


def get_prompt_stats(prompt_id: str, lookback_days: int = 30) -> Dict:
    """Get performance statistics for a prompt"""
    return _prompt_manager.get_prompt_stats(prompt_id, lookback_days)


# Example usage
if __name__ == '__main__':
    print("📋 Testing Prompt Manager...")
    print()

    # Test loading a prompt
    prompt = get_prompt('deal_target_extraction', filing_text='[Sample filing text...]')

    print("System Prompt:")
    print(prompt['system_prompt'][:200])
    print()

    print("User Prompt (first 300 chars):")
    print(prompt['user_prompt'][:300])
    print()

    print("Metadata:")
    import pprint
    pprint.pprint(prompt['metadata'])
