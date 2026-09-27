# N34 partial: disabled client-surface toolset resolution

Repository: `zapabob/hermes-agent-windows`. Product commit `f33ef0e9e2b16bde111c260857226bce8b7033f8`, tree `9be5999f22b9dc9ffaff2e1279ea65451978f5ed`. Frozen D0 is `60deb5c75351a19b1a6fa1d778d7d0c2ff627e5b`, U1 is `678a4762b887f3eabe5cad11254b2ab1ae859485`, R2 is `f97608f178d1ffeca59860195ab7da295f7c8e5f`, and old U0 remains `b936546561888a54d5bf9cd7eae9629a824eb4f7`. R2-to-U1 ledger row `v0215_to_u1.jsonl:1318` identifies upstream `903a57c540917cedd30c7d971938f1af7bdf60e2`; this family maps only its disabled client-surface fold-in contract. Related row `:1107` identifies `788d82fc9759de268c63fc2c6446718acd04ff8c`, whose composite-toolset propagation remains unreviewed.

## Source, caller and RED

D0 `tui_gateway/server.py` blob `c08fd9bd2eff3b06f64afaab6567dff69221fcbc`, observed local feature blob `6e82d82d3867acae006bed0eeabe1529baf5ff40`, and U1 blob `26f133a60b0ca041bde9ff30fb683641d6a12ed4` are distinct. The common ancestor blob is `beff50c2564ad1b81e2901ae17fb62233c1b3416`. In the integration before N34, `tui_gateway/server.py:5824-5842` defined `project` and `desktop_ui` as client-only surfaces. `_load_enabled_toolsets` added those names to the focus return at `:5871` and the configured return at `:5988`; D0 had the same union behavior at nearby lines. The configured resolver had already subtracted `agent.disabled_toolsets` in `hermes_cli/tools_config.py:2929-2943`; the later union silently restored a disabled `project`. `_make_agent` passed the resulting list to AIAgent.

At parent `b82ab1967b92d3788e691d09b4881cea2111dd8f`, new tests of TUI/Desktop crossed with focus/configured selection yielded four failures, each because `project` remained in the result; ten existing controls passed. The effective config in the tests used a JSON-array string, the format supported by the shared `parse_config_string_list` parser.

## Adaptation and evidence

`_with_session_surface_toolsets` now combines the selected toolsets and the client surface, then removes the configured disabled names from that result. `desktop_ui` remains available to a Desktop session as its client-control capability. The focus path reads effective profile config, and the configured path passes its resolved config to the same helper. The existing explicit `HERMES_TUI_TOOLSETS` operator pin branch is unchanged. The added test also verifies that an excluded name already present in a focus selection is removed.

The two affected test files passed 631 native Windows Python 3.12 tests before commit. Source, staged bytes, the CodeGraph index and the product commit match for both changed paths. At the exact product HEAD, 26 focused tests passed with 605 deselected. Four deliberate mutations each failed the targeted test: ignoring all exclusions, removing the `desktop_ui` exception, bypassing focus filtering, and bypassing configured filtering. The mutation script restored byte-identical source after each attempt. Independent read-only rereview returned CLEAR; the reviewer did not run tests, graph analysis, mutation or commit.

Approved CodeGraph 1.6.0 held separate D0, U1 and integration indexes of 8,881, 12,468 and 8,957 files. All three reported zero pending changes and refs. Source-bound query, explore, impact, owner-map outputs and tested Git/index hashes are held in the private local `N34-20260927/receipt.json`, SHA-256 `003cb612eb7638498d57c9b02d8ffa43ed055d25579c108a4435c68256d3a613`. The committed card contains no raw index, query dump or private root path.

## Remaining gates and reversal

N34 is PARTIAL. No live Desktop/TUI model session was executed, and the related `788d82` composite-toolset propagation and explicit env-pin policy need separate semantic audit. This family does not prove full parity for the cited upstream commits or the 17,065-commit inventory. The user confirmed that the Control MCP grant-revocation host writer is not implemented; N07-A1 grant/claim linearization and destination outcome durability remain P0 open, so production write stays DISABLED.

Original main and local feature WIP were not modified. No reset, stash, clean, upstream merge/rebase/cherry-pick, PR, push, production restart or Control MCP production write occurred. Reversal would review and revert the isolated product commit, rerun affected tests and refresh the integration CodeGraph index; no reversal was performed.
