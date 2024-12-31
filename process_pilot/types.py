"""Defines type aliases for various strategies and hook types used in the process pilot."""

from typing import Literal

ShutdownStrategy = Literal["restart", "do_not_restart", "shutdown_everything"]
ProcessHookType = Literal["pre_start", "post_start", "on_shutdown", "on_restart"]
