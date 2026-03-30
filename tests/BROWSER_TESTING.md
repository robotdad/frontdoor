# Browser Testing Guide

Browser tests verify the full user experience of frontdoor by controlling a real browser. They complement static-analysis tests by exercising JavaScript rendering, CSS visual states, and real HTTP interactions that cannot be captured by reading source files as text.

## When to Use Browser Tests

Use browser tests when you need to verify:

- **Rendered UI behavior** — Does the login form actually submit? Does the service dashboard display correctly after auth?
- **JavaScript interactions** — Preact component rendering, HTM template evaluation, dynamic state updates.
- **Authentication flows** — The complete login → redirect → dashboard cycle through a live server.
- **Visual regressions** — Catching layout breaks that are invisible to backend tests.
- **End-to-end smoke checks** — Confirming a fresh deployment is serving the app correctly.

Do **not** write browser tests for:

- Config parsing or Python logic — use `pytest` unit tests instead.
- Presence of patterns in source files — use static-analysis tests (read file as text, `assert pattern in content`) instead.
- Anything resolvable from the API alone — use `httpx` tests via `TestClient` instead.

## Prerequisites

1. **Dev server must be running on port 58080.**

   ```bash
   cd frontdoor
   uv run uvicorn frontdoor.main:app --reload --host 127.0.0.1 --port 58080
   ```

2. **Amplifier with browser testing agents available** (browser-tester bundle or playwright skill).

3. **A valid test user** — PAM authentication is real; use a Linux system user that exists on the dev host, or run with `FRONTDOOR_SECRET_KEY` set and a pre-issued session cookie.

## Running Browser Test Scenarios

Browser tests in this project are expressed as **plain-English descriptions** delegated to the Amplifier browser testing agents (`browser-tester:browser-operator` or the `playwright` skill). They are not `pytest` test functions.

### Via Amplifier browser-operator agent

```
Delegate to browser-tester:browser-operator:

"Navigate to http://127.0.0.1:58080/login.
 Verify the page title is 'frontdoor'.
 Fill username='<testuser>' and password='<testpass>'.
 Click the Sign In button.
 Verify you are redirected to the dashboard at /.
 Verify at least one service card is visible."
```

### Via playwright skill

Load the `playwright` skill and follow its guidance for headless browser automation. Target `http://127.0.0.1:58080`.

## The Baseline-Before / Verify-After Pattern

Before making any UI change, capture a baseline screenshot or DOM snapshot. After the change, run the same scenario and compare.

**Step 1: Capture baseline**
```
Delegate to browser-tester:browser-operator:
"Take a screenshot of http://127.0.0.1:58080/login and save it as baseline-login.png."
```

**Step 2: Make your change** (edit HTML, CSS, or Python).

**Step 3: Verify against baseline**
```
Delegate to browser-tester:browser-operator:
"Take a screenshot of http://127.0.0.1:58080/login and save it as after-login.png.
 Compare it to baseline-login.png and report any visual differences."
```

This prevents silent regressions where a change that looks unrelated breaks the rendered output.

## Writing New Test Scenarios

Test scenarios are plain-English descriptions, not code. Write them as ordered instructions:

1. **Start from a known state** — specify the URL and any required auth state.
2. **Describe actions** — click, fill, navigate, wait.
3. **Assert outcomes** — what should be visible, what URL should be shown, what text should appear.

### Example: Login flow

```
Navigate to http://127.0.0.1:58080/.
Verify you are redirected to /login (because no session cookie is present).
Fill the username field with 'testuser'.
Fill the password field with 'testpass'.
Click the 'Sign In' button.
Verify the page navigates to /.
Verify the heading 'Services' is visible on the dashboard.
```

### Example: Service discovery

```
Log in to http://127.0.0.1:58080 as 'testuser'.
Navigate to /.
Verify at least one service card is rendered in the grid.
Each card should show a service name and a link.
```

### Example: Logout

```
Log in to http://127.0.0.1:58080 as 'testuser'.
Click the sign-out button or link.
Verify you are redirected to /login.
Verify the dashboard is no longer accessible without re-authenticating.
```

Add new scenarios to this file as plain-English blocks. When delegating, paste the block directly into the agent instruction.

## Comparison: Static-Analysis Tests vs Browser Tests

| Dimension | Static-Analysis Tests (`pytest`) | Browser Tests (Amplifier agents) |
|-----------|----------------------------------|----------------------------------|
| **What is tested** | Source file contents — patterns, structure, docs | Rendered UI — visible behavior, interactions |
| **Execution speed** | Fast (milliseconds) | Slow (seconds per action) |
| **Requires running server** | No | Yes (port 58080) |
| **Catches JS rendering bugs** | No | Yes |
| **Catches auth flow bugs** | Partial (via `TestClient`) | Yes (full browser round-trip) |
| **Catches layout/CSS regressions** | No | Yes (via screenshots) |
| **Reproducible in CI without browser** | Yes | Requires headless browser |
| **Good for** | Convention enforcement, structure validation | UX smoke checks, visual regression |
| **Examples in this project** | `test_index_html.py`, `test_login_html.py` | Scenarios in this file |

Both layers are complementary. Static-analysis tests are fast, always-on guards; browser tests are slower validation passes used when visual behavior or full auth flows must be confirmed.
