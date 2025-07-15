# CAMARA Validation Rules Discovered Through Testing

## Critical Rules (Block Release)

### 1. Filename Must Match API Name ⚡
- **Rule**: Filename must match the API name extracted from servers URL
- **Example**:
  - Servers URL: `{apiRoot}/test-service/v1`
  - Required filename: `test-service.yaml`
- **Test Case**: `test-data/invalid/critical-issues/filename-mismatch.yaml`

### 2. XCorrelator Schema Required ⚡
- **Rule**: Must define `XCorrelator` schema in components/schemas
- **Pattern**: `^[a-zA-Z0-9-_:;.\/<>{}]{0,256}$`
- **Test Case**: `test-data/invalid/critical-issues/missing-xcorrelator-schema.yaml`

### 3. OpenID Security Scheme Required ⚡
- **Rule**: APIs using `openId` security must define the scheme in components
- **Test Case**: `test-data/synthetic/missing-openid-security.yaml`

### 4. Wrong Error Codes ⚡
- **Rule**: Use `UNAUTHENTICATED` not `AUTHENTICATION_REQUIRED` for 401
- **Test Case**: `test-data/synthetic/wrong-auth-error-code.yaml`

## Medium Priority Rules

### 5. Title Should Not Include "API" ⚠️
- **Rule**: Info title should be like "Test Service" not "Test API"
- **Example**:
  - ❌ Bad: `title: Test API`
  - ✅ Good: `title: Test Service`

### 6. Required Error Responses ⚠️
- **Rule**: APIs should include standard error responses:
  - 400 Bad Request (when applicable)
  - 401 Unauthorized (when using security)
  - 403 Forbidden (when using security)
  - 500 Internal Server Error
  - 503 Service Unavailable

### 7. Server URL Format ⚠️
- **Rule**: Must use `{apiRoot}/api-name/version` pattern
- **Example**: `{apiRoot}/device-location/v1`
- **Test Case**: `test-data/synthetic/invalid-server-format.yaml`

## Low Priority Rules

### 8. Description Requirements 📝
- **Rule**: All schemas, parameters, and responses should have descriptions

### 9. Example Requirements 📝
- **Rule**: Schemas should include examples where applicable

## Validation Categories

### Structure Validation
- OpenAPI version must be 3.0.3
- Info object completeness
- Required license (Apache 2.0)
- External docs recommended

### Security Validation
- OpenID Connect configuration
- Proper scope naming convention
- Security applied to appropriate endpoints

### Error Response Validation
- ErrorInfo schema structure
- Correct error codes per status
- Consistent error response format

### Naming Conventions
- camelCase for properties
- kebab-case for URLs
- Consistent naming across API

## Test Case Organization

```
test-data/
├── valid/
│   └── regular-apis/
│       └── test-service.yaml      # Passes all rules
├── invalid/
│   ├── critical-issues/
│   │   ├── filename-mismatch.yaml
│   │   └── missing-xcorrelator.yaml
│   └── medium-issues/
│       ├── title-contains-api.yaml
│       └── missing-error-responses.yaml
└── synthetic/
    ├── missing-openid-security.yaml
    ├── wrong-auth-error-code.yaml
    └── invalid-server-format.yaml
```

## Next Steps

1. Create test cases for each discovered rule
2. Document rules in modular validator
3. Implement rules as ValidationRule classes
4. Track coverage of legacy validator rules
