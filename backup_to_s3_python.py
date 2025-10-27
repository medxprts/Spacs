#!/usr/bin/env python3
"""
Database backup to S3 using Python boto3
Avoids AWS CLI version conflicts
"""

import subprocess
import gzip
import boto3
from datetime import datetime
from pathlib import Path
import sys

def backup_database():
    """Create PostgreSQL dump and upload to S3"""

    # Configuration
    bucket_name = 'spac-research-db-backups'
    db_name = 'spac_db'
    db_user = 'spac_user'
    db_password = 'spacpass123'
    backup_dir = Path('/home/ubuntu/spac-research/backups')
    logs_dir = Path('/home/ubuntu/spac-research/logs')

    # Create directories
    backup_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    # Filenames
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    sql_file = backup_dir / f'spac_db_{timestamp}.sql'
    gz_file = backup_dir / f'spac_db_{timestamp}.sql.gz'
    s3_key = f'daily/spac_db_{timestamp}.sql.gz'

    print(f"🗄️  Starting database backup...")
    print(f"   Database: {db_name}")
    print(f"   Time: {datetime.now()}")

    try:
        # 1. Create PostgreSQL dump
        print(f"📤 Creating database dump...")
        env = {'PGPASSWORD': db_password}
        result = subprocess.run(
            ['pg_dump', '-U', db_user, '-d', db_name],
            stdout=open(sql_file, 'w'),
            stderr=subprocess.PIPE,
            env=env,
            text=True
        )

        if result.returncode != 0:
            print(f"❌ Database dump failed: {result.stderr}")
            sys.exit(1)

        size_mb = sql_file.stat().st_size / (1024 * 1024)
        print(f"✓ Database dump created: {sql_file}")
        print(f"   Size: {size_mb:.1f} MB")

        # 2. Compress backup
        print(f"📦 Compressing backup...")
        with open(sql_file, 'rb') as f_in:
            with gzip.open(gz_file, 'wb') as f_out:
                f_out.writelines(f_in)

        compressed_size_mb = gz_file.stat().st_size / (1024 * 1024)
        compression_ratio = (1 - compressed_size_mb / size_mb) * 100
        print(f"✓ Compressed: {compressed_size_mb:.1f} MB ({compression_ratio:.0f}% reduction)")

        # Remove uncompressed file
        sql_file.unlink()

        # 3. Upload to S3
        print(f"☁️  Uploading to S3...")
        s3_client = boto3.client('s3', region_name='us-east-1')

        s3_client.upload_file(
            str(gz_file),
            bucket_name,
            s3_key,
            ExtraArgs={
                'ServerSideEncryption': 'AES256',
                'StorageClass': 'STANDARD'
            }
        )

        print(f"✅ Backup uploaded to S3: s3://{bucket_name}/{s3_key}")

        # 4. Clean up old local backups (keep last 7 days)
        print(f"🧹 Cleaning up old local backups...")
        cutoff_time = datetime.now().timestamp() - (7 * 24 * 60 * 60)
        deleted_count = 0

        for old_file in backup_dir.glob('spac_db_*.sql.gz'):
            if old_file.stat().st_mtime < cutoff_time:
                old_file.unlink()
                deleted_count += 1

        if deleted_count > 0:
            print(f"✓ Cleaned up {deleted_count} old backup(s) (>7 days)")

        # 5. Log success
        log_entry = f"{datetime.now()}: Backup successful - s3://{bucket_name}/{s3_key}\n"
        with open(logs_dir / 'backup.log', 'a') as log_file:
            log_file.write(log_entry)

        print(f"\n✅ Backup complete!")
        print(f"   Local: {gz_file}")
        print(f"   S3: s3://{bucket_name}/{s3_key}")
        print(f"   Size: {compressed_size_mb:.1f} MB")

        return 0

    except Exception as e:
        print(f"❌ Backup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(backup_database())
