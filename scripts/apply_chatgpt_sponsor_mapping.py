#!/usr/bin/env python3
"""
Apply ChatGPT Sponsor Mapping to Database

Uses the comprehensive sponsor family mapping from ChatGPT to normalize all sponsors.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from typing import Dict


# ChatGPT mapping: sponsor -> normalized family name
SPONSOR_MAPPING = {
    "1RT Acquisition Sponsor LLC": "1RT Acquisition",
    "A SPAC III (Holdings) Corp.": "A SPAC Holdings",
    "A SPAC IV (Holdings) Corp.": "A SPAC Holdings",
    "AA Mission Acquisition Sponsor Holdco LLC": "AA Mission",
    "AA Mission Sponsor II": "AA Mission",
    "Agriculture & Natural Solutions Acquisition Sponsor LLC": "Agriculture & Natural Solutions",
    "Aimei Investment Ltd": "Aimei",
    "Aitefund Sponsor LLC": "Aitefund",
    "Alchemy DeepTech Capital LLC": "Alchemy DeepTech",
    "Aldel Investors II LLC": "Aldel Investors",
    "Alfa 24 Limited": "Alfa Acquisition",
    "AlphaVest Holding LP": "AlphaVest",
    "Alphamade Holding LP": "Alphamade",
    "Andretti Sponsor II LLC": "Andretti Acquisition",
    "Archimedes Tech SPAC Partners II Co.": "Archimedes Tech SPAC Partners",
    "Armada Sponsor II LLC": "Armada Acquisition",
    "Artius II Acquisition Partners LLC": "Artius Acquisition",
    "Aurora Beacon LLC": "Aurora Acquisition",
    "BEST SPAC I (Holdings) Corp.": "BEST SPAC Holdings",
    "BTC Development Sponsor LLC": "FTAC / Cohen Family",
    "Bayview Holding LP and Peace Investment Holdings Limited": "Bayview Holdings",
    "Bengochea SPAC Sponsors I LLC": "Bengochea SPAC",
    "Berto Acquisition Sponsor LLC": "Berto Acquisition",
    "Black Hawk Management LLC": "Black Hawk Acquisition",
    "Bleichroeder Sponsor 1 LLC": "Bleichroeder",
    "Blue Jay Investment LLC": "Blue Jay",
    "CSLM Acquisition Sponsor II, Ltd": "CSLM Acquisition",
    "Cantor EP Holdings I, LLC": "Cantor Fitzgerald",
    "Cantor EP Holdings II, LLC": "Cantor Fitzgerald",
    "Cantor EP Holdings III, LLC": "Cantor Fitzgerald",
    "Cantor EP Holdings IV, LLC": "Cantor Fitzgerald",
    "Cantor EP Holdings, LLC": "Cantor Fitzgerald",
    "Cayman Sponsor": "Cayman Acquisition",
    "Centurion Sponsor LP": "Centurion",
    "Chenghe Investment II Limited": "Chenghe Investment",
    "Columbus Acquisition Holdings LLC": "Columbus Acquisition",
    "Copley Acquisition Sponsors, LLC": "Copley Acquisition",
    "Cormorant Asset Management, LP": "Cormorant Asset Management",
    "Crane Harbor Sponsor, LLC": "Crane NXT / Crane Harbor",
    "Createcharm Holdings Ltd and Bowen Holding LP": "Createcharm",
    "DT Cloud Capital Corp.": "DT Cloud",
    "DT Cloud Star Management Limited": "DT Cloud",
    "EQV Ventures Sponsor II LLC": "EQV Ventures",
    "EQV Ventures Sponsor LLC": "EQV Ventures",
    "ESH Sponsor LLC": "ESH Acquisition",
    "Emmis Capital Sponsor LLC": "Emmis Capital",
    "Eric S. Rosenfeld and David D. Sgro": "Eric Rosenfeld SPACs",
    "Eureka Acquisition Corp": "Eureka Acquisition",
    "FACT II Acquisition Parent LLC": "FACT Acquisition",
    "FG Merger Investors II LLC": "FG Merger",
    "FIGX Acquisition Partners LLC": "FIGX Acquisition",
    "Fifth Era Acquisition Sponsor I LLC": "Fifth Era",
    "Four Leaf Sponsor LLC": "Four Leaf Acquisition",
    "GP-Act III Sponsor LLC": "GP-Act Acquisition",
    "GSR III Sponsor LLC": "GSR Acquisition",
    "GSR IV Sponsor LLC": "GSR Acquisition",
    "Galata Acquisition Sponsor II, LLC": "Galata Acquisition",
    "Gesher Acquisition Corp. II": "Gesher Acquisition",
    "GigAcquisitions7 Corp.": "GigCapital Global",
    "GigAcquisitions8 Corp.": "GigCapital Global",
    "Globa Terra Management LLC": "Globa Terra",
    "Graf Global Sponsor LLC": "Graf Acquisition",
    "HC VII Sponsor LLC": "HC Sponsor Holdings",
    "HCM Investor Holdings II, LLC": "HCM Investor Holdings",
    "HCM Investor Holdings III, LLC": "HCM Investor Holdings",
    "HWei Super Speed Co. Ltd.": "HWei Acquisition",
    "Harraden Circle Investments": "Harraden Circle",
    "Haymaker Sponsor IV LLC": "Haymaker Acquisition",
    "Horizon Space Acquisition I Sponsor Corp.": "Horizon Space Acquisition",
    "Horizon Space Acquisition II Sponsor Corp.": "Horizon Space Acquisition",
    "I-B Good Works 4, LLC": "Good Works Acquisition",
    "Indigo Sponsor Group, LLC": "Indigo Acquisition",
    "Inflection Point Holdings III LLC": "Inflection Point Holdings",
    "International SPAC Management Group I LLC": "International SPAC Management",
    "Israel Acquisitions Sponsor LLC": "Israel Acquisitions",
    "Jena Acquisition Sponsor LLC II": "Jena Acquisition",
    "K&F Growth Acquisition Corp. II": "K&F Growth",
    "KVC Sponsor LLC": "Khosla Ventures",
    "Launch One Sponsor LLC": "Launch Acquisition",
    "Launch Two Sponsor LLC": "Launch Acquisition",
    "LightWave Founders LLC": "LightWave Acquisition",
    "Lionheart Sponsor, LLC": "Lionheart Capital",
    "Live Oak Sponsor V, LLC": "Live Oak Acquisition",
    "Lynn Stockwell": "dMY Technology Group",
    "MACRO DREAM Holdings Limited": "Macro Dream",
    "Maywood Sponsor, LLC": "Maywood Acquisition",
    "McKinley Partners LLC": "McKinley Acquisition",
    "Melar Acquisition Sponsor I LLC": "Melar Acquisition",
    "Mountain Lake Acquisition Sponsor LLC": "Mountain Lake",
    "NMP Acquisition Corp. Sponsor LLC": "NMP Acquisition",
    "Nabors Energy Transition Sponsor II LLC": "Nabors Energy Transition",
    "OTG Acquisition Sponsor LLC": "OTG Acquisition",
    "Origin Equity LLC": "Origin Equity",
    "Oyster Enterprises II Acquisition Corp": "Oyster Enterprises",
    "Perceptive Capital Solutions Holdings": "Perceptive Advisors",
    "Perimeter Acquisition Sponsor LLC": "Perimeter Acquisition",
    "Pioneer Acquisition 1 Sponsor Holdco LLC": "Pioneer Acquisition",
    "Plum Partners IV, LLC": "Plum Partners",
    "ProCap Acquisition Sponsor, LLC": "ProCap Acquisition",
    "RJ Healthcare SPAC II, LLC": "RJ Healthcare",
    "Range Capital Acquisition Sponsor II, LLC": "Range Capital",
    "Redone Investment Limited": "Redone Investment",
    "Republic Sponsor 1 LLC": "Republic Capital",
    "Ribbon Investment Company Ltd": "Ribbon Investment",
    "Rice Acquisition Sponsor 3 LLC": "Rice Acquisition",
    "Rithm Acquisition Corp Sponsor LLC": "Rithm Capital",
    "Roman DBDR Acquisition Sponsor II LLC": "Roman DBDR",
    "SIM Sponsor 1 LLC": "SIM Sponsor",
    "SLG SPAC Fund LLC": "SLG SPAC",
    "ST Sponsor II Limited": "ST Sponsor",
    "ST Sponsor Limited": "ST Sponsor",
    "STARRY SEA INVESTMENT LIMITED": "Starry Sea",
    "SilverBox Capital": "SilverBox Engaged",
    "SilverLode Capital LLC": "SilverLode Capital",
    "Social Capital": "Social Capital Hedosophia",
    "Social Capital Hedosophia Holdings": "Social Capital Hedosophia",
    "Soulpower Acquisition Sponsor LLC": "Soulpower Acquisition",
    "Spring Valley Acquisition Sponsor II, LLC": "Spring Valley Acquisition",
    "Stellar V Sponsor LLC": "Stellar Acquisition",
    "StoneBridge Acquisition Sponsor II LLC": "StoneBridge Acquisition",
    "TDAC Partners LLC": "TDAC Partners",
    "TV Partners III, LLC": "TV Partners",
    "Talon Capital Sponsor LLC": "Talon Capital",
    "Tavia Sponsor Pte. Ltd.": "Tavia Sponsor",
    "Thayer Ventures Acquisition Holdings II LLC": "Thayer Ventures",
    "Titan Acquisition Sponsor Holdco LLC": "Titan Acquisition",
    "Trailblazer Sponsor Group, LLC": "Trailblazer Acquisition",
    "Trailblazer Sponsor LLC": "Trailblazer Acquisition",
    "UY Scuti Investments Limited": "UY Scuti",
    "Vendome Acquisition Sponsor I LLC": "Vendome Acquisition",
    "Vine Hill Capital Sponsor I LLC": "Vine Hill Capital",
    "Voyager Acquisition Sponsor Holdco LLC": "Voyager Acquisition",
    "Waldencast Ventures LP": "Waldencast",
    "Wen Sponsor LLC": "Wen Acquisition",
    "Whale Bay International Company Limited": "Whale Bay",
    "Whale Management Corporation": "Whale Management",
    "Whiteowl Holdings LLC": "WhiteOwl",
    "Willow Lane Sponsor, LLC": "Willow Lane",
    "Wuren Fubao Inc.": "Wuren Fubao",
    "Yawei Cao and Cayson Holding LP": "Yawei Cao / Cayson Holding",
    "Yocto Investments LLC": "Yocto Investments",
    "Yorkville Acquisition Sponsor LLC": "Yorkville Acquisition",
    "dMY Squared Sponsor, LLC": "dMY Technology Group",
}


def apply_mapping(commit: bool = False) -> Dict:
    """Apply ChatGPT sponsor mapping to database"""

    db = SessionLocal()

    try:
        spacs = db.query(SPAC).filter(SPAC.sponsor != None).all()

        stats = {
            'total': len(spacs),
            'mapped': 0,
            'already_mapped': 0,
            'no_change': 0,
            'families': {}
        }

        print(f"Applying ChatGPT sponsor mapping to {len(spacs)} SPACs...")
        print("=" * 80)

        for spac in spacs:
            # Check if sponsor in mapping
            if spac.sponsor in SPONSOR_MAPPING:
                new_normalized = SPONSOR_MAPPING[spac.sponsor]
                old_normalized = spac.sponsor_normalized

                if old_normalized != new_normalized:
                    spac.sponsor_normalized = new_normalized
                    stats['mapped'] += 1
                    print(f"  {spac.ticker}: '{spac.sponsor}' → '{new_normalized}'")
                else:
                    stats['already_mapped'] += 1

                # Track family counts
                stats['families'][new_normalized] = stats['families'].get(new_normalized, 0) + 1
            else:
                stats['no_change'] += 1

        # Show statistics
        print(f"\n" + "=" * 80)
        print(f"Results:")
        print(f"  Total SPACs: {stats['total']}")
        print(f"  ✅ Updated mappings: {stats['mapped']}")
        print(f"  ℹ️  Already correct: {stats['already_mapped']}")
        print(f"  ⚠️  No mapping found: {stats['no_change']}")
        print(f"  📊 Unique families: {len(stats['families'])}")

        # Show top 20 families
        print(f"\nTop 20 Sponsor Families:")
        for family, count in sorted(stats['families'].items(), key=lambda x: x[1], reverse=True)[:20]:
            print(f"  {count:2d} SPACs: {family}")

        if commit:
            db.commit()
            print(f"\n✅ Committed sponsor normalizations to database")
        else:
            db.rollback()
            print(f"\nℹ️  DRY RUN - Use --commit to save changes")

        return stats

    finally:
        db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Apply ChatGPT sponsor mapping')
    parser.add_argument('--commit', action='store_true', help='Commit changes to database')
    args = parser.parse_args()

    apply_mapping(commit=args.commit)


if __name__ == '__main__':
    main()
