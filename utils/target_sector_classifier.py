#!/usr/bin/env python3
"""
Target Sector Classifier
========================
Classifies target companies into hot sectors based on company name.

Used as fallback when 8-K filing doesn't explicitly state sector.
"""

import os
from openai import OpenAI


def classify_target_sector(target_name):
    """
    Classify target company into ONE sector based on company name.

    Args:
        target_name: Target company name (e.g., "Xanadu Quantum Technologies Inc.")

    Returns:
        str: Sector classification (max 50 chars)
    """
    if not target_name:
        return None

    # Use DeepSeek for classification
    try:
        client = OpenAI(
            api_key=os.getenv('DEEPSEEK_API_KEY'),
            base_url="https://api.deepseek.com"
        )

        prompt = f"""Classify this target company into ONE sector based on their primary business (infer from company name):

**Hot Sectors (priority - pick these if applicable)**:
- AI & Machine Learning (includes quantum computing, AI chips, ML platforms)
- Healthcare Technology (digital health, biotech with tech focus)
- Electric Vehicles (EVs, EV charging, battery tech)
- FinTech (digital payments, crypto exchanges, blockchain financial services)
- Cybersecurity
- Space Technology
- Clean Energy (solar, wind, nuclear, hydrogen)
- Blockchain & Crypto (pure crypto/blockchain companies)

**Other Sectors**:
- Technology (general software/hardware not in hot categories)
- Healthcare (traditional healthcare, non-tech pharma)
- Financial Services (traditional banking/insurance)
- Consumer (retail, consumer products)
- Industrial (manufacturing, logistics)
- Media & Entertainment
- Real Estate
- Other

Target Company: {target_name}

Return ONLY the sector name, nothing else. Be specific - if it's quantum computing, say "AI & Machine Learning"."""

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )

        sector = response.choices[0].message.content.strip()

        # Truncate if needed (database limit)
        return sector[:50]

    except Exception as e:
        print(f"⚠️  Sector classification failed: {e}")
        return None
