#!/usr/bin/env python3
"""
模块化执行集成测试
测试模块选择、分类执行和执行计划导入的完整流程
"""

import pytest
import tempfile
import os
from pathlib import Path
import sys
import yaml

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.deployment.core import (
    DeployModule,
    ModuleRegistry,
    ModuleCategory,
)
from src.deployment.module_manager import ModuleManager
from src.deployment.execution_plan import (
    ExecutionPlan,
    ExecutionPlanExporter,
    ExecutionPlanLoader,
)
from src.deployment.step_adapter import StepAdapter


class TestModularExecutionIntegration:
    """模块化执行集成测试"""

    def test_module_registry_registration(self):
        """测试模块注册"""
        registry = ModuleRegistry()

        # 注册一个测试模块
        @registry.register(
            module_id="test_module",
            name="Test Module",
            category=ModuleCategory.SYSTEM,
            tags=["test"],
        )
        class TestModule(DeployModule):
            def execute(self, context):
                return {"success": True}

        # 验证注册
        module_info = registry.get("test_module")
        assert module_info is not None
        assert module_info["name"] == "Test Module"
        assert module_info["category"] == ModuleCategory.SYSTEM

    def test_module_manager_initialization(self):
        """测试模块管理器初始化"""
        manager = ModuleManager()

        assert manager is not None
        assert manager.registry is not None

    def test_list_modules_by_category(self):
        """测试按分类列出模块"""
        manager = ModuleManager()

        # 注册一些测试模块
        manager.register_module(
            module_id="network_1",
            name="Network Module 1",
            category=ModuleCategory.NETWORK,
            tags=["rdma"],
        )

        manager.register_module(
            module_id="network_2",
            name="Network Module 2",
            category=ModuleCategory.NETWORK,
            tags=["ethernet"],
        )

        manager.register_module(
            module_id="storage_1",
            name="Storage Module 1",
            category=ModuleCategory.STORAGE,
            tags=["disk"],
        )

        # 按分类获取模块
        network_modules = manager.get_modules_by_category(ModuleCategory.NETWORK)
        assert len(network_modules) >= 2

        storage_modules = manager.get_modules_by_category(ModuleCategory.STORAGE)
        assert len(storage_modules) >= 1

    def test_create_plan_from_categories(self):
        """测试从分类创建执行计划"""
        manager = ModuleManager()

        # 注册测试模块
        manager.register_module(
            module_id="network_rdma",
            name="RDMA Config",
            category=ModuleCategory.NETWORK,
            tags=["rdma"],
        )

        manager.register_module(
            module_id="network_eth",
            name="Ethernet Config",
            category=ModuleCategory.NETWORK,
            tags=["ethernet"],
        )

        # 创建计划
        categories = ["network"]
        plan = manager.create_plan_from_categories(categories)

        assert plan is not None
        assert len(plan.modules) >= 2

    def test_create_plan_from_modules(self):
        """测试从模块列表创建执行计划"""
        manager = ModuleManager()

        manager.register_module(
            module_id="module_a",
            name="Module A",
            category=ModuleCategory.SYSTEM,
        )

        manager.register_module(
            module_id="module_b",
            name="Module B",
            category=ModuleCategory.STORAGE,
        )

        # 创建计划
        module_ids = ["module_a", "module_b"]
        plan = manager.create_plan_from_modules(module_ids)

        assert plan is not None
        assert len(plan.modules) == 2

    def test_execution_plan_export_yaml(self):
        """测试执行计划导出为YAML"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ModuleManager()

            manager.register_module(
                module_id="test_module",
                name="Test Module",
                category=ModuleCategory.GPU,
                tags=["cuda"],
            )

            plan = manager.create_plan_from_modules(["test_module"])

            # 导出
            output_file = os.path.join(tmpdir, "plan.yaml")
            exporter = ExecutionPlanExporter(manager)
            exporter.export(plan, output_file, format="yaml")

            # 验证文件存在
            assert os.path.exists(output_file)

            # 验证内容
            with open(output_file, "r") as f:
                content = yaml.safe_load(f)

            assert "modules" in content
            assert len(content["modules"]) == 1

    def test_execution_plan_export_json(self):
        """测试执行计划导出为JSON"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ModuleManager()

            manager.register_module(
                module_id="test_module",
                name="Test Module",
                category=ModuleCategory.GPU,
            )

            plan = manager.create_plan_from_modules(["test_module"])

            # 导出
            output_file = os.path.join(tmpdir, "plan.json")
            exporter = ExecutionPlanExporter(manager)
            exporter.export(plan, output_file, format="json")

            # 验证文件存在
            assert os.path.exists(output_file)

    def test_execution_plan_load(self):
        """测试执行计划加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建计划文件
            plan_file = os.path.join(tmpdir, "test-plan.yaml")
            with open(plan_file, "w") as f:
                f.write("""
name: test-plan
description: Test execution plan
modules:
  - module_id: gpu_driver
    name: GPU Driver
    category: gpu
  - module_id: cuda_toolkit
    name: CUDA Toolkit
    category: gpu
""")

            manager = ModuleManager()
            loader = ExecutionPlanLoader(manager)

            plan = loader.load(plan_file)

            assert plan is not None
            assert plan.name == "test-plan"
            assert len(plan.modules) == 2

    def test_step_adapter_integration(self):
        """测试步骤适配器集成"""
        adapter = StepAdapter()

        # 测试获取步骤分类
        category = adapter.get_step_category("26")  # RDMA重命名
        assert category is not None

    def test_full_execution_workflow(self):
        """测试完整执行工作流"""
        manager = ModuleManager()

        # 注册多个模块
        modules = [
            ("step_1", "System Update", ModuleCategory.SYSTEM),
            ("step_2", "Network Config", ModuleCategory.NETWORK),
            ("step_3", "Storage Setup", ModuleCategory.STORAGE),
            ("step_4", "GPU Driver", ModuleCategory.GPU),
        ]

        for module_id, name, category in modules:
            manager.register_module(
                module_id=module_id,
                name=name,
                category=category,
            )

        # 创建计划
        plan = manager.create_plan_from_categories(["system", "network"])
        assert plan is not None

        # 验证模块顺序
        assert len(plan.modules) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
