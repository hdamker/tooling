// CAMARA Project - support function for Spectral linter
// Validates that error codes containing a dot follow the
// API_NAME.SPECIFIC_CODE format (both segments in SCREAMING_SNAKE_CASE).
// Non-dot codes are silently skipped (they are common codes).

const DOT_FORMAT = /^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*\.[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$/;

export default (input) => {
  if (typeof input !== "string") return;
  if (!input.includes(".")) return;

  if (!DOT_FORMAT.test(input)) {
    return [{
      message: `API-specific error code '${input}' must follow API_NAME.SPECIFIC_CODE format (SCREAMING_SNAKE_CASE on both sides of the dot)`
    }];
  }
};
