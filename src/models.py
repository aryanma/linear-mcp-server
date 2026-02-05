# Copyright (c) 2026 Dedalus Labs, Inc. and its contributors
# SPDX-License-Identifier: MIT

"""Pydantic models for Linear API responses."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IssuePriority(int, Enum):
    """Issue priority (0=none, 1=urgent, 4=low)."""

    NO_PRIORITY = 0
    URGENT = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class User(BaseModel):
    id: str
    name: str
    email: str | None = None
    active: bool = True


class Team(BaseModel):
    id: str
    name: str
    key: str


class WorkflowState(BaseModel):
    id: str
    name: str
    type: str  # backlog, unstarted, started, completed, canceled


class Issue(BaseModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    state: str | None = None
    state_id: str | None = None
    priority: int | None = None
    estimate: float | None = None
    due_date: str | None = None
    assignee: str | None = None
    assignee_id: str | None = None
    project: str | None = None
    project_id: str | None = None
    cycle_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    label_ids: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class Project(BaseModel):
    id: str
    name: str
    description: str | None = None
    state: str | None = None
    url: str | None = None


class Cycle(BaseModel):
    id: str
    name: str | None = None
    number: int
    starts_at: str | None = None
    ends_at: str | None = None


class Comment(BaseModel):
    id: str
    body: str
    user: str | None = None
    user_id: str | None = None
    created_at: str | None = None


class Label(BaseModel):
    id: str
    name: str
    color: str | None = None


class Document(BaseModel):
    id: str
    title: str
    content: str | None = None
    project_id: str | None = None
    url: str | None = None


class Webhook(BaseModel):
    id: str
    label: str | None = None
    url: str
    enabled: bool = True
    resource_types: list[str] = Field(default_factory=list)
