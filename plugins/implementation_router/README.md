# Implementation router (retired)

The former planner/worker/reviewer engineering workflow is retired for new
runs. Installing or enabling this plugin does not register `engineering_run` or
its stage-specific model picker slots. `/engineer` remains as a diagnostic and
returns a stable blocked result with migration guidance. It does not create a
run, choose a model, start Docker, or write to a workspace.

The diagnostic names `hermes_get_operation` for legacy operation metadata.
This read works only when a Control MCP journal is mounted and the caller has
the matching profile, workspace, client registration, grant revision, subject,
and resource. It
does not read arbitrary workflow receipts or expose a STOP action. Keep an
UNKNOWN operation reserved until an operator checks its owner and journal;
never replay it from here. Other terminal states follow the journal's own
reservation and expiry rules.

Use a normal Hermes session, the ordinary model picker and effort settings,
and standard delegation. The Control MCP resource does not expose the retired
start operation; production writes remain disabled pending their own authority
and native verification gates.

Historical implementation files remain. `EngineeringRunOwner` still contains
internal claim, execution, and transition logic for legacy operation records;
it is not registered as a public execution entrypoint by this plugin. Preserve
the shared approval owner and review its authority before any later migration.
See `docs/control-mcp/RETIREMENT_SPEC.md` for the Control MCP retirement scope.
