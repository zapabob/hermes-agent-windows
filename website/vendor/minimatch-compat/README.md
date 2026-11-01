# Legacy minimatch compatibility

This package retains the callable CommonJS interface used by @electron/asar,
dir-compare, filelist, serve-handler and glob 7. Matching is delegated to the
exact official minimatch 11 engine through an npm alias, without retaining an
older matcher or regenerating backtracking regular expressions.

The parser segment bridge supplies glob 7's `_glob` and `Symbol.match` contract.
Modern named exports are provided by an ESM entry point backed by the same engine. The removed `makeRe` API
is deliberately not emulated; the owning legacy consumers do not call it.

The source lives below website/vendor so both a standalone website installation
and the root installation can resolve the engine through ordinary Node module
lookup. It has no lifecycle scripts. Validate both installation graphs and the
real packaging, glob enumeration and static-serving consumers after changes.

The root and standalone website declare this package directly as `minimatch`
and use npm's `$minimatch` override reference. This hoists one real local source
package and avoids depth-dependent `file:` override targets in nested consumers.

The committed npm tarball is generated with npm pack ./website/vendor/minimatch-compat --pack-destination ./website/vendor --ignore-scripts. Both installs use that relative tarball: npm directory overrides can otherwise resolve relative to a nested consumer. Regenerate the archive after changing this source and retain its lockfile integrity.
