# Git Workflow for SPAC Research Platform

## Overview

This project uses Git and GitHub for version control. **All code changes must be committed to Git before being considered complete.**

## Repository

- **GitHub URL**: https://github.com/medxprts/spacs
- **Branch**: `main` (default)
- **Workflow**: Commit → Review → Push → Deploy

## Daily Workflow

### 1. Check Current Status
```bash
cd /home/ubuntu/spac-research
git status
```

### 2. Make Changes
Edit code, test locally, verify services work.

### 3. Review Changes
```bash
# See what changed
git diff

# See specific file changes
git diff path/to/file.py

# Check modified files
git status
```

### 4. Stage Changes
```bash
# Stage specific files
git add file1.py file2.py

# Stage all Python files
git add *.py

# Stage everything (be careful!)
git add .

# Stage by directory
git add agents/
```

### 5. Commit with Message
```bash
# Good commit message format:
git commit -m "Add volume spike detection to price monitor agent

- Detect when >5% of float trades in single day
- Trigger Telegram alert and investigation
- Update orchestrator trigger system
- Fixes #42"

# Quick commit for small changes:
git commit -m "Fix typo in data_validator_agent.py"
```

### 6. Push to GitHub
```bash
git push origin main
```

## Commit Message Guidelines

### Format
```
Short summary (50 chars or less)

Detailed explanation (optional):
- Bullet point 1
- Bullet point 2
- References issue #123
```

### Good Examples
```
Add AI fallback for vote date extraction
Fix CEP deal status inconsistency
Increase SEC monitor RSS count from 10 to 40
Document terminated deal workflow
```

### Bad Examples
```
fix bug
changes
update
wip
```

## What to Commit

### ✅ ALWAYS Commit
- Python source code (`.py` files)
- Configuration files (`database.py`, `*.json`)
- Documentation (`.md` files)
- Requirements (`requirements.txt`)
- Scripts (`*.sh`)
- Tests (`test_*.py`)

### ❌ NEVER Commit
- `.env` file (contains API keys and passwords)
- `logs/*.log` (log files)
- `venv/` (virtual environment)
- `__pycache__/` (Python cache)
- `.pyc` files (compiled Python)
- Database dumps with sensitive data
- `.state` files (runtime state)
- Personal notes or test data

## Checking Before Commit

### Security Check
```bash
# Make sure .env is NOT staged
git status | grep .env

# If .env shows up, remove it:
git reset .env
```

### .gitignore Verification
```bash
# Check that sensitive files are ignored
cat .gitignore | grep -E "\.env|\.log|venv"
```

## Branch Strategy (Future)

Currently using `main` branch only. Future strategy:

### Development Workflow
```
main (production) ← merge from dev
  ↑
dev (testing) ← merge from feature branches
  ↑
feature/volume-spike-detection
feature/ai-fallback-voting
fix/cep-deal-status
```

### Creating Feature Branch
```bash
# Create and switch to new branch
git checkout -b feature/my-new-feature

# Work on feature, commit changes
git add .
git commit -m "Add new feature"

# Push branch to GitHub
git push origin feature/my-new-feature

# Later: merge to main via GitHub PR
```

## Common Commands

### View History
```bash
# See recent commits
git log --oneline -10

# See commits for specific file
git log --oneline -- agents/price_monitor_agent.py

# See what changed in last commit
git show HEAD
```

### Undo Changes

#### Before Commit
```bash
# Discard changes to specific file
git checkout -- file.py

# Unstage file (keep changes)
git reset file.py

# Discard ALL uncommitted changes (DANGEROUS!)
git reset --hard HEAD
```

#### After Commit (Local Only)
```bash
# Undo last commit, keep changes
git reset --soft HEAD~1

# Undo last commit, discard changes (DANGEROUS!)
git reset --hard HEAD~1
```

### Stash Changes
```bash
# Save work-in-progress
git stash

# List stashes
git stash list

# Apply stashed changes
git stash pop
```

## GitHub Integration

### Pull Latest Changes
```bash
# Fetch and merge from GitHub
git pull origin main
```

