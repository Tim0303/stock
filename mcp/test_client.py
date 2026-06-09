"""
FastMCP client smoke test.
Tests:
  1. scan_strategy — returns candidate list (or 'no candidates' message)
  2. run_query('DELETE FROM analyses') — must return error with REJECTED
  3. run_query('SELECT 1') — must succeed
"""
import asyncio
import json
import sys
from fastmcp import Client


SERVER_URL = "http://localhost:8000/mcp"


async def main():
    passed = 0
    failed = 0

    async with Client(SERVER_URL) as client:
        # ── Test 1: scan_strategy ──────────────────────────────────────────
        print("=== Test 1: scan_strategy (limit=5) ===")
        result = await client.call_tool("scan_strategy", {"limit": 5})
        data = result.data
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str)[:1500])
        print(f"  -> returned {len(data) if isinstance(data, list) else 1} row(s)")
        passed += 1

        # ── Test 2: run_query DELETE (must be rejected) ────────────────────
        print("\n=== Test 2: run_query('DELETE FROM analyses') must be rejected ===")
        result2 = await client.call_tool("run_query", {"sql": "DELETE FROM analyses"})
        data2 = result2.data
        print(json.dumps(data2, indent=2, ensure_ascii=False, default=str))
        if data2.get("status") == "error" and "REJECTED" in data2.get("message", ""):
            print("  -> [PASS] DELETE correctly rejected")
            passed += 1
        else:
            print("  -> [FAIL] DELETE was NOT rejected!")
            failed += 1

        # ── Test 3: run_query SELECT 1 (must succeed) ─────────────────────
        print("\n=== Test 3: run_query('SELECT 1 AS ping') must succeed ===")
        result3 = await client.call_tool("run_query", {"sql": "SELECT 1 AS ping"})
        data3 = result3.data
        print(json.dumps(data3, indent=2, ensure_ascii=False, default=str))
        if data3.get("status") == "ok":
            print("  -> [PASS] SELECT succeeded")
            passed += 1
        else:
            print("  -> [FAIL] SELECT failed unexpectedly")
            failed += 1

    print(f"\n{passed}/{passed+failed} tests passed")
    if failed:
        sys.exit(1)


asyncio.run(main())
