"""
Step Adapter

Adapts existing BaseStep instances to the DeployModule interface,
allowing legacy steps to work with the new modular framework.
"""

from typing import Any, Dict, List, Optional, Type
import logging

from src.deployment.core import DeployModule, ModuleCategory, ModuleMetadata, ModuleResult
from src.steps.base import BaseStep, StepStatus

logger = logging.getLogger(__name__)


# Mapping of step categories based on step_id patterns
STEP_CATEGORY_MAP = {
    # Group A: System checks
    "step_1": ModuleCategory.SYSTEM,
    "step_2": ModuleCategory.SYSTEM,
    "step_3": ModuleCategory.SYSTEM,
    "step_4": ModuleCategory.SYSTEM,
    # Group B: Base configuration
    "step_5": ModuleCategory.SYSTEM,
    "step_6": ModuleCategory.STORAGE,
    "step_7": ModuleCategory.SYSTEM,
    "step_8": ModuleCategory.SYSTEM,
    "step_9": ModuleCategory.SYSTEM,
    # Group C: User and SSH
    "step_10": ModuleCategory.SECURITY,
    "step_0d": ModuleCategory.SECURITY,
    "step_12": ModuleCategory.SYSTEM,
    "step_13": ModuleCategory.SYSTEM,
    # Group D: System optimization
    "step_15": ModuleCategory.SYSTEM,
    "step_16": ModuleCategory.SYSTEM,
    "step_17": ModuleCategory.SYSTEM,
    "step_18": ModuleCategory.NETWORK,
    "step_19": ModuleCategory.SYSTEM,
    # Group E: Network drivers
    "step_20": ModuleCategory.NETWORK,
    "step_21": ModuleCategory.GPU,
    "step_22": ModuleCategory.GPU,
    "step_23": ModuleCategory.GPU,
    # Group F: GPU environment
    "step_24": ModuleCategory.GPU,
    "step_25": ModuleCategory.GPU,
    "step_26": ModuleCategory.NETWORK,
    "step_27": ModuleCategory.GPU,
    "step_28": ModuleCategory.GPU,
    # Group G: Advanced config
    "step_29": ModuleCategory.SYSTEM,
    "step_30": ModuleCategory.SYSTEM,
    "step_34": ModuleCategory.STORAGE,
    # Device check
    "step_0": ModuleCategory.SYSTEM,
}


def get_step_category(step_id: str) -> ModuleCategory:
    """Get the category for a step based on its ID."""
    for prefix, category in STEP_CATEGORY_MAP.items():
        if step_id.startswith(prefix):
            return category
    return ModuleCategory.CUSTOM


