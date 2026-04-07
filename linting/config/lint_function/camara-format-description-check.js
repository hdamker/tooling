// CAMARA Project - support function for Spectral linter
// Checks that properties with a specific format have descriptions
// containing required text (e.g. date-time must mention RFC 3339).
//
// Options:
//   format:       the format value to match (e.g. "date-time", "duration")
//   requiredText: regex pattern to search for in description (e.g. "RFC\\s*3339")

export default (schema, options, context) => {
  const errors = [];
  const { format, requiredText } = options;
  const re = new RegExp(requiredText, "i");

  function check(node, path) {
    if (!node || typeof node !== "object" || node.$ref) return;

    if (node.format === format) {
      if (!node.description || !re.test(node.description)) {
        errors.push({
          message: `Property with format '${format}' must have a description mentioning ${requiredText.replace(/\\\\/g, "\\")}`,
          path
        });
      }
    }

    if (node.properties) {
      for (const [key, value] of Object.entries(node.properties)) {
        check(value, [...path, "properties", key]);
      }
    }
    if (node.items && typeof node.items === "object" && !node.items.$ref) {
      check(node.items, [...path, "items"]);
    }
    if (typeof node.additionalProperties === "object" && node.additionalProperties !== null) {
      check(node.additionalProperties, [...path, "additionalProperties"]);
    }
    for (const combiner of ["allOf", "anyOf", "oneOf"]) {
      if (node[combiner]) {
        node[combiner].forEach((sub, i) => check(sub, [...path, combiner, i]));
      }
    }
  }

  check(schema, context.path);
  return errors;
};
