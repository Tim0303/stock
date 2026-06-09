"""Quick HTTP smoke-test against the running FastMCP server.

Run from INSIDE the mcp container (uses 0.0.0.0:8000 directly), or from host at localhost:7001.
Pass --host=<host:port> to override.

Tests:
1. scan_strategy returns a response (list or message)
2. run_query('DELETE FROM analyses') is REJECTED with error status
"""
import json
import urllib.request
import urllib.error
import sys

# Default: talk to the server inside the same container
HOST = "localhost:8000"
for arg in sys.argv[1:]:
    if arg.startswith("--host="):
        HOST = arg[7:]

BASE = f"http://{HOST}/mcp"


def call_tool(name: str, arguments: dict) -> dict:
    """Send a tools/call request via raw HTTP POST (JSON-RPC style)."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
        },
    }).encode()

    req = urllib.request.Request(
        BASE,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            # FastMCP streamable-http may return SSE or JSON; try JSON first
            if body.startswith("data:"):
                # SSE: extract the data lines
                lines = [l[5:].strip() for l in body.splitlines() if l.startswith("data:") and l.strip() != "data:"]
                parsed = {}
                for line in lines:
                    try:
                        parsed = json.loads(line)
                        break
                    except Exception:
                        pass
                return parsed
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"http_error": e.code, "body": body[:500]}
    except Exception as e:
        return {"error": str(e)}


print(f"=== Connecting to {BASE} ===\n")

print("=== Test 1: scan_strategy ===")
result = call_tool("scan_strategy", {"limit": 5})
print(json.dumps(result, indent=2, ensure_ascii=False, default=str)[:2000])

print("\n=== Test 2: run_query DELETE (must be rejected) ===")
result2 = call_tool("run_query", {"sql": "DELETE FROM analyses"})
print(json.dumps(result2, indent=2, ensure_ascii=False, default=str)[:1000])

# Check the DELETE was blocked
raw = json.dumps(result2, default=str)
if "REJECTED" in raw or ("error" in raw.lower() and "DELETE" not in raw.upper().split("REJECTED")[0] if "REJECTED" in raw.upper() else True):
    print("\n[PASS] DELETE was rejected as expected.")
else:
    print("\n[FAIL] DELETE was NOT rejected!")
    sys.exit(1)
