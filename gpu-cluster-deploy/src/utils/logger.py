"""
日志系统 - 结构化日志、进度追踪、状态报告
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum
import threading


class LogLevel(Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class StepProgress:
    """步骤进度"""
    step_id: str
    step_name: str
    status: str = "pending"  # pending, running, success, failed, skipped
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: float = 0.0
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PhaseProgress:
    """阶段进度"""
    phase_id: int
    phase_name: str
    status: str = "pending"  # pending, running, completed, failed
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    steps: Dict[str, StepProgress] = field(default_factory=dict)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps.values() if s.status == "success")

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.steps.values() if s.status == "failed")

    def to_dict(self) -> Dict:
        return {
            "phase_id": self.phase_id,
            "phase_name": self.phase_name,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "steps": {k: v.to_dict() for k, v in self.steps.items()}
        }


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器"""

    def format(self, record):
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, 'host'):
            log_data['host'] = record.host
        if hasattr(record, 'step'):
            log_data['step'] = record.step
        if hasattr(record, 'phase'):
            log_data['phase'] = record.phase
        if hasattr(record, 'extra_data'):
            log_data['data'] = record.extra_data

        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """控制台格式化器"""

    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        color = self.COLORS.get(record.levelname, '')

        # 基础格式
        msg = f"[{timestamp}] {color}{record.levelname:8}{self.RESET} {record.name}: {record.getMessage()}"

        # 添加额外信息
        extras = []
        if hasattr(record, 'host'):
            extras.append(f"host={record.host}")
        if hasattr(record, 'step'):
            extras.append(f"step={record.step}")
        if hasattr(record, 'phase'):
            extras.append(f"phase={record.phase}")

        if extras:
            msg += f" [{', '.join(extras)}]"

        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"

        return msg


