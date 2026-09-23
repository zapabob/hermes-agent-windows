# Sequential engineering in Hermes

This is a sequence of planning, implementation and host verification—not MoA or provider fallback.
Enable the `implementation_router` plugin, then select `engineering_planner`, `engineering_worker` and `engineering_reviewer` in the existing auxiliary model picker. Any model supported by its configured provider may be selected; an unavailable choice stops execution.
Configure approved non-secret `source_paths`, immutable `protected_paths`, a locally prepared image digest and deterministic `checks` in the plugin settings. Invoke `/engineer {"workspace":"sample","task":"Implement the required change"}`.
Credentials and inference clients stay in the parent Hermes host. Child processes run in a fresh measured Docker environment with no host credential mounts, ambient environment or network. A Linux Docker engine is required, including on Windows hosts. No ordinary local-shell fallback is permitted.
A successful result returns a verified workspace copy, not an automatically edited original checkout or merged PR. The exact-head CI and native acceptance record determines qualification; fixture tests do not establish live-account access.
An empty environment is not an OS sandbox. The local daemon, image, host and installed trusted plugins remain the trust base. Review source inputs for embedded secrets. Inspect a surviving lease before manual recovery; do not replay uncertain work.

<!-- routing-not-moa -->
<!-- credentials-host-only -->
<!-- native-adapter-requirements -->
<!-- not-os-sandbox -->

[Agent protocol](../AGENT_PROTOCOL.md)
