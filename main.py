#!/usr/bin/env python3
# Copyright (c) 2025 Dedalus Labs, Inc. and its contributors
# SPDX-License-Identifier: MIT

"""
Linear MCP Server - OAuth-protected MCP server for Linear issue tracking.

This server uses the Dedalus dispatch mechanism for secure credential handling.
OAuth tokens are stored encrypted and decrypted via Gateway → Enclave flow,
ensuring credentials never leave the secure enclave.

Deployment Environment Variables:
    OAUTH_ENABLED=true
    OAUTH_AUTHORIZE_URL=https://linear.app/oauth/authorize
    OAUTH_TOKEN_URL=https://api.linear.app/oauth/token
    OAUTH_CLIENT_ID=b119ad4bbfdf5e3c7e6bb8dc42bda206
    OAUTH_CLIENT_SECRET=encrypted:<fernet_encrypted_secret>
    OAUTH_SCOPES_AVAILABLE=read,write,issues:create

Note on OAUTH_CLIENT_SECRET:
    The client secret must be encrypted using the platform encryption key.
    Use the encrypt_client_secret() function from admin.services.oauth:

        from admin.services.oauth import encrypt_client_secret
        encrypted = encrypt_client_secret("your_raw_client_secret")
        # Returns: "encrypted:gAAA..."

    For local testing, you can use a plain text secret (legacy support),
    but production deployments MUST use encrypted secrets.

Note on OAUTH_SCOPES_AVAILABLE:
    These are the scopes the server SUPPORTS. Clients can request a subset
    when initiating the OAuth flow:
        GET /oauth/connect?server=xxx&scopes=read,issues:create
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

from pydantic import BaseModel

from dedalus_mcp import MCPServer, get_context, tool
from dedalus_mcp.auth import Connection, SecretKeys
from dedalus_mcp.server.authorization import AuthorizationConfig
from dedalus_mcp.dispatch import HttpMethod, HttpRequest


# -----------------------------------------------------------------------------
# Types & Models
# -----------------------------------------------------------------------------


class IssueState(str, Enum):
    """Linear issue states."""
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELED = "canceled"


class IssuePriority(int, Enum):
    """Linear issue priorities (0 = no priority, 1 = urgent, 4 = low)."""
    NO_PRIORITY = 0
    URGENT = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class Issue(BaseModel):
    """Linear issue."""
    id: str
    identifier: str  # e.g., "ENG-123"
    title: str
    description: str | None = None
    state: str | None = None
    priority: int | None = None
    assignee: str | None = None
    project: str | None = None
    url: str | None = None


class Team(BaseModel):
    """Linear team."""
    id: str
    name: str
    key: str  # e.g., "ENG"


class Project(BaseModel):
    """Linear project."""
    id: str
    name: str
    state: str | None = None


class User(BaseModel):
    """Linear user."""
    id: str
    name: str
    email: str | None = None


# -----------------------------------------------------------------------------
# GraphQL Helpers
# -----------------------------------------------------------------------------


LINEAR_API_BASE = "https://api.linear.app"


async def graphql_request(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a GraphQL request to Linear API via dispatch.

    This routes the request through Gateway → Enclave where credentials
    are securely decrypted and injected into the request.
    """
    ctx = get_context()

    # Note: Content-Type header is automatically added by the Enclave
    # Do not include it here to avoid duplicate headers
    response = await ctx.dispatch(HttpRequest(
        method=HttpMethod.POST,
        path="/graphql",
        body={"query": query, "variables": variables or {}},
    ))

    print(f"DEBUG dispatch response: success={response.success}")
    if not response.success:
        print(f"DEBUG dispatch error: {response.error}")
        raise Exception(f"Dispatch error: {response.error.code} - {response.error.message}")

    print(f"DEBUG response status={response.response.status} body={response.response.body}")

    if response.response.status >= 400:
        raise Exception(f"Linear API error ({response.response.status}): {response.response.body}")

    result = response.response.body
    if isinstance(result, dict) and "errors" in result:
        print(f"DEBUG GraphQL errors: {result['errors']}")
        raise Exception(f"GraphQL error: {result['errors']}")

    return result.get("data", {}) if isinstance(result, dict) else {}


# -----------------------------------------------------------------------------
# Connection & Server Setup
# -----------------------------------------------------------------------------

# Define the connection - credentials will be provided via OAuth flow
linear = Connection(
    "linear",
    secrets=SecretKeys(token="LINEAR_TOKEN"),
    base_url=LINEAR_API_BASE,
)

# Authorization server URL
AS_URL = "http://dev.as.dedaluslabs.ai"

