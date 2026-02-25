"""
Tests for the modular deployment framework.

Tests cover:
- ModuleRegistry: registration, retrieval, categorization
- ModuleManager: execution, validation, results
- StepAdapter: adaptation of BaseStep to DeployModule
- ExecutionPlan: serialization, validation, dependency resolution
"""

import pytest
from dataclasses import dataclass
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.deployment.core import (
    DeployModule,
    ModuleCategory,
    ModuleMetadata,
    ModuleRegistry,
    ModuleResult,
    module,
)
from src.deployment.module_manager import ModuleManager
from src.deployment.step_adapter import StepAdapter, StepAdapterFactory, get_step_category
from src.deployment.execution_plan import (
    ExecutionPlan,
    ExecutionPlanSerializer,
    PlanBuilder,
)
from src.models.module import (
    ModuleDefinition,
    ModuleGroup,
    ExecutionResult,
    ExecutionStatus,
)
from src.steps.base import BaseStep, StepResult, StepStatus


# ============== Test Fixtures ==============

@dataclass
class MockNodeConfig:
    """Mock node configuration for testing."""
    hostname: str
    ip: str = "192.168.1.1"


class MockDeployModule(DeployModule):
    """Mock module for testing."""

    metadata = ModuleMetadata(
        name="mock_module",
        category=ModuleCategory.SYSTEM,
        description="Mock module for testing",
    )

    def execute(self, node_config: Any, **kwargs) -> ModuleResult:
        return ModuleResult(
            success=True,
            module_name=self.metadata.name,
            message="Mock execution successful",
        )


class FailingDeployModule(DeployModule):
    """Mock module that fails for testing."""

    metadata = ModuleMetadata(
        name="failing_module",
        category=ModuleCategory.SYSTEM,
        description="Mock module that fails",
    )

    def execute(self, node_config: Any, **kwargs) -> ModuleResult:
        return ModuleResult(
            success=False,
            module_name=self.metadata.name,
            message="Mock execution failed",
            error="Test failure",
        )


class MockBaseStep(BaseStep):
    """Mock BaseStep for testing the adapter."""

    step_id = "test_step"
    step_name = "Test Step"
    step_description = "A test step for unit testing"
    requires_sudo = False
    requires_reboot = False

    def __init__(self, config=None, ssh_manager=None, batch_executor=None, logger=None):
        self.config = config
        self.ssh_manager = ssh_manager
        self.batch_executor = batch_executor
        self.logger = logger or MagicMock()
        self._status = StepStatus.PENDING
        self._retry_count = 0

    def execute(self, hosts: List[str]) -> StepResult:
        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="Test step executed",
            host_results={host: {"stdout": "ok", "stderr": ""} for host in hosts},
        )


# ============== ModuleRegistry Tests ==============

class TestModuleRegistry:
    """Tests for ModuleRegistry."""

    def setup_method(self):
        """Clear registry before each test."""
        ModuleRegistry.clear()

    def test_register_module(self):
        """Test module registration."""
        ModuleRegistry.register(MockDeployModule)

        assert "mock_module" in ModuleRegistry.list_modules()
        assert ModuleRegistry.get("mock_module") == MockDeployModule

    def test_unregister_module(self):
        """Test module unregistration."""
        ModuleRegistry.register(MockDeployModule)
        result = ModuleRegistry.unregister("mock_module")

        assert result is True
        assert "mock_module" not in ModuleRegistry.list_modules()

    def test_unregister_nonexistent(self):
        """Test unregistering a nonexistent module."""
        result = ModuleRegistry.unregister("nonexistent")
        assert result is False

    def test_get_by_category(self):
        """Test getting modules by category."""
        ModuleRegistry.register(MockDeployModule)

        modules = ModuleRegistry.get_by_category(ModuleCategory.SYSTEM)
        assert len(modules) == 1
        assert modules[0] == MockDeployModule

    def test_list_categories(self):
        """Test listing all categories."""
        ModuleRegistry.register(MockDeployModule)

        categories = ModuleRegistry.list_categories()
        assert ModuleCategory.SYSTEM in categories
        assert "mock_module" in categories[ModuleCategory.SYSTEM]

    def test_create_instance(self):
        """Test creating a module instance."""
        ModuleRegistry.register(MockDeployModule)

        instance = ModuleRegistry.create_instance("mock_module")
        assert isinstance(instance, MockDeployModule)

    def test_module_decorator(self):
        """Test the @module decorator."""
        @module(
            name="decorated_module",
            category=ModuleCategory.GPU,
            description="Decorated test module",
            tags=["test", "decorator"],
        )
        class DecoratedModule(DeployModule):
            def execute(self, node_config, **kwargs):
                return ModuleResult(success=True, module_name="decorated_module")

        assert "decorated_module" in ModuleRegistry.list_modules()
        module_class = ModuleRegistry.get("decorated_module")
        assert module_class.metadata.category == ModuleCategory.GPU
        assert "test" in module_class.metadata.tags