class DeployLogger:
    """部署日志管理器"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, log_dir: str = "logs", log_level: str = "INFO"):
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.phases: Dict[int, PhaseProgress] = {}
        self.current_phase: Optional[int] = None
        self.current_step: Optional[str] = None

        self._setup_loggers()
        self._initialized = True

    def _setup_loggers(self):
        """设置日志记录器"""
        # 主日志记录器
        self.logger = logging.getLogger('gpu-deploy')
        self.logger.setLevel(self.log_level)
        self.logger.handlers.clear()

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(ConsoleFormatter())
        self.logger.addHandler(console_handler)

        # 文件处理器（结构化日志）
        log_file = self.log_dir / f"deploy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter())
        self.logger.addHandler(file_handler)

        # 普通文本日志
        text_log_file = self.log_dir / f"deploy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        text_handler = logging.FileHandler(text_log_file, encoding='utf-8')
        text_handler.setLevel(logging.DEBUG)
        text_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
        ))
        self.logger.addHandler(text_handler)

        self.log_file = log_file
        self.text_log_file = text_log_file

    def _log(self, level: int, message: str, **kwargs):
        """内部日志方法"""
        extra = {}
        if self.current_phase is not None:
            extra['phase'] = self.current_phase
        if self.current_step:
            extra['step'] = self.current_step
        if 'host' in kwargs:
            extra['host'] = kwargs['host']
        if 'extra_data' in kwargs:
            extra['extra_data'] = kwargs['extra_data']

        self.logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)

    def start_phase(self, phase_id: int, phase_name: str):
        """开始一个阶段"""
        self.current_phase = phase_id
        self.phases[phase_id] = PhaseProgress(
            phase_id=phase_id,
            phase_name=phase_name,
            status="running",
            start_time=datetime.now().isoformat()
        )
        self.info(f"========== 开始阶段 {phase_id}: {phase_name} ==========")

    def end_phase(self, phase_id: int, success: bool = True):
        """结束一个阶段"""
        if phase_id in self.phases:
            phase = self.phases[phase_id]
            phase.status = "completed" if success else "failed"
            phase.end_time = datetime.now().isoformat()

            status = "✓ 完成" if success else "✗ 失败"
            self.info(f"========== 阶段 {phase_id}: {phase.phase_name} {status} ==========")
            self.info(f"步骤统计: 总计={phase.total_steps}, 成功={phase.completed_steps}, 失败={phase.failed_steps}")

        self.current_phase = None
        self.current_step = None

    def start_step(self, step_id: str, step_name: str, phase_id: Optional[int] = None):
        """开始一个步骤"""
        phase_id = phase_id or self.current_phase
        if phase_id is None:
            self.warning(f"步骤 {step_id} 没有关联的阶段")
            return

        if phase_id not in self.phases:
            self.warning(f"阶段 {phase_id} 不存在")
            return

        self.current_step = step_id
        self.phases[phase_id].steps[step_id] = StepProgress(
            step_id=step_id,
            step_name=step_name,
            status="running",
            start_time=datetime.now().isoformat()
        )
        self.info(f"[{step_id}] 开始: {step_name}")

    def end_step(self, step_id: str, success: bool = True, message: str = "",
                 details: Optional[Dict] = None, phase_id: Optional[int] = None):
        """结束一个步骤"""
        phase_id = phase_id or self.current_phase
        if phase_id is None:
            return

        phase = self.phases.get(phase_id)
        if not phase:
            return

        step = phase.steps.get(step_id)
        if not step:
            return

        step.status = "success" if success else "failed"
        step.end_time = datetime.now().isoformat()
        step.message = message
        step.details = details or {}

        # 计算持续时间
        if step.start_time:
            start = datetime.fromisoformat(step.start_time)
            end = datetime.fromisoformat(step.end_time)
            step.duration = (end - start).total_seconds()

        status = "✓" if success else "✗"
        self.info(f"[{step_id}] {status} {step.step_name}: {message} (耗时: {step.duration:.2f}s)")

        self.current_step = None

    def log_command(self, host: str, command: str, success: bool,
                    exit_code: int, duration: float):
        """记录命令执行"""
        status = "✓" if success else "✗"
        self.info(
            f"{status} [{host}] 执行命令: {command}",
            host=host,
            extra_data={
                "command": command,
                "exit_code": exit_code,
                "duration": duration
            }
        )

    def get_progress_report(self) -> Dict:
        """获取进度报告"""
        return {
            "timestamp": datetime.now().isoformat(),
            "phases": {str(k): v.to_dict() for k, v in self.phases.items()},
            "summary": {
                "total_phases": len(self.phases),
                "completed_phases": sum(1 for p in self.phases.values() if p.status == "completed"),
                "failed_phases": sum(1 for p in self.phases.values() if p.status == "failed"),
            }
        }

    def save_progress_report(self, filename: str = "progress_report.json"):
        """保存进度报告"""
        report_path = self.log_dir / filename
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(self.get_progress_report(), f, indent=2, ensure_ascii=False)
        self.info(f"进度报告已保存: {report_path}")

    def generate_html_report(self, filename: str = "deployment_report.html") -> str:
        """生成HTML报告"""
        report = self.get_progress_report()

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>GPU集群部署报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
        .summary-card {{ flex: 1; padding: 15px; border-radius: 8px; text-align: center; }}
        .summary-card.total {{ background: #e3f2fd; }}
        .summary-card.success {{ background: #e8f5e9; }}
        .summary-card.failed {{ background: #ffebee; }}
        .summary-card .number {{ font-size: 2em; font-weight: bold; }}
        .phase {{ margin: 20px 0; border: 1px solid #ddd; border-radius: 8px; }}
        .phase-header {{ background: #f8f9fa; padding: 15px; border-bottom: 1px solid #ddd; }}
        .phase-body {{ padding: 15px; }}
        .step {{ padding: 10px; margin: 5px 0; border-radius: 4px; display: flex; justify-content: space-between; }}
        .step.success {{ background: #e8f5e9; }}
        .step.failed {{ background: #ffebee; }}
        .step.running {{ background: #fff3e0; }}
        .step.pending {{ background: #f5f5f5; }}
        .status-icon {{ font-weight: bold; }}
        .timestamp {{ color: #888; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>GPU集群部署报告</h1>
        <p class="timestamp">生成时间: {report['timestamp']}</p>

        <div class="summary">
            <div class="summary-card total">
                <div class="number">{report['summary']['total_phases']}</div>
                <div>总阶段数</div>
            </div>
            <div class="summary-card success">
                <div class="number">{report['summary']['completed_phases']}</div>
                <div>已完成</div>
            </div>
            <div class="summary-card failed">
                <div class="number">{report['summary']['failed_phases']}</div>
                <div>失败</div>
            </div>
        </div>
"""

        for phase_id, phase in report['phases'].items():
            html += f"""
        <div class="phase">
            <div class="phase-header">
                <strong>Phase {phase['phase_id']}: {phase['phase_name']}</strong>
                <span class="status-icon">{'✓' if phase['status'] == 'completed' else '✗' if phase['status'] == 'failed' else '⋯'}</span>
                <span class="timestamp">{phase['start_time'] or ''}</span>
            </div>
            <div class="phase-body">
"""
            for step_id, step in phase['steps'].items():
                html += f"""
                <div class="step {step['status']}">
                    <span>
                        <span class="status-icon">{'✓' if step['status'] == 'success' else '✗' if step['status'] == 'failed' else '⋯'}</span>
                        [{step['step_id']}] {step['step_name']}
                        {f'- {step["message"]}' if step['message'] else ''}
                    </span>
                    <span class="timestamp">{f'{step["duration"]:.2f}s' if step['duration'] else ''}</span>
                </div>
"""
            html += """
            </div>
        </div>
"""

        html += """
    </div>
</body>
</html>
"""

        report_path = self.log_dir / filename
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)

        self.info(f"HTML报告已生成: {report_path}")
        return str(report_path)


# 全局日志实例
logger = DeployLogger()


def get_logger() -> DeployLogger:
    """获取日志实例"""
    return logger
