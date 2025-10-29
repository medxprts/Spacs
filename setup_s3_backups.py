#!/usr/bin/env python3
"""
Setup S3 bucket for SPAC database backups

Creates:
- S3 bucket with versioning enabled
- Server-side encryption
- Lifecycle policy (30 days standard, then Glacier)
- Backup script with daily cron job
"""

import boto3
import json
from datetime import datetime

def create_backup_bucket():
    """Create S3 bucket for database backups"""

    s3_client = boto3.client('s3', region_name='us-east-1')
    bucket_name = 'spac-research-db-backups'

    try:
        # Create bucket
        print(f"Creating S3 bucket: {bucket_name}")
        try:
            s3_client.create_bucket(Bucket=bucket_name)
            print(f"✓ Bucket created: {bucket_name}")
        except s3_client.exceptions.BucketAlreadyOwnedByYou:
            print(f"✓ Bucket already exists: {bucket_name}")
        except Exception as e:
            if 'BucketAlreadyExists' in str(e):
                print(f"⚠️  Bucket name '{bucket_name}' is taken globally. Trying with timestamp...")
                bucket_name = f"spac-research-db-backups-{datetime.now().strftime('%Y%m%d')}"
                s3_client.create_bucket(Bucket=bucket_name)
                print(f"✓ Bucket created: {bucket_name}")
            else:
                raise

        # Enable versioning
        print("Enabling versioning...")
        s3_client.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={'Status': 'Enabled'}
        )
        print("✓ Versioning enabled")

        # Enable encryption
        print("Enabling server-side encryption...")
        s3_client.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                'Rules': [{
                    'ApplyServerSideEncryptionByDefault': {
                        'SSEAlgorithm': 'AES256'
                    }
                }]
            }
        )
        print("✓ Encryption enabled (AES256)")

        # Set lifecycle policy (optional: move to Glacier after 30 days)
        print("Setting lifecycle policy...")
        lifecycle_policy = {
            'Rules': [
                {
                    'Id': 'Archive old backups to Glacier',
                    'Status': 'Enabled',
                    'Filter': {'Prefix': 'daily/'},
                    'Transitions': [
                        {
                            'Days': 30,
                            'StorageClass': 'GLACIER'
                        }
                    ],
                    'Expiration': {
                        'Days': 365  # Delete after 1 year
                    }
                }
            ]
        }
        s3_client.put_bucket_lifecycle_configuration(
            Bucket=bucket_name,
            LifecycleConfiguration=lifecycle_policy
        )
        print("✓ Lifecycle policy set (30 days → Glacier, 365 days → Delete)")

        # Block public access (security)
        print("Blocking public access...")
        s3_client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': True,
                'IgnorePublicAcls': True,
                'BlockPublicPolicy': True,
                'RestrictPublicBuckets': True
            }
        )
        print("✓ Public access blocked (private bucket)")

        print(f"\n✅ S3 backup bucket configured successfully!")
        print(f"   Bucket name: {bucket_name}")
        print(f"   Region: us-east-1")
        print(f"   Versioning: Enabled")
        print(f"   Encryption: AES256")
        print(f"   Lifecycle: 30d → Glacier, 365d → Delete")

        return bucket_name

    except Exception as e:
        print(f"❌ Error creating bucket: {e}")
        raise

def create_backup_script(bucket_name):
    """Create automated backup script"""

    backup_script = f"""#!/bin/bash
# Automated PostgreSQL database backup to S3
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

set -e  # Exit on error

BUCKET="{bucket_name}"
DB_NAME="spac_db"
DB_USER="spac_user"
BACKUP_DIR="/home/ubuntu/spac-research/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/spac_db_$DATE.sql"
S3_PATH="s3://$BUCKET/daily/spac_db_$DATE.sql.gz"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "🗄️  Starting database backup..."
echo "   Database: $DB_NAME"
echo "   Time: $(date)"

# Create PostgreSQL dump
export PGPASSWORD=spacpass123
pg_dump -U $DB_USER -d $DB_NAME > "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "✓ Database dump created: $BACKUP_FILE"

    # Get file size
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "   Size: $SIZE"

    # Compress backup
    echo "📦 Compressing backup..."
    gzip "$BACKUP_FILE"
    COMPRESSED_SIZE=$(du -h "$BACKUP_FILE.gz" | cut -f1)
    echo "✓ Compressed: $COMPRESSED_SIZE"

    # Upload to S3
    echo "☁️  Uploading to S3..."
    aws s3 cp "$BACKUP_FILE.gz" "$S3_PATH" --quiet

    if [ $? -eq 0 ]; then
        echo "✅ Backup uploaded to S3: $S3_PATH"

        # Remove local compressed file (keep last 7 days only)
        find "$BACKUP_DIR" -name "spac_db_*.sql.gz" -mtime +7 -delete
        echo "🧹 Cleaned up old local backups (>7 days)"

        # Log success
        echo "$(date): Backup successful - $S3_PATH" >> /home/ubuntu/spac-research/logs/backup.log
    else
        echo "❌ Failed to upload to S3"
        exit 1
    fi
else
    echo "❌ Database dump failed"
    exit 1
fi

echo "✅ Backup complete!"
"""

    # Write backup script
    script_path = '/home/ubuntu/spac-research/backup_to_s3.sh'
    with open(script_path, 'w') as f:
        f.write(backup_script)

    import os
    os.chmod(script_path, 0o755)  # Make executable

    print(f"\n✓ Backup script created: {script_path}")
    return script_path

