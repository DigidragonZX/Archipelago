"""
A module containing the RetroArchClient base class and metaclass
"""


from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, Tuple, Union

from worlds.LauncherComponents import Component, SuffixIdentifier, Type, components, launch_subprocess

if TYPE_CHECKING:
    from .context import RetroArchClientContext
else:
    RetroArchClientContext = object


def launch_client(*args) -> None:
    from .context import launch
    launch_subprocess(launch, name="RetroArchClient")

component = Component("RetroArch Client", "RetroArchClient", component_type=Type.CLIENT, func=launch_client,
                      file_identifier=SuffixIdentifier())
components.append(component)


class AutoRetroArchClientRegister(abc.ABCMeta):
    game_handlers: ClassVar[Dict[Tuple[str, ...], Dict[str, RetroArchClient]]] = {}

    def __new__(cls, name: str, bases: Tuple[type, ...], namespace: Dict[str, Any]) -> AutoRetroArchClientRegister:
        new_class = super().__new__(cls, name, bases, namespace)

        # Register handler
        if "system" in namespace:
            systems = (namespace["system"],) if type(namespace["system"]) is str else tuple(sorted(namespace["system"]))
            if systems not in AutoRetroArchClientRegister.game_handlers:
                AutoRetroArchClientRegister.game_handlers[systems] = {}

            if "game" in namespace:
                AutoRetroArchClientRegister.game_handlers[systems][namespace["game"]] = new_class()

        # Update launcher component's suffixes
        if "patch_suffix" in namespace:
            if namespace["patch_suffix"] is not None:
                existing_identifier: SuffixIdentifier = component.file_identifier
                new_suffixes = [*existing_identifier.suffixes]

                if type(namespace["patch_suffix"]) is str:
                    new_suffixes.append(namespace["patch_suffix"])
                else:
                    new_suffixes.extend(namespace["patch_suffix"])

                component.file_identifier = SuffixIdentifier(*new_suffixes)

        return new_class

    @staticmethod
    async def get_handler(ctx: RetroArchClientContext, system: str) -> Optional[RetroArchClient]:
        for systems, handlers in AutoRetroArchClientRegister.game_handlers.items():
            if system in systems:
                for handler in handlers.values():
                    if await handler.validate_rom(ctx):
                        return handler

        return None


class RetroArchClient(abc.ABC, metaclass=AutoRetroArchClientRegister):
    system: ClassVar[Union[str, Tuple[str, ...]]]
    """The system(s) that the game this client is for runs on"""

    game: ClassVar[str]
    """The game this client is for"""

    patch_suffix: ClassVar[Optional[Union[str, Tuple[str, ...]]]]
    """The file extension(s) this client is meant to open and patch (e.g. ".apz3")"""

    @abc.abstractmethod
    async def validate_rom(self, ctx: RetroArchClientContext) -> bool:
        """Should return whether the currently loaded ROM should be handled by this client. You might read the game name
        from the ROM header, for example. This function will only be asked to validate ROMs from the system set by the
        client class, so you do not need to check the system yourself.

        Once this function has determined that the ROM should be handled by this client, it should also modify `ctx`
        as necessary (such as setting `ctx.game = self.game`, modifying `ctx.items_handling`, etc...)."""
        ...

    async def set_auth(self, ctx: RetroArchClientContext) -> None:
        """Should set ctx.auth in anticipation of sending a `Connected` packet. You may override this if you store slot
        name in your patched ROM. If ctx.auth is not set after calling, the player will be prompted to enter their
        username."""
        pass

    @abc.abstractmethod
    async def game_watcher(self, ctx: RetroArchClientContext) -> None:
        """Runs on a loop with the approximate interval `ctx.watcher_timeout`. The currently loaded ROM is guaranteed
        to have passed your validator when this function is called, and the emulator is very likely to be connected."""
        ...

    def on_package(self, ctx: RetroArchClientContext, cmd: str, args: dict) -> None:
        """For handling packages from the server. Called from `RetroArchClientContext.on_package`."""
        pass
