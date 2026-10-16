# F01: classic CLI queue management

Authorized delivery is a separate local commit in codex/v0216-semantic-20261010. The fixed downstream base is 606f7e557c13a0789a2420f7adf6181becf60d75; U_RELEASE is 818c13be1dc4fd28987e1e881a9408224afd4535. Introduction ce318290bddd39199a15ee973ec513581f81231e is credited to Teknium; the atomic/literal routing follow-up ded27d42548ba927d24f1a172d1d7fcae0988e27 is credited to teknium1.

## Source and composition

Frozen upstream CLILoopsMixin._cmd_queue and _mutate_pending_input in hermes_cli/cli_loops_mixin.py implement classic CLI list/edit/rm/move/clear/add; CLIInfoMixin admits queue controls inline while busy. The downstream owners are HermesCLI.process_command, _should_handle_steer_command_inline, _pending_input and _tui_process_one_input in cli.py. A focused hermes_cli/cli_queue.py helper operates on that existing queue and receives the existing output callback. CommandDef metadata expands the existing queue entry. No second queue, model tool, provider, dispatcher, setting or dependency is introduced.

This family qualifies classic CLI only. The frozen upstream TUI RPC queue handler, ACP adapter and idle messaging gateway retain plain-prompt paths. Desktop subcommand admission is F04. This family does not infer queue CRUD parity from shared metadata or qualify those independent surfaces.

## Behavioral contract

The public sequence add A, add B, add C, list, edit 2 B2, move 3 1, rm 2 produces C then B2 exactly once at the existing chat boundary. A never executes. Bare queue and list inspect pending entries; clear removes pending entries. Queue and q share one owner. Busy text-only controls dispatch before the foreground model turn ends; image-bearing input retains its current route. Neither steering nor interrupting is invoked, and the cached conversation prefix is unchanged.

Frozen source aliases ls/show, set and remove/delete/del/pop are retained. Indexed verbs select management when bare or when the first remaining token is digit-like. Malformed management shows usage without mutation; clear the logs, edit the config, list the errors and rm -1 remain literal prompts. Add forces literal content. Command and verb matching is case insensitive, while payload case and non-ASCII text are preserved. Collapsed paste references expand through the existing UTF-8 reader.

Intentional corrections to the frozen source cover whitespace-separated tabs, convertible Unicode decimal indices, conversion failures for digit-like Unicode and excessively long integers, and bounds validation before same-index move. Same-value edit is valid. Invalid zero/upper bounds, missing arguments and extra move/remove arguments do not enqueue. A typed missing-index sentinel is unused by clear after prior indexed-operation validation.

Snapshot, validation, mutation and write-back hold Queue.mutex. Removal subtracts only removed pending entries from unfinished_tasks, preserving already claimed work. Reaching zero wakes all_tasks_done; freed capacity wakes not_full. Concurrent producers/consumers cannot commit against stale indexes. Another CLI instance remains unchanged.

Move preserves object identity. Edit preserves voice/seeded wrappers and image attachments; seeded text remains literal. ProcessNotificationBatch preview displays only a neutral count, without render or registry consumption. SubagentNotification uses its existing human display_text, and both notification classes reject edit before generic string handling. Model-facing notification bodies are not listed.

## Verification and qualification

The 51-case contract uses actual process_command, Queue and _tui_process_one_input. Only the chat boundary records effects. Actual blocked bounded producers, join waiters, claimed tasks, mutex snapshots and concurrent get/put barriers test coordination. Its RED run produced 47 assertion failures and four preserved literal successes. The first GREEN attempt exposed missing voice initialization in the fixture; adding a real Lock and false voice flags completes the normal input state without replacing the consumer.

The Windows oracle uses the actual CLI, ConPTY WinPtyBridge, public input and Enter, and an external loopback provider. The first foreground response is held until a fresh terminal list displays C/B2. An explicit final queued fence response completes before public quit. The tool-bearing foreground ledger must equal FIRST,C,B2,END_FENCE. The full source-bound background review prompt is recognized only by exact equality to its actual sender's AST-bound text. Unknown tool-bearing requests remain in that ledger; tool-less requests are retained raw separately. Review arrival time is not an oracle assumption.

Owned process identities include PID, creation time, executable and argv. Final cleanup attempts every independent action, records failures and verifies reader/server completion, zero survivors and refused listener connection. Any retained ConPTY conhost is recovered only after exact owned-identity validation. This is explicit cleanup evidence; the underlying B08 public PTY cleanup risk remains open.

Eight semantic mutants target acknowledgement-only dispatch, no-op move, wrong queue instance, double chat delivery, missing mutex, erased claimed work, missing bounded-capacity notification and private notification preview. Each selected test population needs a GREEN baseline before and after, actual assertion failure, fresh real CodeGraph for edited/restored source and exact restoration of all five source files. Syntax, collection and infrastructure failures do not qualify. Full 51-case baselines bracket the sequence.

Fresh CodeGraph callers/callees/explore/impact/affected support navigation. Generic name collisions and broad affected sets are not runtime reachability or executed coverage. Direct dispatcher ownership and consumer boundaries are confirmed from source and native effects. Source, lockfile, graph, runner and raw-artifact hashes are bound before independent acceptance and explicit staging.

CLI initialization's two discovered terminal-compatibility failures require same fixed-base reproduction and a disclosed separate disposition. The early mutation controller's summary-parser refusal after a successful 51-case baseline is retained as unqualified harness evidence. It is not a product failure or semantic kill.

## Delivery and limits

Acceptance is F01-local only. Family evidence does not qualify the remaining 31 seed families, inventory-derived work, packaged release, production runtime, cloud CI, Security Center, MCP control panel or scheduled-task durability. The primary checkout, profile state, existing dirty/untracked work and active services are protected. Rollback uses a reviewed revert of the logical F01 product commit in the isolated branch, without reset or profile restoration.
