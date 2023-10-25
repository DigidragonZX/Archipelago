"""
A module containing context and functions relevant to running the client. This module should only be imported for type
checking or launching the client, otherwise it will probably cause circular import issues.
"""


import asyncio
import traceback
from typing import Any, Dict, Optional

from CommonClient import CommonContext, ClientCommandProcessor, get_base_parser, server_loop, logger, gui_enabled
import Patch
import Utils

from . import RetroArchContext, ConnectionStatus, RequestFailedError, connect, disconnect, get_status, get_retroarch_version, \
    get_core_type, get_game_crc
from .client import RetroArchClient, AutoRetroArchClientRegister


EXPECTED_RETROARCH_VERSION = "1.16.0"


class RetroArchClientCommandProcessor(ClientCommandProcessor):
    def _cmd_ra(self):
        """Shows the current status of the client's connection to RetroArch"""
        if isinstance(self.ctx, RetroArchClientContext):
            if self.ctx.retroarch_ctx.connection_status == ConnectionStatus.NOT_CONNECTED:
                logger.info("RetroArch Connection Status: Not Connected")
            elif self.ctx.retroarch_ctx.connection_status == ConnectionStatus.TENTATIVE:
                logger.info("RetroArch Connection Status: Tentatively Connected")
            elif self.ctx.retroarch_ctx.connection_status == ConnectionStatus.CONNECTED:
                logger.info("RetroArch Connection Status: Connected")


class RetroArchClientContext(CommonContext):
    command_processor = RetroArchClientCommandProcessor
    client_handler: Optional[RetroArchClient]
    slot_data: Optional[Dict[str, Any]] = None
    rom_crc: Optional[str] = None
    retroarch_ctx: RetroArchContext

    watcher_timeout: float
    """The maximum amount of time the game watcher loop will wait for an update from the server before executing"""

    def __init__(self, server_address: Optional[str], password: Optional[str]):
        super().__init__(server_address, password)
        self.client_handler = None
        self.retroarch_ctx = RetroArchContext()
        self.watcher_timeout = 0.5

    def run_gui(self):
        from kvui import GameManager

        class RetroArchManager(GameManager):
            base_title = "Archipelago RetroArch Client"

        self.ui = RetroArchManager(self)
        self.ui_task = asyncio.create_task(self.ui.async_run(), name="UI")

    def on_package(self, cmd, args):
        if cmd == "Connected":
            self.slot_data = args.get("slot_data", None)

        if self.client_handler is not None:
            self.client_handler.on_package(self, cmd, args)


async def _game_watcher(ctx: RetroArchClientContext):
    showed_connecting_message = False
    showed_connected_message = False
    showed_no_handler_message = False

    while not ctx.exit_event.is_set():
        try:
            await asyncio.wait_for(ctx.watcher_event.wait(), ctx.watcher_timeout)
        except asyncio.TimeoutError:
            pass

        ctx.watcher_event.clear()

        try:
            if ctx.retroarch_ctx.connection_status == ConnectionStatus.NOT_CONNECTED:
                showed_connected_message = False

                if not showed_connecting_message:
                    logger.info("Waiting to connect to RetroArch...")
                    showed_connecting_message = True

                if not await connect(ctx.retroarch_ctx):
                    continue

                showed_no_handler_message = False

                version = await get_retroarch_version(ctx.retroarch_ctx)

                #if str.version EXPECTED_RETROARCH_VERSION:
                #    logger.info(f"Connector script is incompatible. Expected version {EXPECTED_RETROARCH_VERSION} but got {version}. Disconnecting.")
                #    disconnect(ctx.retroarch_ctx)
                #    continue

            showed_connecting_message = False

            await get_status(ctx.retroarch_ctx)

            if not showed_connected_message:
                showed_connected_message = True
                logger.info("Connected to RetroArch")

            rom_crc = await get_game_crc(ctx.retroarch_ctx)
            if ctx.rom_crc is not None and ctx.rom_crc != rom_crc:
                if ctx.server is not None:
                    logger.info(f"ROM changed. Disconnecting from server.")
                    await ctx.disconnect(True)

                ctx.auth = None
                ctx.username = None
            ctx.rom_crc = rom_crc

            if ctx.client_handler is None:
                system = await get_core_type(ctx.retroarch_ctx)
                ctx.client_handler = await AutoRetroArchClientRegister.get_handler(ctx, system)

                if ctx.client_handler is None:
                    if not showed_no_handler_message:
                        logger.info("No handler was found for this game")
                        showed_no_handler_message = True
                    continue
                else:
                    showed_no_handler_message = False
                    logger.info(f"Running handler for {ctx.client_handler.game}")

        except RequestFailedError as exc:
            logger.info(f"Lost connection to RetroArch: {exc.args[0]}")
            continue

        # Get slot name and send `Connect`
        if ctx.server is not None and ctx.username is None:
            await ctx.client_handler.set_auth(ctx)

            if ctx.auth is None:
                await ctx.get_username()

            await ctx.send_connect()

        await ctx.client_handler.game_watcher(ctx)


async def _run_game(rom: str):
    import webbrowser
    webbrowser.open(rom)


async def _patch_and_run_game(patch_file: str):
    metadata, output_file = Patch.create_rom_file(patch_file)
    Utils.async_start(_run_game(output_file))


def launch() -> None:
    async def main():
        parser = get_base_parser()
        parser.add_argument("patch_file", default="", type=str, nargs="?", help="Path to an Archipelago patch file")
        args = parser.parse_args()

        ctx = RetroArchClientContext(args.connect, args.password)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        if args.patch_file != "":
            Utils.async_start(_patch_and_run_game(args.patch_file))

        watcher_task = asyncio.create_task(_game_watcher(ctx), name="GameWatcher")

        try:
            await watcher_task
        except Exception as e:
            logger.error("".join(traceback.format_exception(e)))

        await ctx.exit_event.wait()
        await ctx.shutdown()

    Utils.init_logging("RetroArchClient", exception_logger="Client")
    import colorama
    colorama.init()
    asyncio.run(main())
    colorama.deinit()
