# Desktop interim-history projection acceptance

Date: 2026-10-14

The session-history projection fix from Sol was exercised in the current
ROOT checkout at HEAD a0fad3deffdfb39f91454584e100d9ccbb9d9fa7. With the
existing Desktop dist and isolated H-drive profile, both interim-message E2E
cases passed: the default ON case retained interim and final text, and the
OFF case displayed the final response without the interim paragraphs.

The focused Python API regression had already passed 5 tests in Sol's
receipt. The implementation copies history rows for display and blanks
display_content on assistant tool-call rows only when
display.interim_assistant_messages is false. It leaves raw content,
tool calls, tool results, and stored history unchanged. The E2E spec waits
for completion and allows the renderer to settle; it does not explicitly
invoke a user refresh or session-resume action.

The E2E fixture starts a real Desktop backend and a loopback mock inference
server. Its app environment sets HERMES_DESKTOP_HERMES_ROOT to the ROOT
checkout, while HERMES_HOME and Electron user data point to the test sandbox.
The fixture closes the owned Electron application and the mock server. The
outer Playwright Node process exited with code 0 and was absent on a
post-run PID check. The fixture does not emit the Electron child PID or its
creation time to the runner receipt, so no separate OS-level identity record
for that child is claimed.

The R4 run used the restored current E2E spec, not the earlier R3 diagnostic
copy. No build, product change, or test-source change was made for this run.
