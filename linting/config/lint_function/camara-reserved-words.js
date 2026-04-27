// CAMARA Project - support function for Spectral linter
// Flags reserved words that conflict with code-generated identifiers
// (Java/etc. keywords) when they appear as standalone tokens in path
// segments, parameter names, schema/property/component names, security
// scheme names, or operationId values.
//
// Word-boundary regex excludes hyphen and underscore: reserved-word
// substrings inside hyphenated path segments (e.g. "public" inside
// "blockchain-public-addresses") and inside snake_case names do not
// match — code-gen tools tokenize/camelCase those into valid
// identifiers. camelCase identifiers (e.g. "getPublic") are also safe
// because there is no boundary between letters.

const reservedWords = [
  'abstract',
  'apiclient',
  'apiexception',
  'apiresponse',
  'assert',
  'boolean',
  'break',
  'byte',
  'case',
  'catch',
  'char',
  'class',
  'configuration',
  'const',
  'continue',
  'do',
  'double',
  'else',
  'extends',
  'file',
  'final',
  'finally',
  'float',
  'for',
  'goto',
  'if',
  'implements',
  'import',
  'instanceof',
  'int',
  'interface',
  'list',
  'localdate',
  'localreturntype',
  'localtime',
  'localvaraccept',
  'localvaraccepts',
  'localvarauthnames',
  'localvarcollectionqueryparams',
  'localvarcontenttype',
  'localvarcontenttypes',
  'localvarcookieparams',
  'localvarformparams',
  'localvarheaderparams',
  'localvarpath',
  'localvarpostbody',
  'localvarqueryparams',
  'long',
  'native',
  'new',
  'null',
  'object',
  'offsetdatetime',
  'package',
  'private',
  'protected',
  'public',
  'return',
  'short',
  'static',
  'strictfp',
  'stringutil',
  'super',
  'switch',
  'synchronized',
  'this',
  'throw',
  'throws',
  'transient',
  'try',
  'void',
  'volatile',
  'while'
];
// Reserved words 'enum' and 'default' intentionally excluded — common
// in OpenAPI keywords.

const PATTERNS = reservedWords.map((word) => ({
  word,
  re: new RegExp(`(?<![A-Za-z0-9_-])${word}(?![A-Za-z0-9_-])`)
}));

// Container path-tail names where the rule should iterate the input
// object's own keys (each key is a user-controlled name). For other
// inputs at a non-container path tail, the path tail itself is the
// user-controlled name.
const ITERATE_KEYS_CONTAINERS = new Set([
  'paths',
  'securitySchemes',
  'parameters',
  'schemas',
  'responses',
  'requestBodies',
  'headers',
  'examples',
  'links',
  'callbacks',
  'pathItems'
]);

function matchedWord(value) {
  if (typeof value !== 'string') return null;
  for (const { word, re } of PATTERNS) {
    if (re.test(value)) return word;
  }
  return null;
}

function makeError(path, name, word) {
  return {
    message: `Consider avoiding the use of reserved word '${word}' in '${name}'`,
    path
  };
}

export default (input, _options, context) => {
  const errors = [];
  const basePath = [...(context.path || [])];

  // 1. Direct string input (e.g. operationId).
  if (typeof input === 'string') {
    const word = matchedWord(input);
    if (word) errors.push(makeError(basePath, input, word));
    return errors;
  }

  if (!input || typeof input !== 'object') return errors;

  // 2. Parameter object — check the user-controlled `.name` field.
  // Skip header parameters (HTTP headers are case-insensitive per RFC).
  if (typeof input.name === 'string' && input.in !== 'header') {
    const word = matchedWord(input.name);
    if (word) errors.push(makeError([...basePath, 'name'], input.name, word));
    return errors;
  }

  // 3. Map at a known container path (paths object, securitySchemes,
  // generic component maps): iterate keys (each is a user-controlled
  // name).
  const last = basePath.length ? basePath[basePath.length - 1] : null;
  if (basePath.length === 0 || ITERATE_KEYS_CONTAINERS.has(last)) {
    for (const key of Object.keys(input)) {
      const word = matchedWord(key);
      if (word) errors.push(makeError([...basePath, key], key, word));
    }
    return errors;
  }

  // 4. Otherwise check the path tail (component name, property name)
  // unless it is an array index.
  if (typeof last === 'string' && !/^\d+$/.test(last)) {
    const word = matchedWord(last);
    if (word) errors.push(makeError(basePath, last, word));
  }
  return errors;
};
