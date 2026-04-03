// CAMARA Project - support function for Spectral linter
// Recursive type check for schema definitions with combiner support.
// 03.04.2026 - initial version

const VALID_TYPES = new Set(["string", "number", "integer", "boolean", "array", "object"]);

export default (schema, _options, context) => {
  const errors = [];

  function check(node, path, isPartial = false) {
    if (!node || typeof node !== "object" || node.$ref) return;

    const hasCombiner = node.allOf || node.anyOf || node.oneOf;

    // Only require 'type' if:
    // - not a partial schema (inside a combiner)
    // - and no combiner is used as a substitute
    if (!isPartial && !hasCombiner) {
      if (!node.type) {
        errors.push({ message: `Missing 'type' at ${path.join(".")}`, path });
      } else if (!VALID_TYPES.has(node.type)) {
        errors.push({ message: `Invalid type '${node.type}' at ${path.join(".")}`, path });
      }
    }

    // Recurse into properties
    if (node.properties) {
      for (const [key, value] of Object.entries(node.properties)) {
        check(value, [...path, "properties", key], isPartial);
      }
    }

    // Recurse into array items
    if (node.items) {
      check(node.items, [...path, "items"], isPartial);
    }

    // Recurse into additionalProperties when it is a schema
    if (typeof node.additionalProperties === "object" && node.additionalProperties !== null) {
      check(node.additionalProperties, [...path, "additionalProperties"], isPartial);
    }

    // Recurse into combiners — mark children as partial
    for (const combiner of ["allOf", "anyOf", "oneOf"]) {
      if (node[combiner]) {
        node[combiner].forEach((subSchema, i) => {
          check(subSchema, [...path, combiner, i], true);
        });
      }
    }
  }

  check(schema, context.path);
  return errors;
};
