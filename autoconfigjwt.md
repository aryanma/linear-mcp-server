# JWT Auto-Configuration Issue in dedalus_mcp

## Problem

The `dedalus_mcp` framework has mutually exclusive logic for:
1. Custom `AuthorizationConfig` (needed for `fail_open=True`)
2. Auto-configured JWT validator (needed for token validation)

## Root Cause

In `dedalus_mcp/server/core.py`:

```python
if authorization is not None:    # User passed explicit config
    auth_config = authorization
    auto_configure_jwt = False   # ← JWT validator NOT created
elif connections:
    auth_config = AuthorizationConfig(enabled=True)
    auto_configure_jwt = True    # ← JWT validator IS created
```

When you pass explicit `authorization=AuthorizationConfig(...)`:
- `auto_configure_jwt = False`
- No JWT validator is set up
- Auth manager uses `_NoopAuthorizationProvider` which always fails
- Result: "authorization failed" on every request

## Why We Need Explicit Config

Deployment validation calls the MCP endpoint without a valid token. Without `fail_open=True`, this returns 401 and deployment fails.

To set `fail_open=True`, you must pass explicit `AuthorizationConfig`. But this disables JWT auto-configuration.

## Workaround

Manually configure the JWT validator after creating the server:

```python
from dedalus_mcp.server.authorization import AuthorizationConfig
from dedalus_mcp.server.services.jwt_validator import JWTValidator, JWTValidatorConfig

AS_URL = "http://dev.as.dedaluslabs.ai"

server = MCPServer(
    name="my-server",
    connections=[my_connection],
    authorization_server=AS_URL,
    authorization=AuthorizationConfig(
        enabled=True,
        fail_open=True,
        authorization_servers=[AS_URL],
    ),
)

# Manually configure JWT validator (explicit auth config disables auto-config)
jwt_config = JWTValidatorConfig(
    jwks_uri=f"{AS_URL}/.well-known/jwks.json",
    issuer=AS_URL,
)
server._authorization_manager.set_provider(JWTValidator(jwt_config))
```

## Proper Fix

The framework should auto-configure JWT when `connections` are defined, regardless of whether explicit `authorization` config is passed:

```python
# Proposed fix in core.py
if authorization is not None:
    auth_config = authorization
else:
    auth_config = AuthorizationConfig(enabled=True) if connections else AuthorizationConfig()

# Auto-configure JWT whenever connections are defined
auto_configure_jwt = bool(connections)
```

This would allow both custom config AND auto JWT setup.
