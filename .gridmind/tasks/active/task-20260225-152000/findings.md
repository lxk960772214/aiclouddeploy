# 发现记录

## 任务信息

- **任务ID**: task-20260225-152000
- **标题**: 增强配置文件夹路径指定功能

## 发现列表

### 发现 #1: 基本功能已存在

**类型**: 现状分析
**日期**: 2026-02-25T15:20:00Z
**重要性**: 高

**描述**:
项目已经实现了 `--config-dir/-c` 参数支持，用于指定配置文件夹路径。

**代码位置**:
- `main.py:64-67`: 定义 `--config-dir` 参数
- `cli/main.py:100-104`: CLI模式下的 `--config-dir` 参数
- `config_loader.py:256-259`: `ConfigLoader.__init__` 接受 `config_dir` 参数

**影响**:
用户需求实际上已经满足，但可以增强环境变量支持、路径验证等功能。

---

### 发现 #2: 计划文件路径处理

**类型**: 潜在问题
**日期**: 2026-02-25T15:20:00Z
**重要性**: 中

**描述**:
`--plan` 参数在 `cli/main.py:155-156` 中定义，但计划文件的相对路径解析可能不是基于 `config_dir`。

**代码位置**:
- `cli/main.py:155-156`: `--plan` 参数定义
- `module_manager.py`: 计划文件加载

**建议**:
计划文件的相对路径应该相对于 `config_dir/plans/` 目录解析。

---

### 发现 #3: hosts_file 路径处理

**类型**: 潜在问题
**日期**: 2026-02-25T15:20:00Z
**重要性**: 低

**描述**:
`NodeBatchConfig.hosts_file` 字段用于指定hosts格式文件路径，但路径解析逻辑不够健壮。

**代码位置**:
- `config_loader.py:229`: `hosts_file` 字段定义
- `config_loader.py:476-527`: `_parse_hosts_batch_nodes` 方法

**建议**:
增强路径解析，支持相对路径、~扩展等。

---

## 问题与解决方案

| 问题 | 解决方案 | 状态 |
|------|----------|------|
| 缺少环境变量支持 | 添加 GPU_DEPLOY_CONFIG_DIR | 待实现 |
| 相对路径处理不完善 | 添加路径规范化函数 | 待实现 |
| 缺少配置目录验证 | 添加必需文件检查 | 待实现 |

## 技术笔记

### 配置路径优先级设计

```
优先级 1: --config-dir 命令行参数
优先级 2: GPU_DEPLOY_CONFIG_DIR 环境变量
优先级 3: 默认值 "config"
```

实现位置建议: 在 `ConfigLoader.__init__` 中处理

### 路径解析函数设计

```python
def resolve_config_dir(config_dir: Optional[str] = None) -> Path:
    """
    解析配置目录路径

    Args:
        config_dir: 命令行指定的配置目录

    Returns:
        解析后的绝对路径

    Raises:
        FileNotFoundError: 目录不存在
    """
    # 1. 确定原始路径
    if config_dir is None:
        config_dir = os.environ.get('GPU_DEPLOY_CONFIG_DIR', 'config')

    # 2. 展开并规范化
    path = Path(config_dir).expanduser().resolve()

    # 3. 验证存在
    if not path.exists():
        raise FileNotFoundError(f"配置目录不存在: {path}")

    return path
```

---

*此文件将在任务执行过程中持续更新*
