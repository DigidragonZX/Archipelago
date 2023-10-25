"""
A module for interacting with RetroArch through Network Commands.
RetrooArch Network Command: https://github.com/libretro/RetroArch/blob/ce6a00b4955365a729fbb0a64f5de9c5cfc1ca10/command.h

Based on the bizhawk module writen by @Zunawe

"""

import asyncio
import enum
import typing

from .socket import RetroArchSocket, Commands


RETROARCH_SOCKET_PORT = 55355
EXPECTED_SCRIPT_VERSION = 1


class ConnectionStatus(enum.IntEnum):
    NOT_CONNECTED = 1
    TENTATIVE = 2
    CONNECTED = 3

class RetroArchContext:
    socket: typing.Optional[RetroArchSocket]
    connection_status: ConnectionStatus
    info: typing.Optional[typing.Dict[str, typing.Any]]

    def __init__(self) -> None:
        self.socket = None
        self.connection_status = ConnectionStatus.NOT_CONNECTED
        self.info = None

    def close(self) -> None:
        self.connection_status = ConnectionStatus.NOT_CONNECTED
        self.info = None


class NotConnectedError(Exception):
    """Raised when something tries to make a request before a connection has been established"""
    pass


class RequestFailedError(Exception):
    """Raised when there was no response to a request"""
    pass


class ConnectorError(Exception):
    """Raised when there was an error while processing a request"""
    pass


class SyncError(Exception):
    """Raised when there was a mismatched response type"""
    pass


def connect(ctx: RetroArchContext) -> bool:
    """Attempts to establish a connection with RetroArch server. Returns True if successful."""
    try:
        ctx.socket = RetroArchSocket()
        ctx.connection_status = ConnectionStatus.TENTATIVE
        return True
    except (TimeoutError, ConnectionRefusedError):
        ctx.socket = None
        ctx.connection_status = ConnectionStatus.NOT_CONNECTED
        return False


def disconnect(ctx: RetroArchContext) -> None:
    """Closes the connection to the RetroArch server."""
    if ctx.socket is not None:
        ctx.socket.close()
        ctx.socket = None
    ctx.connection_status = ConnectionStatus.NOT_CONNECTED

async def send_request(ctx: RetroArchContext, request: str) -> str:
    """Sends a request to the RetroArch and returns the response.

    It's likely you want to use the wrapper functions instead of this."""
    response = await send_requests(ctx, request)[0]
    return response

async def send_requests(ctx: RetroArchContext, req_list: typing.List[str]) -> typing.List[str]:
    """Sends a list of requests to the RetroArch and returns their responses.

    It's likely you want to use the wrapper functions instead of this."""
    if ctx.socket is None:
        raise NotConnectedError("You tried to send a request before a connection to RetroArch was made")

    try:
        responses = await ctx.socket.multi_command_transactions(req_list)

        if responses == b"":
            ctx.socket.close()
            ctx.socket = None
            ctx.close()
            raise RequestFailedError("Connection closed")

        if ctx.connection_status == ConnectionStatus.TENTATIVE:
            ctx.connection_status = ConnectionStatus.CONNECTED

        return responses
    except ValueError as exc:
        await ctx.socket.clear_responses()
        raise RequestFailedError(exc.args) from exc
    except (ConnectionError, ConnectionResetError) as exc:
        ctx.socket.close()
        ctx.socket = None
        ctx.close()
        ctx.connection_status = ConnectionStatus.NOT_CONNECTED
        raise RequestFailedError("Connection reset") from exc


async def get_retroarch_version(ctx: RetroArchContext) -> str:
    """Gets the version of RetroArch"""
    response = await send_request(ctx, Commands.VERSION)
    return response


async def get_status(ctx: RetroArchContext) -> str:
    """Gets the status of RetroArch"""
    response = await send_request(ctx, Commands.GET_STATUS)

    (command, status, info) = response.split(b" ", 2)
    if command != Commands.GET_STATUS:
        raise SyncError(f"Expected response of type {Commands.GET_STATUS} but got {command}")
    
    (core_type, rom_name, game_crc) = info.split(b",", 2)
    ctx.info[core_type] = core_type
    ctx.info[rom_name] = rom_name
    ctx.info[game_crc] = game_crc
    
    return status


