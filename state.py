from asyncio import Lock
import json
import pathlib


class StateManager:
    def __init__(self) -> None:
        self.chat_locks: dict[int, Lock] = {}
        self.chat_state: dict[int, int] = {}
        self.block_list: dict[int, set[int]] = {}
        self.inbox: dict[int, dict[int, list[int]]] = {}

    async def save(self):
        with open('states.json', 'w', encoding='utf-8') as f:
            json.dump(self.chat_state, f)
        with open('blocks.json', 'w', encoding='utf-8') as f:
            json.dump(self.block_list, f)
        with open('inbox.json', 'w', encoding='utf-8') as f:
            json.dump(self.inbox, f)

    async def load(self):
        if pathlib.Path('states.json').exists():
            with open('states.json', 'r', encoding='utf-8') as f:
                self.chat_state = json.load(f)
        if pathlib.Path('blocks.json').exists():
            with open('blocks.json', 'r', encoding='utf-8') as f:
                self.block_list = json.load(f)
        if pathlib.Path('inbox.json').exists():
            with open('inbox.json', 'r', encoding='utf-8') as f:
                self.inbox = json.load(f)

    async def block(self, reciever_id: int, sender_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            if reciever_id not in self.block_list:
                self.block_list[reciever_id] = set()
            self.block_list[reciever_id].add(sender_id)
            self.chat_state[reciever_id] = None
            # no locking to avoid deadlocks
            if sender_id in self.chat_state and self.chat_state[sender_id] == reciever_id:
                self.chat_state[sender_id] = None

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

    async def get_inbox(self, reciever_id: int) -> tuple[int, list[int]]:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            if reciever_id not in self.inbox:
                return []
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
            if sender_id not in self.chat_state:
                return False
            return self.chat_state[sender_id] is not None

    async def get_reciever_id(self, sender_id: int) -> int:
        if sender_id not in self.chat_locks:
            self.chat_locks[sender_id] = Lock()
        async with self.chat_locks[sender_id]:
            if sender_id not in self.chat_state:
                return None
            return self.chat_state[sender_id]

    async def end_chat(self, reciever_id: int) -> None:
        if reciever_id not in self.chat_locks:
            self.chat_locks[reciever_id] = Lock()
        async with self.chat_locks[reciever_id]:
            self.chat_state[reciever_id] = None

    async def start_chat(self, sender_id: int, reciever_id: int) -> None:
        if sender_id not in self.chat_locks:
            self.chat_locks[sender_id] = Lock()
        async with self.chat_locks[sender_id]:
            self.chat_state[sender_id] = reciever_id
