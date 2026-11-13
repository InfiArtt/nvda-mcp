"""A relay for tests: pairs a sharer and a helper by room and forwards their binary messages.

The InfiArtt relay adds limits (rate limits, connection caps, time limits); the protocol is the same.
"""

import asyncio
import json

from websockets.asyncio.server import serve


class FakeRelay:
    def __init__(self):
        self.rooms = {}
        self.seen = []

    async def handle(self, connection):
        hello = json.loads(await connection.recv())
        role, room = hello["role"], hello["room"]
        if role == "sharer":
            entry = {"sharer": connection, "paired": asyncio.Event(), "done": asyncio.Event()}
            self.rooms[room] = entry
            await connection.send(json.dumps({"type": "waiting", "expiresIn": 600}))
            await entry["paired"].wait()
            await entry["done"].wait()
            return
        entry = self.rooms.get(room)
        if entry is None or entry["paired"].is_set():
            await connection.send(
                json.dumps({"type": "error", "code": "noSuchRoom", "message": "No such room."})
            )
            await connection.close(4001)
            return
        entry["paired"].set()
        sharer = entry["sharer"]
        for side in (sharer, connection):
            await side.send(json.dumps({"type": "paired"}))

        async def forward(source, target):
            async for message in source:
                self.seen.append(message)
                await target.send(message)

        tasks = [
            asyncio.create_task(forward(sharer, connection)),
            asyncio.create_task(forward(connection, sharer)),
        ]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            task.cancel()
        for side in (sharer, connection):
            await side.close(4000)
        entry["done"].set()

    def serve(self):
        return serve(self.handle, "127.0.0.1", 0, compression=None, max_size=9 * 1024 * 1024)