class StepAdapter(DeployModule):
    """
    Adapter that wraps a BaseStep instance and exposes it as a DeployModule.

    This allows existing steps to work with the new modular deployment framework
    without requiring modifications to the step implementations.
    """

    def __init__(
        self,
        step: BaseStep,
        category: Optional[ModuleCategory] = None,
        **kwargs
    ):
        """
        Initialize the adapter with a BaseStep instance.

        Args:
            step: The BaseStep instance to adapt
            category: Optional category override
            **kwargs: Additional arguments passed to parent
        """
        # Get config and ssh_manager from step if not provided
        config = kwargs.get("config") or getattr(step, "config", None)
        ssh_manager = kwargs.get("ssh_manager") or getattr(step, "ssh_manager", None)

        super().__init__(config=config, ssh_manager=ssh_manager)

        self._step = step
        self._category = category or get_step_category(step.step_id)

        # Set up metadata from step
        self.metadata = ModuleMetadata(
            name=step.step_id,
            category=self._category,
            description=step.step_description or step.step_name,
            requires_remote=True,
            risk_level="high" if step.requires_sudo else "medium",
            estimated_time=step.timeout,
        )

    @property
    def step(self) -> BaseStep:
        """Get the wrapped step instance."""
        return self._step

    def execute(self, node_config: Any, **kwargs) -> ModuleResult:
        """
        Execute the step on a specific node.

        Adapts from BaseStep.execute(hosts: List[str]) to DeployModule.execute(node_config).

        Args:
            node_config: Configuration for the target node (must have hostname attribute)
            **kwargs: Additional keyword arguments

        Returns:
            ModuleResult with execution status and details
        """
        hostname = getattr(node_config, "hostname", None)
        if hostname is None:
            return ModuleResult(
                success=False,
                module_name=self.metadata.name,
                message="Invalid node configuration: missing hostname",
                error="Node configuration must have a 'hostname' attribute"
            )

        try:
            # Execute the step with a single host
            step_result = self._step.execute([hostname])

            # Convert StepResult to ModuleResult
            success = step_result.status == StepStatus.SUCCESS

            # Extract host-specific results if available
            host_results = step_result.host_results.get(hostname, {})

            return ModuleResult(
                success=success,
                module_name=self.metadata.name,
                message=step_result.message,
                output=host_results.get("stdout", ""),
                error=host_results.get("stderr") if not success else None,
                duration=step_result.duration,
                details={
                    "step_id": step_result.step_id,
                    "step_name": step_result.step_name,
                    "host_results": step_result.host_results,
                    "errors": step_result.errors,
                }
            )

        except Exception as e:
            logger.exception(f"Error executing step {self._step.step_id}")
            return ModuleResult(
                success=False,
                module_name=self.metadata.name,
                message=f"Execution failed: {str(e)}",
                error=str(e)
            )

    def validate(self, node_config: Any) -> List[str]:
        """
        Validate the step configuration.

        Args:
            node_config: Configuration for the target node

        Returns:
            List of validation error messages
        """
        errors = []
        hostname = getattr(node_config, "hostname", None)

        if hostname is None:
            errors.append("Node configuration must have a 'hostname' attribute")

        # Check if step requires sudo and we have access
        if self._step.requires_sudo:
            # Could add sudo check here
            pass

        return errors

    def pre_execute(self, node_config: Any) -> bool:
        """
        Pre-execution hook. Calls the step's pre_check method.

        Args:
            node_config: Configuration for the target node

        Returns:
            True to proceed with execution, False to skip
        """
        hostname = getattr(node_config, "hostname", None)
        if hostname is None:
            return False

        try:
            return self._step.pre_check([hostname])
        except Exception as e:
            logger.error(f"Pre-check failed for step {self._step.step_id}: {e}")
            return False

    def post_execute(self, node_config: Any, result: ModuleResult) -> ModuleResult:
        """
        Post-execution hook. Calls the step's post_check method.

        Args:
            node_config: Configuration for the target node
            result: Result from execute()

        Returns:
            Modified or original result
        """
        if not result.success:
            return result

        hostname = getattr(node_config, "hostname", None)
        if hostname is None:
            return result

        try:
            post_check_passed = self._step.post_check([hostname])
            if not post_check_passed:
                result.success = False
                result.message = "Post-check failed"
        except Exception as e:
            logger.error(f"Post-check failed for step {self._step.step_id}: {e}")
            result.success = False
            result.message = f"Post-check error: {str(e)}"

        return result

    def rollback(self, node_config: Any, result: ModuleResult) -> bool:
        """
        Rollback the step execution.

        Args:
            node_config: Configuration for the target node
            result: Result from execute()

        Returns:
            True if rollback succeeded, False otherwise
        """
        hostname = getattr(node_config, "hostname", None)
        if hostname is None:
            return False

        try:
            return self._step.rollback([hostname])
        except Exception as e:
            logger.error(f"Rollback failed for step {self._step.step_id}: {e}")
            return False


