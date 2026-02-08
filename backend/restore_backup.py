#!/usr/bin/env python3
"""
Restore Backup Script for Agentic RAG System (Feature #171)

This script provides a simple CLI interface to restore from backups.

Usage:
    # List available backups
    python restore_backup.py --list

    # Restore from a specific backup
    python restore_backup.py 2026-01-28_15-30-00

    # Restore without files (database only)
    python restore_backup.py 2026-01-28_15-30-00 --no-files

    # Get info about a backup
    python restore_backup.py 2026-01-28_15-30-00 --info

Run this script from the backend directory:
    python restore_backup.py
"""

import sys
import argparse
import logging
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Restore from backup - Agentic RAG System",
        epilog="""
Examples:
  python restore_backup.py --list                    # List all backups
  python restore_backup.py 2026-01-28_15-30-00      # Restore from backup
  python restore_backup.py --list --info             # Show detailed info for all backups
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        'backup_name',
        nargs='?',
        help='Name of the backup to restore (timestamp format: YYYY-MM-DD_HH-MM-SS)'
    )
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all available backups'
    )
    parser.add_argument(
        '--info', '-i',
        action='store_true',
        help='Show detailed info about a backup (or all backups with --list)'
    )
    parser.add_argument(
        '--no-files',
        action='store_true',
        help='Skip file restoration (restore database records only)'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt (dangerous!)'
    )

    args = parser.parse_args()

    from utils.backup import list_backups, restore_backup, get_backup_info

    # List backups
    if args.list:
        backups = list_backups()
        if not backups:
            print("\nNo backups found.")
            print("Backups are stored in: backend/backups/")
            return 0

        print("\n" + "=" * 70)
        print("AVAILABLE BACKUPS")
        print("=" * 70)

        for b in backups:
            print(f"\n  {b['timestamp']}")
            if args.info:
                if 'documents_count' in b:
                    print(f"    Documents: {b['documents_count']}")
                    print(f"    Rows: {b.get('rows_count', 'N/A')}")
                    print(f"    Collections: {b.get('collections_count', 'N/A')}")
                    print(f"    Files: {b.get('files_count', 'N/A')}")
                    print(f"    Size: {b.get('total_file_bytes', 0):,} bytes")
                if 'reason' in b and b['reason']:
                    print(f"    Reason: {b['reason']}")
                if 'created_at' in b:
                    print(f"    Created: {b['created_at']}")
            else:
                if 'documents_count' in b:
                    print(f"    {b['documents_count']} docs, {b.get('files_count', 0)} files")
                if 'reason' in b and b['reason']:
                    print(f"    Reason: {b['reason']}")

        print("\n" + "=" * 70)
        print(f"Total: {len(backups)} backup(s)")
        print("=" * 70)
        return 0

    # Show info for specific backup
    if args.info and args.backup_name:
        info = get_backup_info(args.backup_name)
        if not info:
            print(f"\nBackup not found: {args.backup_name}")
            return 1

        print("\n" + "=" * 70)
        print(f"BACKUP INFO: {args.backup_name}")
        print("=" * 70)
        for key, value in info.items():
            if key != 'path':
                print(f"  {key}: {value}")
        print(f"  path: {info.get('path', 'N/A')}")
        print("=" * 70)
        return 0

    # Restore from backup
    if args.backup_name:
        info = get_backup_info(args.backup_name)
        if not info:
            print(f"\nBackup not found: {args.backup_name}")
            print("\nUse --list to see available backups.")
            return 1

        # Show what will be restored
        print("\n" + "=" * 70)
        print(f"RESTORE FROM BACKUP: {args.backup_name}")
        print("=" * 70)
        print(f"  Documents: {info.get('documents_count', 'N/A')}")
        print(f"  Rows: {info.get('rows_count', 'N/A')}")
        print(f"  Collections: {info.get('collections_count', 'N/A')}")
        print(f"  Files: {info.get('files_count', 'N/A')}")
        if info.get('reason'):
            print(f"  Reason: {info['reason']}")
        print("=" * 70)

        # Warn about data deletion
        print("\n" + "*" * 70)
        print("  WARNING: This will DELETE all existing data!")
        print("  - All current documents will be removed")
        print("  - All current document rows will be removed")
        print("  - All current embeddings will be removed")
        print("  - Files in uploads/ will be replaced")
        print("*" * 70)

        if not args.yes:
            response = input("\n  Proceed with restore? (y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                print("\n  Restore cancelled.")
                return 0

        # Perform restore
        try:
            stats = restore_backup(args.backup_name, restore_files=not args.no_files)
            print("\n" + "=" * 70)
            print("RESTORE COMPLETE")
            print("=" * 70)
            print(f"  Documents restored: {stats['documents_restored']}")
            print(f"  Rows restored: {stats['rows_restored']}")
            print(f"  Collections restored: {stats['collections_restored']}")
            print(f"  Files restored: {stats['files_restored']}")
            if stats.get('errors'):
                print(f"  Errors: {len(stats['errors'])}")
                for err in stats['errors'][:5]:
                    print(f"    - {err}")
            print("=" * 70)

            if stats['documents_restored'] > 0:
                print("\n  NOTE: Document embeddings were NOT restored.")
                print("  You may need to re-process documents to regenerate embeddings.")

            return 0
        except Exception as e:
            print(f"\n  ERROR: Restore failed: {e}")
            return 1

    # No action specified
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
