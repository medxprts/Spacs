#!/bin/bash
# Restore PostgreSQL database from S3 backup

set -e

BUCKET="spac-research-db-backups"
DB_NAME="spac_db"
DB_USER="spac_user"
RESTORE_DIR="/home/ubuntu/spac-research/backups"

# Check if backup file specified
if [ -z "$1" ]; then
    echo "Usage: $0 <backup_file_name>"
    echo ""
    echo "Available backups (last 10):"
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
    SQL_FILE="${LOCAL_FILE%.gz}"

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
