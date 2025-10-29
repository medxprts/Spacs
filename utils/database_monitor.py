#!/usr/bin/env python3
"""
Database Write Failure Monitor

Tracks and alerts on database write failures to prevent silent data loss.
Integrates with orchestrator's Telegram agent for critical alerts.
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
import traceback

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from sqlalchemy import text

# Track write failures in memory (for alerting)
_write_failures = []
_last_alert_time = None
ALERT_COOLDOWN_MINUTES = 30  # Don't spam alerts


class DatabaseWriteError(Exception):
    """Exception raised when database write fails"""
    pass


def log_write_failure(
    operation: str,
    ticker: Optional[str],
    error: Exception,
    context: Dict[str, Any] = None
) -> None:
    """
    Log database write failure to database and trigger alerts if needed

    Args:
        operation: Description of operation (e.g., "deal_update", "trust_value_update")
        ticker: SPAC ticker affected (if applicable)
        error: Exception that occurred
        context: Additional context (data being written, etc.)
    """
    global _write_failures, _last_alert_time

    failure_record = {
        'timestamp': datetime.now(),
        'operation': operation,
        'ticker': ticker,
        'error_type': type(error).__name__,
        'error_message': str(error),
        'traceback': traceback.format_exc(),
        'context': context or {}
    }

    _write_failures.append(failure_record)

    # Keep only last 100 failures in memory
    if len(_write_failures) > 100:
        _write_failures = _write_failures[-100:]

    # Log to database (in separate transaction to avoid cascade failures)
    try:
        db = SessionLocal()
        try:
            # Ensure table exists
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS database_write_failures (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    operation VARCHAR(100) NOT NULL,
                    ticker VARCHAR(10),
                    error_type VARCHAR(100),
                    error_message TEXT,
                    traceback TEXT,
                    context_json TEXT,
                    alerted BOOLEAN DEFAULT FALSE
                )
            """))
            db.commit()

            # Insert failure record
            db.execute(text("""
                INSERT INTO database_write_failures
                (timestamp, operation, ticker, error_type, error_message, traceback, context_json)
                VALUES
                (:timestamp, :operation, :ticker, :error_type, :error_message, :traceback, :context)
            """), {
                'timestamp': failure_record['timestamp'],
                'operation': operation,
                'ticker': ticker,
                'error_type': failure_record['error_type'],
                'error_message': failure_record['error_message'],
                'traceback': failure_record['traceback'],
                'context': str(context) if context else None
            })
            db.commit()
        except Exception as e:
            # Even logging failed - print to console
            print(f"⚠️  Could not log database write failure: {e}")
            db.rollback()
        finally:
            db.close()
    except:
        pass  # Don't let logging failure block execution

    # Check if we should send alert
    critical_operations = ['deal_update', 'deal_structure_update', 'trust_value_update', 'redemption_update']

    if operation in critical_operations:
        _send_alert_if_needed(failure_record)


def _send_alert_if_needed(failure: Dict[str, Any]) -> None:
    """Send Telegram alert for critical database write failures"""
    global _last_alert_time

    # Rate limiting - don't alert more than once per ALERT_COOLDOWN_MINUTES
    now = datetime.now()
    if _last_alert_time and (now - _last_alert_time) < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
        return

    _last_alert_time = now

    # Format alert message
    ticker_str = f" ({failure['ticker']})" if failure['ticker'] else ""
    alert_text = f"""🚨 <b>DATABASE WRITE FAILURE</b>

<b>Operation:</b> {failure['operation']}{ticker_str}
<b>Error:</b> {failure['error_type']}
<b>Message:</b> {failure['error_message'][:200]}

<b>Time:</b> {failure['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}

⚠️ <b>This may result in data loss!</b>
Review logs and database state immediately.
"""

    # Send via orchestrator's Telegram agent
    try:
        from agent_orchestrator import Orchestrator, AgentTask, TaskPriority, TaskStatus

        orchestrator = Orchestrator()

        task = AgentTask(
            task_id=f"db_failure_alert_{now.strftime('%Y%m%d_%H%M%S')}",
            agent_name="telegram",
            task_type="send_alert",
            priority=TaskPriority.CRITICAL,
            status=TaskStatus.PENDING,
            created_at=now,
            parameters={'alert_text': alert_text}
        )

        orchestrator.agents['telegram'].execute(task)

        # Mark as alerted in database
        try:
            db = SessionLocal()
            db.execute(text("""
                UPDATE database_write_failures
                SET alerted = TRUE
                WHERE timestamp = :timestamp AND operation = :operation
            """), {
                'timestamp': failure['timestamp'],
                'operation': failure['operation']
            })
            db.commit()
            db.close()
        except:
            pass

    except Exception as e:
        print(f"⚠️  Could not send Telegram alert: {e}")


