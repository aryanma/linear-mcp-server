# Copyright (c) 2026 Dedalus Labs, Inc. and its contributors
# SPDX-License-Identifier: MIT

"""Linear API tools for linear-mcp.

Manage Linear issues, projects, cycles, and more via the Linear GraphQL API.
Ref: https://developers.linear.app/docs/graphql/working-with-the-graphql-api
"""

from __future__ import annotations

from typing import Any

from dedalus_mcp import tool
from mcp.types import Tool

from client import (
    ISSUE_FIELDS,
    LinearAPIError,
    get_issue_id,
    get_team_id,
    gql,
    parse_issue,
)
from models import (
    Comment,
    Cycle,
    Document,
    Issue,
    IssuePriority,
    Label,
    Project,
    Team,
    User,
    Webhook,
    WorkflowState,
)

# -----------------------------------------------------------------------------
# User & Team Tools
# -----------------------------------------------------------------------------


@tool(description="Get the authenticated user")
async def get_me() -> User:
    """Get the current user's profile."""
    data = await gql("query { viewer { id name email } }")
    v = data.get("viewer", {})
    return User(id=v["id"], name=v["name"], email=v.get("email"))


@tool(description="List users in the organization")
async def list_users(limit: int = 50) -> list[User]:
    """List all users."""
    data = await gql(
        "query($first: Int!) { users(first: $first) { nodes { id name email active } } }",
        {"first": limit},
    )
    return [
        User(id=u["id"], name=u["name"], email=u.get("email"), active=u.get("active", True))
        for u in data.get("users", {}).get("nodes", [])
    ]


@tool(description="List teams")
async def list_teams() -> list[Team]:
    """List all teams."""
    data = await gql("query { teams { nodes { id name key } } }")
    return [Team(id=t["id"], name=t["name"], key=t["key"]) for t in data.get("teams", {}).get("nodes", [])]


@tool(description="List workflow states for a team")
async def list_workflow_states(team_key: str) -> list[WorkflowState]:
    """List workflow states (statuses) for a team."""
    team_id = await get_team_id(team_key)
    data = await gql(
        "query($teamId: ID!) { workflowStates(filter: { team: { id: { eq: $teamId } } }) { nodes { id name type } } }",
        {"teamId": team_id},
    )
    return [
        WorkflowState(id=s["id"], name=s["name"], type=s["type"])
        for s in data.get("workflowStates", {}).get("nodes", [])
    ]


# -----------------------------------------------------------------------------
# Issue Tools
# -----------------------------------------------------------------------------


@tool(description="List issues with optional filters")
async def list_issues(
    team_key: str | None = None,
    assignee_id: str | None = None,
    state_id: str | None = None,
    project_id: str | None = None,
    cycle_id: str | None = None,
    limit: int = 20,
) -> list[Issue]:
    """List issues with optional filtering."""
    filters = []
    variables: dict[str, Any] = {"first": limit}

    if team_key:
        variables["teamKey"] = team_key.upper()
        filters.append("team: { key: { eq: $teamKey } }")
    if assignee_id:
        variables["assigneeId"] = assignee_id
        filters.append("assignee: { id: { eq: $assigneeId } }")
    if state_id:
        variables["stateId"] = state_id
        filters.append("state: { id: { eq: $stateId } }")
    if project_id:
        variables["projectId"] = project_id
        filters.append("project: { id: { eq: $projectId } }")
    if cycle_id:
        variables["cycleId"] = cycle_id
        filters.append("cycle: { id: { eq: $cycleId } }")

    filter_str = f"filter: {{ {', '.join(filters)} }}" if filters else ""
    var_decl = ", ".join(
        [
            "$first: Int!",
            *(["$teamKey: String!"] if team_key else []),
            *(["$assigneeId: ID!"] if assignee_id else []),
            *(["$stateId: ID!"] if state_id else []),
            *(["$projectId: ID!"] if project_id else []),
            *(["$cycleId: ID!"] if cycle_id else []),
        ]
    )

    query = f"query({var_decl}) {{ issues(first: $first, {filter_str}) {{ nodes {{ {ISSUE_FIELDS} }} }} }}"
    data = await gql(query, variables)
    return [parse_issue(i) for i in data.get("issues", {}).get("nodes", [])]


@tool(description="Get an issue by identifier (e.g., ENG-123)")
async def get_issue(identifier: str) -> Issue | None:
    """Get a specific issue."""
    data = await gql(
        f"query($id: String!) {{ issues(filter: {{ identifier: {{ eq: $id }} }}, first: 1) {{ nodes {{ {ISSUE_FIELDS} }} }} }}",
        {"id": identifier.upper()},
    )
    issues = data.get("issues", {}).get("nodes", [])
    return parse_issue(issues[0]) if issues else None


