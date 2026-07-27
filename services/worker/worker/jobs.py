from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class JobResult:
    status: str
    payload: dict[str, Any]


class Job(Protocol):
    async def run(self) -> JobResult: ...
