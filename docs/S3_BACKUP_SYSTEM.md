# S3 Database Backup System

## Overview

Automated daily backups of the PostgreSQL database to AWS S3 for durability, disaster recovery, and deployment to new servers.

## S3 Bucket Configuration

**Bucket Name**: `spac-research-db-backups`
**Region**: `us-east-1`
**Features**:
- ✓ Versioning enabled (keeps multiple versions of each backup)
- ✓ Server-side encryption (AES256)
- ✓ Private access (no public access)
- ✓ Lifecycle policy: Old backups automatically archived to Glacier after 30 days

## Backup Schedule

**Frequency**: Daily at 2:00 AM UTC
**Retention**:
- Local: 7 days (then deleted)
- S3 Standard: 30 days
- S3 Glacier: 335 days (archives old backups)
- Total retention: 365 days (1 year)

**Cron Job**:
```bash
0 2 * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/backup_to_s3_python.py >> /home/ubuntu/spac-research/logs/backup.log 2>&1
```

## Backup Process

1. **PostgreSQL Dump**: `pg_dump` creates SQL file (~3.6 MB)
2. **Compression**: gzip reduces to ~0.7 MB (81% reduction)
3. **S3 Upload**: boto3 uploads with AES256 encryption
4. **Local Cleanup**: Deletes backups older than 7 days
5. **Logging**: Records success/failure to `logs/backup.log`

## Manual Backup