# Create the server with explicit auth config
# CRITICAL: streamable_http_stateless=True is required for Lambda deployments
server = MCPServer(
    name="linear",
    version="1.0.0",
    instructions="Linear issue tracking MCP server. Use these tools to manage issues, projects, and teams in Linear.",
    connections=[linear],
    streamable_http_stateless=True,
    authorization_server=AS_URL,
    authorization=AuthorizationConfig(
        enabled=True,
        fail_open=True,
        authorization_servers=[AS_URL],
    ),
)

# Manually configure JWT validator (explicit auth config disables auto-config)
from dedalus_mcp.server.services.jwt_validator import JWTValidator, JWTValidatorConfig
jwt_config = JWTValidatorConfig(
    jwks_uri=f"{AS_URL}/.well-known/jwks.json",
    issuer=AS_URL,
)
server._authorization_manager.set_provider(JWTValidator(jwt_config))


# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------


@tool(description="Get the current authenticated user's profile")
async def get_me() -> User:
    """Get the authenticated user's profile."""
    query = """
    query {
        viewer {
            id
            name
            email
        }
    }
    """

    data = await graphql_request(query)
    viewer = data.get("viewer", {})

    return User(
        id=viewer.get("id", ""),
        name=viewer.get("name", ""),
        email=viewer.get("email"),
    )


@tool(description="List teams the user has access to")
async def list_teams() -> list[Team]:
    """List all teams the user has access to."""
    query = """
    query {
        teams {
            nodes {
                id
                name
                key
            }
        }
    }
    """

    data = await graphql_request(query)
    teams = data.get("teams", {}).get("nodes", [])

    return [
        Team(id=t["id"], name=t["name"], key=t["key"])
        for t in teams
    ]


@tool(description="List issues, optionally filtered by team or state")
async def list_issues(
    team_key: str | None = None,
    state: IssueState | None = None,
    limit: int = 10,
) -> list[Issue]:
    """List issues with optional filters.

    Args:
        team_key: Filter by team key (e.g., "ENG")
        state: Filter by issue state
        limit: Maximum number of issues to return (default: 10)
    """

    # Build filter
    filters = []
    if team_key:
        filters.append(f'team: {{ key: {{ eq: "{team_key}" }} }}')
    if state:
        # Map our state enum to Linear's state names
        state_map = {
            IssueState.BACKLOG: "Backlog",
            IssueState.TODO: "Todo",
            IssueState.IN_PROGRESS: "In Progress",
            IssueState.DONE: "Done",
            IssueState.CANCELED: "Canceled",
        }
        linear_state = state_map.get(state, state.value)
        filters.append(f'state: {{ name: {{ eq: "{linear_state}" }} }}')

    filter_str = ", ".join(filters) if filters else ""
    filter_clause = f"filter: {{ {filter_str} }}" if filter_str else ""

    query = f"""
    query {{
        issues(first: {limit}, {filter_clause}) {{
            nodes {{
                id
                identifier
                title
                description
                url
                priority
                state {{
                    name
                }}
                assignee {{
                    name
                }}
                project {{
                    name
                }}
            }}
        }}
    }}
    """

    data = await graphql_request(query)
    issues = data.get("issues", {}).get("nodes", [])

    return [
        Issue(
            id=i["id"],
            identifier=i["identifier"],
            title=i["title"],
            description=i.get("description"),
            state=i.get("state", {}).get("name") if i.get("state") else None,
            priority=i.get("priority"),
            assignee=i.get("assignee", {}).get("name") if i.get("assignee") else None,
            project=i.get("project", {}).get("name") if i.get("project") else None,
            url=i.get("url"),
        )
        for i in issues
    ]


@tool(description="Get details of a specific issue by its identifier (e.g., ENG-123)")
async def get_issue(identifier: str) -> Issue | None:
    """Get a specific issue by its identifier.

    Args:
        identifier: The issue identifier (e.g., "ENG-123")
    """

    query = """
    query($identifier: String!) {
        issue(id: $identifier) {
            id
            identifier
            title
            description
            url
            priority
            state {
                name
            }
            assignee {
                name
            }
            project {
                name
            }
        }
    }
    """

    # Linear uses the identifier directly in the id field for lookups
    # But we need to search by identifier filter instead
    search_query = f"""
    query {{
        issues(filter: {{ identifier: {{ eq: "{identifier}" }} }}, first: 1) {{
            nodes {{
                id
                identifier
                title
                description
                url
                priority
                state {{
                    name
                }}
                assignee {{
                    name
                }}
                project {{
                    name
                }}
            }}
        }}
    }}
    """

    data = await graphql_request(search_query)
    issues = data.get("issues", {}).get("nodes", [])

    if not issues:
        return None

    i = issues[0]
    return Issue(
        id=i["id"],
        identifier=i["identifier"],
        title=i["title"],
        description=i.get("description"),
        state=i.get("state", {}).get("name") if i.get("state") else None,
        priority=i.get("priority"),
        assignee=i.get("assignee", {}).get("name") if i.get("assignee") else None,
        project=i.get("project", {}).get("name") if i.get("project") else None,
        url=i.get("url"),
    )


