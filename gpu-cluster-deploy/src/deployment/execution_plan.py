"""
Execution Plan Serialization

Provides functionality for importing/exporting execution plans in
YAML and JSON formats.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import logging
import yaml

from src.deployment.core import ModuleRegistry
from src.models.module import (
    ExecutionPlan,
    ExecutionResult,
    ExecutionStatus,
    ModuleDefinition,
    ModuleGroup,
    PlanFormat,
)

logger = logging.getLogger(__name__)


class ExecutionPlanSerializer:
    """
    Serializer for execution plans.

    Supports YAML and JSON formats for import/export.
    """

    @staticmethod
    def serialize(
        plan: ExecutionPlan,
        format: PlanFormat = PlanFormat.YAML,
    ) -> str:
        """
        Serialize an execution plan to string.

        Args:
            plan: The execution plan to serialize
            format: Output format (YAML or JSON)

        Returns:
            Serialized plan as string
        """
        data = plan.to_dict()

        if format == PlanFormat.YAML:
            return yaml.dump(data, default_flow_style=False, sort_keys=False)
        else:
            return json.dumps(data, indent=2)

    @staticmethod
    def deserialize(
        content: str,
        format: PlanFormat = PlanFormat.YAML,
    ) -> ExecutionPlan:
        """
        Deserialize an execution plan from string.

        Args:
            content: The serialized plan content
            format: Input format (YAML or JSON)

        Returns:
            ExecutionPlan instance
        """
        if format == PlanFormat.YAML:
            data = yaml.safe_load(content)
        else:
            data = json.loads(content)

        return ExecutionPlan.from_dict(data)

    @staticmethod
    def save(
        plan: ExecutionPlan,
        path: Union[str, Path],
        format: Optional[PlanFormat] = None,
    ) -> None:
        """
        Save an execution plan to a file.

        Args:
            plan: The execution plan to save
            path: File path to save to
            format: Output format (inferred from extension if not specified)
        """
        path = Path(path)

        # Infer format from extension if not specified
        if format is None:
            ext = path.suffix.lower()
            if ext in (".yaml", ".yml"):
                format = PlanFormat.YAML
            elif ext == ".json":
                format = PlanFormat.JSON
            else:
                format = PlanFormat.YAML  # Default to YAML

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize and write
        content = ExecutionPlanSerializer.serialize(plan, format)
        path.write_text(content)

        logger.info(f"Saved execution plan '{plan.name}' to {path}")

    @staticmethod
    def load(
        path: Union[str, Path],
        format: Optional[PlanFormat] = None,
    ) -> ExecutionPlan:
        """
        Load an execution plan from a file.

        Args:
            path: File path to load from
            format: Input format (inferred from extension if not specified)

        Returns:
            ExecutionPlan instance
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Execution plan file not found: {path}")

        # Infer format from extension if not specified
        if format is None:
            ext = path.suffix.lower()
            if ext in (".yaml", ".yml"):
                format = PlanFormat.YAML
            elif ext == ".json":
                format = PlanFormat.JSON
            else:
                format = PlanFormat.YAML  # Default to YAML

        content = path.read_text()
        plan = ExecutionPlanSerializer.deserialize(content, format)

        logger.info(f"Loaded execution plan '{plan.name}' from {path}")
        return plan

    @staticmethod
    def validate(plan: ExecutionPlan) -> List[str]:
        """
        Validate an execution plan.

        Args:
            plan: The execution plan to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check required fields
        if not plan.name:
            errors.append("Plan name is required")

        # Validate modules
        for module in plan.modules:
            # Check if module class exists
            if ModuleRegistry.get(module.module_class) is None:
                errors.append(
                    f"Module class '{module.module_class}' not found for module '{module.name}'"
                )

            # Check for invalid dependencies
            for dep in module.depends_on:
                if plan.get_module(dep) is None:
                    errors.append(
                        f"Module '{module.name}' depends on non-existent module '{dep}'"
                    )

        # Check for circular dependencies
        try:
            plan.resolve_dependencies()
        except ValueError as e:
            errors.append(str(e))

        # Validate groups
        for group in plan.groups:
            for module_name in group.modules:
                if plan.get_module(module_name) is None:
                    errors.append(
                        f"Group '{group.name}' references non-existent module '{module_name}'"
                    )

        return errors


class ExecutionResultSerializer:
    """
    Serializer for execution results.
    """

    @staticmethod
    def serialize(result: ExecutionResult, format: PlanFormat = PlanFormat.JSON) -> str:
        """Serialize an execution result to string."""
        data = result.to_dict()
        if format == PlanFormat.YAML:
            return yaml.dump(data, default_flow_style=False, sort_keys=False)
        else:
            return json.dumps(data, indent=2)

    @staticmethod
    def deserialize(content: str, format: PlanFormat = PlanFormat.JSON) -> ExecutionResult:
        """Deserialize an execution result from string."""
        if format == PlanFormat.YAML:
            data = yaml.safe_load(content)
        else:
            data = json.loads(content)
        return ExecutionResult.from_dict(data)

    @staticmethod
    def save(result: ExecutionResult, path: Union[str, Path], format: Optional[PlanFormat] = None) -> None:
        """Save an execution result to a file."""
        path = Path(path)
        if format is None:
            ext = path.suffix.lower()
            format = PlanFormat.YAML if ext in (".yaml", ".yml") else PlanFormat.JSON

        path.parent.mkdir(parents=True, exist_ok=True)
        content = ExecutionResultSerializer.serialize(result, format)
        path.write_text(content)

    @staticmethod
    def load(path: Union[str, Path], format: Optional[PlanFormat] = None) -> ExecutionResult:
        """Load an execution result from a file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Execution result file not found: {path}")

        if format is None:
            ext = path.suffix.lower()
            format = PlanFormat.YAML if ext in (".yaml", ".yml") else PlanFormat.JSON

        content = path.read_text()
        return ExecutionResultSerializer.deserialize(content, format)


