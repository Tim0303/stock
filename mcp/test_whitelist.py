"""Unit tests for run_query whitelist logic - can run without DB."""
import sys
import os
import re

# Replicate _validate_read_only logic inline for isolated testing
_FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE|CALL|DO)\b",
    re.IGNORECASE,
)

def _validate_read_only(sql: str) -> str:
    cleaned = sql.strip()
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise ValueError(f"REJECTED: only SELECT or WITH queries are allowed. Statement starts with: {cleaned[:40]!r}")
    no_comments = re.sub(r"--[^\n]*", " ", cleaned)
    no_comments = re.sub(r"/\*.*?\*/", " ", no_comments, flags=re.DOTALL)
    m = _FORBIDDEN_PATTERN.search(no_comments)
    if m:
        raise ValueError(f"REJECTED: forbidden keyword '{m.group()}' detected.")
    stripped_semi = no_comments.rstrip().rstrip(";").rstrip()
    if ";" in stripped_semi:
        raise ValueError("REJECTED: multiple statements (semicolon) are not allowed.")
    return cleaned


tests = [
    # (sql, should_raise, label)
    ("SELECT * FROM analyses", False, "plain SELECT"),
    ("WITH cte AS (SELECT 1) SELECT * FROM cte", False, "WITH/CTE"),
    ("  select symbol from symbols  ", False, "lowercase select with spaces"),
    ("SELECT * FROM analyses;", False, "trailing semicolon OK"),
    ("DELETE FROM analyses", True, "DELETE blocked"),
    ("INSERT INTO analyses VALUES (1)", True, "INSERT blocked"),
    ("UPDATE analyses SET score=1", True, "UPDATE blocked"),
    ("DROP TABLE analyses", True, "DROP blocked"),
    ("ALTER TABLE analyses ADD COLUMN x INT", True, "ALTER blocked"),
    ("CREATE TABLE foo (id int)", True, "CREATE blocked"),
    ("TRUNCATE analyses", True, "TRUNCATE blocked"),
    ("GRANT ALL ON analyses TO public", True, "GRANT blocked"),
    ("REVOKE ALL ON analyses FROM public", True, "REVOKE blocked"),
    ("COPY analyses TO '/tmp/x.csv'", True, "COPY blocked"),
    ("SELECT 1; DELETE FROM analyses", True, "multi-statement blocked"),
    ("SELECT 1; SELECT 2", True, "multi-statement blocked (two selects)"),
    # Sneaky: keyword in comment should not bypass
    ("SELECT * FROM analyses -- DELETE FROM analyses", False, "keyword in comment is safe"),
]

passed = 0
failed = 0
for sql, should_raise, label in tests:
    try:
        _validate_read_only(sql)
        raised = False
    except ValueError:
        raised = True

    ok = (raised == should_raise)
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"[{status}] {label}")

print(f"\n{passed}/{passed+failed} tests passed")
if failed:
    sys.exit(1)