async def get_core_type(ctx: RetroArchContext) -> str:
    """Gets the core type for the currently loaded CORE"""
    if ctx.info is None:
        response = await send_request(ctx, Commands.GET_STATUS)

        (command, status, info) = response.split(b" ", 2)
        if command != Commands.GET_STATUS:
            raise SyncError(f"Expected response of type {Commands.GET_STATUS} but got {command}")
        
        (core_type, rom_name, game_crc) = info.split(b",", 2)
        ctx.info[core_type] = core_type
        ctx.info[rom_name] = rom_name
        ctx.info[game_crc] = game_crc

    return ctx.info[core_type]


async def get_rom_name(ctx: RetroArchContext) -> str:
    """Gets the rom name for the currently loaded ROM"""
    if ctx.info is None:
        response = await send_request(ctx, Commands.GET_STATUS)

        (command, status, info) = response.split(b" ", 2)
        if command != Commands.GET_STATUS:
            raise SyncError(f"Expected response of type {Commands.GET_STATUS} but got {command}")
        
        (core_type, rom_name, game_crc) = info.split(b",", 2)
        ctx.info[core_type] = core_type
        ctx.info[rom_name] = rom_name
        ctx.info[game_crc] = game_crc

    return ctx.info[rom_name]


async def get_game_crc(ctx: RetroArchContext) -> str:
    """Gets the rom name for the currently loaded ROM"""
    if ctx.info is None:
        response = await send_requests(ctx, Commands.GET_STATUS)

        (command, status, info) = response.split(b" ", 2)
        if command != Commands.GET_STATUS:
            raise SyncError(f"Expected response of type {Commands.GET_STATUS} but got {command}")
        
        (core_type, rom_name, game_crc) = info.split(b",", 2)
        ctx.info[core_type] = core_type
        ctx.info[rom_name] = rom_name
        ctx.info[game_crc] = game_crc

    return ctx.info[game_crc]

async def lock(ctx: RetroArchContext) -> None:
    """Locks RetroArch in anticipation of receiving more requests this frame.

    While locked, emulation will halt until an `UNLOCK` request sent or a user unpauses the emulator. 
    Remember to unlock when you're done.

    Sending multiple lock commands is the same as sending one."""

    status = await get_status(ctx)
    if status != "PAUSED":
        #Use FRAMEADVANCE command to force a pause
        ctx.socket.send_command(Commands.FRAMEADVANCE)


async def unlock(ctx: RetroArchContext) -> None:
    """Unlocks RetroArch to allow it to resume emulation. See `lock` for more info.

    Sending multiple unlock commands is the same as sending one."""
    status = await get_status(ctx)
    if status == "PAUSED":
        ctx.socket.send_command(Commands.PAUSE_TOGGLE)

def display_message(ctx: RetroArchContext, message: str) -> None:
    """Displays the provided message in RetroArch message queue."""
    ctx.socket.send_command(ctx, [Commands.SHOW_MSG + " " + message])


