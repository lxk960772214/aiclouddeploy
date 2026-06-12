#!/usr/bin/env python3
"""
完整部署测试脚本
按正确顺序执行所有部署步骤
"""

import sys
import os
import logging
import time
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config_loader import ConfigLoader
from src.ssh_manager import SSHManager
from src.batch_executor import BatchExecutor
from src.steps import ALL_STEPS, STEP_MAP
from src.steps.base import StepStatus

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/mnt/e/openclaw-workspace/deploy/logs/test-cluster/deploy.log', mode='w')
    ]
)
logger = logging.getLogger(__name__)


def run_full_deployment(config_dir: str):
    """执行完整部署"""
    start_time = time.time()
    
    logger.info("=" * 70)
    logger.info("GPU集群完整部署测试")
    logger.info(f"开始时间: {datetime.now().isoformat()}")
    logger.info("=" * 70)
    
    # 1. 加载配置
    logger.info("\n[1] 加载配置...")
    loader = ConfigLoader(config_dir)
    config = loader.load_cluster_config()
    versions = loader.load_versions_config()
    
    logger.info(f"  集群名称: {config.name}")
    logger.info(f"  节点数量: {config.node_count}")
    for node in config.nodes:
        logger.info(f"    - {node.hostname} ({node.ip})")
    
    # 2. 初始化SSH
    logger.info("\n[2] 初始化SSH连接...")
    jumphost_config = {
        'host': config.jumphost.host,
        'port': config.jumphost.port,
        'username': config.jumphost.username,
        'password': config.jumphost.password
    }
    ssh_manager = SSHManager(jumphost_config)
    
    if not ssh_manager.connect_jumphost(timeout=30):
        logger.error("跳板机连接失败")
        return False
    logger.info("  跳板机连接成功")
    
    # 3. 创建批量执行器
    batch_executor = BatchExecutor(
        ssh_manager=ssh_manager,
        use_pdsh=False,
        config=config
    )
    
    # 4. 获取目标主机
    hosts = [node.ip for node in config.nodes]
    logger.info(f"\n[3] 目标主机: {hosts}")
    
    # 5. 执行所有步骤
    results = {}
    failed_steps = []
    
    for i, step_class in enumerate(ALL_STEPS):
        step_id = step_class.step_id
        step_name = step_class.step_name
        
        logger.info("\n" + "-" * 70)
        logger.info(f"[{i+1}/{len(ALL_STEPS)}] 步骤 {step_id}: {step_name}")
        logger.info("-" * 70)
        
        try:
            # 创建步骤实例
            step = step_class(
                config=config,
                ssh_manager=ssh_manager,
                batch_executor=batch_executor
            )

            # 如果步骤需要 versions 配置，设置它
            if hasattr(step, 'versions'):
                step.versions = versions

            # 执行步骤
            step_start = time.time()
            result = step.execute(hosts)
            step_duration = time.time() - step_start

            results[step_id] = {
                'name': step_name,
                'status': result.status.value,
                'message': result.message,
                'duration': step_duration
            }

            if result.status == StepStatus.SUCCESS:
                logger.info(f"  ✓ 成功: {result.message} ({step_duration:.1f}s)")
            elif result.status == StepStatus.SKIPPED:
                logger.info(f"  ⊘ 跳过: {result.message}")
            else:
                logger.warning(f"  ✗ 失败: {result.message}")
                if result.errors:
                    for err in result.errors[:3]:
                        logger.warning(f"    - {err}")
                if result.warnings:
                    for warn in result.warnings[:3]:
                        logger.warning(f"    ! {warn}")
                # 只有关键步骤失败才记录
                if not step_class.can_skip:
                    failed_steps.append(step_id)

                # 如果是关键步骤失败，询问是否继续
                if step_class.requires_sudo and not step_class.can_skip:
                    logger.error(f"  关键步骤 {step_id} 失败，停止部署")
                    break
                    
        except Exception as e:
            logger.error(f"  ✗ 异常: {e}")
            results[step_id] = {
                'name': step_name,
                'status': 'error',
                'message': str(e),
                'duration': 0
            }
            failed_steps.append(step_id)
    
    # 6. 汇总结果
    total_duration = time.time() - start_time
    
    logger.info("\n" + "=" * 70)
    logger.info("部署汇总")
    logger.info("=" * 70)
    
    success_count = len([r for r in results.values() if r['status'] == 'success'])
    total_count = len(results)
    
    logger.info(f"  总步骤: {total_count}")
    logger.info(f"  成功: {success_count}")
    logger.info(f"  失败: {len(failed_steps)}")
    logger.info(f"  总耗时: {total_duration:.1f}s")
    
    if failed_steps:
        logger.info(f"\n  失败步骤: {failed_steps}")
    
    logger.info("\n步骤详情:")
    for step_id, result in results.items():
        status_icon = "✓" if result['status'] == 'success' else "✗"
        logger.info(f"  {status_icon} {step_id}: {result['name']} ({result['duration']:.1f}s)")
    
    # 7. 清理
    ssh_manager.close_all()
    
    logger.info("\n" + "=" * 70)
    logger.info(f"部署{'成功' if not failed_steps else '完成(有失败)'}")
    logger.info(f"结束时间: {datetime.now().isoformat()}")
    logger.info("=" * 70)
    
    return len(failed_steps) == 0


if __name__ == "__main__":
    config_dir = "/mnt/e/openclaw-workspace/deploy/config/test-cluster/"
    
    try:
        success = run_full_deployment(config_dir)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.warning("\n用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"部署异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
