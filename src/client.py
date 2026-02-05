# Copyright (c) 2026 Dedalus Labs, Inc. and its contributors
# SPDX-License-Identifier: MIT

"""Linear GraphQL client and helpers."""

from __future__ import annotations

from typing import Any

from dedalus_mcp import HttpMethod, HttpRequest, get_context
from dedalus_mcp.auth import Connection, SecretKeys

from models import Issue

# -----------------------------------------------------------------------------
# Connection
# -----------------------------------------------------------------------------

LINEAR_API_BASE = "https://api.linear.app"

linear = Connection(
    secrets=SecretKeys(token="LINEAR_ACCESS_TOKEN"),
    base_url=LINEAR_API_BASE,
)


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------


class LinearAPIError(Exception):
    """Error from Linear API."""

    pass


# -----------------------------------------------------------------------------
# GraphQL Client
# -----------------------------------------------------------------------------


async def gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute GraphQL request via dispatch."""
    ctx = get_context()
    response = await ctx.dispatch(
        HttpRequest(
            method=HttpMethod.POST,
            path="/graphql",
            body={"query": query, "variables": variables or {}},
        )
    )

    if not response.success:
        raise LinearAPIError(f"Dispatch error: {response.error.code}")

    if response.response.status >= 400:
        raise LinearAPIError(f"API error: {response.response.body}")

    result = response.response.body
    if isinstance(result, dict) and "errors" in result:
        raise LinearAPIError(f"GraphQL error: {result['errors']}")

    return result.get("data", {}) if isinstance(result, dict) else {}


# -----------------------------------------------------------------------------
# Resolvers
# -----------------------------------------------------------------------------


async def get_team_id(team_key: str) -> str:
    """Resolve team key to ID."""
    data = await gql(
        "query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes { id } } }",
        {"key": team_key.upper()},
    )
    teams = data.get("teams", {}).get("nodes", [])
    if not teams:
        raise LinearAPIError(f"Team '{team_key}' not found")
    return teams[0]["id"]


async def get_issue_id(identifier: str) -> str:
    """Resolve issue identifier to ID."""
    data = await gql(
        "query($id: String!) { issues(filter: { identifier: { eq: $id } }, first: 1) { nodes { id } } }",
        {"id": identifier.upper()},
    )
    issues = data.get("issues", {}).get("nodes", [])
    if not issues:
        raise LinearAPIError(f"Issue '{identifier}' not found")
    return issues[0]["id"]


# -----------------------------------------------------------------------------
# Parsers
# -----------------------------------------------------------------------------

ISSUE_FIELDS = """
    id identifier title description url priority estimate dueDate createdAt updatedAt
    state { id name }
    assignee { id name }
    project { id name }
    cycle { id }
    parent { id }
    labels { nodes { id name } }
"""


def parse_issue(i: dict) -> Issue:
    """Parse issue from GraphQL response."""
    return Issue(
        id=i["id"],
        identifier=i["identifier"],
        title=i["title"],
        description=i.get("description"),
        state=i.get("state", {}).get("name") if i.get("state") else None,
        state_id=i.get("state", {}).get("id") if i.get("state") else None,
        priority=i.get("priority"),
        estimate=i.get("estimate"),
        due_date=i.get("dueDate"),
        assignee=i.get("assignee", {}).get("name") if i.get("assignee") else None,
        assignee_id=i.get("assignee", {}).get("id") if i.get("assignee") else None,
        project=i.get("project", {}).get("name") if i.get("project") else None,
        project_id=i.get("project", {}).get("id") if i.get("project") else None,
        cycle_id=i.get("cycle", {}).get("id") if i.get("cycle") else None,
        labels=[label["name"] for label in i.get("labels", {}).get("nodes", [])],
        label_ids=[label["id"] for label in i.get("labels", {}).get("nodes", [])],
        parent_id=i.get("parent", {}).get("id") if i.get("parent") else None,
        url=i.get("url"),
        created_at=i.get("createdAt"),
        updated_at=i.get("updatedAt"),
    )
