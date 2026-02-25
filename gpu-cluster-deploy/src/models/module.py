"""
Module Definition Data Models

This module defines data models for module definitions, module groups,
and execution plans used by the modular deployment framework.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import json
import yaml


class ExecutionStatus(Enum):
    """Status of module or plan execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


class PlanFormat(Enum):
    """Supported execution plan formats."""
    YAML = "yaml"
    JSON = "json"


@dataclass
class ModuleDefinition:
    """
    Definition of a deployment module in an execution plan.

    This represents a module configuration within an execution plan,
    not the module class itself.
    """
    name: str
    module_class: str  # Name of the registered module class
    enabled: bool = True
    category: str = "custom"
    config: Dict[str, Any] = field(default_factory=dict)
    node_filter: Optional[List[str]] = None  # If set, only run on these nodes
    depends_on: List[str] = field(default_factory=list)  # Module names this depends on
    continue_on_failure: bool = False
    timeout: int = 300  # Timeout in seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "module_class": self.module_class,
            "enabled": self.enabled,
            "category": self.category,
            "config": self.config,
            "node_filter": self.node_filter,
            "depends_on": self.depends_on,
            "continue_on_failure": self.continue_on_failure,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModuleDefinition":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            module_class=data["module_class"],
            enabled=data.get("enabled", True),
            category=data.get("category", "custom"),
            config=data.get("config", {}),
            node_filter=data.get("node_filter"),
            depends_on=data.get("depends_on", []),
            continue_on_failure=data.get("continue_on_failure", False),
            timeout=data.get("timeout", 300),
        )


@dataclass
class ModuleGroup:
    """
    A group of modules that can be executed together.

    Groups can be used to organize modules logically and enable
    batch execution of related modules.
    """
    name: str
    description: str = ""
    modules: List[str] = field(default_factory=list)  # Module names
    parallel: bool = False  # Whether to execute modules in parallel
    stop_on_failure: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "modules": self.modules,
            "parallel": self.parallel,
            "stop_on_failure": self.stop_on_failure,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModuleGroup":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            modules=data.get("modules", []),
            parallel=data.get("parallel", False),
            stop_on_failure=data.get("stop_on_failure", True),
        )


@dataclass
class ExecutionPlan:
    """
    A complete execution plan for deployment.

    An execution plan defines a set of modules to execute,
    their configurations, and execution order.
    """
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modules: List[ModuleDefinition] = field(default_factory=list)
    groups: List[ModuleGroup] = field(default_factory=list)
    global_config: Dict[str, Any] = field(default_factory=dict)
    execution_order: List[str] = field(default_factory=list)  # Module names in order
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_module(self, module: ModuleDefinition) -> None:
        """Add a module to the plan."""
        self.modules.append(module)
        if module.name not in self.execution_order:
            self.execution_order.append(module.name)

    def remove_module(self, name: str) -> bool:
        """Remove a module from the plan by name."""
        for i, module in enumerate(self.modules):
            if module.name == name:
                self.modules.pop(i)
                if name in self.execution_order:
                    self.execution_order.remove(name)
                return True
        return False

    def get_module(self, name: str) -> Optional[ModuleDefinition]:
        """Get a module by name."""
        for module in self.modules:
            if module.name == name:
                return module
        return None

    def get_modules_by_category(self, category: str) -> List[ModuleDefinition]:
        """Get all modules in a category."""
        return [m for m in self.modules if m.category == category]

    def get_enabled_modules(self) -> List[ModuleDefinition]:
        """Get all enabled modules."""
        return [m for m in self.modules if m.enabled]

    def get_group(self, name: str) -> Optional[ModuleGroup]:
        """Get a group by name."""
        for group in self.groups:
            if group.name == name:
                return group
        return None

    def resolve_dependencies(self) -> List[str]:
        """
        Resolve module dependencies and return execution order.

        Uses topological sort to determine the correct execution order
        based on module dependencies.

        Returns:
            List of module names in dependency order

        Raises:
            ValueError: If circular dependencies are detected
        """
        # Build dependency graph
        graph: Dict[str, List[str]] = {}
        in_degree: Dict[str, int] = {}

        for module in self.modules:
            if module.name not in graph:
                graph[module.name] = []
                in_degree[module.name] = 0

            for dep in module.depends_on:
                if dep not in graph:
                    graph[dep] = []
                    in_degree[dep] = 0
                graph[dep].append(module.name)
                in_degree[module.name] += 1

        # Kahn's algorithm for topological sort
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for neighbor in graph.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(graph):
            raise ValueError("Circular dependency detected in module definitions")

        # Filter to only include modules in this plan
        return [name for name in result if name in {m.name for m in self.modules}]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "created_at": self.created_at,
            "modules": [m.to_dict() for m in self.modules],
            "groups": [g.to_dict() for g in self.groups],
            "global_config": self.global_config,
            "execution_order": self.execution_order,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            modules=[ModuleDefinition.from_dict(m) for m in data.get("modules", [])],
            groups=[ModuleGroup.from_dict(g) for g in data.get("groups", [])],
            global_config=data.get("global_config", {}),
            execution_order=data.get("execution_order", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ExecutionResult:
    """
    Result of executing an execution plan.

    Contains the results of all module executions and overall status.
    """
    plan_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_modules: int = 0
    completed_modules: int = 0
    failed_modules: int = 0
    skipped_modules: int = 0
    module_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plan_name": self.plan_name,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_modules": self.total_modules,
            "completed_modules": self.completed_modules,
            "failed_modules": self.failed_modules,
            "skipped_modules": self.skipped_modules,
            "module_results": self.module_results,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionResult":
        """Create from dictionary."""
        return cls(
            plan_name=data["plan_name"],
            status=ExecutionStatus(data["status"]),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            total_modules=data.get("total_modules", 0),
            completed_modules=data.get("completed_modules", 0),
            failed_modules=data.get("failed_modules", 0),
            skipped_modules=data.get("skipped_modules", 0),
            module_results=data.get("module_results", {}),
            error=data.get("error"),
        )
