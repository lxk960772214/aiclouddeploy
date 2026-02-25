"""
Deployment Module Core Classes

This module defines the core abstractions for the modular deployment framework:
- ModuleCategory: Categories for grouping deployment modules
- DeployModule: Abstract base class for deployment modules
- ModuleRegistry: Registry for discovering and managing modules
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Callable
import logging

logger = logging.getLogger(__name__)


class ModuleCategory(Enum):
    """Categories for deployment modules."""
    SYSTEM = "system"           # System-level configuration (hostname, hosts, etc.)
    NETWORK = "network"         # Network configuration (RDMA, Ethernet, etc.)
    STORAGE = "storage"         # Storage configuration (disk mount, NFS, etc.)
    GPU = "gpu"                 # GPU-related configuration (drivers, CUDA, etc.)
    SECURITY = "security"       # Security configuration (firewall, SSH, etc.)
    MONITORING = "monitoring"   # Monitoring tools (Prometheus, Grafana, etc.)
    CUSTOM = "custom"           # Custom user-defined modules


@dataclass
class ModuleMetadata:
    """Metadata for a deployment module."""
    name: str
    category: ModuleCategory
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 100  # Lower numbers run first within category
    requires_remote: bool = True  # Whether the module requires SSH connection
    risk_level: str = "low"  # low, medium, high
    estimated_time: int = 0  # Estimated execution time in seconds


@dataclass
class ModuleResult:
    """Result of a module execution."""
    success: bool
    module_name: str
    message: str = ""
    output: str = ""
    error: Optional[str] = None
    duration: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


class DeployModule(ABC):
    """
    Abstract base class for deployment modules.

    All deployment modules must inherit from this class and implement
    the execute() method. Modules can be registered with the ModuleRegistry
    for discovery and execution by the ModuleManager.
    """

    # Class-level metadata (should be overridden by subclasses)
    metadata: ModuleMetadata = ModuleMetadata(
        name="base",
        category=ModuleCategory.CUSTOM,
        description="Base module class"
    )

    def __init__(self, config: Any = None, ssh_manager: Any = None):
        """
        Initialize the module.

        Args:
            config: Configuration object for the deployment
            ssh_manager: SSH manager for remote connections
        """
        self.config = config
        self.ssh_manager = ssh_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def execute(self, node_config: Any, **kwargs) -> ModuleResult:
        """
        Execute the module on a specific node.

        Args:
            node_config: Configuration for the target node
            **kwargs: Additional keyword arguments

        Returns:
            ModuleResult with execution status and details
        """
        pass

    def validate(self, node_config: Any) -> List[str]:
        """
        Validate the module configuration before execution.

        Args:
            node_config: Configuration for the target node

        Returns:
            List of validation error messages (empty if valid)
        """
        return []

    def pre_execute(self, node_config: Any) -> bool:
        """
        Pre-execution hook. Called before execute().

        Args:
            node_config: Configuration for the target node

        Returns:
            True to proceed with execution, False to skip
        """
        return True

    def post_execute(self, node_config: Any, result: ModuleResult) -> ModuleResult:
        """
        Post-execution hook. Called after execute().

        Args:
            node_config: Configuration for the target node
            result: Result from execute()

        Returns:
            Modified or original result
        """
        return result

    def rollback(self, node_config: Any, result: ModuleResult) -> bool:
        """
        Rollback the module execution if it failed.

        Args:
            node_config: Configuration for the target node
            result: Result from execute()

        Returns:
            True if rollback succeeded, False otherwise
        """
        self._logger.warning(f"Rollback not implemented for module {self.metadata.name}")
        return False

    @classmethod
    def get_metadata(cls) -> ModuleMetadata:
        """Get the module metadata."""
        return cls.metadata

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.metadata.name}, category={self.metadata.category.value})"


class ModuleRegistry:
    """
    Registry for deployment modules.

    Provides module registration, discovery, and retrieval by various criteria.
    Supports decorator-based and explicit registration.
    """

    _modules: Dict[str, Type[DeployModule]] = {}
    _categories: Dict[ModuleCategory, List[str]] = {cat: [] for cat in ModuleCategory}

    @classmethod
    def register(cls, module_class: Type[DeployModule]) -> Type[DeployModule]:
        """
        Register a module class.

        Args:
            module_class: The module class to register

        Returns:
            The registered module class (for decorator chaining)
        """
        metadata = module_class.get_metadata()
        name = metadata.name

        if name in cls._modules:
            logger.warning(f"Module '{name}' already registered, replacing")

        cls._modules[name] = module_class
        cls._categories[metadata.category].append(name)

        logger.debug(f"Registered module '{name}' in category {metadata.category.value}")
        return module_class

    @classmethod
    def unregister(cls, name: str) -> bool:
        """
        Unregister a module by name.

        Args:
            name: Name of the module to unregister

        Returns:
            True if the module was unregistered, False if not found
        """
        if name not in cls._modules:
            return False

        module_class = cls._modules[name]
        metadata = module_class.get_metadata()

        del cls._modules[name]
        cls._categories[metadata.category].remove(name)

        return True

    @classmethod
    def get(cls, name: str) -> Optional[Type[DeployModule]]:
        """
        Get a module class by name.

        Args:
            name: Name of the module

        Returns:
            The module class, or None if not found
        """
        return cls._modules.get(name)

    @classmethod
    def get_by_category(cls, category: ModuleCategory) -> List[Type[DeployModule]]:
        """
        Get all modules in a category.

        Args:
            category: The category to filter by

        Returns:
            List of module classes in the category
        """
        names = cls._categories.get(category, [])
        return [cls._modules[name] for name in names if name in cls._modules]

    @classmethod
    def get_all(cls) -> Dict[str, Type[DeployModule]]:
        """
        Get all registered modules.

        Returns:
            Dictionary of module name to module class
        """
        return cls._modules.copy()

    @classmethod
    def list_modules(cls) -> List[str]:
        """
        List all registered module names.

        Returns:
            List of module names
        """
        return list(cls._modules.keys())

    @classmethod
    def list_categories(cls) -> Dict[ModuleCategory, List[str]]:
        """
        List all modules grouped by category.

        Returns:
            Dictionary mapping category to list of module names
        """
        return {
            cat: [name for name in names if name in cls._modules]
            for cat, names in cls._categories.items()
        }

    @classmethod
    def clear(cls) -> None:
        """Clear all registered modules."""
        cls._modules.clear()
        cls._categories = {cat: [] for cat in ModuleCategory}

    @classmethod
    def create_instance(cls, name: str, config: Any = None, ssh_manager: Any = None) -> Optional[DeployModule]:
        """
        Create an instance of a module by name.

        Args:
            name: Name of the module
            config: Configuration for the module
            ssh_manager: SSH manager for remote connections

        Returns:
            Module instance, or None if not found
        """
        module_class = cls.get(name)
        if module_class is None:
            return None
        return module_class(config=config, ssh_manager=ssh_manager)


def module(
    name: str,
    category: ModuleCategory,
    description: str = "",
    version: str = "1.0.0",
    author: str = "",
    tags: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None,
    priority: int = 100,
    requires_remote: bool = True,
    risk_level: str = "low",
    estimated_time: int = 0
) -> Callable[[Type[DeployModule]], Type[DeployModule]]:
    """
    Decorator for registering a module with metadata.

    Usage:
        @module(
            name="disk_mount",
            category=ModuleCategory.STORAGE,
            description="Mount and format data disks"
        )
        class DiskMountModule(DeployModule):
            ...

    Args:
        name: Unique name for the module
        category: Module category
        description: Human-readable description
        version: Module version
        author: Module author
        tags: List of tags for filtering
        dependencies: List of module names this module depends on
        priority: Execution priority (lower = earlier)
        requires_remote: Whether SSH connection is required
        risk_level: Risk level (low, medium, high)
        estimated_time: Estimated execution time in seconds

    Returns:
        Decorator function
    """
    def decorator(cls: Type[DeployModule]) -> Type[DeployModule]:
        cls.metadata = ModuleMetadata(
            name=name,
            category=category,
            description=description,
            version=version,
            author=author,
            tags=tags or [],
            dependencies=dependencies or [],
            priority=priority,
            requires_remote=requires_remote,
            risk_level=risk_level,
            estimated_time=estimated_time
        )
        return ModuleRegistry.register(cls)

    return decorator
