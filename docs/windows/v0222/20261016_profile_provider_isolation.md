# Profile isolation during Desktop cron execution

Baseline: `ce2cf36b6b994d3cbbe137ed7f1e4963ab65089a`.

A profile-pinned cron job changed the shared process `HERMES_HOME` and
reloaded its dotenv into the process environment. Concurrent Desktop model
requests could therefore read another profile's provider and saved local-model
catalogue. The picker also preserves a selected uncurated model by inserting it
under the current provider, making a mixed model/provider pair visible under
the wrong heading.

Cron execution and delivery now bind a context-local home and a private
environment mapping. The SessionDB initialization worker receives a copied
context. A Bot Chat child receives the explicit target home and that target's
credentials through the existing subprocess boundary. A routed profile cannot
borrow a missing provider credential from the launch profile. Launch-home
credentials supplied through the process environment remain supported.

Configuration environment references and their cache validation follow the
bound profile. Administrator overlays expand against the process environment
and have a separate cache snapshot. Read-only cache projection does not parse
an unbound profile's environment; it reports an unknown cache instead.

The change preserves configured catalogues and uncurated selections. It does
not remove saved providers, model files, session records, or credentials.

## Focused verification

The original concurrent-home trigger failed before the change. Additional
regressions demonstrated a missing-key cross-profile fallback and stale
administrator environment references before their fixes.

| Boundary | Evidence |
| --- | --- |
| Concurrent Desktop and cron | Real cron execution held behind an event while authenticated REST model info/options requests read launch, worker, then launch again. The external catalogue is a test double; profile routing and config reads are real. |
| Session ownership | Real SessionDB initialization with synchronous and timeout-worker paths writes only the execution profile's cron session. Existing timeout/late-close regressions also pass. |
| Credential ownership | Launch environment remains unchanged during normal and no-agent jobs; Bot Chat children use their own or explicit target profile. Existing child credential boundary suite passes. |
| Managed policy | Both managed loaders preserve administrator precedence; environment rotation invalidates the cache even when the profile references the same variable. |
| Read-only projection | A hot cache with a bound scope is available; an unbound foreign scope reports unknown without reading its environment. |

Independent local review identified the SessionDB worker context, dotenv
reload, and Bot Chat child-environment paths. The implementation and focused
regressions address those findings. CodeGraph evidence covers selected complete
source files, rather than a whole-repository graph.

This is a focused bug fix. Full same-SHA cloud CI, the remaining dependency
advisories, long-duration Windows qualification, and final live Desktop
verification remain separate acceptance gates. No semantic version is changed.
