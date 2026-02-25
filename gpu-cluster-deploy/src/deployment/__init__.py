"""
Deployment Module Framework

This module provides a modular execution framework for GPU cluster deployment.
It supports:
- Module registration and discovery
- Category-based execution
- Dependency resolution
- Execution plan serialization/import/export
"""

from src.deployment.core import DeployModule, ModuleRegistry, ModuleCategory, ModuleMetadata, ModuleResult, module
from src.deployment.module_manager import ModuleManager
from src.deployment.step_adapter import StepAdapter, StepAdapterFactory
from src.deployment.execution_plan import ExecutionPlan, ExecutionPlanSerializer, PlanBuilder

__all__ = [
    'DeployModule',
    'ModuleRegistry',
    'ModuleCategory',
    'ModuleMetadata',
    'ModuleResult',
    'module',
    'ModuleManager',
    'StepAdapter',
    'StepAdapterFactory',
    'ExecutionPlan',
    'ExecutionPlanSerializer',
    'PlanBuilder',
]
