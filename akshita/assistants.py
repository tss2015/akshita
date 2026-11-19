"""Exclusive assistant reservations: a user account handles one active group at a time."""
import asyncio
from dataclasses import dataclass


class NoAssistant(Exception):
    pass


@dataclass
class Assistant:
    name: str
    client: object
    calls: object
    healthy: bool = True
    chat_id: int | None = None


class AssistantPool:
    def __init__(self, assistants: list[Assistant]):
        self.assistants = assistants
        self.lock = asyncio.Lock()

    async def acquire(self, chat_id: int, exclude: set[str] | None = None) -> Assistant:
        async with self.lock:
            exclude = exclude or set()
            for assistant in self.assistants:
                if assistant.healthy and assistant.chat_id == chat_id and assistant.name not in exclude:
                    return assistant
            for assistant in self.assistants:
                if assistant.healthy and assistant.chat_id is None and assistant.name not in exclude:
                    assistant.chat_id = chat_id
                    return assistant
            raise NoAssistant('No healthy assistant is available. Try again later.')

    async def release(self, chat_id: int):
        async with self.lock:
            for assistant in self.assistants:
                if assistant.chat_id == chat_id:
                    assistant.chat_id = None
