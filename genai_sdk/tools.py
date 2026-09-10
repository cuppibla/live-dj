"""Music-control tools for Mira.

The whole lesson of these tools: in a live session, function calls are SYNCHRONOUS —
the model's voice pauses until the tool returns. So each handler does the minimum
(decide a "play" command for the browser) and returns INSTANTLY. It never awaits playback.
"""

# Declared to the Live config (dict form, matching the API docs).
TOOL_DECLARATIONS = [
    {
        "name": "play_playlist",
        "description": "Start playing music of a given vibe or mood (e.g. 'dream pop', 'lofi', 'chill').",
        "parameters": {
            "type": "object",
            "properties": {"mood": {"type": "string", "description": "the vibe to play"}},
            "required": ["mood"],
        },
    },
    {
        "name": "play_track",
        "description": "Play a specific track by its title.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "the track title"}},
            "required": ["title"],
        },
    },
    {"name": "skip", "description": "Skip to the next track.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "pause", "description": "Pause or resume the music.",
     "parameters": {"type": "object", "properties": {}}},
]


def dispatch_tool(name: str, args: dict):
    """Return (play_command | None, function_result).

    play_command is a dict the server forwards to the browser's music player.
    function_result is what we hand back to the model — instantly, no blocking.
    """
    if name == "play_playlist":
        return {"action": "playlist", "value": args.get("mood", "")}, {"result": "ok"}
    if name == "play_track":
        return {"action": "track", "value": args.get("title", "")}, {"result": "ok"}
    if name == "skip":
        return {"action": "skip"}, {"result": "ok"}
    if name == "pause":
        return {"action": "pause"}, {"result": "ok"}
    return None, {"result": f"unknown tool: {name}"}
