// CAMARA Project - support function for Spectral linter
// PascalCase check for schema names with exact CloudEvents exceptions.
// 03.04.2026 - initial version

// Schema names allowed to deviate from PascalCase (CloudEvents convention).
const ALLOWED = new Set([
  "HTTPSettings",
  "HTTPSubscriptionRequest",
  "HTTPSubscriptionResponse",
  "PrivateKeyJWTCredential",
]);

// PascalCase: first char uppercase, each uppercase followed by lowercase/digit
// or end-of-string. Matches Spectral's built-in casing: pascal behavior.
const PASCAL = /^[A-Z](?:[a-z0-9]|[A-Z](?=[a-z0-9]|$))*$/;

export default (input) => {
  if (typeof input !== "string" || ALLOWED.has(input)) return;

  if (!PASCAL.test(input)) {
    return [{ message: `${input} should be PascalCase (UpperCamelCase)` }];
  }
};
