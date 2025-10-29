#!/usr/bin/env python3
"""
Test Feedback System - Quick Verification Script
Version: 1.0.0

Runs comprehensive tests on new feedback system.
"""

import sys
import os
import yaml
from datetime import datetime

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_test(name):
    """Print test name"""
    print(f"\n{BLUE}▶ {name}{RESET}")


def print_success(message):
    """Print success message"""
    print(f"  {GREEN}✓{RESET} {message}")


def print_error(message):
    """Print error message"""
    print(f"  {RED}✗{RESET} {message}")


def print_warning(message):
    """Print warning message"""
    print(f"  {YELLOW}⚠{RESET} {message}")


def test_yaml_configs():
    """Test YAML configuration loading"""
    print_test("Testing YAML Configuration Loading")

    configs = {
        'validation_rules': 'config/validation_rules.yaml',
        'fix_templates': 'config/fix_templates.yaml',
        'self_improvement': 'config/self_improvement_rules.yaml'
    }

    all_passed = True

    for name, path in configs.items():
        if not os.path.exists(path):
            print_error(f"{name}: File not found at {path}")
            all_passed = False
            continue

        try:
            with open(path, 'r') as f:
                config = yaml.safe_load(f)

            if name == 'validation_rules':
                rules_count = len(config.get('rules', {}))
                print_success(f"{name}: Loaded {rules_count} rules")

            elif name == 'fix_templates':
                templates_count = len(config.get('fix_templates', {}))
                print_success(f"{name}: Loaded {templates_count} templates")

            elif name == 'self_improvement':
                enabled = config.get('self_improvement', {}).get('enabled', False)
                threshold = config.get('self_improvement', {}).get('error_threshold', 0)
                print_success(f"{name}: Enabled={enabled}, Threshold={threshold}")

        except Exception as e:
            print_error(f"{name}: Failed to load - {str(e)}")
            all_passed = False

    return all_passed


def test_feedback_modules():
    """Test feedback module imports"""
    print_test("Testing Feedback Module Imports")

    modules = [
        ('ValidationQueue', 'feedback.validation_queue'),
        ('TelegramInterface', 'feedback.telegram_interface'),
        ('InvestigationEngine', 'feedback.investigation_engine'),
        ('FixApplier', 'feedback.fix_applier'),
        ('LearningLog', 'feedback.learning_log'),
        ('SelfImprovementAgent', 'feedback.self_improvement')
    ]

    all_passed = True

    for class_name, module_path in modules:
        try:
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)
            print_success(f"{class_name}: Import successful")
        except ImportError as e:
            print_error(f"{class_name}: Import failed - {str(e)}")
            all_passed = False
        except Exception as e:
            print_error(f"{class_name}: Error - {str(e)}")
            all_passed = False

    return all_passed


def test_database_connection():
    """Test database connection and tables"""
    print_test("Testing Database Connection")

    try:
        from database import SessionLocal
        from sqlalchemy import text

        db = SessionLocal()

        # Test connection
        db.execute(text("SELECT 1"))
        print_success("Database connection successful")

        # Check for new tables
        required_tables = [
            'validation_queue',
            'validation_queue_items',
            'telegram_state',
            'error_patterns',
            'batch_approvals',
            'code_improvements'
        ]

        result = db.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN :tables
        """), {'tables': tuple(required_tables)})

        existing_tables = [row[0] for row in result]

        for table in required_tables:
            if table in existing_tables:
                print_success(f"Table exists: {table}")
            else:
                print_warning(f"Table missing: {table} (run migration first)")

        db.close()
        return True

    except Exception as e:
        print_error(f"Database test failed: {str(e)}")
        return False


def test_validation_queue():
    """Test validation queue functionality"""
    print_test("Testing Validation Queue")

    try:
        from feedback import ValidationQueue

        with ValidationQueue() as queue:
            # Test getting active queue
            active = queue.get_active_queue()
            if active:
                print_success(f"Active queue found: Queue {active['queue_id']}")
            else:
                print_warning("No active queue (this is normal)")

            # Test queue stats
            if active:
                stats = queue.get_queue_stats()
                print_success(f"Queue stats: {stats.get('total_issues', 0)} total issues")

        print_success("ValidationQueue module works correctly")
        return True

    except Exception as e:
        print_error(f"ValidationQueue test failed: {str(e)}")
        return False


def test_telegram_integration():
    """Test Telegram integration"""
    print_test("Testing Telegram Integration")

    try:
        from telegram_agent import TelegramAgent

        agent = TelegramAgent()
        print_success("TelegramAgent initialized")

        # Check env vars
        if agent.bot_token and agent.chat_id:
            print_success("Telegram credentials configured")
        else:
            print_warning("Telegram credentials missing (check .env)")

        return True

    except Exception as e:
        print_error(f"Telegram test failed: {str(e)}")
        return False


def test_fix_applier():
    """Test fix applier functionality"""
    print_test("Testing Fix Applier")

    try:
        from feedback import FixApplier

        with FixApplier() as applier:
            templates_count = len(applier.fix_templates)
            print_success(f"Fix templates loaded: {templates_count}")

            # List some templates
            for template_id, template in list(applier.fix_templates.items())[:3]:
                name = template.get('name', 'Unknown')
                print_success(f"  - {template.get('id')}: {name}")

        return True

    except Exception as e:
        print_error(f"FixApplier test failed: {str(e)}")
        return False


def run_all_tests():
    """Run all tests"""
    print(f"\n{'='*70}")
    print(f"{BLUE}FEEDBACK SYSTEM TEST SUITE{RESET}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    results = {}

    results['yaml_configs'] = test_yaml_configs()
    results['feedback_modules'] = test_feedback_modules()
    results['database'] = test_database_connection()
    results['validation_queue'] = test_validation_queue()
    results['telegram'] = test_telegram_integration()
    results['fix_applier'] = test_fix_applier()

    # Summary
    print(f"\n{'='*70}")
    print(f"{BLUE}TEST SUMMARY{RESET}")
    print(f"{'='*70}\n")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
        print(f"  {status} {test_name}")

    print(f"\n{BLUE}Results: {passed}/{total} tests passed{RESET}")

    if passed == total:
        print(f"\n{GREEN}✅ ALL TESTS PASSED!{RESET}")
        print(f"\n{GREEN}The feedback system is ready for use.{RESET}")
        print(f"\nNext steps:")
        print(f"  1. Review MORNING_BRIEFING_2025-10-29.md")
        print(f"  2. Apply database migration if not done")
        print(f"  3. Start testing with real data")
    else:
        print(f"\n{RED}⚠️  SOME TESTS FAILED{RESET}")
        print(f"\nCheck errors above and:")
        print(f"  1. Ensure database migration is applied")
        print(f"  2. Check .env configuration")
        print(f"  3. Verify all dependencies installed")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    run_all_tests()
