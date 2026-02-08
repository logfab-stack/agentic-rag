#!/usr/bin/env python3
"""Verify Feature #266 columns in database."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as session:
    result = session.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'audit_embeddings_delete'
        ORDER BY ordinal_position
    """))
    print('Columns in audit_embeddings_delete:')
    for row in result:
        print(f'  {row[0]}: {row[1]}')
