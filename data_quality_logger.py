#!/usr/bin/env python3
"""
Data Quality Logger - Track missing data and extraction failures

Logs:
- Fields that couldn't be extracted (with source filing URL)
- API failures (delisted tickers, rate limits)
- Data validation failures
- Reasons for missing data

Output: logs/data_quality.jsonl (machine-readable)
        logs/data_quality_summary.log (human-readable)
"""

import os
import json
from datetime import datetime
from typing import Dict, Optional, List
from pathlib import Path

# Ensure logs directory exists
Path("/home/ubuntu/spac-research/logs").mkdir(parents=True, exist_ok=True)

class DataQualityLogger:
    """Track and log data quality issues"""

    def __init__(self, log_file: str = "logs/data_quality.jsonl"):
        self.log_file = log_file

    def log_missing_field(
        self,
        ticker: str,
        field: str,
        source: str,
        reason: str,
        filing_url: Optional[str] = None,
        severity: str = "WARNING"
    ):
        """
        Log a missing data field

        Args:
            ticker: SPAC ticker
            field: Field name (e.g., 'shares_outstanding', 'deal_value')
            source: Data source (e.g., 'IPO Press Release', '10-Q', 'Super 8-K')
            reason: Why it's missing (e.g., 'Not found in document', 'AI extraction failed')
            filing_url: SEC filing URL if applicable
            severity: INFO, WARNING, ERROR, CRITICAL
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "missing_field",
            "ticker": ticker,
            "field": field,
            "source": source,
            "reason": reason,
            "filing_url": filing_url,
            "severity": severity
        }

        self._write_log(entry)

    def log_extraction_failure(
        self,
        ticker: str,
        source_type: str,
        filing_url: str,
        error: str,
        fields_attempted: List[str]
    ):
        """
        Log AI/regex extraction failure

        Args:
            ticker: SPAC ticker
            source_type: Filing type (e.g., '8-K', 'S-4', '10-Q')
            filing_url: URL of filing
            error: Error message
            fields_attempted: List of fields we tried to extract
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "extraction_failure",
            "ticker": ticker,
            "source_type": source_type,
            "filing_url": filing_url,
            "error": str(error),
            "fields_attempted": fields_attempted,
            "severity": "ERROR"
        }

        self._write_log(entry)

    def log_api_failure(
        self,
        ticker: str,
        api: str,
        error_type: str,
        error_message: str
    ):
        """
        Log API call failure

        Args:
            ticker: SPAC ticker
            api: API name (e.g., 'Yahoo Finance', 'SEC EDGAR')
            error_type: Type of error (e.g., 'Delisted', 'Rate Limit', '404')
            error_message: Full error message
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "api_failure",
            "ticker": ticker,
            "api": api,
            "error_type": error_type,
            "error_message": error_message,
            "severity": "WARNING"
        }

        self._write_log(entry)

    def log_validation_failure(
        self,
        ticker: str,
        rule_number: int,
        rule_name: str,
        current_value: any,
        expected_value: any,
        severity: str = "WARNING"
    ):
        """
        Log data validation failure

        Args:
            ticker: SPAC ticker
            rule_number: Validation rule number (e.g., 18)
            rule_name: Rule name (e.g., 'market_cap_calculation')
            current_value: Actual value in database
            expected_value: Expected/calculated value
            severity: INFO, WARNING, ERROR, CRITICAL
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "validation_failure",
            "ticker": ticker,
            "rule_number": rule_number,
            "rule_name": rule_name,
            "current_value": str(current_value),
            "expected_value": str(expected_value),
            "severity": severity
        }

        self._write_log(entry)

    def log_data_inconsistency(
        self,
        ticker: str,
        field: str,
        source1: str,
        value1: any,
        source2: str,
        value2: any
    ):
        """
        Log inconsistent data from multiple sources

        Args:
            ticker: SPAC ticker
            field: Field with inconsistent data
            source1: First source
            value1: Value from first source
            source2: Second source
            value2: Value from second source
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "data_inconsistency",
            "ticker": ticker,
            "field": field,
            "source1": source1,
            "value1": str(value1),
            "source2": source2,
            "value2": str(value2),
            "difference": abs(float(value1) - float(value2)) if isinstance(value1, (int, float)) and isinstance(value2, (int, float)) else "N/A",
            "severity": "WARNING"
        }

        self._write_log(entry)

    def log_change(
        self,
        ticker: str,
        field: str,
        old_value: str,
        new_value: str,
        source: str,
        confidence: float,
        validation_method: str
    ):
        """
        Log a data change/correction

        Args:
            ticker: SPAC ticker
            field: Field name that changed
            old_value: Previous value
            new_value: New value
            source: Source of the change (e.g., 'data_validator_autofix', 'manual_correction')
            confidence: Confidence level (0.0-1.0)
            validation_method: How the change was validated ('calculation', 'correction', 'ai_extraction')
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "data_change",
            "ticker": ticker,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "source": source,
            "confidence": confidence,
            "validation_method": validation_method,
            "severity": "INFO"
        }

        self._write_log(entry)

    def _write_log(self, entry: Dict):
        """Write log entry to JSONL file"""
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            print(f"Failed to write log: {e}")

    def generate_summary(self, output_file: str = "logs/data_quality_summary.log"):
        """
        Generate human-readable summary of data quality issues

        Groups by:
        - Most common missing fields
        - SPACs with most missing data
        - Error types by frequency
        """
        try:
            if not os.path.exists(self.log_file):
                print(f"No log file found at {self.log_file}")
                return

            # Load all log entries
            entries = []
            with open(self.log_file, 'r') as f:
                for line in f:
                    entries.append(json.loads(line))

            if not entries:
                print("No log entries found")
                return

            # Analyze
            missing_fields = {}
            spac_issues = {}
            error_types = {}

            for entry in entries:
                if entry['type'] == 'missing_field':
                    field = entry['field']
                    missing_fields[field] = missing_fields.get(field, 0) + 1

                    ticker = entry['ticker']
                    if ticker not in spac_issues:
                        spac_issues[ticker] = []
                    spac_issues[ticker].append(entry['field'])

                elif entry['type'] == 'api_failure':
                    error_type = entry['error_type']
                    error_types[error_type] = error_types.get(error_type, 0) + 1

            # Write summary
            with open(output_file, 'w') as f:
                f.write("=" * 80 + "\n")
                f.write("DATA QUALITY SUMMARY\n")
                f.write(f"Generated: {datetime.now().isoformat()}\n")
                f.write(f"Total Entries: {len(entries)}\n")
                f.write("=" * 80 + "\n\n")

                # Most common missing fields
                f.write("TOP 10 MISSING FIELDS:\n")
                f.write("-" * 80 + "\n")
                for field, count in sorted(missing_fields.items(), key=lambda x: x[1], reverse=True)[:10]:
                    f.write(f"  {field}: {count} SPACs\n")

                f.write("\n\nSPACs WITH MOST MISSING DATA:\n")
                f.write("-" * 80 + "\n")
                spac_counts = {k: len(v) for k, v in spac_issues.items()}
                for ticker, count in sorted(spac_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                    f.write(f"  {ticker}: {count} missing fields - {', '.join(spac_issues[ticker])}\n")

                f.write("\n\nAPI ERROR TYPES:\n")
                f.write("-" * 80 + "\n")
                for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"  {error_type}: {count} occurrences\n")

                f.write("\n" + "=" * 80 + "\n")

            print(f"✅ Summary written to {output_file}")

        except Exception as e:
            print(f"Error generating summary: {e}")


