"""
A module containing the RetroArchSocket base class
"""

import asyncio
import socket
import select
import typing
from attr import dataclass


_SEND_LIMIT = 2 ** 11 # 2 KiB
_READ_LIMIT = (2 ** 16) # 64 KiB

@dataclass
class Commands:
    VERSION: str
    GET_STATUS: str
    SHOW_MSG: str 
    FRAMEADVANCE: str
    PAUSE_TOGGLE: str
    READ_CORE_MEMORY: str
    WRITE_CORE_MEMORY: str

    def __init__(self):
        self.VERSION = "GET_VERSION"
        self.GET_STATUS = "GET_STATUS"
        self.SHOW_MSG = "SHOW_MSG"
        self.FRAMEADVANCE = "FRAMEADVANCE"
        self.PAUSE_TOGGLE = "PAUSE_TOGGLE"
        self.READ_CORE_MEMORY = "READ_CORE_MEMORY"
        self.WRITE_CORE_MEMORY = "WRITE_CORE_MEMORY"

class RetroArchSocket():
    _socket: typing.Optional[socket.SocketType]

    def __init__(self, addr:str='127.0.0.1', port:int=55355) -> None:
        self._socket = None
        self.connect(addr, port)

    def connect(self, addr:str, port:int) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        assert (self.socket)
        self._socket.setblocking(False)
        self._socket.connect((addr, port))

    def close(self) -> None:
        self._socket.close()
        self._socket = None

    def send_command(self, request: str) -> None:
        if self._socket is None:
            raise ConnectionError('Socket not connected')
        message = request.encode('ascii')
        if len(message) > _SEND_LIMIT:
            raise ValueError('Send too long')
        self._socket.send(message)

    def read_response(self, size:int=_READ_LIMIT, timeout:float=1.0) -> str:
        if self._socket is None:
            raise ConnectionError('Socket not connected')
        select.select([self._socket], [], [], timeout)
        return self._socket.recv(size).decode('ascii')
    
    async def async_read_response(self, size:int=_READ_LIMIT, timeout:float=1.0) -> str:
        if self._socket is None:
            raise ConnectionError('Socket not connected')
        
        if size > _READ_LIMIT:
            raise ValueError('Read too long')
        
        try:
            response = await asyncio.wait_for(asyncio.get_event_loop().sock_recv(self._socket, size), timeout)
        except asyncio.TimeoutError:
            raise TimeoutError('Socket timeout')
        
        return response.decode('ascii')

    async def clear_responses(self) -> None:
        while await self.async_read_response(timeout=0) is not None:
            pass

    async def command_transaction(self, request:str) -> str:
        return await self.multi_command_transactions([request])[0]
    
    async def multi_command_transactions(self, requests:typing.List[str]) -> typing.List[str]:
        await self.clear_responses()
        self.send_command('\n'.join(requests))
        return [ await self.async_read_response() for _ in requests ]