def create_restore_script(bucket_name):
    """Create restore script"""

    restore_script = f"""#!/bin/bash
# Restore PostgreSQL database from S3 backup
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

set -e

BUCKET="{bucket_name}"
DB_NAME="spac_db"
DB_USER="spac_user"
RESTORE_DIR="/home/ubuntu/spac-research/backups"

# Check if backup file specified
if [ -z "$1" ]; then
    echo "Usage: $0 <backup_file_name>"
    echo ""
    echo "Available backups:"
    aws s3 ls s3://$BUCKET/daily/ | tail -10
    echo ""
    echo "Example: $0 spac_db_20251027_120000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"
S3_PATH="s3://$BUCKET/daily/$BACKUP_FILE"
LOCAL_FILE="$RESTORE_DIR/$BACKUP_FILE"

mkdir -p "$RESTORE_DIR"

echo "🔄 Restoring database from S3 backup..."
echo "   Source: $S3_PATH"
echo "   Database: $DB_NAME"

# Download from S3
echo "📥 Downloading backup from S3..."
aws s3 cp "$S3_PATH" "$LOCAL_FILE"

if [ $? -eq 0 ]; then
    echo "✓ Backup downloaded: $LOCAL_FILE"

    # Decompress
    echo "📦 Decompressing backup..."
    gunzip "$LOCAL_FILE"
    SQL_FILE="${{LOCAL_FILE%.gz}}"

    # Restore to database
    echo "🗄️  Restoring to database..."
    export PGPASSWORD=spacpass123

    # Drop and recreate database (CAREFUL!)
    read -p "⚠️  This will DROP and recreate database '$DB_NAME'. Continue? (yes/no): " confirm
    if [ "$confirm" == "yes" ]; then
        dropdb -U $DB_USER $DB_NAME 2>/dev/null || true
        createdb -U $DB_USER $DB_NAME
        psql -U $DB_USER -d $DB_NAME < "$SQL_FILE"

        if [ $? -eq 0 ]; then
            echo "✅ Database restored successfully!"
            rm "$SQL_FILE"  # Clean up
        else
            echo "❌ Restore failed"
            exit 1
        fi
    else
        echo "❌ Restore cancelled"
        exit 1
    fi
else
    echo "❌ Failed to download backup from S3"
    exit 1
fi
"""

    script_path = '/home/ubuntu/spac-research/restore_from_s3.sh'
    with open(script_path, 'w') as f:
        f.write(restore_script)

    import os
    os.chmod(script_path, 0o755)

    print(f"✓ Restore script created: {script_path}")
    return script_path

if __name__ == '__main__':
    print("=" * 60)
    print("SPAC Research Platform - S3 Backup Setup")
    print("=" * 60)
    print()

    # Create bucket
    bucket_name = create_backup_bucket()

    # Create scripts
    backup_script = create_backup_script(bucket_name)
    restore_script = create_restore_script(bucket_name)

    print("\n" + "=" * 60)
    print("📋 Next Steps:")
    print("=" * 60)
    print(f"1. Test backup manually:")
    print(f"   {backup_script}")
    print()
    print(f"2. Test restore (optional):")
    print(f"   {restore_script} spac_db_20251027_120000.sql.gz")
    print()
    print(f"3. Setup daily cron job:")
    print(f"   crontab -e")
    print(f"   # Add this line:")
    print(f"   0 2 * * * {backup_script} >> /home/ubuntu/spac-research/logs/backup.log 2>&1")
    print()
    print(f"4. View S3 backups:")
    print(f"   aws s3 ls s3://{bucket_name}/daily/")
    print("=" * 60)
