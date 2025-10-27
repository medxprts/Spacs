#!/usr/bin/env python3
"""
Error Detection Utility

Decorator to catch and log code errors for investigation by the Investigation Agent.
Integrates with the agentic AI system for autonomous error resolution.
"""

import traceback
import json
from functools import wraps
from datetime import datetime


def detect_errors(script_name=None):
    """
    Decorator to catch errors and log them to code_errors table for investigation

    Usage:
        @detect_errors('sec_data_scraper.py')
        def enrich_spac(ticker):
            ...

    Args:
        script_name: Name of the script (e.g., 'sec_data_scraper.py')
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Import here to avoid circular imports
                from database import SessionLocal, CodeError

                # Extract ticker if available in args/kwargs
                ticker = None
                if args and isinstance(args[0], str) and len(args[0]) <= 10:
                    ticker = args[0]
                elif 'ticker' in kwargs:
                    ticker = kwargs['ticker']

                # Build context
                context = {
                    'args': str(args)[:500],  # Truncate to 500 chars
                    'kwargs': {k: str(v)[:100] for k, v in list(kwargs.items())[:5]},  # First 5 kwargs
                    'timestamp': datetime.now().isoformat()
                }

                # Log error to database
                db = SessionLocal()
                try:
                    error_record = CodeError(
                        error_type=type(e).__name__,
                        error_message=str(e),
                        traceback=traceback.format_exc(),
                        script=script_name or 'unknown',
                        function=func.__name__,
                        ticker=ticker,
                        context=json.dumps(context)
                    )
                    db.add(error_record)
                    db.commit()

                    print(f"\n❌ Error logged for investigation (ID: {error_record.id})")
                    print(f"   Type: {type(e).__name__}")
                    print(f"   Message: {str(e)}")
                    print(f"   Script: {script_name or 'unknown'} → {func.__name__}()")
                    if ticker:
                        print(f"   Ticker: {ticker}")
                    print(f"   🤖 Investigation Agent will analyze this error\n")

                except Exception as log_error:
                    print(f"⚠️  Failed to log error to database: {log_error}")
                finally:
                    db.close()

                # Re-raise so script fails visibly (don't silently swallow errors)
                raise

        return wrapper
    return decorator


def log_manual_error(error_type, error_message, script, function, ticker=None, context=None):
    """
    Manually log an error (for errors caught in try/except blocks)

    Usage:
        try:
            risky_operation()
        except TypeError as e:
            log_manual_error('TypeError', str(e), 'my_script.py', 'my_function', ticker='AEXA')
            # Handle error...
    """
    from database import SessionLocal, CodeError

    db = SessionLocal()
    try:
        error_record = CodeError(
            error_type=error_type,
            error_message=error_message,
            traceback=traceback.format_exc(),
            script=script,
            function=function,
            ticker=ticker,
            context=json.dumps(context) if context else None
        )
        db.add(error_record)
        db.commit()

        print(f"❌ Error logged for investigation (ID: {error_record.id})")
        return error_record.id

    except Exception as e:
        print(f"⚠️  Failed to log error: {e}")
        return None
    finally:
        db.close()
