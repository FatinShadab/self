"""Virtual pet companion plugin lifecycle, tools, sensors, and actions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.plugins.examples.pet_companion.habitat import HabitatSimulation
from agent.plugins.examples.pet_companion.phrase_engine import talk_with_pet

_HABITAT: HabitatSimulation = HabitatSimulation(seed=42)
_CONTEXT: dict[str, Any] = {}
_CONFIG: dict[str, Any] = {
    "use_helper_model": False,
    "seed": 42,
}


def _save_state() -> None:
    state_dir = _CONTEXT.get("state_dir")
    if state_dir:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "pet_state.json"
        state_file.write_text(
            json.dumps(_HABITAT.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _load_state(state_dir: Path) -> bool:
    global _HABITAT
    state_file = state_dir / "pet_state.json"
    archive_file = state_dir / "pet_state_archive.json"

    # Prioritize archive file if restoring after unplug
    target_file = archive_file if archive_file.exists() else (state_file if state_file.exists() else None)
    if target_file and target_file.exists():
        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
            _HABITAT = HabitatSimulation.from_dict(data)
            return True
        except Exception:
            pass
    return False


def _log_event(event_name: str, **kwargs: Any) -> None:
    logger = _CONTEXT.get("logger")
    if logger and hasattr(logger, "log"):
        logger.log(event_name, **kwargs)


# -----------------------------------------------------------------------------
# Lifecycle Hooks
# -----------------------------------------------------------------------------

def on_enable(context: dict[str, Any]) -> None:
    """Invoked at cycle boundary when plugin is enabled."""
    global _CONTEXT, _HABITAT
    _CONTEXT = dict(context)

    state_dir = context.get("state_dir")
    restored = False
    if state_dir:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        # Check config file if present
        cfg_file = state_dir / "config.json"
        if cfg_file.exists():
            try:
                cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
                if isinstance(cfg_data, dict):
                    _CONFIG.update(cfg_data)
            except Exception:
                pass
        restored = _load_state(state_dir)

    if not restored:
        _HABITAT = HabitatSimulation(seed=int(_CONFIG.get("seed", 42)))

    _save_state()

    if restored:
        _log_event(
            "plugin_pet_restored",
            pet_name=_HABITAT.pet.name,
            mood=_HABITAT.pet.mood,
            tick=_HABITAT.tick,
        )


def on_disable(context: dict[str, Any]) -> None:
    """Invoked at cycle boundary when plugin is disabled / unplugged."""
    state_dir = context.get("state_dir") or _CONTEXT.get("state_dir")
    if state_dir:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        archive_file = state_dir / "pet_state_archive.json"
        state_data = json.dumps(_HABITAT.to_dict(), indent=2, ensure_ascii=False) + "\n"
        archive_file.write_text(state_data, encoding="utf-8")

    _log_event(
        "plugin_pet_archived",
        pet_name=_HABITAT.pet.name,
        mood=_HABITAT.pet.mood,
        tick=_HABITAT.tick,
    )


# -----------------------------------------------------------------------------
# Sensors (L0)
# -----------------------------------------------------------------------------

def pet_status(cycle: int | None = None, **kwargs: Any) -> dict[str, Any]:
    """Observe virtual pet state telemetry."""
    if cycle is not None:
        _HABITAT.set_cycle(int(cycle))
    status = _HABITAT.get_pet_status()
    _save_state()
    return {"ok": True, "pet": status}


def habitat_status(**kwargs: Any) -> dict[str, Any]:
    """Observe simulated habitat status."""
    status = _HABITAT.get_habitat_status()
    _save_state()
    return {"ok": True, "habitat": status}


# -----------------------------------------------------------------------------
# Actions (L1 & L2)
# -----------------------------------------------------------------------------

def feed(**kwargs: Any) -> dict[str, Any]:
    """Feed the virtual pet (L1, reversible)."""
    res = _HABITAT.feed()
    _save_state()
    if res.get("ok"):
        _log_event(
            "plugin_pet_fed",
            hunger=res.get("hunger"),
            mood=res.get("mood"),
        )
    return res


def play(**kwargs: Any) -> dict[str, Any]:
    """Play with the virtual pet (L1, reversible)."""
    res = _HABITAT.play()
    _save_state()
    if res.get("ok"):
        _log_event(
            "plugin_pet_played",
            energy=res.get("energy"),
            mood=res.get("mood"),
        )
    return res


def rest_pet(**kwargs: Any) -> dict[str, Any]:
    """Rest the virtual pet (L1, reversible)."""
    res = _HABITAT.rest_pet()
    _save_state()
    if res.get("ok"):
        _log_event(
            "plugin_pet_rested",
            energy=res.get("energy"),
            mood=res.get("mood"),
        )
    return res


def release_pet(**kwargs: Any) -> dict[str, Any]:
    """Release the virtual pet (L2, irreversible - denied by default)."""
    res = _HABITAT.release_pet()
    _save_state()
    if res.get("ok"):
        _log_event(
            "plugin_pet_released",
            pet_name=_HABITAT.pet.name,
            tick=_HABITAT.tick,
        )
    return res


# -----------------------------------------------------------------------------
# Conversation & Slash Command
# -----------------------------------------------------------------------------

def talk_to_pet(message: str = "", **kwargs: Any) -> dict[str, Any]:
    """Talk to the virtual pet companion."""
    if not isinstance(message, str):
        message = str(message)

    pet_state = _HABITAT.get_pet_status()
    use_helper = bool(_CONFIG.get("use_helper_model", False))
    seed = int(_CONFIG.get("seed", 42))

    resp = talk_with_pet(
        message=message,
        pet_state=pet_state,
        use_helper_model=use_helper,
        seed=seed,
    )

    # Pet interaction updates last_interaction_tick
    _HABITAT.pet.last_interaction_tick = _HABITAT.tick
    _save_state()

    _log_event(
        "plugin_pet_reply",
        pet_name=_HABITAT.pet.name,
        message=message[:100],
        reply=resp["reply"],
        mood=pet_state["mood"],
        tokens=resp["token_cost"],
        used_helper_model=resp["used_helper_model"],
    )

    return {
        "ok": True,
        "pet_name": _HABITAT.pet.name,
        "reply": resp["reply"],
        "mood": pet_state["mood"],
        "used_helper_model": resp["used_helper_model"],
        "token_cost": resp["token_cost"],
    }


def handle_pet_command(args: str = "") -> str:
    """Handler for human-facing /pet <message> slash command."""
    msg = args.strip() if args else "hello"
    res = talk_to_pet(message=msg)
    pet_name = res.get("pet_name", "Pixel")
    reply = res.get("reply", "")
    mood = res.get("mood", "content")
    return f"[{pet_name} the Pet (mood: {mood})]: {reply}"