def safe_database_write(
    db_session,
    operation: str,
    ticker: Optional[str],
    write_function,
    context: Dict[str, Any] = None,
    raise_on_error: bool = False
) -> bool:
    """
    Safely execute a database write with monitoring and error handling

    Args:
        db_session: SQLAlchemy session
        operation: Description of operation
        ticker: SPAC ticker (if applicable)
        write_function: Function that performs the write (takes db_session as arg)
        context: Additional context for logging
        raise_on_error: If True, re-raise exception after logging

    Returns:
        True if write succeeded, False if failed

    Example:
        def update_deal(db):
            spac = db.query(SPAC).filter(SPAC.ticker == 'CEP').first()
            spac.target = 'Securitize, Inc.'
            db.commit()

        success = safe_database_write(
            db,
            'deal_update',
            'CEP',
            update_deal,
            context={'target': 'Securitize, Inc.'}
        )
    """
    try:
        write_function(db_session)
        return True

    except IntegrityError as e:
        # Duplicate or constraint violation
        db_session.rollback()
        log_write_failure(operation, ticker, e, context)
        if raise_on_error:
            raise DatabaseWriteError(f"Integrity error in {operation}: {e}") from e
        return False

    except OperationalError as e:
        # Database connection or operational issue
        db_session.rollback()
        log_write_failure(operation, ticker, e, context)
        if raise_on_error:
            raise DatabaseWriteError(f"Operational error in {operation}: {e}") from e
        return False

    except SQLAlchemyError as e:
        # Any other database error
        db_session.rollback()
        log_write_failure(operation, ticker, e, context)
        if raise_on_error:
            raise DatabaseWriteError(f"Database error in {operation}: {e}") from e
        return False

    except Exception as e:
        # Unexpected error
        db_session.rollback()
        log_write_failure(operation, ticker, e, context)
        if raise_on_error:
            raise DatabaseWriteError(f"Unexpected error in {operation}: {e}") from e
        return False


def get_recent_failures(hours: int = 24, operation: Optional[str] = None) -> list:
    """
    Get recent database write failures

    Args:
        hours: Look back this many hours
        operation: Filter by operation type (optional)

    Returns:
        List of failure records
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(hours=hours)

        query = """
            SELECT
                timestamp, operation, ticker, error_type,
                error_message, alerted
            FROM database_write_failures
            WHERE timestamp >= :cutoff
        """

        if operation:
            query += " AND operation = :operation"

        query += " ORDER BY timestamp DESC"

        params = {'cutoff': cutoff}
        if operation:
            params['operation'] = operation

        result = db.execute(text(query), params)

        failures = []
        for row in result:
            failures.append({
                'timestamp': row[0],
                'operation': row[1],
                'ticker': row[2],
                'error_type': row[3],
                'error_message': row[4],
                'alerted': row[5]
            })

        return failures

    except:
        return []
    finally:
        db.close()


def get_failure_stats(hours: int = 24) -> Dict[str, Any]:
    """Get statistics on database write failures"""
    failures = get_recent_failures(hours=hours)

    if not failures:
        return {
            'total_failures': 0,
            'failure_rate': 0.0,
            'by_operation': {},
            'by_error_type': {},
            'critical_failures': 0
        }

    from collections import Counter

    operations = Counter(f['operation'] for f in failures)
    error_types = Counter(f['error_type'] for f in failures)

    critical_ops = ['deal_update', 'deal_structure_update', 'trust_value_update', 'redemption_update']
    critical_count = sum(1 for f in failures if f['operation'] in critical_ops)

    return {
        'total_failures': len(failures),
        'by_operation': dict(operations),
        'by_error_type': dict(error_types),
        'critical_failures': critical_count,
        'recent_failures': failures[:10]  # Last 10
    }


# Health check function for monitoring
def database_write_health_check() -> Dict[str, Any]:
    """
    Check database write health - used by monitoring systems

    Returns:
        Dict with health status and metrics
    """
    stats = get_failure_stats(hours=1)  # Last hour

    # Determine health status
    if stats['total_failures'] == 0:
        status = 'HEALTHY'
    elif stats['critical_failures'] == 0:
        status = 'WARNING'
    else:
        status = 'CRITICAL'

    return {
        'status': status,
        'failures_last_hour': stats['total_failures'],
        'critical_failures_last_hour': stats['critical_failures'],
        'details': stats
    }


if __name__ == '__main__':
    # Test/demo
    print("Database Write Failure Monitor\n")

    print("Recent failures (last 24 hours):")
    failures = get_recent_failures(hours=24)
    if failures:
        for f in failures[:10]:
            print(f"  {f['timestamp']} - {f['operation']} ({f['ticker'] or 'N/A'}): {f['error_type']}")
    else:
        print("  ✅ No failures recorded")

    print("\nFailure statistics:")
    stats = get_failure_stats(hours=24)
    print(f"  Total: {stats['total_failures']}")
    print(f"  Critical: {stats['critical_failures']}")
    if stats['by_operation']:
        print("  By operation:")
        for op, count in stats['by_operation'].items():
            print(f"    - {op}: {count}")

    print("\nHealth check:")
    health = database_write_health_check()
    print(f"  Status: {health['status']}")
    print(f"  Failures (last hour): {health['failures_last_hour']}")