# Global instance
logger = DataQualityLogger()


# ============================================================================
# Analysis Functions
# ============================================================================

def analyze_field_coverage(field: str) -> Dict:
    """
    Analyze coverage for a specific field

    Returns:
        Dict with success rate, common failure reasons, etc.
    """
    entries = []
    log_file = "logs/data_quality.jsonl"

    if not os.path.exists(log_file):
        return {"error": "No log file found"}

    with open(log_file, 'r') as f:
        for line in f:
            entry = json.loads(line)
            if entry.get('field') == field:
                entries.append(entry)

    if not entries:
        return {"error": f"No entries found for field '{field}'"}

    reasons = {}
    sources = {}

    for entry in entries:
        reason = entry.get('reason', 'Unknown')
        reasons[reason] = reasons.get(reason, 0) + 1

        source = entry.get('source', 'Unknown')
        sources[source] = sources.get(source, 0) + 1

    return {
        "field": field,
        "total_failures": len(entries),
        "failure_reasons": reasons,
        "sources_checked": sources
    }


def get_improvement_opportunities() -> List[Dict]:
    """
    Identify top opportunities for improvement

    Returns patterns like:
    - "shares_outstanding missing from 80 IPO press releases → Enhance AI prompt"
    - "redemptions missing from 30 8-Ks → Add exhibit checking"
    """
    entries = []
    log_file = "logs/data_quality.jsonl"

    if not os.path.exists(log_file):
        return []

    with open(log_file, 'r') as f:
        for line in f:
            entries.append(json.loads(line))

    # Group by field + source combination
    opportunities = {}

    for entry in entries:
        if entry['type'] != 'missing_field':
            continue

        field = entry['field']
        source = entry['source']
        key = f"{field}|{source}"

        if key not in opportunities:
            opportunities[key] = {
                "field": field,
                "source": source,
                "count": 0,
                "tickers": []
            }

        opportunities[key]["count"] += 1
        opportunities[key]["tickers"].append(entry['ticker'])

    # Sort by frequency
    sorted_opps = sorted(opportunities.values(), key=lambda x: x["count"], reverse=True)

    return sorted_opps[:10]  # Top 10 opportunities


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """Command-line interface for data quality analysis"""
    import argparse

    parser = argparse.ArgumentParser(description='Data Quality Logger Analysis')
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Generate summary report'
    )
    parser.add_argument(
        '--field',
        type=str,
        help='Analyze coverage for specific field'
    )
    parser.add_argument(
        '--opportunities',
        action='store_true',
        help='Show improvement opportunities'
    )

    args = parser.parse_args()

    if args.summary:
        logger.generate_summary()

    elif args.field:
        analysis = analyze_field_coverage(args.field)
        print(json.dumps(analysis, indent=2))

    elif args.opportunities:
        opps = get_improvement_opportunities()
        print("\nTOP IMPROVEMENT OPPORTUNITIES:")
        print("=" * 80)
        for i, opp in enumerate(opps, 1):
            print(f"\n{i}. {opp['field']} missing from {opp['count']} {opp['source']} filings")
            print(f"   Tickers: {', '.join(opp['tickers'][:10])}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
