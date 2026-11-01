"use strict";

const engine = require("minimatch-engine");

// glob 7 consumes parser segments via String.match() and the old _glob field.
// Keep the upstream nonrecursive Matcher and its limits; never rebuild a regex.
function createLegacy(defaultOptions = {}) {
  const optionsFor = (options) => ({ ...defaultOptions, ...options });
  const legacyOptions = (options) => ({ windowsPathsNoEscape: engine.sep === "\\", ...optionsFor(options) });
  class LegacyMinimatch extends engine.Minimatch {
    constructor(pattern, options) {
      super(pattern, legacyOptions(options));
      for (const row of this.set) {
        for (const segment of row) {
          if (segment && typeof segment === "object" && typeof segment.test === "function") {
            Object.defineProperties(segment, {
              _glob: { configurable: true, get: () => segment.pattern },
              [Symbol.match]: {
                configurable: true,
                value: (input) => segment.test(input) ? [input] : null,
              },
            });
          }
        }
      }
    }

    // glob 7 indexes globSet and set in parallel, including nonull results.
    // Preserve separate brace alternatives instead of the modern walk optimization.
    mergeRows() {}

    static defaults(options) {
      return createLegacy(optionsFor(options)).Minimatch;
    }
  }

  const match = (input, pattern, options) => new LegacyMinimatch(pattern, legacyOptions(options)).match(input);
  Object.assign(match, {
    Minimatch: LegacyMinimatch,
    GLOBSTAR: engine.GLOBSTAR,
    sep: engine.sep,
    minimatch: engine.defaults(defaultOptions),
    defaults: (options) => createLegacy(optionsFor(options)),
    filter: (pattern, options) => (input) => match(input, pattern, options),
    match: (list, pattern, options) => engine.match(list, pattern, legacyOptions(options)),
    braceExpand: (pattern, options) => engine.braceExpand(pattern, optionsFor(options)),
    escape: (input, options) => engine.escape(input, optionsFor(options)),
    unescape: (input, options) => engine.unescape(input, optionsFor(options)),
  });
  return match;
}

module.exports = createLegacy();
