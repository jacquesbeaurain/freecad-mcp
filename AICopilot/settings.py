# FreeCAD AI Copilot Settings Manager
# Copyright (c) 2026
# SPDX-License-Responsibility: LGPL-2.1-or-later

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AICopilot.Settings")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_save_on_execute": False,
    "selected_model": "gemini-3.6-flash",
    "command_history": [],
}


def get_settings_file_path() -> str:
    """Return the absolute path to the Copilot settings JSON file."""
    custom = os.environ.get("AICOPILOT_SETTINGS_PATH")
    if custom:
        os.makedirs(os.path.dirname(os.path.abspath(custom)), exist_ok=True)
        return os.path.abspath(custom)

    base_dir = None
    try:
        import FreeCAD
        if hasattr(FreeCAD, "getUserAppDataDir"):
            appdata = FreeCAD.getUserAppDataDir()
            if appdata:
                base_dir = os.path.join(appdata, "AICopilot")
    except Exception:
        pass

    if not base_dir:
        base_dir = os.path.join(os.path.expanduser("~"), ".freecad-copilot")

    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "settings.json")


def load_settings() -> Dict[str, Any]:
    """Load settings from JSON file, merged with defaults."""
    settings = dict(DEFAULT_SETTINGS)
    path = get_settings_file_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as e:
            logger.warning("Failed to read settings from %s: %s", path, e)
    return settings


def save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings dictionary to JSON file preserving LF line endings."""
    path = get_settings_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        return True
    except Exception as e:
        logger.warning("Failed to save settings to %s: %s", path, e)
        return False


def get_setting(key: str, default: Any = None) -> Any:
    """Get a single setting value."""
    settings = load_settings()
    if key in settings:
        return settings[key]
    return default if default is not None else DEFAULT_SETTINGS.get(key)


def set_setting(key: str, value: Any) -> bool:
    """Set and persist a single setting value."""
    settings = load_settings()
    settings[key] = value
    return save_settings(settings)


def append_command_history(prompt: str, max_items: int = 100) -> List[str]:
    """Append a prompt to command history (avoiding consecutive duplicates) and persist."""
    p = prompt.strip()
    if not p:
        return get_setting("command_history", [])

    settings = load_settings()
    history = list(settings.get("command_history", []))
    if not history or history[-1] != p:
        history.append(p)
        if len(history) > max_items:
            history = history[-max_items:]
        settings["command_history"] = history
        save_settings(settings)
    return history


def clear_command_history() -> bool:
    """Clear persisted command history."""
    return set_setting("command_history", [])
