from __future__ import annotations

"""Minimal workflow adapter to emulate AstrBot's upcoming workflow mode.

This module provides lightweight placeholder classes so existing plugins can
build workflow definitions without depending on the real framework. It does
not implement any scheduling logic but offers compatible data structures that
can be extended once the official workflow engine becomes available."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class WorkflowData:
    """Represents a workflow definition.

    Attributes
    ----------
    name:
        Human readable workflow name.
    nodes:
        Mapping of node name to callable implementation.
    start:
        Entry node name.
    end:
        Exit node name.
    """

    name: str
    nodes: Dict[str, Callable[[WorkflowSession, Any], Any]] = field(default_factory=dict)
    start: str = "start"
    end: str = "end"


@dataclass
class WorkflowSession:
    """Holds per-session variables for a workflow run."""

    session_id: str
    variables: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowRun:
    """Simple run state container."""

    workflow: WorkflowData
    session: WorkflowSession
    status: str = "pending"


class WorkflowEngine:
    """Very small engine executing workflow nodes sequentially."""

    def __init__(self, workflow: WorkflowData) -> None:
        self.workflow = workflow

    async def run(self, session: WorkflowSession, *args: Any, **kwargs: Any) -> Any:
        node_name = self.workflow.start
        result: Any = None
        while node_name:
            node = self.workflow.nodes.get(node_name)
            if not node:
                raise RuntimeError(f"Unknown node: {node_name}")
            result = await node(session, *args, **kwargs)
            if node_name == self.workflow.end:
                break
            node_name = result if isinstance(result, str) else self.workflow.end
        return result