async def guarded_read(ctx: RetroArchContext, read_list: typing.List[typing.Tuple[int, int]],
                       guard_list: typing.List[typing.Tuple[int, typing.Iterable[int]]]) -> typing.Optional[typing.List[bytes]]:
    """Reads an array of bytes at 1 or more addresses if and only if every byte in guard_list matches its expected value. 
    
    NOTE: Due to RetroArch Network Protocol limitations this isn't a true 'guarded' read 
    it just bundles them close together to minimize frametime in between commands

    Items in read_list should be organized (address, size, domain) where
    - `address` is the address of the first byte of data
    - `length` is the number of bytes to read

    Items in `guard_list` should be organized `(address, expected_data, domain)` where
    - `address` is the address of the first byte of data
    - `expected_data` is the bytes that the data starting at this address is expected to match

    Returns None if any item in guard_list failed to validate. Otherwise returns a list of bytes in the order they
    were requested."""
    responses = [guard_response.split(b" ", 2) for guard_response in await send_requests(ctx, [Commands.READ_CORE_MEMORY + " " + hex(address) + " " + len(expected_data) 
                                   for (address, expected_data) in guard_list])]
    for (address, expected_data) in guard_list:
        for (r_command, r_address, r_data) in responses:
            if r_command == Commands.READ_CORE_MEMORY and int(r_address) == address and bytearray.fromhex(r_data) == expected_data:
                break
            else:
                return None

    result: typing.List[bytes] = []
    responses = [read_response.split(b" ", 2) for read_response in await send_requests(ctx, [Commands.READ_CORE_MEMORY + " " + hex(address) + " " + length 
                                   for (address, length) in read_list])]
    for (address, length) in read_list:
        for (r_command, r_address, r_data) in responses:
            if r_command == Commands.READ_CORE_MEMORY and int(r_address) == address and len(bytearray.fromhex(r_data)) == length:
                result.append(bytearray.fromhex(r_data))
                break
            else:
                raise SyncError(f"Expected response of type {Commands.READ_CORE_MEMORY} for address {address}")

    return result


async def read(ctx: RetroArchContext, read_list: typing.List[typing.Tuple[hex, int]]) -> typing.List[bytes]:
    """Reads data at 1 or more addresses.

    Items in `read_list` should be organized `(address, size, domain)` where
    - `address` is the address of the first byte of data
    - `length` is the number of bytes to read

    Returns a list of bytes in the order they were requested."""
    return await guarded_read(ctx, read_list, [])


async def guarded_write(ctx: RetroArchContext, write_list: typing.List[typing.Tuple[int, typing.Iterable[int]]],
                        guard_list: typing.List[typing.Tuple[int, typing.Iterable[int]]]) -> bool:
    """Writes data to 1 or more addresses if and only if every byte in guard_list matches its expected value.

    NOTE: Due to RetroArch Network Protocol limitations this isn't a true 'guarded' read 
    it just bundles them close together to minimize frametime in between commands

    Items in `write_list` should be organized `(address, value, domain)` where
    - `address` is the address of the first byte of data
    - `values` is a list of bytes to write, in order, starting at `address`

    Items in `guard_list` should be organized `(address, expected_data, domain)` where
    - `address` is the address of the first byte of data
    - `expected_data` is the bytes that the data starting at this address is expected to match

    Returns False if any item in guard_list failed to validate. Otherwise returns True."""
    responses = [guard_response.split(b" ", 2) for guard_response in await send_requests(ctx, [Commands.READ_CORE_MEMORY + " " + hex(address) + " " + len(expected_data) 
                                   for (address, expected_data) in guard_list])]
    for (address, expected_data) in guard_list:
        for (r_command, r_address, r_data) in responses:
            if r_command == Commands.READ_CORE_MEMORY and int(r_address) == address and bytearray.fromhex(r_data) == expected_data:
                break
            else:
                return False

    responses = [read_response.split(b" ", 2) for read_response in await send_requests(ctx, [Commands.WRITE_CORE_MEMORY + " " + hex(address) + " " + values 
                                   for (address, values) in write_list])]
    for (address, values) in write_list:
        for (r_command, r_address, r_data) in responses:
            if r_command == Commands.WRITE_CORE_MEMORY and int(r_address) == address and int(r_data) == len(values):
                break
            else:
                raise SyncError(f"Expected response of type {Commands.WRITE_CORE_MEMORY} for address {address}")

    return True


async def write(ctx: RetroArchContext, write_list: typing.List[typing.Tuple[int, typing.Iterable[int]]]) -> None:
    """Writes data to 1 or more addresses.

    Items in write_list should be organized `(address, value, domain)` where
    - `address` is the address of the first byte of data
    - `values` is a list of bytes to write, in order, starting at `address`"""
    await guarded_write(ctx, write_list, [])
