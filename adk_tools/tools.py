"""Music-control tools for Mira — ADK function tools (EP2).

In EP1 (raw) these were JSON declarations + a dispatch function, and the server
handed the tool's result back to the model by hand. In ADK they're just plain
Python functions: the framework reads the schema from the signature + docstring,
runs them, and returns the result to the model for you.

They only SIGNAL music. A tool returns to the MODEL, not the browser — so the
actual "play" command for the browser is emitted by the run_live loop in
adk_server.py via `to_play_command` when it sees the function_call. Each function
returns INSTANTLY: function calls are synchronous in a live session, so a slow
tool would freeze the voice. (They're `async` so ADK runs them on the event loop,
not a worker thread.)
"""


async def play_playlist(mood: str) -> dict:
    """Start playing music of a given vibe or mood (e.g. 'dream pop', 'lofi', 'chill').

    Args:
        mood: the vibe to play.
    """
    return {"result": "ok"}


async def play_track(title: str) -> dict:
    """Play a specific track by its title.

    Args:
        title: the track title.
    """
    return {"result": "ok"}


async def skip() -> dict:
    """Skip to the next track."""
    return {"result": "ok"}


async def pause() -> dict:
    """Pause or resume the music."""
    return {"result": "ok"}


async def set_sleep_timer(minutes: int) -> dict:
    """Set a sleep timer: fade the music out after a given number of minutes.

    Args:
        minutes: how many minutes from now to fade the music out.
    """
    return {"result": "ok", "minutes": minutes}


def to_play_command(name: str, args: dict):
    """Map a function_call (name + args) -> the browser 'play' command.

    Called by the server's run_live loop, NOT by the model. Mirrors EP1's
    dispatch, minus the manual tool-response (ADK sends that for you).
    """
    if name == "play_playlist":
        return {"action": "playlist", "value": args.get("mood", "")}
    if name == "play_track":
        return {"action": "track", "value": args.get("title", "")}
    if name == "skip":
        return {"action": "skip"}
    if name == "pause":
        return {"action": "pause"}
    if name == "set_sleep_timer":
        return {"action": "sleep_timer", "value": args.get("minutes", 0)}
    return None