@tool(description="Search issues by text")
async def search_issues(query: str, limit: int = 20) -> list[Issue]:
    """Full-text search for issues."""
    data = await gql(
        f"query($q: String!, $first: Int!) {{ issueSearch(query: $q, first: $first) {{ nodes {{ {ISSUE_FIELDS} }} }} }}",
        {"q": query, "first": limit},
    )
    return [parse_issue(i) for i in data.get("issueSearch", {}).get("nodes", [])]


@tool(description="Create a new issue")
async def create_issue(
    title: str,
    team_key: str,
    description: str | None = None,
    priority: IssuePriority | None = None,
    estimate: float | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    state_id: str | None = None,
    project_id: str | None = None,
    cycle_id: str | None = None,
    label_ids: list[str] | None = None,
    parent_id: str | None = None,
) -> Issue:
    """Create a new issue."""
    team_id = await get_team_id(team_key)

    input_data: dict[str, Any] = {"title": title, "teamId": team_id}
    if description:
        input_data["description"] = description
    if priority is not None:
        input_data["priority"] = priority.value
    if estimate is not None:
        input_data["estimate"] = estimate
    if due_date:
        input_data["dueDate"] = due_date
    if assignee_id:
        input_data["assigneeId"] = assignee_id
    if state_id:
        input_data["stateId"] = state_id
    if project_id:
        input_data["projectId"] = project_id
    if cycle_id:
        input_data["cycleId"] = cycle_id
    if label_ids:
        input_data["labelIds"] = label_ids
    if parent_id:
        input_data["parentId"] = parent_id

    data = await gql(
        f"mutation($input: IssueCreateInput!) {{ issueCreate(input: $input) {{ success issue {{ {ISSUE_FIELDS} }} }} }}",
        {"input": input_data},
    )
    result = data.get("issueCreate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to create issue")
    return parse_issue(result["issue"])


@tool(description="Update an issue")
async def update_issue(
    identifier: str,
    title: str | None = None,
    description: str | None = None,
    priority: IssuePriority | None = None,
    estimate: float | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    state_id: str | None = None,
    project_id: str | None = None,
    cycle_id: str | None = None,
    label_ids: list[str] | None = None,
    parent_id: str | None = None,
) -> Issue:
    """Update an existing issue. Use empty string to clear optional fields."""
    issue_id = await get_issue_id(identifier)

    input_data: dict[str, Any] = {}
    if title is not None:
        input_data["title"] = title
    if description is not None:
        input_data["description"] = description
    if priority is not None:
        input_data["priority"] = priority.value
    if estimate is not None:
        input_data["estimate"] = estimate if estimate >= 0 else None
    if due_date is not None:
        input_data["dueDate"] = due_date if due_date else None
    if assignee_id is not None:
        input_data["assigneeId"] = assignee_id if assignee_id else None
    if state_id is not None:
        input_data["stateId"] = state_id
    if project_id is not None:
        input_data["projectId"] = project_id if project_id else None
    if cycle_id is not None:
        input_data["cycleId"] = cycle_id if cycle_id else None
    if label_ids is not None:
        input_data["labelIds"] = label_ids
    if parent_id is not None:
        input_data["parentId"] = parent_id if parent_id else None

    if not input_data:
        raise LinearAPIError("No fields to update")

    data = await gql(
        f"mutation($id: ID!, $input: IssueUpdateInput!) {{ issueUpdate(id: $id, input: $input) {{ success issue {{ {ISSUE_FIELDS} }} }} }}",
        {"id": issue_id, "input": input_data},
    )
    result = data.get("issueUpdate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to update issue")
    return parse_issue(result["issue"])


@tool(description="Delete an issue")
async def delete_issue(identifier: str) -> bool:
    """Permanently delete an issue."""
    issue_id = await get_issue_id(identifier)
    data = await gql("mutation($id: ID!) { issueDelete(id: $id) { success } }", {"id": issue_id})
    return data.get("issueDelete", {}).get("success", False)


# -----------------------------------------------------------------------------
# Project Tools
# -----------------------------------------------------------------------------


