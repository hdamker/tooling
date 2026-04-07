// CAMARA Project - support function for Spectral linter
// Checks that callback POST requestBody content includes the
// 'application/cloudevents+json' media type key.

export default (content) => {
  if (!content || typeof content !== "object") return;

  const keys = Object.keys(content);
  if (!keys.includes("application/cloudevents+json")) {
    return [{
      message: `Notification callback content type must include 'application/cloudevents+json', found: ${keys.join(", ") || "(empty)"}`
    }];
  }
};
