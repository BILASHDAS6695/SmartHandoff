#!/usr/bin/env python3
"""Direct database connection test to verify URL encoding fix."""
import asyncio
import sys
import os

# Set environment
os.environ["PYTHONPATH"] = "."
os.environ["PRIMARY_DATABASE_URL"] = "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"

async def test_db():
    """Test direct asyncpg connection."""
    print("=" * 80)
    print("DATABASE CONNECTION TEST")
    print("=" * 80)
    
    try:
        import asyncpg
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import select, func
        from sqlalchemy.ext.asyncio import AsyncSession
        
        # Test 1: Direct asyncpg
        print("\n1. Testing direct asyncpg connection...")
        conn = await asyncpg.connect(
            host='127.0.0.1',
            port=9432,
            user='postgres',
            password='SmartHandoff@123',  # Note: NOT URL-encoded in asyncpg params
            database='smarthandoff',
            timeout=5
        )
        result = await conn.fetchval('SELECT COUNT(*) FROM patient')
        print(f"   ✓ Direct asyncpg connected! Patient count: {result}")
        await conn.close()
        
        # Test 2: SQLAlchemy with URL-encoded URL
        print("\n2. Testing SQLAlchemy with URL-encoded URL...")
        engine = create_async_engine(
            "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff",
            pool_pre_ping=True,
            echo=False
        )
        
        async with engine.begin() as conn:
            result = await conn.execute(select(func.count()).select_from(__import__('app.models.patient', fromlist=['Patient']).Patient.__table__))
            count = result.scalar()
            print(f"   ✓ SQLAlchemy connected! Patient count: {count}")
        
        print("\n" + "=" * 80)
        print("✅ DATABASE CONNECTION TEST PASSED")
        print("=" * 80)
        print("\nThe database URL encoding fix (@ → %40) is WORKING!")
        print(f"Real patient count in database: {count}")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(test_db())
    sys.exit(exit_code)