@tool(description="List projects")
async def list_projects(team_key: str | None = None, limit: int = 50) -> list[Project]:
    """List projects, optionally filtered by team."""
    if team_key:
        team_id = await get_team_id(team_key)
        data = await gql(
            "query($first: Int!, $teamId: ID!) { projects(first: $first, filter: { accessibleTeams: { id: { eq: $teamId } } }) { nodes { id name description state url } } }",
            {"first": limit, "teamId": team_id},
        )
    else:
        data = await gql(
            "query($first: Int!) { projects(first: $first) { nodes { id name description state url } } }",
            {"first": limit},
        )
    return [
        Project(
            id=p["id"],
            name=p["name"],
            description=p.get("description"),
            state=p.get("state"),
            url=p.get("url"),
        )
        for p in data.get("projects", {}).get("nodes", [])
    ]


@tool(description="Create a project")
async def create_project(
    name: str,
    team_keys: list[str],
    description: str | None = None,
) -> Project:
    """Create a new project."""
    team_ids = [await get_team_id(k) for k in team_keys]
    input_data: dict[str, Any] = {"name": name, "teamIds": team_ids}
    if description:
        input_data["description"] = description

    data = await gql(
        "mutation($input: ProjectCreateInput!) { projectCreate(input: $input) { success project { id name description state url } } }",
        {"input": input_data},
    )
    result = data.get("projectCreate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to create project")
    p = result["project"]
    return Project(
        id=p["id"],
        name=p["name"],
        description=p.get("description"),
        state=p.get("state"),
        url=p.get("url"),
    )


@tool(description="Update a project")
async def update_project(
    project_id: str,
    name: str | None = None,
    description: str | None = None,
    state: str | None = None,
) -> Project:
    """Update a project. State can be: planned, backlog, started, paused, completed, canceled."""
    input_data: dict[str, Any] = {}
    if name is not None:
        input_data["name"] = name
    if description is not None:
        input_data["description"] = description
    if state is not None:
        input_data["state"] = state

    if not input_data:
        raise LinearAPIError("No fields to update")

    data = await gql(
        "mutation($id: ID!, $input: ProjectUpdateInput!) { projectUpdate(id: $id, input: $input) { success project { id name description state url } } }",
        {"id": project_id, "input": input_data},
    )
    result = data.get("projectUpdate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to update project")
    p = result["project"]
    return Project(
        id=p["id"],
        name=p["name"],
        description=p.get("description"),
        state=p.get("state"),
        url=p.get("url"),
    )


# -----------------------------------------------------------------------------
# Cycle Tools
# -----------------------------------------------------------------------------


@tool(description="List cycles for a team")
async def list_cycles(team_key: str, limit: int = 20) -> list[Cycle]:
    """List cycles (sprints) for a team."""
    team_id = await get_team_id(team_key)
    data = await gql(
        "query($teamId: ID!, $first: Int!) { cycles(first: $first, filter: { team: { id: { eq: $teamId } } }) { nodes { id name number startsAt endsAt } } }",
        {"teamId": team_id, "first": limit},
    )
    return [
        Cycle(
            id=c["id"],
            name=c.get("name"),
            number=c["number"],
            starts_at=c.get("startsAt"),
            ends_at=c.get("endsAt"),
        )
        for c in data.get("cycles", {}).get("nodes", [])
    ]


@tool(description="Create a cycle")
async def create_cycle(
    team_key: str,
    starts_at: str,
    ends_at: str,
    name: str | None = None,
) -> Cycle:
    """Create a new cycle. Dates in ISO 8601 format."""
    team_id = await get_team_id(team_key)
    input_data: dict[str, Any] = {"teamId": team_id, "startsAt": starts_at, "endsAt": ends_at}
    if name:
        input_data["name"] = name

    data = await gql(
        "mutation($input: CycleCreateInput!) { cycleCreate(input: $input) { success cycle { id name number startsAt endsAt } } }",
        {"input": input_data},
    )
    result = data.get("cycleCreate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to create cycle")
    c = result["cycle"]
    return Cycle(
        id=c["id"],
        name=c.get("name"),
        number=c["number"],
        starts_at=c.get("startsAt"),
        ends_at=c.get("endsAt"),
    )


# -----------------------------------------------------------------------------
# Comment Tools
# -----------------------------------------------------------------------------


@tool(description="List comments on an issue")
async def list_comments(identifier: str, limit: int = 50) -> list[Comment]:
    """List comments on an issue."""
    issue_id = await get_issue_id(identifier)
    data = await gql(
        "query($id: ID!, $first: Int!) { issue(id: $id) { comments(first: $first) { nodes { id body createdAt user { id name } } } } }",
        {"id": issue_id, "first": limit},
    )
    return [
        Comment(
            id=c["id"],
            body=c["body"],
            user=c.get("user", {}).get("name") if c.get("user") else None,
            user_id=c.get("user", {}).get("id") if c.get("user") else None,
            created_at=c.get("createdAt"),
        )
        for c in data.get("issue", {}).get("comments", {}).get("nodes", [])
    ]


