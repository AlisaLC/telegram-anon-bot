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

    def _get_chat_state(self, chat_id):
        result = self.redis_client.get(f'state:{chat_id}')
        if result is None:
            return None
        return int(result)
    
    def _set_chat_state(self, chat_id, reciever_id):
        self.redis_client.set(f'state:{chat_id}', str(reciever_id))

    def _delete_chat_state(self, chat_id):
        self.redis_client.delete(f'state:{chat_id}')
    
    async def save(self):
        with open('salt.secret', 'wb') as f:
            f.write(self.salt)

    async def load(self):
        if pathlib.Path('states.json').exists():
            with open('states.json', 'r', encoding='utf-8') as f:
                self.chat_state = json.load(f)
                pipe = self.redis_client.pipeline()
                for chat, state in self.chat_state.items():
                    if state is None:
                        pipe.set(f'state:{chat}', '-1')
                        continue
                    pipe.set(f'state:{chat}', str(state))
                pipe.execute()
        if pathlib.Path('blocks.json').exists():
            with open('blocks.json', 'r', encoding='utf-8') as f:
                self.block_list = json.load(f)
                pipe = self.redis_client.pipeline()
                for chat, blocks in self.block_list.items():
                    pipe.sadd(f'block:{chat}', *[str(chat_id) for chat_id in blocks])
                pipe.execute()
        if pathlib.Path('inbox.json').exists():
            with open('inbox.json', 'r', encoding='utf-8') as f:
                self.inbox = json.load(f)
                pipe = self.redis_client.pipeline()
                for chat, inbox in self.inbox.items():
                    pipe.sadd(f'inbox:{chat}', *[str(chat_id) for chat_id in inbox.keys()])
                    for sender, messages in inbox.items():
                        pipe.rpush(f'inbox:{chat}:{sender}', *[str(message_id) for message_id in messages])
                pipe.execute()
        if pathlib.Path('hashes.json').exists():
            with open('hashes.json', 'r', encoding='utf-8') as f:
                self.hash_index = json.load(f)
                pipe = self.redis_client.pipeline()
                for hash, chat_id in self.hash_index.items():
                    pipe.set(f'hash:{hash}', str(chat_id))
                pipe.execute()
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
            if reciever_id not in self.block_list:
                self.block_list[reciever_id] = set()
            self.block_list[reciever_id].add(sender_id)
            self._delete_chat_state(reciever_id)
            # no locking to avoid deadlocks
            if self._get_chat_state(sender_id) == reciever_id:
                self._delete_chat_state(sender_id)

    async def unblock(self, reciever_id: int, sender_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            if reciever_id not in self.block_list:
                return
            self.block_list[reciever_id].remove(sender_id)
            if len(self.block_list[reciever_id]) == 0:
                del self.block_list[reciever_id]

    async def chat(self, sender_id: int, reciever_id: int, message_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            if reciever_id not in self.inbox:
                self.inbox[reciever_id] = {}
            if sender_id not in self.inbox[reciever_id]:
                self.inbox[reciever_id][sender_id] = []
            self.inbox[reciever_id][sender_id].append(message_id)

    async def get_inbox_len(self, reciever_id: int) -> tuple[int, int]:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            if reciever_id not in self.inbox:
                return 0, 0
            return len(self.inbox[reciever_id]), sum(len(self.inbox[reciever_id][sender_id]) for sender_id in self.inbox[reciever_id])

    async def get_inbox(self, reciever_id: int) -> tuple[Union[int, None], list[int]]:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            if reciever_id not in self.inbox:
                return None, []
            sender_id = list(self.inbox[reciever_id].keys())[0]
            messages = self.inbox[reciever_id][sender_id]
            del self.inbox[reciever_id][sender_id]
            if len(self.inbox[reciever_id].keys()) == 0:
                del self.inbox[reciever_id]
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