# ============== ModuleManager Tests ==============

class TestModuleManager:
    """Tests for ModuleManager."""

    def setup_method(self):
        """Clear registry before each test."""
        ModuleRegistry.clear()

    def test_init(self):
        """Test manager initialization."""
        manager = ModuleManager()
        assert manager.max_workers == 4
        assert manager._module_instances == {}

    def test_get_module_instance(self):
        """Test getting module instances."""
        ModuleRegistry.register(MockDeployModule)
        manager = ModuleManager()

        instance = manager.get_module_instance("mock_module")
        assert isinstance(instance, MockDeployModule)

        # Second call should return the same instance
        instance2 = manager.get_module_instance("mock_module")
        assert instance is instance2

    def test_list_modules(self):
        """Test listing modules."""
        ModuleRegistry.register(MockDeployModule)
        manager = ModuleManager()

        modules = manager.list_modules()
        assert "mock_module" in modules

    def test_execute_modules_single(self):
        """Test executing a single module."""
        ModuleRegistry.register(MockDeployModule)
        manager = ModuleManager()

        nodes = [MockNodeConfig(hostname="node1")]
        results = manager.execute_modules(["mock_module"], nodes)

        assert "mock_module" in results
        assert results["mock_module"]["success"] is True

    def test_execute_modules_parallel(self):
        """Test parallel module execution."""
        ModuleRegistry.register(MockDeployModule)
        ModuleRegistry.register(FailingDeployModule)
        manager = ModuleManager(max_workers=2)

        nodes = [MockNodeConfig(hostname="node1")]
        results = manager.execute_modules(
            ["mock_module", "failing_module"],
            nodes,
            parallel=True
        )

        assert "mock_module" in results
        assert "failing_module" in results

    def test_execute_category(self):
        """Test executing modules by category."""
        ModuleRegistry.register(MockDeployModule)
        ModuleRegistry.register(FailingDeployModule)
        manager = ModuleManager()

        nodes = [MockNodeConfig(hostname="node1")]
        results = manager.execute_category(ModuleCategory.SYSTEM, nodes)

        # Both mock modules are in SYSTEM category
        assert "mock_module" in results
        assert "failing_module" in results


# ============== StepAdapter Tests ==============

class TestStepAdapter:
    """Tests for StepAdapter."""

    def test_adapter_creation(self):
        """Test creating an adapter from a step."""
        step = MockBaseStep()
        adapter = StepAdapter(step)

        assert adapter.metadata.name == "test_step"
        assert adapter.metadata.category == ModuleCategory.CUSTOM

    def test_adapter_execute(self):
        """Test executing through the adapter."""
        step = MockBaseStep()
        adapter = StepAdapter(step)

        node = MockNodeConfig(hostname="test-node")
        result = adapter.execute(node)

        assert result.success is True
        assert result.module_name == "test_step"

    def test_adapter_category_mapping(self):
        """Test step category mapping."""
        # Test known step IDs
        assert get_step_category("step_1") == ModuleCategory.SYSTEM
        assert get_step_category("step_6") == ModuleCategory.STORAGE
        assert get_step_category("step_20") == ModuleCategory.NETWORK
        assert get_step_category("step_22") == ModuleCategory.GPU

    def test_factory_create_adapter(self):
        """Test creating adapter via factory."""
        adapter = StepAdapterFactory.create_adapter(
            MockBaseStep,
            config=None,
            ssh_manager=None,
        )

        assert isinstance(adapter, StepAdapter)
        assert adapter.metadata.name == "test_step"


# ============== ExecutionPlan Tests ==============

