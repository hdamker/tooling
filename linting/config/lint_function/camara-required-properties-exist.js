// CAMARA Project - support function for Spectral linter
// Checks that every entry in a schema's 'required' array has a
// corresponding key in 'properties'. Only checks nodes where both
// 'required' and 'properties' coexist (avoids false positives on
// allOf partial fragments that have 'required' without 'properties').

export default (schema, _options, context) => {
  const errors = [];

  function check(node, path) {
    if (!node || typeof node !== "object" || node.$ref) return;

    if (Array.isArray(node.required) && node.properties) {
      for (const name of node.required) {
        if (!(name in node.properties)) {
          errors.push({
            message: `Required property '${name}' is not defined in 'properties'`,
            path: [...path, "required"]
          });
        }
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
