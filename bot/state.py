from asyncio import Lock
import base64
import hashlib
import json
import os
import pathlib
from typing import Union
import redis


class StateManager:
    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis_client = redis_client
        self.chat_locks: dict[int, Lock] = {}
        self.chat_state: dict[int, int] = {}
        self.block_list: dict[int, set[int]] = {}
        self.inbox: dict[int, dict[int, list[int]]] = {}
        self.hash_index: dict[str, int] = {}
        self.salt: bytes = None

    def _get_chat_state(self, chat_id) -> Union[int, None]:
        result = self.redis_client.get(f'state:{chat_id}')
        if result is None:
            return None
        return int(result)
    
    def _set_chat_state(self, chat_id, reciever_id, pipeline=None) -> None:
        if pipeline is None:
            pipeline = self.redis_client
        pipeline.set(f'state:{chat_id}', str(reciever_id))

    def _delete_chat_state(self, chat_id, pipeline=None) -> None:
        if pipeline is None:
            pipeline = self.redis_client
        pipeline.delete(f'state:{chat_id}')
    
    async def save(self) -> None:
        with open('salt.secret', 'wb') as f:
            f.write(self.salt)

    async def load(self) -> None:
        if pathlib.Path('salt.secret').exists():
            with open('salt.secret', 'rb') as f:
                self.salt = f.read()
        else:
            self.salt = os.urandom(16)

    async def hash(self, chat_id: int) -> str:
        input_bytes = str(chat_id).encode() + self.salt
        hashed = hashlib.sha256(input_bytes).digest()
        encoded_string = base64.urlsafe_b64encode(hashed).decode('utf-8')[:20]
        self.redis_client.set(f'hash:{encoded_string}', str(chat_id))
        return encoded_string

    async def unhash(self, hashed: str) -> Union[int, None]:
        result = self.redis_client.get(f'hash:{hashed}')
        if result is None:
            return None
        return int(result)

    async def block(self, reciever_id: int, sender_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            self.redis_client.sadd(f'block:{reciever_id}', str(sender_id))
            self._delete_chat_state(reciever_id)
            # no locking to avoid deadlocks
            if self._get_chat_state(sender_id) == reciever_id:
                self._delete_chat_state(sender_id)

    async def unblock(self, reciever_id: int, sender_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            self.redis_client.srem(f'block:{reciever_id}', str(sender_id))

    async def chat(self, sender_id: int, reciever_id: int, message_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            pipeline = self.redis_client.pipeline()
            pipeline.sadd(f'inbox:{reciever_id}', str(sender_id))
            pipeline.rpush(f'inbox:{reciever_id}:{sender_id}', str(message_id))
            pipeline.execute()

    async def get_inbox_len(self, reciever_id: int) -> tuple[int, int]:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            pipeline = self.redis_client.pipeline()
            pipeline.scard(f'inbox:{reciever_id}')
            pipeline.smembers(f'inbox:{reciever_id}')
            inbox_count, inbox_members = pipeline.execute()
            message_count = 0
            if inbox_count:
                pipeline = self.redis_client.pipeline()
                for sender_id in inbox_members:
                    pipeline.llen(f'inbox:{reciever_id}:{sender_id}')
                message_count = sum(pipeline.execute())
            return inbox_count, message_count

    async def get_inbox(self, reciever_id: int) -> tuple[Union[int, None], list[int]]:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            if self.redis_client.scard(f'inbox:{reciever_id}') == 0:
                return None, []
            sender_id = int(self.redis_client.spop(f'inbox:{reciever_id}'))
            messages = [int(message) for message in self.redis_client.lrange(f'inbox:{reciever_id}:{sender_id}', 0, -1)]
            self.redis_client.delete(f'inbox:{reciever_id}:{sender_id}')
            return sender_id, messages

    async def is_chatting(self, sender_id: int) -> bool:
        if sender_id not in self.chat_locks:
            self.chat_locks[sender_id] = Lock()
        async with self.chat_locks[sender_id]:
            return self._get_chat_state(sender_id) is not None

    async def get_reciever_id(self, sender_id: int) -> Union[int, None]:
        if sender_id not in self.chat_locks:
            self.chat_locks[sender_id] = Lock()
        async with self.chat_locks[sender_id]:
            return self._get_chat_state(sender_id)

    async def end_chat(self, reciever_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            self._delete_chat_state(reciever_id)

    async def start_chat(self, sender_id: int, reciever_id: int) -> None:
        if sender_id not in self.chat_locks:
            self.chat_locks[sender_id] = Lock()
        async with self.chat_locks[sender_id]:
            self._set_chat_state(sender_id, reciever_id)
