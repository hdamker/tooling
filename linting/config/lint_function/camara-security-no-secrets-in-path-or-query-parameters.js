// CAMARA Project - support function for Spectral linter
// Flags sensitive identifiers (MSISDN, IMSI, phoneNumber) in path
// strings and in path/query parameter names. Per the rule's own name
// the wired `given` should cover both paths and parameters; previous
// implementation logged via console.log and emitted no Spectral
// findings.
//
// Word-boundary regex excludes hyphen and underscore so accidental
// substring matches inside hyphenated identifiers do not trigger.

const sensitiveData = ['MSISDN', 'IMSI', 'phoneNumber'];

const PATTERNS = sensitiveData.map((word) => ({
  word,
  re: new RegExp(`(?<![A-Za-z0-9_-])${word}(?![A-Za-z0-9_-])`)
}));

function matchedWord(value) {
  if (typeof value !== 'string') return null;
  for (const { word, re } of PATTERNS) {
    if (re.test(value)) return word;
  }
  return null;
}

function makeError(path, name, word) {
  return {
    message: `Consider avoiding the use of sensitive data '${word}' in '${name}'`,
    path
  };
}

export default (input, _options, context) => {
  const errors = [];
  const basePath = [...(context.path || [])];

  // Parameter object — check user-controlled `.name`. Skip header
  // parameters (HTTP headers are case-insensitive per RFC).
  if (input && typeof input === 'object' &&
      typeof input.name === 'string' && input.in !== 'header') {
    const word = matchedWord(input.name);
    if (word) errors.push(makeError([...basePath, 'name'], input.name, word));
    return errors;
  }

  // Paths object — iterate keys (each is a user-controlled path string).
  if (input && typeof input === 'object') {
    for (const key of Object.keys(input)) {
      const word = matchedWord(key);
      if (word) errors.push(makeError([...basePath, key], key, word));
    }
  }
  return errors;
};
