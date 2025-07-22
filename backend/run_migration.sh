#!/bin/bash
# Quick migration script to add delivery_analytics column

echo "Running migration to add delivery_analytics column..."

docker exec shopify_api python -c "
import sys
from sqlalchemy import create_engine, text
from database import DATABASE_URL

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    try:
        # Check if column exists
        result = conn.execute(text(\"\"\"
            SELECT COUNT(*) 
            FROM pragma_table_info('fraud_analyses') 
            WHERE name='delivery_analytics'
        \"\"\"))
        
        if result.scalar() > 0:
            print('✅ Column delivery_analytics already exists')
        else:
            # Add the column
            conn.execute(text(\"\"\"
                ALTER TABLE fraud_analyses 
                ADD COLUMN delivery_analytics JSON
            \"\"\"))
            conn.commit()
            print('✅ Successfully added delivery_analytics column')
    except Exception as e:
        print(f'❌ Error: {e}')
"

echo "Migration complete!"