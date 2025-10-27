#!/usr/bin/env python3
"""
Shared Telegram notification utility with automatic message chunking

Telegram has a 4096 character limit per message.
This utility automatically splits long messages into multiple messages.
"""

import os
import time
from typing import Optional


def send_telegram_alert(message: str, parse_mode: str = "HTML") -> bool:
    """
    Send Telegram alert with automatic chunking for long messages

    Args:
        message: Message to send (will be automatically split if >4000 chars)
        parse_mode: Telegram parse mode ("HTML" or "Markdown")

    Returns:
        True if message(s) sent successfully, False otherwise

    Features:
        - Automatically splits messages at 4000 chars (leaving safety margin)
        - Splits on newlines to avoid breaking in middle of content
        - Adds "Part X/Y" headers for multi-part messages
        - Rate limits between messages (0.5s delay)
    """
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  ⚠️  Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing)")
        return False

    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        MAX_LENGTH = 4000  # Leave margin for safety (Telegram limit is 4096)

        # If message fits, send as single message
        if len(message) <= MAX_LENGTH:
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": parse_mode
            }
            response = requests.post(url, data=data, timeout=10)

            if response.status_code == 200:
                print("  ✓ Telegram alert sent")
                return True
            else:
                print(f"  ⚠️  Telegram failed: {response.status_code} - {response.text}")
                return False

        # Message too long - split into chunks
        print(f"  📱 Message too long ({len(message)} chars), splitting into chunks...")

        # Split on newlines to avoid breaking in middle of issue
        lines = message.split('\n')
        chunks = []
        current_chunk = ""

        for line in lines:
            # If adding this line would exceed limit, start new chunk
            if len(current_chunk) + len(line) + 1 > MAX_LENGTH:
                if current_chunk:
                    chunks.append(current_chunk)

                # Handle case where single line is too long
                if len(line) > MAX_LENGTH:
                    # Split long line into smaller pieces
                    for i in range(0, len(line), MAX_LENGTH):
                        chunks.append(line[i:i+MAX_LENGTH])
                    current_chunk = ""
                else:
                    current_chunk = line
            else:
                if current_chunk:
                    current_chunk += '\n' + line
                else:
                    current_chunk = line

        # Add last chunk
        if current_chunk:
            chunks.append(current_chunk)

        # Send each chunk
        success = True
        for i, chunk in enumerate(chunks, 1):
            # Add part indicator for multi-part messages
            if len(chunks) > 1:
                if parse_mode == "HTML":
                    header = f"📊 <b>Message (Part {i}/{len(chunks)})</b>\n\n"
                else:
                    header = f"📊 **Message (Part {i}/{len(chunks)})**\n\n"
            else:
                header = ""

            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": header + chunk,
                "parse_mode": parse_mode
            }

            response = requests.post(url, data=data, timeout=10)

            if response.status_code == 200:
                print(f"  ✓ Telegram alert sent (part {i}/{len(chunks)})")
            else:
                print(f"  ⚠️  Telegram failed (part {i}/{len(chunks)}): {response.status_code}")
                success = False

            # Small delay between messages to avoid rate limiting
            if i < len(chunks):
                time.sleep(0.5)

        return success

    except Exception as e:
        print(f"  ⚠️  Telegram error: {e}")
        return False


def send_telegram_message_simple(message: str, parse_mode: str = "HTML") -> bool:
    """
    Simple telegram send without chunking (for short messages only)

    Use send_telegram_alert() instead for automatic chunking.
    This is kept for backwards compatibility only.
    """
    return send_telegram_alert(message, parse_mode)


if __name__ == "__main__":
    # Test message splitting
    print("Testing Telegram message chunking...")

    # Test 1: Short message
    print("\n1. Testing short message:")
    send_telegram_alert("🧪 Test: Short message works fine")

    # Test 2: Long message
    print("\n2. Testing long message (should split into chunks):")
    long_message = "🧪 Test: Long message\n\n" + "\n".join([f"Line {i}: " + "x" * 100 for i in range(50)])
    send_telegram_alert(long_message)

    print("\n✅ Test complete")
