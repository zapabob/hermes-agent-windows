# CI delivery observation — 2026-10-05

Observed at 2026-10-04 22:57:37 UTC.

Observed checkout: fbefa12bb987d6d85cf1e71b9398fee9500551a2. Built Desktop product: feda2921da95cb5d112e49f84cdb932721be762d. Their difference is 14 documentation/report paths; runtime product bytes are identical.

Windows release qualification for product commit feda2921da95cb5d112e49f84cdb932721be762d completed successfully: build, upgrade-baseline build, qualification, provenance and qualified bundle upload. Tag publication was skipped. Run: https://github.com/zapabob/hermes-agent-windows/actions/runs/37240940647.

Tier-1 run for observed checkout: https://github.com/zapabob/hermes-agent-windows/actions/runs/37241758577. Downstream policy, carry metrics, upstream API compatibility and Windows watchdog Go jobs completed successfully. Composed regression test step succeeded, but its job cleanup was still running. Desktop typecheck succeeded; Desktop lint and later tests/build were not terminal at this observation.

Windows native Python failed the Windows footgun scan; subsequent native-contract steps were skipped. Security and lockfiles failed the Node production dependency advisory audit; Python dependency audit and locked-graph validation succeeded. These failures remain OPEN. Earlier source review identified the existing Nimble footgun and dependency advisories; this observation reports current CI results without treating earlier diagnosis as a new log inspection.

All-required-success is false. Seven remaining implementation families and six auxiliary metadata callers remain OPEN. Continue with the source-bound S05 RED checkpoint and implementation plan in docs/windows/selective-security-20261003/IMPLEMENTATION_PLAN_20261005.md after a new work deadline is authorized.

This observation is published in a subsequent documentation-only commit under _docs/. It does not assert that CI for that later commit has completed. No source, dependency, runtime, configuration, llama or embedding change was made for this observation.
