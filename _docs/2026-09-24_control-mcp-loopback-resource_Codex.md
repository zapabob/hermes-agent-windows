# Local loopback Control MCP resource and Windows timestamp fixture

## Scope

Repository: zapabob/hermes-agent-windows. Predecessor: 27685609cd, recovered integration branch. T03 requires a standard authenticated Streamable HTTP resource usable by local desktop clients without Docker or a second harness. This commit permits explicit loopback HTTP resource audiences while retaining HTTPS for the token issuer and non-loopback resources. It also repairs the remaining Windows EventBridge tests that assumed an immediate file timestamp advance.

The PC-wide implementation prompt and applicable common, start, security, Application Development, LLMOps and Python SOPs were read. The hermes-agent and executing-plans skills and the attached CodeGraph protocol apply. CodeGraph 1.6.0 at the approved local path was used. Before/after receipts are under evidence/codegraph/T03-2768560-*.json.

## RED and GREEN

A signed resource JWT test first produced three behavioural failures because ResourceVerifier rejected http://localhost, 127.0.0.1 and [::1] audiences. The scoped validation now accepts those only with an explicit valid port and non-root path. Six negative resource cases cover remote HTTP hosts, lookalikes, a wrong loopback address, zero/bad ports and user-info confusion. The token audience remains exact, so a signed HTTPS audience does not authenticate to the HTTP resource.

The locked MCP SDK successfully negotiated initialise and read on ASGI test hosts at both http://127.0.0.1:9118 and http://[::1]:9118 with resource-only bearer grants. It did not use a dashboard token. This is a protocol fixture, not a network listener or actual Desktop application connection.

Independent static review found that the ingress previously skipped loopback checks whenever the ASGI scheme was HTTPS, even for a loopback HTTP audience. It also rejected a normal bracketed IPv6 Host. The two behavioural RED assertions returned 200 instead of 403 and 403 instead of 200 respectively. The ingress now binds the actual request scheme to the resource scheme, requires exact authority and loopback peer for HTTP resources, and accepts the bracketed IPv6 authority. A third negative isolates the peer check while scheme and Host match. Boundary tests returned 25 passed; SDK IPv4 and IPv6 integration returned 2 passed. The reviewer re-read the fix and found no remaining material issue in these paths.

The affected regression initially returned 265 passed, 1 skipped, 1 failed. The failure was tests/test_mcp_serve.py::TestEventBridgePollE2E::test_new_conversation_after_baseline_is_delivered and reproduced alone. That fixture and another remaining immediate os.utime fixture assumed Windows had advanced state.db mtime on the same tick. Both now set a later explicit nanosecond timestamp. The two focused EventBridge tests passed; an earlier affected run returned 266 passed, 1 skipped in 22.38s. After the ingress review fix, the final affected command uv run --frozen python -m pytest tests/control_mcp tests/test_mcp_serve.py -q returned 270 passed, 1 skipped in 71.74s. Changed-file Ruff passed.

## Ownership and limits

CodeGraph traced _https_url to ResourceVerifier.__init__, AuthenticatedControlASGI to transport.create_control_mcp, and EventBridge._poll_once to its polling regression tests. After a final three-file sync, the index reported up to date; it also produced a spurious similarly named Desktop symbol in broad ResourceVerifier impact, which was not treated as a call edge. The JWT/Host/peer boundary was checked by direct protocol and HTTP tests because static indexing does not model ASGI dispatch.

Files changed: downstream/control_mcp/auth.py, downstream/control_mcp/http_boundary.py, tests/control_mcp/test_auth.py, tests/control_mcp/test_http_boundary.py, tests/control_mcp/test_mcp_protocol.py, tests/test_mcp_serve.py. No actual account, issuer, local listener, tunnel, Desktop configuration or deployment was changed. Operator-approved issuer/grant configuration and live two-client proof remain open. Write stays disabled. Reverting this logical commit restores the prior HTTPS-only resource rule and older test fixture.