class TestExecutionPlan:
    """Tests for ExecutionPlan."""

    def test_plan_creation(self):
        """Test creating an execution plan."""
        plan = ExecutionPlan(name="test_plan")
        assert plan.name == "test_plan"
        assert plan.modules == []
        assert plan.groups == []

    def test_add_module(self):
        """Test adding a module to the plan."""
        plan = ExecutionPlan(name="test_plan")
        module = ModuleDefinition(
            name="test_module",
            module_class="MockDeployModule",
        )

        plan.add_module(module)

        assert len(plan.modules) == 1
        assert "test_module" in plan.execution_order

    def test_remove_module(self):
        """Test removing a module from the plan."""
        plan = ExecutionPlan(name="test_plan")
        module = ModuleDefinition(
            name="test_module",
            module_class="MockDeployModule",
        )
        plan.add_module(module)

        result = plan.remove_module("test_module")

        assert result is True
        assert len(plan.modules) == 0
        assert "test_module" not in plan.execution_order

    def test_resolve_dependencies(self):
        """Test dependency resolution."""
        plan = ExecutionPlan(name="test_plan")
        plan.add_module(ModuleDefinition(
            name="module_a",
            module_class="MockDeployModule",
            depends_on=[],
        ))
        plan.add_module(ModuleDefinition(
            name="module_b",
            module_class="MockDeployModule",
            depends_on=["module_a"],
        ))
        plan.add_module(ModuleDefinition(
            name="module_c",
            module_class="MockDeployModule",
            depends_on=["module_a", "module_b"],
        ))

        order = plan.resolve_dependencies()

        # module_a must come before module_b
        assert order.index("module_a") < order.index("module_b")
        # module_b must come before module_c
        assert order.index("module_b") < order.index("module_c")

    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies."""
        plan = ExecutionPlan(name="test_plan")
        plan.add_module(ModuleDefinition(
            name="module_a",
            module_class="MockDeployModule",
            depends_on=["module_b"],
        ))
        plan.add_module(ModuleDefinition(
            name="module_b",
            module_class="MockDeployModule",
            depends_on=["module_a"],
        ))

        with pytest.raises(ValueError, match="Circular dependency"):
            plan.resolve_dependencies()

    def test_serialization(self):
        """Test plan serialization and deserialization."""
        plan = ExecutionPlan(
            name="test_plan",
            version="1.0.0",
            description="Test plan",
        )
        plan.add_module(ModuleDefinition(
            name="test_module",
            module_class="MockDeployModule",
            category="system",
        ))

        # Serialize to YAML
        yaml_content = ExecutionPlanSerializer.serialize(plan)
        assert "name: test_plan" in yaml_content
        assert "test_module" in yaml_content

        # Deserialize back
        loaded_plan = ExecutionPlanSerializer.deserialize(yaml_content)
        assert loaded_plan.name == "test_plan"
        assert len(loaded_plan.modules) == 1


class TestPlanBuilder:
    """Tests for PlanBuilder."""

    def test_builder(self):
        """Test the plan builder."""
        plan = (PlanBuilder("test_plan")
            .with_description("Test description")
            .with_version("2.0.0")
            .with_author("Test Author")
            .add_module(
                name="module_a",
                module_class="MockDeployModule",
                category="system",
            )
            .add_module(
                name="module_b",
                module_class="MockDeployModule",
                category="gpu",
                depends_on=["module_a"],
            )
            .add_group(
                name="test_group",
                modules=["module_a", "module_b"],
            )
            .build()
        )

        assert plan.name == "test_plan"
        assert plan.description == "Test description"
        assert plan.version == "2.0.0"
        assert len(plan.modules) == 2
        assert len(plan.groups) == 1


# ============== ModuleDefinition Tests ==============

class TestModuleDefinition:
    """Tests for ModuleDefinition."""

    def test_to_dict(self):
        """Test converting to dictionary."""
        module = ModuleDefinition(
            name="test_module",
            module_class="TestClass",
            category="system",
            enabled=True,
            config={"key": "value"},
            timeout=300,
        )

        data = module.to_dict()

        assert data["name"] == "test_module"
        assert data["module_class"] == "TestClass"
        assert data["category"] == "system"
        assert data["config"] == {"key": "value"}

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "name": "test_module",
            "module_class": "TestClass",
            "category": "gpu",
            "enabled": False,
            "config": {"foo": "bar"},
        }

        module = ModuleDefinition.from_dict(data)

        assert module.name == "test_module"
        assert module.module_class == "TestClass"
        assert module.category == "gpu"
        assert module.enabled is False


# ============== ExecutionResult Tests ==============

class TestExecutionResult:
    """Tests for ExecutionResult."""

    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = ExecutionResult(
            plan_name="test_plan",
            status=ExecutionStatus.COMPLETED,
            total_modules=5,
            completed_modules=5,
        )

        data = result.to_dict()

        assert data["plan_name"] == "test_plan"
        assert data["status"] == "completed"
        assert data["total_modules"] == 5

    def test_from_dict(self):
        """Test creating result from dictionary."""
        data = {
            "plan_name": "test_plan",
            "status": "failed",
            "total_modules": 3,
            "completed_modules": 1,
            "failed_modules": 2,
        }

        result = ExecutionResult.from_dict(data)

        assert result.plan_name == "test_plan"
        assert result.status == ExecutionStatus.FAILED
        assert result.total_modules == 3
        assert result.failed_modules == 2


# ============== Integration Tests ==============

class TestIntegration:
    """Integration tests for the modular framework."""

    def setup_method(self):
        """Clear registry before each test."""
        ModuleRegistry.clear()

    def test_full_workflow(self):
        """Test the full workflow: register, plan, execute."""
        # Register modules
        ModuleRegistry.register(MockDeployModule)

        # Create a plan
        plan = (PlanBuilder("integration_test")
            .add_module(
                name="mock_module",
                module_class="mock_module",
                category="system",
            )
            .build()
        )

        # Create manager and execute
        manager = ModuleManager()
        nodes = [MockNodeConfig(hostname="node1")]

        result = manager.execute_plan(plan, nodes)

        assert result.status == ExecutionStatus.COMPLETED
        assert result.total_modules == 1
        assert result.completed_modules == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
