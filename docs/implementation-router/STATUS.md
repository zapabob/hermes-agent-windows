# Native engineering workflow — qualification record

The feature branch now contains a native plugin entrypoint, existing-picker
integration, strict parent-owned inference, measured credential-free Docker
execution and deterministic verification. It is not merely the original kernel
fixture. **It is not released or merge-qualified until exact-head required CI
and native Docker acceptance pass.**

Initial branch base: `669039a501e13e9f48f1e995b0836944854eea33`.
Downstream main base: `15f60413bd5d5394aeb8e374c52c1010b8052224`.
Separate upstream worktree: `71a2fe399bbd7a219c71f9d9fca2b313b01f2057`.
Earlier component-only CI does not qualify this new integration.

## Evidence categories

- Local native-helper and existing auxiliary regression tests are run with
  synthetic credentials and a real restored source checkout.
- The UI suite exercises the existing provider/model picker, including custom
  endpoints, profile scope and all five locale inventories.
- Component mutation tests are deliberate behavioural failures, not syntax errors.
- Native Docker E2E uses real containers, the native host/tool/provider paths,
  and a deterministic local HTTP inference endpoint. It is not live OAuth or
  paid-model evaluation. It checks actual child/grandchild environment isolation,
  protected acceptance files, verification failures/replanning and cleanup.
- Full Linux/Windows/macOS repository gates are distinct from focused tests.
  Consult final-head Actions outcomes and the PR's verification record.

The original checkout is not modified by workflow execution: success returns a
verified workspace copy and audit receipt. An operator-prepared Linux Docker
engine/image is required; no unsafe local-shell fallback is supplied. Existing
MoA, Switchyard, normal terminal mode and credential handling are not replaced.

See [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md), and the [English](i18n/en.md),
[Japanese](i18n/ja.md), [Simplified Chinese](i18n/zh.md),
[Traditional Chinese](i18n/zh-hant.md), [Arabic](i18n/ar.md) guides.