@tool(description="Create a comment on an issue")
async def create_comment(identifier: str, body: str) -> Comment:
    """Add a comment to an issue."""
    issue_id = await get_issue_id(identifier)
    data = await gql(
        "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success comment { id body createdAt user { id name } } } }",
        {"input": {"issueId": issue_id, "body": body}},
    )
    result = data.get("commentCreate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to create comment")
    c = result["comment"]
    return Comment(
        id=c["id"],
        body=c["body"],
        user=c.get("user", {}).get("name") if c.get("user") else None,
        user_id=c.get("user", {}).get("id") if c.get("user") else None,
        created_at=c.get("createdAt"),
    )


@tool(description="Update a comment")
async def update_comment(comment_id: str, body: str) -> Comment:
    """Update a comment."""
    data = await gql(
        "mutation($id: ID!, $input: CommentUpdateInput!) { commentUpdate(id: $id, input: $input) { success comment { id body createdAt user { id name } } } }",
        {"id": comment_id, "input": {"body": body}},
    )
    result = data.get("commentUpdate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to update comment")
    c = result["comment"]
    return Comment(
        id=c["id"],
        body=c["body"],
        user=c.get("user", {}).get("name") if c.get("user") else None,
        user_id=c.get("user", {}).get("id") if c.get("user") else None,
        created_at=c.get("createdAt"),
    )


@tool(description="Delete a comment")
async def delete_comment(comment_id: str) -> bool:
    """Delete a comment."""
    data = await gql("mutation($id: ID!) { commentDelete(id: $id) { success } }", {"id": comment_id})
    return data.get("commentDelete", {}).get("success", False)


# -----------------------------------------------------------------------------
# Label Tools
# -----------------------------------------------------------------------------


@tool(description="List labels")
async def list_labels(team_key: str | None = None, limit: int = 100) -> list[Label]:
    """List labels, optionally filtered by team."""
    if team_key:
        team_id = await get_team_id(team_key)
        data = await gql(
            "query($first: Int!, $teamId: ID!) { issueLabels(first: $first, filter: { team: { id: { eq: $teamId } } }) { nodes { id name color } } }",
            {"first": limit, "teamId": team_id},
        )
    else:
        data = await gql(
            "query($first: Int!) { issueLabels(first: $first) { nodes { id name color } } }",
            {"first": limit},
        )
    return [
        Label(id=label["id"], name=label["name"], color=label.get("color"))
        for label in data.get("issueLabels", {}).get("nodes", [])
    ]


@tool(description="Create a label")
async def create_label(name: str, team_key: str, color: str | None = None) -> Label:
    """Create a new label."""
    team_id = await get_team_id(team_key)
    input_data: dict[str, Any] = {"name": name, "teamId": team_id}
    if color:
        input_data["color"] = color

    data = await gql(
        "mutation($input: IssueLabelCreateInput!) { issueLabelCreate(input: $input) { success issueLabel { id name color } } }",
        {"input": input_data},
    )
    result = data.get("issueLabelCreate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to create label")
    label = result["issueLabel"]
    return Label(id=label["id"], name=label["name"], color=label.get("color"))


@tool(description="Delete a label")
async def delete_label(label_id: str) -> bool:
    """Delete a label."""
    data = await gql("mutation($id: ID!) { issueLabelDelete(id: $id) { success } }", {"id": label_id})
    return data.get("issueLabelDelete", {}).get("success", False)


# -----------------------------------------------------------------------------
# Document Tools
# -----------------------------------------------------------------------------


@tool(description="List documents")
async def list_documents(project_id: str | None = None, limit: int = 50) -> list[Document]:
    """List documents, optionally filtered by project."""
    if project_id:
        data = await gql(
            "query($first: Int!, $projectId: ID!) { documents(first: $first, filter: { project: { id: { eq: $projectId } } }) { nodes { id title content url project { id } } } }",
            {"first": limit, "projectId": project_id},
        )
    else:
        data = await gql(
            "query($first: Int!) { documents(first: $first) { nodes { id title content url project { id } } } }",
            {"first": limit},
        )
    return [
        Document(
            id=d["id"],
            title=d["title"],
            content=d.get("content"),
            project_id=d.get("project", {}).get("id") if d.get("project") else None,
            url=d.get("url"),
        )
        for d in data.get("documents", {}).get("nodes", [])
    ]