Run anytime (doesn't wait for cron):
```bash
/home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/backup_to_s3_python.py
```

Output:
```
🗄️  Starting database backup...
   Database: spac_db
   Time: 2025-10-27 16:59:52
📤 Creating database dump...
✓ Database dump created: 3.6 MB
📦 Compressing backup...
✓ Compressed: 0.7 MB (81% reduction)
☁️  Uploading to S3...
✅ Backup uploaded to S3: s3://spac-research-db-backups/daily/spac_db_20251027_165952.sql.gz
🧹 Cleaning up old local backups...
✅ Backup complete!
```

## View Available Backups

**Using Python**:
```bash
python3 -c "import boto3; s3=boto3.client('s3'); objects=s3.list_objects_v2(Bucket='spac-research-db-backups', Prefix='daily/')['Contents']; [print(f\"{obj['Key']} - {obj['Size']/1024/1024:.1f} MB - {obj['LastModified']}\") for obj in objects]"
```

**Using AWS CLI** (if fixed):
```bash
aws s3 ls s3://spac-research-db-backups/daily/ | tail -20
```

## Restore from Backup

### Method 1: Using Restore Script

```bash
# List recent backups
python3 -c "import boto3; s3=boto3.client('s3'); objects=s3.list_objects_v2(Bucket='spac-research-db-backups', Prefix='daily/')['Contents']; [print(obj['Key'].replace('daily/', '')) for obj in objects[-10:]]"

# Restore (replace with actual filename)
/home/ubuntu/spac-research/restore_from_s3.sh spac_db_20251027_165952.sql.gz
```

**⚠️ WARNING**: This will DROP and recreate the database!

### Method 2: Manual Python Restore

```python
import boto3
import gzip
import subprocess
from pathlib import Path

# Download backup
s3_client = boto3.client('s3')
bucket = 'spac-research-db-backups'
key = 'daily/spac_db_20251027_165952.sql.gz'
local_file = '/home/ubuntu/spac-research/backups/restore.sql.gz'

print("Downloading backup from S3...")
s3_client.download_file(bucket, key, local_file)

# Decompress
print("Decompressing...")
with gzip.open(local_file, 'rb') as f_in:
    with open('/home/ubuntu/spac-research/backups/restore.sql', 'wb') as f_out:
        f_out.write(f_in.read())

# Restore (CAUTION: drops database!)
print("Restoring database...")
subprocess.run(['dropdb', '-U', 'spac_user', 'spac_db'], env={'PGPASSWORD': 'spacpass123'})
subprocess.run(['createdb', '-U', 'spac_user', 'spac_db'], env={'PGPASSWORD': 'spacpass123'})
subprocess.run(['psql', '-U', 'spac_user', '-d', 'spac_db', '-f', '/home/ubuntu/spac-research/backups/restore.sql'], env={'PGPASSWORD': 'spacpass123'})

print("✅ Restore complete!")
```

## Deploy to New Server

When deploying the SPAC platform to a new EC2 instance:

1. **Clone code from GitHub**:
```bash
git clone https://github.com/medxprts/Spacs.git /home/ubuntu/spac-research
cd /home/ubuntu/spac-research
```

2. **Install dependencies**:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. **Setup PostgreSQL**:
```bash
sudo apt install postgresql postgresql-contrib
sudo -u postgres createdb spac_db
sudo -u postgres psql -c "CREATE USER spac_user WITH PASSWORD 'spacpass123';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE spac_db TO spac_user;"
```

4. **Configure AWS credentials**:
```bash
aws configure
# Enter access key, secret key, region (us-east-1)
```

5. **Restore latest backup**:
```bash
# List backups
python3 -c "import boto3; s3=boto3.client('s3'); objects=s3.list_objects_v2(Bucket='spac-research-db-backups', Prefix='daily/')['Contents']; print('Latest backup:', objects[-1]['Key'])"

# Download and restore
python3 -c "
import boto3, gzip, subprocess
s3 = boto3.client('s3')
s3.download_file('spac-research-db-backups', 'daily/spac_db_LATEST.sql.gz', 'restore.sql.gz')
with gzip.open('restore.sql.gz') as f_in:
    with open('restore.sql', 'wb') as f_out:
        f_out.write(f_in.read())
subprocess.run(['psql', '-U', 'spac_user', '-d', 'spac_db', '-f', 'restore.sql'], env={'PGPASSWORD': 'spacpass123'})
print('✅ Database restored')
"
```

6. **Setup .env file**:
```bash
cp .env.example .env
# Edit .env with API keys
```

7. **Setup cron jobs**:
```bash
crontab -e
# Copy cron jobs from old server
```

8. **Start services**:
```bash
sudo systemctl start orchestrator
sudo systemctl start streamlit
```

## Cost Estimation

**S3 Storage Costs** (us-east-1):
- Standard (30 days): 0.7 MB × 30 = 21 MB × $0.023/GB = **$0.0005/month**
- Glacier (335 days): 0.7 MB × 335 = 235 MB × $0.004/GB = **$0.001/month**
- **Total: ~$0.002/month** (essentially free!)

**S3 Transfer Costs**:
- Upload: Free
- Download (restore): $0.09/GB (0.7 MB = **$0.00006 per restore**)

**Total Monthly Cost**: Less than $0.01/month

## Monitoring

**Check backup log**:
```bash
tail -f /home/ubuntu/spac-research/logs/backup.log
```

**Recent backup status**:
```bash
grep "Backup successful" /home/ubuntu/spac-research/logs/backup.log | tail -5
```

**Verify backup completed today**:
```bash
python3 -c "
import boto3
from datetime import datetime, timedelta
s3 = boto3.client('s3')
objects = s3.list_objects_v2(Bucket='spac-research-db-backups', Prefix='daily/')['Contents']
latest = max(objects, key=lambda x: x['LastModified'])
age = datetime.now(latest['LastModified'].tzinfo) - latest['LastModified']
print(f\"Latest backup: {latest['Key']}\")
print(f\"Age: {age.total_seconds()/3600:.1f} hours ago\")
if age.total_seconds() > 86400:
    print('⚠️  WARNING: Backup is more than 24 hours old!')
else:
    print('✅ Backup is fresh')
"
```

## Troubleshooting

### Backup fails with "access denied"
- Check AWS credentials: `aws sts get-caller-identity`
- Verify S3 bucket permissions

### Backup log shows errors
- Check disk space: `df -h`
- Check PostgreSQL is running: `sudo systemctl status postgresql`
- Test pg_dump manually: `PGPASSWORD=spacpass123 pg_dump -U spac_user -d spac_db > test.sql`

### Restore fails
- Verify backup file exists in S3
- Check PostgreSQL service is running
- Ensure spac_user has CREATE DATABASE privileges

## Security Notes

- ✓ S3 bucket is private (no public access)
- ✓ Backups encrypted at rest (AES256)
- ✓ AWS credentials stored securely in `~/.aws/credentials`
- ✓ Database password in `.env` (not in Git)
- ✗ Backups NOT encrypted in transit (use VPC endpoint for extra security)

## Files

**Backup scripts**:
- `backup_to_s3_python.py` - Main backup script (uses boto3)
- `backup_to_s3.sh` - Bash version (AWS CLI, has version conflicts)

**Restore scripts**:
- `restore_from_s3.sh` - Interactive restore script

**Setup**:
- `setup_s3_backups.py` - One-time S3 bucket creation script

**Logs**:
- `logs/backup.log` - Backup history and errors

**Documentation**:
- `docs/S3_BACKUP_SYSTEM.md` - This file

## References

- AWS S3 Pricing: https://aws.amazon.com/s3/pricing/
- PostgreSQL pg_dump: https://www.postgresql.org/docs/current/app-pgdump.html
- boto3 S3 Documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3.html