class StepAdapterFactory:
    """
    Factory for creating StepAdapter instances from step classes or instances.
    """

    @staticmethod
    def create_adapter(
        step_class_or_instance: Any,
        config: Any = None,
        ssh_manager: Any = None,
        batch_executor: Any = None,
        category: Optional[ModuleCategory] = None,
        **kwargs
    ) -> StepAdapter:
        """
        Create a StepAdapter from a step class or instance.

        Args:
            step_class_or_instance: Either a BaseStep class or instance
            config: Configuration for the deployment
            ssh_manager: SSH manager for remote connections
            batch_executor: Batch executor for parallel operations
            category: Optional category override
            **kwargs: Additional arguments for step instantiation

        Returns:
            StepAdapter instance wrapping the step
        """
        if isinstance(step_class_or_instance, type):
            # It's a class, create an instance
            step = step_class_or_instance(
                config=config,
                ssh_manager=ssh_manager,
                batch_executor=batch_executor,
                **kwargs
            )
        else:
            # It's already an instance
            step = step_class_or_instance

        return StepAdapter(step, category=category, config=config, ssh_manager=ssh_manager)

    @staticmethod
    def register_step_as_module(
        step_class: Type[BaseStep],
        registry: Optional[Any] = None,
        category: Optional[ModuleCategory] = None,
    ) -> None:
        """
        Register a step class as a module in the registry.

        This creates a wrapper class that can be instantiated by the registry.

        Args:
            step_class: The BaseStep class to register
            registry: The ModuleRegistry to register with (uses default if None)
            category: Optional category override
        """
        from src.deployment.core import ModuleRegistry as DefaultRegistry

        actual_registry = registry or DefaultRegistry
        step_id = step_class.step_id

        # Create a wrapper class
        class StepModuleWrapper(DeployModule):
            metadata = ModuleMetadata(
                name=step_id,
                category=category or get_step_category(step_id),
                description=getattr(step_class, "step_description", "") or getattr(step_class, "step_name", ""),
                requires_remote=True,
                risk_level="high" if getattr(step_class, "requires_sudo", False) else "medium",
                estimated_time=getattr(step_class, "timeout", 300),
            )

            def __init__(self, config=None, ssh_manager=None):
                super().__init__(config=config, ssh_manager=ssh_manager)
                self._step_instance = None

            def _get_step(self):
                """Lazy initialization of the step instance."""
                if self._step_instance is None:
                    # Import here to avoid circular imports
                    from src.batch_executor import BatchExecutor
                    batch_executor = BatchExecutor(self.ssh_manager) if self.ssh_manager else None
                    self._step_instance = step_class(
                        config=self.config,
                        ssh_manager=self.ssh_manager,
                        batch_executor=batch_executor,
                    )
                return self._step_instance

            def execute(self, node_config, **kwargs):
                step = self._get_step()
                hostname = getattr(node_config, "hostname", None)
                if hostname is None:
                    return ModuleResult(
                        success=False,
                        module_name=self.metadata.name,
                        error="Node configuration must have a 'hostname' attribute"
                    )

                try:
                    step_result = step.execute([hostname])
                    success = step_result.status == StepStatus.SUCCESS
                    host_results = step_result.host_results.get(hostname, {})

                    return ModuleResult(
                        success=success,
                        module_name=self.metadata.name,
                        message=step_result.message,
                        output=host_results.get("stdout", ""),
                        error=host_results.get("stderr") if not success else None,
                        duration=step_result.duration,
                        details={
                            "step_id": step_result.step_id,
                            "step_name": step_result.step_name,
                            "host_results": step_result.host_results,
                        }
                    )
                except Exception as e:
                    return ModuleResult(
                        success=False,
                        module_name=self.metadata.name,
                        error=str(e)
                    )

        # Set a proper class name
        StepModuleWrapper.__name__ = f"{step_class.__name__}Module"
        StepModuleWrapper.__qualname__ = f"{step_class.__name__}Module"

        # Register with the registry
        actual_registry.register(StepModuleWrapper)


def register_all_steps() -> None:
    """
    Register all existing steps as modules.

    This function imports all steps from the steps module and registers
    them with the module registry.
    """
    from src.deployment.core import ModuleRegistry
    from src.steps import ALL_STEPS

    for step_class in ALL_STEPS:
        StepAdapterFactory.register_step_as_module(step_class, ModuleRegistry)

    logger.info(f"Registered {len(ALL_STEPS)} steps as modules")