class PlanBuilder:
    """
    Builder for creating execution plans programmatically.
    """

    def __init__(self, name: str):
        """Initialize the builder with a plan name."""
        self._plan = ExecutionPlan(name=name)

    def with_description(self, description: str) -> "PlanBuilder":
        """Set the plan description."""
        self._plan.description = description
        return self

    def with_version(self, version: str) -> "PlanBuilder":
        """Set the plan version."""
        self._plan.version = version
        return self

    def with_author(self, author: str) -> "PlanBuilder":
        """Set the plan author."""
        self._plan.author = author
        return self

    def with_global_config(self, config: Dict[str, Any]) -> "PlanBuilder":
        """Set the global configuration."""
        self._plan.global_config = config
        return self

    def add_module(
        self,
        name: str,
        module_class: str,
        category: str = "custom",
        enabled: bool = True,
        config: Optional[Dict[str, Any]] = None,
        node_filter: Optional[List[str]] = None,
        depends_on: Optional[List[str]] = None,
        continue_on_failure: bool = False,
        timeout: int = 300,
    ) -> "PlanBuilder":
        """Add a module to the plan."""
        module = ModuleDefinition(
            name=name,
            module_class=module_class,
            category=category,
            enabled=enabled,
            config=config or {},
            node_filter=node_filter,
            depends_on=depends_on or [],
            continue_on_failure=continue_on_failure,
            timeout=timeout,
        )
        self._plan.add_module(module)
        return self

    def add_group(
        self,
        name: str,
        modules: List[str],
        description: str = "",
        parallel: bool = False,
        stop_on_failure: bool = True,
    ) -> "PlanBuilder":
        """Add a module group to the plan."""
        group = ModuleGroup(
            name=name,
            description=description,
            modules=modules,
            parallel=parallel,
            stop_on_failure=stop_on_failure,
        )
        self._plan.groups.append(group)
        return self

    def with_metadata(self, metadata: Dict[str, Any]) -> "PlanBuilder":
        """Set additional metadata."""
        self._plan.metadata = metadata
        return self

    def build(self) -> ExecutionPlan:
        """Build and return the execution plan."""
        return self._plan


def create_default_plan() -> ExecutionPlan:
    """
    Create a default execution plan with all registered modules.

    Returns:
        ExecutionPlan with all modules in default order
    """
    builder = PlanBuilder("default-full-deployment")
    builder.with_description("Full GPU cluster deployment with all modules")
    builder.with_version("1.0.0")

    # Get all modules from registry and add them
    categories = ModuleRegistry.list_categories()

    # Define category order
    category_order = [
        "system",
        "storage",
        "network",
        "gpu",
        "security",
        "monitoring",
        "custom",
    ]

    added_modules = []
    for cat_name in category_order:
        # Find the category enum
        from src.deployment.core import ModuleCategory
        for cat in ModuleCategory:
            if cat.value == cat_name:
                module_names = categories.get(cat, [])
                for name in module_names:
                    module_class = ModuleRegistry.get(name)
                    if module_class:
                        metadata = module_class.get_metadata()
                        builder.add_module(
                            name=name,
                            module_class=name,
                            category=cat_name,
                            description=metadata.description,
                            depends_on=[m for m in added_modules if m in metadata.dependencies],
                        )
                        added_modules.append(name)
                break

    return builder.build()