@tool(description="Create a document")
async def create_document(title: str, project_id: str, content: str | None = None) -> Document:
    """Create a new document in a project."""
    input_data: dict[str, Any] = {"title": title, "projectId": project_id}
    if content:
        input_data["content"] = content

    data = await gql(
        "mutation($input: DocumentCreateInput!) { documentCreate(input: $input) { success document { id title content url project { id } } } }",
        {"input": input_data},
    )
    result = data.get("documentCreate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to create document")
    d = result["document"]
    return Document(
        id=d["id"],
        title=d["title"],
        content=d.get("content"),
        project_id=d.get("project", {}).get("id") if d.get("project") else None,
        url=d.get("url"),
    )


@tool(description="Update a document")
async def update_document(document_id: str, title: str | None = None, content: str | None = None) -> Document:
    """Update a document."""
    input_data: dict[str, Any] = {}
    if title is not None:
        input_data["title"] = title
    if content is not None:
        input_data["content"] = content

    if not input_data:
        raise LinearAPIError("No fields to update")

    data = await gql(
        "mutation($id: ID!, $input: DocumentUpdateInput!) { documentUpdate(id: $id, input: $input) { success document { id title content url project { id } } } }",
        {"id": document_id, "input": input_data},
    )
    result = data.get("documentUpdate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to update document")
    d = result["document"]
    return Document(
        id=d["id"],
        title=d["title"],
        content=d.get("content"),
        project_id=d.get("project", {}).get("id") if d.get("project") else None,
        url=d.get("url"),
    )


@tool(description="Delete a document")
async def delete_document(document_id: str) -> bool:
    """Delete a document."""
    data = await gql("mutation($id: ID!) { documentDelete(id: $id) { success } }", {"id": document_id})
    return data.get("documentDelete", {}).get("success", False)


# -----------------------------------------------------------------------------
# Webhook Tools
# -----------------------------------------------------------------------------


@tool(description="List webhooks")
async def list_webhooks(limit: int = 50) -> list[Webhook]:
    """List all webhooks."""
    data = await gql(
        "query($first: Int!) { webhooks(first: $first) { nodes { id label url enabled resourceTypes } } }",
        {"first": limit},
    )
    return [
        Webhook(
            id=w["id"],
            label=w.get("label"),
            url=w["url"],
            enabled=w.get("enabled", True),
            resource_types=w.get("resourceTypes", []),
        )
        for w in data.get("webhooks", {}).get("nodes", [])
    ]


@tool(description="Create a webhook")
async def create_webhook(
    url: str,
    resource_types: list[str],
    team_key: str | None = None,
    label: str | None = None,
) -> Webhook:
    """Create a webhook. Resource types: Issue, Comment, Project, Cycle, Label, etc."""
    input_data: dict[str, Any] = {"url": url, "resourceTypes": resource_types}
    if team_key:
        input_data["teamId"] = await get_team_id(team_key)
    if label:
        input_data["label"] = label

    data = await gql(
        "mutation($input: WebhookCreateInput!) { webhookCreate(input: $input) { success webhook { id label url enabled resourceTypes } } }",
        {"input": input_data},
    )
    result = data.get("webhookCreate", {})
    if not result.get("success"):
        raise LinearAPIError("Failed to create webhook")
    w = result["webhook"]
    return Webhook(
        id=w["id"],
        label=w.get("label"),
        url=w["url"],
        enabled=w.get("enabled", True),
        resource_types=w.get("resourceTypes", []),
    )


@tool(description="Delete a webhook")
async def delete_webhook(webhook_id: str) -> bool:
    """Delete a webhook."""
    data = await gql("mutation($id: ID!) { webhookDelete(id: $id) { success } }", {"id": webhook_id})
    return data.get("webhookDelete", {}).get("success", False)


# -----------------------------------------------------------------------------
# Tool Export
# -----------------------------------------------------------------------------

linear_tools: list[Tool] = [
    # User & Team
    get_me,
    list_users,
    list_teams,
    list_workflow_states,
    # Issues
    list_issues,
    get_issue,
    search_issues,
    create_issue,
    update_issue,
    delete_issue,
    # Projects
    list_projects,
    create_project,
    update_project,
    # Cycles
    list_cycles,
    create_cycle,
    # Comments
    list_comments,
    create_comment,
    update_comment,
    delete_comment,
    # Labels
    list_labels,
    create_label,
    delete_label,
    # Documents
    list_documents,
    create_document,
    update_document,
    delete_document,
    # Webhooks
    list_webhooks,
    create_webhook,
    delete_webhook,
]
