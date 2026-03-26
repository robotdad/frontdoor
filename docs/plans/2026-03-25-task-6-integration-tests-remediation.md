# Task 6: Integration Tests — Remediation Plan

> **Status:** FLAGGED FOR HUMAN REVIEW — spec review loop exhausted after 3 iterations.

**Goal:** Resolve spec-vs-reality conflict in `test_deep_link_flow` and commit count discrepancy.

---

## What Was Implemented

`TestFullAuthFlow` in `frontdoor/tests/test_auth.py` with 3 tests. All 34 tests pass (0 failures).

| Test | Status | Spec Match |
|------|--------|------------|
| `test_unauthenticated_validate_returns_401` | PASS | Exact match |
| `test_login_then_validate_then_logout` | PASS | Exact match |
| `test_deep_link_flow` | PASS | **Diverges** — see Issue 1 |

---

## Issue 1: Spec vs Production Conflict in `test_deep_link_flow`

### The Conflict

The task spec says:

> POST login with next=https://monad.tail09557f.ts.net:8443/files -> **verify 303 location matches full URL**

But the production code (`frontdoor/routes/auth.py:23-31`) intentionally rejects absolute URLs:

```python
def _safe_next_url(url: str) -> str:
    if url.startswith("/") and not url.startswith("//"):
        return url
    return "/"
```

This security behavior was added in task-3 (commit `0ce67ca`) and is validated by existing tests:
- `test_open_redirect_absolute_url_rejected` — asserts `location == "/"`
- `test_open_redirect_protocol_relative_rejected` — asserts `location == "/"`

**The spec asks the test to verify behavior that would be a security vulnerability.**

### What the Test Actually Does (Current Code)

After commit `e707931`, `test_deep_link_flow` exercises the real production code with no extra patches:
1. GET validate → 401 (unauthenticated)
2. POST login with `next=https://monad.tail09557f.ts.net:8443/files` → 303
3. Assert `location == "/"` (absolute URL correctly sanitized)
4. Extract cookie from `set-cookie` header
5. GET validate → 200 (authenticated)

This tests the real deep link flow as it actually works — absolute external URLs are rejected.

### Spec Review Loop History

| Iteration | What Changed | Verdict |
|-----------|-------------|---------|
| 1 | Added `_safe_next_url` patch to bypass security | NEEDS CHANGES — patch not in spec |
| 2 | Reverted extra changes, kept patch | NEEDS CHANGES — still has patch |
| 3 | Removed patch, asserts real behavior (`location == "/"`) | **Loop exhausted** — verdict was for iteration 2 |

The final fix (commit `e707931`) was never re-reviewed because the loop exhausted at 3 iterations.

### Options for Human Reviewer

**Option A: Accept current test as-is (RECOMMENDED)**
- Test exercises real production behavior with only PAM mocked
- Absolute URL sanitization to `/` is correct security behavior
- The spec's "location matches full URL" contradicts the open redirect protection
- All tests pass

**Option B: Change the deep link test to use a relative path**
- Replace `next=https://monad.tail09557f.ts.net:8443/files` with `next=/files`
- Assert `location == "/files"` — this passes through `_safe_next_url`
- Better matches the "deep link" intent with a safe URL

**Option C: Add trusted_origins to production code**
- Add a config-driven allowlist of trusted absolute URLs
- This is a feature change, not a test fix — scope creep for task-6

---

## Issue 2: Commit Count Discrepancy

### Expected
The acceptance criteria state: "Expected 6 total commits for Phase 2."

### Actual
Phase 2 has 9 commits (from `8f2fe12` to `e707931`):

```
e707931 fix: remove out-of-spec _safe_next_url patch from test_deep_link_flow
6b0fd23 fix: revert extra production changes, patch _safe_next_url in deep link test
a6d6a86 fix: set cookie on client and clear client cookies in integration tests
9a5abcf test: add full auth lifecycle integration tests
5768033 feat: add GET /login, protect /api/services with require_auth
0ce67ca fix: validate next_url to prevent open redirect and use urlencode for failure redirect
4c5d6a4 fix: add Request import and tighten login test assertions
649081f feat: add POST /api/auth/login with PAM, cookie, and next redirect
2112930 feat: add /api/auth/validate and /api/auth/logout endpoints
```

The 6 planned `feat`/`test` commits are present. The 3 extra `fix` commits come from spec review iteration cycles.

### Options for Human Reviewer

**Option A: Squash fix commits into their parent task commits**
- Squash `4c5d6a4` and `0ce67ca` into `649081f` (login task fixes)
- Squash `a6d6a86`, `6b0fd23`, `e707931` into `9a5abcf` (integration test fixes)
- Result: 4 clean commits for Phase 2

**Option B: Accept 9 commits as-is**
- Fix commits document the iterative review process
- History shows what was caught and corrected

---

## Implementation Tasks (if remediation needed)

### Task 1: Fix Deep Link Test URL (Option B from Issue 1)

**Files:**
- Modify: `frontdoor/tests/test_auth.py:387-416`

**Step 1: Update the test to use a relative deep link path**

Replace the current `test_deep_link_flow` method body:

```python
def test_deep_link_flow(self, auth_client):
    """Deep link flow: validate -> 401, login with next -> redirect, validate -> 200."""
    from urllib.parse import urlencode

    # GET validate -> 401
    response = auth_client.get("/api/auth/validate")
    assert response.status_code == 401

    next_url = "/files"

    # POST login with next=/files -> 303 to /files
    login_url = f"/api/auth/login?{urlencode({'next': next_url})}"
    with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
        login_response = auth_client.post(
            login_url,
            data={"username": "testuser", "password": "goodpass"},
        )
    assert login_response.status_code == 303
    assert login_response.headers.get("location") == "/files"

    # Extract cookie from set-cookie header
    set_cookie_header = login_response.headers.get("set-cookie", "")
    cookie_value = set_cookie_header.split("frontdoor_session=")[1].split(";")[0]

    # Set cookie on client
    auth_client.cookies.set("frontdoor_session", cookie_value)

    # GET validate -> 200
    validate_response = auth_client.get("/api/auth/validate")
    assert validate_response.status_code == 200
```

**Step 2: Run tests to verify**

```bash
cd frontdoor && pytest tests/test_auth.py::TestFullAuthFlow -v
```

Expected: 3 passed

**Step 3: Run full suite**

```bash
cd frontdoor && pytest -v
```

Expected: 34+ passed, 0 failed

**Step 4: Commit**

```bash
git add frontdoor/tests/test_auth.py
git commit -m "fix: use relative path in test_deep_link_flow to match production safety check"
```

---

### Task 2: Squash Fix Commits (Option A from Issue 2, if desired)

**This is an interactive rebase — human must perform manually.**

```bash
cd frontdoor
git rebase -i 0f21ed6
```

In the editor, mark `4c5d6a4` and `0ce67ca` as `fixup` under `649081f`, and mark `a6d6a86`, `6b0fd23`, `e707931` as `fixup` under `9a5abcf`.

---

## Decision Required

The human reviewer should decide:

1. **Deep link test**: Accept current behavior (Option A) or change to relative URL (Option B)?
2. **Commit history**: Accept as-is (Option B) or squash (Option A)?

No automated action should be taken until these decisions are made.
