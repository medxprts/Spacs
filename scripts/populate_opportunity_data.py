#!/usr/bin/env python3
"""
Populate Opportunity Agent Data
Runs all data population scripts with completeness checks and issue reporting

Steps:
1. Normalize sponsor names
2. Calculate public float
3. Classify sectors (using existing sector_classifier.py)
4. Report data completeness

Each step reports:
- Success count
- Missing data count
- Issues found
- Recommended next steps
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from sqlalchemy import text
import re
from datetime import datetime


class OpportunityDataPopulator:
    """Populate opportunity agent data with completeness checks"""

    def __init__(self):
        self.db = SessionLocal()
        self.report = {
            'sponsor_normalization': {},
            'public_float': {},
            'sector_classification': {},
            'issues': []
        }

    def close(self):
        self.db.close()

    # ========================================================================
    # STEP 1: NORMALIZE SPONSOR NAMES
    # ========================================================================

    def normalize_sponsor_names(self, commit=False):
        """
        Normalize sponsor names for grouping

        Examples:
        - "Klein Sponsor II LLC" → "Klein Sponsor"
        - "Cantor EP Holdings IV, LLC" → "Cantor EP Holdings"
        - "GSR III Sponsor LLC" → "GSR Sponsor"
        """
        print("\n" + "="*80)
        print("STEP 1: NORMALIZE SPONSOR NAMES")
        print("="*80)

        spacs = self.db.query(SPAC).all()

        normalized_count = 0
        missing_sponsor = 0
        normalization_map = {}

        for spac in spacs:
            if not spac.sponsor:
                missing_sponsor += 1
                continue

            # Normalize sponsor name
            normalized = self._normalize_sponsor_name(spac.sponsor)

            if normalized != spac.sponsor:
                normalization_map[spac.sponsor] = normalized

            spac.sponsor_normalized = normalized
            normalized_count += 1

        # Report
        print(f"\nResults:")
        print(f"  Total SPACs: {len(spacs)}")
        print(f"  ✅ Normalized: {normalized_count}")
        print(f"  ⚠️  Missing sponsor: {missing_sponsor}")

        if normalization_map:
            print(f"\nSample normalizations:")
            for i, (original, normalized) in enumerate(list(normalization_map.items())[:10], 1):
                print(f"  {i}. '{original}' → '{normalized}'")

        # Check for grouping effectiveness
        # Count from our normalization_map (before database commit)
        unique_original = len(set(s.sponsor for s in spacs if s.sponsor))
        # Get unique normalized values from the SPACs we just updated
        normalized_values = [s.sponsor_normalized for s in spacs if s.sponsor_normalized]
        unique_normalized = len(set(normalized_values))
        reduction = unique_original - unique_normalized

        print(f"\nGrouping effectiveness:")
        print(f"  Original unique sponsors: {unique_original}")
        print(f"  Normalized unique sponsors: {unique_normalized}")
        print(f"  ✅ Grouped {reduction} sponsor families")

        if commit:
            self.db.commit()
            print(f"\n✅ Committed sponsor normalizations to database")
        else:
            self.db.rollback()
            print(f"\nℹ️  DRY RUN - Use --commit to save changes")

        self.report['sponsor_normalization'] = {
            'total': len(spacs),
            'normalized': normalized_count,
            'missing': missing_sponsor,
            'reduction': reduction
        }

        # Issues
        if missing_sponsor > 0:
            self.report['issues'].append({
                'category': 'sponsor',
                'severity': 'MEDIUM',
                'count': missing_sponsor,
                'message': f'{missing_sponsor} SPACs missing sponsor name',
                'action': 'Review and populate sponsor from SEC filings'
            })

    def _normalize_sponsor_name(self, sponsor_name: str) -> str:
        """Normalize a sponsor name"""
        if not sponsor_name:
            return None

        normalized = sponsor_name

        # Remove Roman numerals ANYWHERE in the name (not just at end)
        # Examples: "Churchill Sponsor IX LLC" → "Churchill Sponsor"
        #           "Gores Sponsor X LLC" → "Gores Sponsor"
        #           "Live Oak Sponsor V, LLC" → "Live Oak Sponsor"
        patterns = [
            r'\s+(II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\s*',  # Roman numerals anywhere
            r'\s+(\d+)\s*',  # Arabic numerals (2, 3, 4, etc.)
        ]

        for pattern in patterns:
            normalized = re.sub(pattern, ' ', normalized, flags=re.IGNORECASE)

        # Standardize entity types at end
        normalized = re.sub(r',?\s+(LLC|Corp\.?|Inc\.?|Ltd\.?|Limited|L\.P\.|LP)$', '', normalized, flags=re.IGNORECASE)

        # Clean up extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized

    # ========================================================================
    # STEP 2: CALCULATE PUBLIC FLOAT
    # ========================================================================

    def calculate_public_float(self, commit=False):
        """
        Calculate public float for all SPACs

        Formula: shares_outstanding - founder_shares - private_placement_units

        Fallback for founder_shares: 20% of shares_outstanding (standard SPAC structure)
        """
        print("\n" + "="*80)
        print("STEP 2: CALCULATE PUBLIC FLOAT")
        print("="*80)

        spacs = self.db.query(SPAC).all()

        calculated_count = 0
        missing_shares_outstanding = 0
        used_fallback = 0

        for spac in spacs:
            if not spac.shares_outstanding or spac.shares_outstanding <= 0:
                missing_shares_outstanding += 1
                spac.public_float = None
                continue

            # Get founder shares (with fallback)
            if spac.founder_shares and spac.founder_shares > 0:
                founder_shares = spac.founder_shares
            else:
                # Fallback: Standard SPAC structure = 20% founder shares
                founder_shares = spac.shares_outstanding * 0.20
                used_fallback += 1

            # Get private placement units
            pp_units = spac.private_placement_units if spac.private_placement_units else 0

            # Calculate public float
            public_float = spac.shares_outstanding - founder_shares - pp_units

            if public_float > 0:
                spac.public_float = int(public_float)
                calculated_count += 1
            else:
                spac.public_float = None

        # Report
        print(f"\nResults:")
        print(f"  Total SPACs: {len(spacs)}")
        print(f"  ✅ Public float calculated: {calculated_count}")
        print(f"  ⚠️  Used 20% founder fallback: {used_fallback}")
        print(f"  ❌ Missing shares_outstanding: {missing_shares_outstanding}")

        # Show sample calculations
        print(f"\nSample calculations:")
        spacs_with_float = [s for s in spacs if s.public_float][:5]
        for spac in spacs_with_float:
            pct_float = (spac.public_float / spac.shares_outstanding * 100) if spac.shares_outstanding else 0
            print(f"  {spac.ticker}: {spac.public_float:,} shares ({pct_float:.1f}% of {spac.shares_outstanding:,.0f})")

        if commit:
            self.db.commit()
            print(f"\n✅ Committed public float calculations to database")
        else:
            self.db.rollback()
            print(f"\nℹ️  DRY RUN - Use --commit to save changes")

        self.report['public_float'] = {
            'total': len(spacs),
            'calculated': calculated_count,
            'used_fallback': used_fallback,
            'missing_shares': missing_shares_outstanding
        }

        # Issues
        if missing_shares_outstanding > 0:
            self.report['issues'].append({
                'category': 'shares_outstanding',
                'severity': 'HIGH',
                'count': missing_shares_outstanding,
                'message': f'{missing_shares_outstanding} SPACs missing shares_outstanding',
                'action': 'Extract from S-1 or 424B4 filings'
            })

        if used_fallback > calculated_count * 0.5:
            self.report['issues'].append({
                'category': 'founder_shares',
                'severity': 'MEDIUM',
                'count': used_fallback,
                'message': f'{used_fallback} SPACs using 20% founder fallback',
                'action': 'Extract actual founder shares from S-1 filings'
            })

    # ========================================================================
    # STEP 3: RUN SECTOR CLASSIFIER
    # ========================================================================

    def run_sector_classifier(self, commit=False):
        """
        Run sector classifier on all SEARCHING SPACs

        Uses existing sector_classifier.py
        """
        print("\n" + "="*80)
        print("STEP 3: SECTOR CLASSIFICATION")
        print("="*80)

        from utils.sector_classifier import SectorClassifier

        # Only classify SEARCHING SPACs (pre-deal)
        searching_spacs = self.db.query(SPAC).filter(SPAC.deal_status == 'SEARCHING').all()

        print(f"\nTotal SEARCHING SPACs: {len(searching_spacs)}")

        # Check how many already classified
        already_classified = sum(1 for s in searching_spacs if s.sector_classified)
        print(f"Already classified: {already_classified}")
        print(f"Need classification: {len(searching_spacs) - already_classified}")

        if not commit:
            print(f"\nℹ️  DRY RUN - Skipping actual classification")
            print(f"   Run with --commit to classify {len(searching_spacs) - already_classified} SPACs")
            return

        # Run classifier
        classifier = SectorClassifier()

        hot_count = 0
        boring_count = 0
        general_count = 0
        errors = 0

        for i, spac in enumerate(searching_spacs, 1):
            if spac.sector_classified:
                continue  # Skip already classified

            print(f"\n[{i}/{len(searching_spacs)}] Classifying {spac.ticker}...")

            try:
                result = classifier.classify_spac(spac.ticker)

                if 'error' not in result:
                    if result['is_hot_sector']:
                        hot_count += 1
                    elif result['sector_classified'] == 'General':
                        general_count += 1
                    else:
                        boring_count += 1
                else:
                    errors += 1
                    print(f"   ⚠️  Error: {result['error']}")

            except Exception as e:
                errors += 1
                print(f"   ❌ Exception: {e}")

            # Rate limiting
            import time
            time.sleep(2)

        classifier.close()

        # Report
        print(f"\n{'='*80}")
        print(f"SECTOR CLASSIFICATION COMPLETE")
        print(f"{'='*80}")
        print(f"Hot sectors: {hot_count}")
        print(f"Boring sectors: {boring_count}")
        print(f"General: {general_count}")
        print(f"Errors: {errors}")

        self.report['sector_classification'] = {
            'total': len(searching_spacs),
            'already_classified': already_classified,
            'hot': hot_count,
            'boring': boring_count,
            'general': general_count,
            'errors': errors
        }

        if errors > 0:
            self.report['issues'].append({
                'category': 'sector_classification',
                'severity': 'LOW',
                'count': errors,
                'message': f'{errors} SPACs failed sector classification',
                'action': 'Review errors and retry failed SPACs'
            })

    # ========================================================================
    # STEP 4: DATA COMPLETENESS REPORT
    # ========================================================================

    def generate_completeness_report(self):
        """Generate comprehensive data completeness report"""
        print("\n" + "="*80)
        print("DATA COMPLETENESS REPORT")
        print("="*80)

        # Query database for completeness metrics
        completeness_query = text("""
            SELECT
                COUNT(*) as total_spacs,
                COUNT(sponsor_normalized) as has_sponsor_normalized,
                COUNT(public_float) as has_public_float,
                COUNT(sector_classified) as has_sector_classified,
                COUNT(promote_vesting_type) as has_promote_vesting,
                COUNT(shares_outstanding) as has_shares_outstanding,
                COUNT(founder_shares) as has_founder_shares,
                COUNT(warrant_ratio) as has_warrant_ratio,
                COUNT(private_placement_units) as has_pp_units,
                COUNT(ipo_date) as has_ipo_date,
                COUNT(deadline_date) as has_deadline_date
            FROM spacs
            WHERE deal_status = 'SEARCHING'
        """)

        result = self.db.execute(completeness_query).fetchone()

        total = result.total_spacs

        print(f"\nSEARCHING SPACs (n={total}):")
        print(f"{'─'*80}")

        fields = [
            ('sponsor_normalized', result.has_sponsor_normalized, 'HIGH'),
            ('public_float', result.has_public_float, 'HIGH'),
            ('sector_classified', result.has_sector_classified, 'HIGH'),
            ('shares_outstanding', result.has_shares_outstanding, 'HIGH'),
            ('ipo_date', result.has_ipo_date, 'MEDIUM'),
            ('deadline_date', result.has_deadline_date, 'MEDIUM'),
            ('founder_shares', result.has_founder_shares, 'MEDIUM'),
            ('warrant_ratio', result.has_warrant_ratio, 'LOW'),
            ('private_placement_units', result.has_pp_units, 'LOW'),
            ('promote_vesting_type', result.has_promote_vesting, 'LOW'),
        ]

        for field, count, priority in fields:
            pct = (count / total * 100) if total > 0 else 0
            status = "✅" if pct >= 90 else "⚠️" if pct >= 50 else "❌"

            print(f"  {status} {field:<25} {count:>3}/{total} ({pct:>5.1f}%)  [{priority}]")

        # Overall completeness score
        core_fields = ['sponsor_normalized', 'public_float', 'sector_classified', 'shares_outstanding']
        core_completeness = sum([getattr(result, f'has_{f}') for f in core_fields]) / (len(core_fields) * total) * 100

        print(f"\n{'─'*80}")
        print(f"Core Data Completeness: {core_completeness:.1f}%")

        if core_completeness >= 90:
            print("✅ EXCELLENT - Ready for Phase 1 scoring")
        elif core_completeness >= 75:
            print("⚠️  GOOD - Can run Phase 1 with some gaps")
        else:
            print("❌ POOR - Need more data before scoring")

        # Issues summary
        if self.report['issues']:
            print(f"\n{'='*80}")
            print(f"ISSUES FOUND ({len(self.report['issues'])})")
            print(f"{'='*80}")

            for i, issue in enumerate(self.report['issues'], 1):
                severity_emoji = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}
                emoji = severity_emoji.get(issue['severity'], '⚪')

                print(f"\n{i}. {emoji} {issue['severity']} - {issue['category']}")
                print(f"   {issue['message']}")
                print(f"   → Action: {issue['action']}")

    # ========================================================================
    # RUN ALL STEPS
    # ========================================================================

    def run_all(self, commit=False):
        """Run all data population steps"""
        print("\n" + "="*80)
        print("OPPORTUNITY DATA POPULATION")
        print("="*80)
        print(f"Mode: {'COMMIT' if commit else 'DRY RUN'}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        self.normalize_sponsor_names(commit=commit)
        self.calculate_public_float(commit=commit)
        self.run_sector_classifier(commit=commit)
        self.generate_completeness_report()

        print(f"\n{'='*80}")
        print(f"POPULATION COMPLETE")
        print(f"{'='*80}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Populate opportunity agent data with completeness checks')
    parser.add_argument('--commit', action='store_true', help='Commit changes to database (default is dry run)')
    parser.add_argument('--step', choices=['sponsors', 'float', 'sectors', 'report', 'all'], default='all',
                        help='Run specific step or all steps')
    args = parser.parse_args()

    populator = OpportunityDataPopulator()

    try:
        if args.step == 'sponsors':
            populator.normalize_sponsor_names(commit=args.commit)
        elif args.step == 'float':
            populator.calculate_public_float(commit=args.commit)
        elif args.step == 'sectors':
            populator.run_sector_classifier(commit=args.commit)
        elif args.step == 'report':
            populator.generate_completeness_report()
        else:
            populator.run_all(commit=args.commit)

    finally:
        populator.close()


if __name__ == '__main__':
    main()