@tool(description="Create a new issue in Linear")
async def create_issue(
    title: str,
    team_key: str,
    description: str | None = None,
    priority: IssuePriority = IssuePriority.NO_PRIORITY,
) -> Issue:
    """Create a new issue.

    Args:
        title: Issue title
        team_key: Team key (e.g., "ENG") - use list_teams to find available teams
        description: Optional issue description (markdown supported)
        priority: Issue priority (0=none, 1=urgent, 2=high, 3=medium, 4=low)
    """

    # First, get the team ID from the key
    team_query = f"""
    query {{
        teams(filter: {{ key: {{ eq: "{team_key}" }} }}) {{
            nodes {{
                id
            }}
        }}
    }}
    """

    team_data = await graphql_request(team_query)
    teams = team_data.get("teams", {}).get("nodes", [])

    if not teams:
        raise ValueError(f"Team with key '{team_key}' not found")

    team_id = teams[0]["id"]

    # Create the issue
    mutation = """
    mutation($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue {
                id
                identifier
                title
                description
                url
                priority
                state {
                    name
                }
            }
        }
    }
    """

    variables = {
        "input": {
            "title": title,
            "teamId": team_id,
            "description": description,
            "priority": priority.value,
        }
    }

    data = await graphql_request(mutation, variables)
    result = data.get("issueCreate", {})

    if not result.get("success"):
        raise Exception("Failed to create issue")

    i = result.get("issue", {})
    return Issue(
        id=i["id"],
        identifier=i["identifier"],
        title=i["title"],
        description=i.get("description"),
        state=i.get("state", {}).get("name") if i.get("state") else None,
        priority=i.get("priority"),
        url=i.get("url"),
    )


@tool(description="Search issues by text query")
async def search_issues(
    query: str,
    limit: int = 10,
) -> list[Issue]:
    """Search for issues by text.

    Args:
        query: Search query (searches title and description)
        limit: Maximum number of results (default: 10)
    """

    # Linear doesn't have a direct text search in GraphQL filters,
    # so we use the issueSearch query
    search_query = """
    query($query: String!, $first: Int!) {
        issueSearch(query: $query, first: $first) {
            nodes {
                id
                identifier
                title
                description
                url
                priority
                state {
                    name
                }
                assignee {
                    name
                }
                project {
                    name
                }
            }
        }
    }
    """

    data = await graphql_request(search_query, {"query": query, "first": limit})
    issues = data.get("issueSearch", {}).get("nodes", [])

    return [
        Issue(
            id=i["id"],
            identifier=i["identifier"],
            title=i["title"],
            description=i.get("description"),
            state=i.get("state", {}).get("name") if i.get("state") else None,
            priority=i.get("priority"),
            assignee=i.get("assignee", {}).get("name") if i.get("assignee") else None,
            project=i.get("project", {}).get("name") if i.get("project") else None,
            url=i.get("url"),
        )
        for i in issues
    ]


@tool(description="List projects in a team")
async def list_projects(team_key: str | None = None) -> list[Project]:
    """List projects, optionally filtered by team.

    Args:
        team_key: Optional team key to filter projects
    """

    filter_clause = ""
    if team_key:
        # Get team ID first
        team_query = f"""
        query {{
            teams(filter: {{ key: {{ eq: "{team_key}" }} }}) {{
                nodes {{
                    id
                }}
            }}
        }}
        """
        team_data = await graphql_request(team_query)
        teams = team_data.get("teams", {}).get("nodes", [])
        if teams:
            team_id = teams[0]["id"]
            filter_clause = f'filter: {{ accessibleTeams: {{ id: {{ eq: "{team_id}" }} }} }}'

    query = f"""
    query {{
        projects({filter_clause}) {{
            nodes {{
                id
                name
                state
            }}
        }}
    }}
    """

    data = await graphql_request(query)
    projects = data.get("projects", {}).get("nodes", [])

    return [
        Project(id=p["id"], name=p["name"], state=p.get("state"))
        for p in projects
    ]


# Register all tools with the server
server.collect(
    get_me,
    list_teams,
    list_issues,
    get_issue,
    create_issue,
    search_issues,
    list_projects,
)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


async def main() -> None:
    """Run the server."""
    # Server always starts - credentials provided per-request via OAuth
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
