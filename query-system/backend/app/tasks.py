"""极简内存异步任务模型（对齐 docs/api.md 0.5）。

耗时操作（爬虫抓取等）立即返回 taskId，后台协程执行并更新进度；
调用方轮询 GET /api/tasks/{taskId} 获取 status/progress/result。

仅内存、单进程：够本地/单实例用；多实例需换 Redis 等共享存储。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional


class Task:
    def __init__(self, type_: str) -> None:
        self.id = "task_" + uuid.uuid4().hex[:8]
        self.type = type_
        self.status = "pending"          # pending | running | success | failed
        self.progress = 0                # 0-100
        self.message = ""
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskId": self.id, "type": self.type, "status": self.status,
            "progress": self.progress, "message": self.message,
            "result": self.result, "error": self.error,
        }


class TaskStore:
    """内存任务表；超过 ttl 的任务在新建时惰性清理，避免无限增长。"""

    def __init__(self, ttl_seconds: float = 1800) -> None:
        self._tasks: Dict[str, Task] = {}
        self._ttl = ttl_seconds

    def create(self, type_: str) -> Task:
        self._gc()
        t = Task(type_)
        self._tasks[t.id] = t
        return t

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def _gc(self) -> None:
        now = time.time()
        for tid in [k for k, v in self._tasks.items()
                    if now - v.created_at > self._ttl]:
            self._tasks.pop(tid, None)

    def run(self, task: Task, coro_factory: Callable[[Task], Awaitable[Any]]) -> None:
        """后台执行协程；成功写 result+success，异常写 error+failed。"""
        async def _runner() -> None:
            task.status = "running"
            try:
                task.result = await coro_factory(task)
                task.status = "success"
                task.progress = 100
            except Exception as exc:  # noqa: BLE001 —— 兜底：任何异常都记进任务，不冒泡
                task.status = "failed"
                task.error = f"{type(exc).__name__}: {exc}"

        asyncio.create_task(_runner())


store = TaskStore()
"""进程级单例任务表。"""
