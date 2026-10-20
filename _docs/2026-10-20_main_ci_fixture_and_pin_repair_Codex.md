# Main CI fixture and dependency pin repair — 2026-10-20

The Python job for main 040af4f5525a7f7c35a59677954ea89d291860ef failed in GitHub Actions run 39341633141. The other workflow successes do not qualify this SHA as all green. This repair addresses the 31 distinct failed nodes in 16 files without weakening the Gateway ownership checks.

Four lazy messaging dependency declarations now use aiohttp 3.14.4, matching the existing pyproject extras and uv.lock. No dependency installation or runtime environment change is included. The HTTPS identity unit test now supplies a deterministic monotonic clock: its simulated DNS, TCP and TLS operations consume no time, while its original SNI, certificate and timeout assertions remain intact. Production deadline handling is unchanged.

Thirteen Gateway and CLI test fixtures now use actual persistent run generations, accept the private ownership arguments supplied by production, and supply valid session keys matching real ingress. All 387 original assertion expressions, test names and decorators remain identical. No Gateway, clarify, approval, CLI or process-registry product changes are included in this fixture migration.

Focused Windows evidence contains 148 cases across 13 fresh file processes: 27 behavioral failures before the fixture repair and 148 passes afterward, with no errors or skips. The dependency metadata and TLS selection separately passed all 15 cases. The initial missing-pytest and over-restrictive socket-guard setup attempts are retained separately and excluded from behavioral counts. Tests used the established interpreter, isolated HOME/HERMES_HOME, and scrubbed credentials; no packages were installed.

Local proof is retained under tmp/main-ci-preflight/nash-fixtures-01 and tmp/main-ci-preflight/pins-tls-fix in the isolated main-cicd worktree. The fixture manifest binds 184 evidence files, independently rehashed with zero mismatches. Its receipt SHA256 is f23222338e50be7988e7bf2f895c34a4754cfa11c36b432bcea1b30293c9ad5f. The cloud failure log and before copies are preserved. Local focused passes are not a claim of full Linux CI or runtime acceptance; a new pushed SHA must complete the required workflows successfully before Desktop activation.

The unintegrated R6 native PTY work and all historical qualification limits remain separate. Previously built Desktop candidates remain unchanged and have not been activated by this repair.
