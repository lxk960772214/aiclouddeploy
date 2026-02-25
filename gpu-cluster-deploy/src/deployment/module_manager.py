"""
Module Manager

The ModuleManager is responsible for:
- Module registration and discovery
- Dependency resolution
- Execution scheduling
- Result collection and reporting
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.deployment.core import DeployModule, ModuleCategory, ModuleRegistry, ModuleResult
from src.models.module import (
    ExecutionPlan,
    ExecutionResult,
    ExecutionStatus,
    ModuleDefinition,
    ModuleGroup,
)

logger = logging.getLogger(__name__)


class ModuleManager:
    """
    Manager for deployment modules.

    Handles module registration, dependency resolution, execution scheduling,
    and result collection.
    """

    def __init__(
        self,
        config: Any = None,
        ssh_manager: Any = None,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[str, str, float], None]] = None,
    ):
        """
        Initialize the module manager.

        Args:
            config: Global configuration for the deployment
            ssh_manager: SSH manager for remote connections
            max_workers: Maximum number of parallel workers
            progress_callback: Callback for progress updates (module_name, status, progress)
        """
        self.config = config
        self.ssh_manager = ssh_manager
        self.max_workers = max_workers
        self.progress_callback = progress_callback
        self._module_instances: Dict[str, DeployModule] = {}
        self._execution_results: Dict[str, ModuleResult] = {}

    def register_module(self, module_class: type) -> bool:
        """
        Register a module class with the registry.

        Args:
            module_class: The module class to register

        Returns:
            True if registration succeeded
        """
        ModuleRegistry.register(module_class)
        return True

    def get_module_instance(self, name: str) -> Optional[DeployModule]:
        """
        Get or create a module instance by name.

        Args:
            name: Name of the module

        Returns:
            Module instance, or None if not found
        """
        if name in self._module_instances:
            return self._module_instances[name]

        instance = ModuleRegistry.create_instance(
            name, config=self.config, ssh_manager=self.ssh_manager
        )
        if instance:
            self._module_instances[name] = instance

        return instance

    def list_modules(self) -> List[str]:
        """List all registered module names."""
        return ModuleRegistry.list_modules()

    def list_categories(self) -> Dict[ModuleCategory, List[str]]:
        """List all modules grouped by category."""
        return ModuleRegistry.list_categories()

    def get_modules_by_category(self, category: ModuleCategory) -> List[DeployModule]:
        """
        Get all modules in a category.

        Args:
            category: The category to filter by

        Returns:
            List of module instances in the category
        """
        module_classes = ModuleRegistry.get_by_category(category)
        return [
            self.get_module_instance(m.metadata.name)
            for m in module_classes
            if self.get_module_instance(m.metadata.name) is not None
        ]

    def validate_plan(self, plan: ExecutionPlan) -> List[str]:
        """
        Validate an execution plan.

        Args:
            plan: The execution plan to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check that all modules exist
        for module_def in plan.modules:
            if ModuleRegistry.get(module_def.module_class) is None:
                errors.append(
                    f"Module class '{module_def.module_class}' not found for module '{module_def.name}'"
                )

        # Check for circular dependencies
        try:
            plan.resolve_dependencies()
        except ValueError as e:
            errors.append(str(e))

        # Validate individual modules
        for module_def in plan.modules:
            instance = self.get_module_instance(module_def.module_class)
            if instance:
                # We can't validate node config here, so skip validation errors
                # that would require node-specific information
                pass

        return errors

    def execute_plan(
        self,
        plan: ExecutionPlan,
        node_configs: List[Any],
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Execute an execution plan on a set of nodes.

        Args:
            plan: The execution plan to execute
            node_configs: List of node configurations
            dry_run: If True, validate but don't execute

        Returns:
            ExecutionResult with execution status and details
        """
        result = ExecutionResult(
            plan_name=plan.name,
            status=ExecutionStatus.PENDING,
            total_modules=len(plan.get_enabled_modules()),
        )

        # Validate plan
        errors = self.validate_plan(plan)
        if errors:
            result.status = ExecutionStatus.FAILED
            result.error = "Plan validation failed: " + "; ".join(errors)
            return result

        if dry_run:
            result.status = ExecutionStatus.COMPLETED
            result.error = "Dry run completed successfully"
            return result

        # Get execution order
        try:
            execution_order = plan.resolve_dependencies()
        except ValueError as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            return result

        result.status = ExecutionStatus.RUNNING
        result.start_time = datetime.now().isoformat()

        # Execute modules in order
        for module_name in execution_order:
            module_def = plan.get_module(module_name)
            if module_def is None or not module_def.enabled:
                result.skipped_modules += 1
                continue

            module_result = self._execute_module_on_nodes(
                module_def, node_configs, plan.global_config
            )
            result.module_results[module_name] = module_result

            if module_result.get("success", False):
                result.completed_modules += 1
            elif module_def.continue_on_failure:
                result.failed_modules += 1
                logger.warning(f"Module '{module_name}' failed but continuing")
            else:
                result.failed_modules += 1
                result.status = ExecutionStatus.FAILED
                result.error = f"Module '{module_name}' failed: {module_result.get('error', 'Unknown error')}"
                result.end_time = datetime.now().isoformat()
                return result

        result.status = ExecutionStatus.COMPLETED
        result.end_time = datetime.now().isoformat()
        return result

    def _execute_module_on_nodes(
        self,
        module_def: ModuleDefinition,
        node_configs: List[Any],
        global_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a module on multiple nodes.

        Args:
            module_def: The module definition
            node_configs: List of node configurations
            global_config: Global configuration

        Returns:
            Dictionary with execution results
        """
        instance = self.get_module_instance(module_def.module_class)
        if instance is None:
            return {"success": False, "error": f"Module '{module_def.module_class}' not found"}

        # Filter nodes if node_filter is specified
        if module_def.node_filter:
            filtered_nodes = [
                n for n in node_configs
                if getattr(n, "hostname", None) in module_def.node_filter
            ]
        else:
            filtered_nodes = node_configs

        results = []
        start_time = time.time()

        # Notify progress
        if self.progress_callback:
            self.progress_callback(module_def.name, "started", 0.0)

        for node_config in filtered_nodes:
            try:
                # Pre-execute hook
                if not instance.pre_execute(node_config):
                    results.append({
                        "node": getattr(node_config, "hostname", "unknown"),
                        "success": False,
                        "error": "Pre-execution check failed",
                    })
                    continue

                # Execute with timeout (simplified - in production would use threading)
                module_result = instance.execute(
                    node_config, **{**global_config, **module_def.config}
                )

                # Post-execute hook
                module_result = instance.post_execute(node_config, module_result)

                results.append({
                    "node": getattr(node_config, "hostname", "unknown"),
                    "success": module_result.success,
                    "message": module_result.message,
                    "output": module_result.output,
                    "error": module_result.error,
                })

                # Store result for rollback
                self._execution_results[f"{module_def.name}_{getattr(node_config, 'hostname', 'unknown')}"] = module_result

            except Exception as e:
                logger.exception(f"Error executing module '{module_def.name}' on node")
                results.append({
                    "node": getattr(node_config, "hostname", "unknown"),
                    "success": False,
                    "error": str(e),
                })

        duration = time.time() - start_time

        # Determine overall success
        success = all(r.get("success", False) for r in results)

        # Notify progress
        if self.progress_callback:
            self.progress_callback(module_def.name, "completed" if success else "failed", 1.0)

        return {
            "success": success,
            "duration": duration,
            "node_results": results,
        }

    def execute_category(
        self,
        category: ModuleCategory,
        node_configs: List[Any],
        global_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute all modules in a category.

        Args:
            category: The category to execute
            node_configs: List of node configurations
            global_config: Global configuration

        Returns:
            Dictionary with execution results per module
        """
        module_classes = ModuleRegistry.get_by_category(category)
        results = {}

        # Sort by priority
        module_classes.sort(key=lambda m: m.metadata.priority)

        for module_class in module_classes:
            instance = self.get_module_instance(module_class.metadata.name)
            if instance is None:
                continue

            module_def = ModuleDefinition(
                name=module_class.metadata.name,
                module_class=module_class.metadata.name,
                category=category.value,
            )

            results[module_class.metadata.name] = self._execute_module_on_nodes(
                module_def, node_configs, global_config or {}
            )

        return results

    def execute_modules(
        self,
        module_names: List[str],
        node_configs: List[Any],
        global_config: Optional[Dict[str, Any]] = None,
        parallel: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute specific modules by name.

        Args:
            module_names: Names of modules to execute
            node_configs: List of node configurations
            global_config: Global configuration
            parallel: Whether to execute in parallel

        Returns:
            Dictionary with execution results per module
        """
        results = {}

        if parallel:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {}
                for name in module_names:
                    instance = self.get_module_instance(name)
                    if instance is None:
                        results[name] = {"success": False, "error": f"Module '{name}' not found"}
                        continue

                    module_def = ModuleDefinition(
                        name=name,
                        module_class=name,
                    )
                    future = executor.submit(
                        self._execute_module_on_nodes,
                        module_def,
                        node_configs,
                        global_config or {},
                    )
                    futures[future] = name

                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        results[name] = future.result()
                    except Exception as e:
                        results[name] = {"success": False, "error": str(e)}
        else:
            for name in module_names:
                instance = self.get_module_instance(name)
                if instance is None:
                    results[name] = {"success": False, "error": f"Module '{name}' not found"}
                    continue

                module_def = ModuleDefinition(
                    name=name,
                    module_class=name,
                )
                results[name] = self._execute_module_on_nodes(
                    module_def, node_configs, global_config or {}
                )

        return results

    def execute_group(
        self,
        group: ModuleGroup,
        node_configs: List[Any],
        global_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a module group.

        Args:
            group: The module group to execute
            node_configs: List of node configurations
            global_config: Global configuration

        Returns:
            Dictionary with execution results per module
        """
        results = self.execute_modules(
            group.modules,
            node_configs,
            global_config,
            parallel=group.parallel,
        )

        if group.stop_on_failure:
            failed = [name for name, r in results.items() if not r.get("success", False)]
            if failed:
                logger.error(f"Group '{group.name}' failed on modules: {failed}")

        return results

    def rollback_module(
        self,
        module_name: str,
        node_configs: List[Any],
    ) -> Dict[str, Any]:
        """
        Rollback a module execution.

        Args:
            module_name: Name of the module to rollback
            node_configs: List of node configurations

        Returns:
            Dictionary with rollback results
        """
        instance = self.get_module_instance(module_name)
        if instance is None:
            return {"success": False, "error": f"Module '{module_name}' not found"}

        results = []
        for node_config in node_configs:
            key = f"{module_name}_{getattr(node_config, 'hostname', 'unknown')}"
            module_result = self._execution_results.get(key)

            if module_result is None:
                results.append({
                    "node": getattr(node_config, "hostname", "unknown"),
                    "success": False,
                    "error": "No execution result found for rollback",
                })
                continue

            try:
                success = instance.rollback(node_config, module_result)
                results.append({
                    "node": getattr(node_config, "hostname", "unknown"),
                    "success": success,
                })
            except Exception as e:
                results.append({
                    "node": getattr(node_config, "hostname", "unknown"),
                    "success": False,
                    "error": str(e),
                })

        return {
            "success": all(r.get("success", False) for r in results),
            "node_results": results,
        }

    def clear_results(self) -> None:
        """Clear all stored execution results."""
        self._execution_results.clear()