### View Remote Info
```bash
# See remote repository URL
git remote -v

# See remote branches
git branch -r
```

### Create Pull Request (Future)
1. Push feature branch: `git push origin feature/my-feature`
2. Go to GitHub: https://github.com/medxprts/spacs
3. Click "Compare & pull request"
4. Add description, reviewers
5. Click "Create pull request"
6. After approval, merge to main

## Emergency Rollback

### Revert to Previous Commit
```bash
# Find commit hash
git log --oneline

# Revert to specific commit (creates new commit)
git revert abc123

# Force reset to specific commit (DANGEROUS - rewrites history)
git reset --hard abc123
git push --force origin main  # USE WITH CAUTION
```

## Best Practices

### 1. Commit Often
- Small, focused commits are better than large ones
- Commit after each logical change
- Makes debugging easier (git bisect)

### 2. Write Good Messages
- Explain WHY, not just WHAT
- Reference issue numbers
- Use imperative mood ("Add feature" not "Added feature")

### 3. Review Before Push
```bash
# Always review before pushing
git diff origin/main..HEAD
```

### 4. Never Commit Secrets
- Check for API keys before commit
- Use `.env.example` for templates
- Rotate keys if accidentally committed

### 5. Pull Before Push
```bash
# Avoid conflicts
git pull origin main
git push origin main
```

## Integration with Services

### Orchestrator Service
After pushing code changes, restart services:
```bash
sudo systemctl restart orchestrator
sudo systemctl restart streamlit
```

### Database Migrations
When schema changes:
```bash
# Commit migration script
git add database_migrations/add_column_xyz.py
git commit -m "Add migration for new column xyz"
git push origin main

# Then run migration
python3 database_migrations/add_column_xyz.py
```

## Troubleshooting

### "Repository not found"
```bash
# Verify remote URL
git remote -v

# Update remote URL
git remote set-url origin https://github.com/medxprts/spacs.git
```

### "Permission denied"
```bash
# Check Git credentials
cat ~/.git-credentials

# Update credentials
git config --global credential.helper store
git push  # Will prompt for username/token
```

### Merge Conflicts
```bash
# Pull latest
git pull origin main

# If conflicts, edit files to resolve
# Look for <<<<<<< HEAD markers

# After fixing:
git add .
git commit -m "Resolve merge conflicts"
git push origin main
```

### Large Files Warning
```bash
# GitHub has 100MB file limit
# If you accidentally staged large files:
git reset file.log

# Add to .gitignore
echo "large_file.csv" >> .gitignore
```

## Daily Checklist

### End of Development Session
- [ ] Review all changes: `git status`
- [ ] Check no secrets committed: `git diff | grep -i api_key`
- [ ] Stage relevant files: `git add <files>`
- [ ] Write descriptive commit message
- [ ] Commit: `git commit -m "Message"`
- [ ] Push to GitHub: `git push origin main`
- [ ] Verify on GitHub: https://github.com/medxprts/spacs

### Before Starting Work
- [ ] Pull latest: `git pull origin main`
- [ ] Check services: `sudo systemctl status orchestrator`
- [ ] Review recent commits: `git log --oneline -5`

## Resources

- **GitHub Repository**: https://github.com/medxprts/spacs
- **Git Documentation**: https://git-scm.com/doc
- **GitHub Guides**: https://guides.github.com/
- **Git Cheat Sheet**: https://education.github.com/git-cheat-sheet-education.pdf

## Quick Reference

```bash
# Basic workflow
git status                  # Check what changed
git add .                   # Stage everything
git commit -m "Message"     # Commit with message
git push origin main        # Push to GitHub

# Check history
git log --oneline -10       # Last 10 commits
git diff                    # See uncommitted changes
git show abc123             # See specific commit

# Undo
git reset file.py           # Unstage file
git checkout -- file.py     # Discard changes
git revert abc123           # Revert commit

# Remote
git remote -v               # Show remote URL
git pull origin main        # Get latest from GitHub
git push origin main        # Push to GitHub
```

## Support

If you encounter Git issues:
1. Check this document
2. Review Git documentation
3. Search GitHub Issues
4. Ask for help in project Slack/Discord
