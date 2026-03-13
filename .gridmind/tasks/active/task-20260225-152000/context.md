# 任务上下文

## 目标

增强 gpu-cluster-deploy 项目的配置文件夹路径指定功能，提供更灵活的配置路径管理方式。

## 背景

用户请求"增加能指定config文件夹路径的功能"。经分析，项目**已经具备**基本的 `--config-dir` 参数支持，但存在以下改进空间：

### 当前实现状态

| 功能 | 状态 | 位置 |
|------|------|------|
| `--config-dir/-c` 参数 | ✅ 已实现 | `main.py:64`, `cli/main.py:101` |
| ConfigLoader config_dir 参数 | ✅ 已实现 | `config_loader.py:256` |
| 参数传递到执行控制器 | ✅ 已实现 | `execution_controller.py:90` |

### 需要增强的领域

1. **环境变量支持**
   - 当前不支持通过环境变量指定配置路径
   - 建议: 添加 `GPU_DEPLOY_CONFIG_DIR` 环境变量

2. **路径解析增强**
   - 相对路径处理可能存在歧义
   - 需要支持 `~` 扩展
   - 路径规范化

3. **配置目录验证**
   - 缺少对必需文件存在性的检查
   - 建议: 启动时验证 `cluster.yaml` 和 `versions.yaml`

4. **计划文件路径**
   - `--plan` 参数相对路径应基于 config_dir

## 技术决策

### 配置路径优先级

```
命令行参数 > 环境变量 > 默认值
```

优先级顺序：
1. `--config-dir` 命令行参数
2. `GPU_DEPLOY_CONFIG_DIR` 环境变量
3. 默认值 `config`

### 路径处理策略

```python
def resolve_config_dir(config_dir: str) -> Path:
    """
    解析配置目录路径
    1. 展开 ~ 为用户目录
    2. 转换为绝对路径
    3. 验证目录存在
    """
```

### 验证策略

- **必需文件**: `cluster.yaml`, `versions.yaml`
- **可选文件**: `plans/*.yaml`
- **行为**: 缺少必需文件时抛出错误，缺少可选文件时警告

## 约束

1. **向后兼容**: 现有用法必须继续工作
2. **最小改动**: 不改变现有API签名
3. **清晰的错误信息**: 路径问题应给出明确提示

## 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 破坏向后兼容性 | 高 | 保持默认行为不变 |
| 路径解析错误 | 中 | 完善测试用例 |
| 环境变量冲突 | 低 | 明确优先级 |

## 关键代码位置

- 配置加载: `gpu-cluster-deploy/src/config_loader.py`
- CLI入口: `gpu-cluster-deploy/src/cli/main.py`
- 主入口: `gpu-cluster-deploy/src/main.py`
- 测试: `gpu-cluster-deploy/tests/test_config_loader.py`
