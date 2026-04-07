// CAMARA Project - support function for Spectral linter
// Checks that inline array 'items' schemas have a 'description' field.
// Items that are $ref are skipped (the target schema should have its
// own description).

export default (schema, _options, context) => {
  const errors = [];

  function check(node, path) {
    if (!node || typeof node !== "object" || node.$ref) return;

    if (node.type === "array" && node.items) {
      if (typeof node.items === "object" && !node.items.$ref && !node.items.description) {
        errors.push({
          message: `Array items must have a description`,
          path: [...path, "items"]
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
