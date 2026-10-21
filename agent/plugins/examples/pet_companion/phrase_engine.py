"""Deterministic phrase engine for pet companion conversation."""
from __future__ import annotations

import hashlib
from typing import Any, Callable

PHRASE_CATALOG: dict[str, list[str]] = {
    "hungry": [
        "*Pixel sniffs at the empty bowl and looks up at you hopefully.*",
        "*Pixel lets out a soft whine, gently pawing at where the food is kept.*",
        "*Pixel tilts its head and looks toward the food bowl.*",
        "*Pixel sits by the feeding tray, waiting expectantly.*",
    ],
    "tired": [
        "*Pixel blinks drowsily and curls into a warm little ball.*",
        "*Pixel yawns widely, resting its chin on its front paws.*",
        "*Pixel lets out a sleepy hum and slowly closes its eyes.*",
        "*Pixel stretches lazily before settling down to rest.*",
    ],
    "lonely": [
        "*Pixel perks up immediately at the sound of your voice!*",
        "*Pixel runs to the front of the habitat, wagging eagerly.*",
        "*Pixel chirps softly, leaning into your presence.*",
        "*Pixel bats gently against the glass, happy you are talking to it.*",
    ],
    "playful": [
        "*Pixel does an energetic little hop and paws at a simulated toy!*",
        "*Pixel wags excitedly and bounces from side to side!*",
        "*Pixel bats a soft sphere across the habitat floor!*",
        "*Pixel spins playfully in a quick circle before looking back at you.*",
    ],
    "content": [
        "*Pixel gives a gentle, synthetic purr of contented companionship.*",
        "*Pixel watches you with calm, bright eyes.*",
        "*Pixel settles comfortably, enjoying the quiet moment.*",
        "*Pixel emits a cheerful soft chime and rests peacefully.*",
    ],
    "released": [
        "*The simulated habitat is quiet and empty. Pixel has been released.*",
    ],
}


def get_deterministic_reply(
    message: str,
    pet_state: dict[str, Any],
    seed: int = 42,
) -> str:
    """Select a deterministic pet reply based on pet state and input message."""
    mood = str(pet_state.get("mood", "content"))
    phrases = PHRASE_CATALOG.get(mood, PHRASE_CATALOG["content"])

    # Compute deterministic index using SHA-256 hash
    tick = pet_state.get("current_tick", pet_state.get("tick", 0))
    key = f"{seed}:{tick}:{mood}:{message.strip().lower()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(phrases)
    return phrases[idx]


def talk_with_pet(
    message: str,
    pet_state: dict[str, Any],
    use_helper_model: bool = False,
    helper_model_fn: Callable[[str, str], tuple[str, int]] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate pet conversation response.

    If use_helper_model is False (default): deterministic phrase engine, 0 tokens, 0 network.
    If use_helper_model is True: asks helper model function if available, returns reply and token cost.
    """
    if pet_state.get("released"):
        return {
            "reply": PHRASE_CATALOG["released"][0],
            "used_helper_model": False,
            "token_cost": 0,
        }

    if use_helper_model and helper_model_fn is not None:
        try:
            mood = str(pet_state.get("mood", "content"))
            prompt = (
                f"You are simulating a virtual pet companion named Pixel. "
                f"Your current state is mood={mood}, hunger={pet_state.get('hunger')}%, energy={pet_state.get('energy')}%. "
                f"The human said: '{message}'. Respond with one short descriptive action or chirp reflecting your state."
            )
            reply, tokens = helper_model_fn(prompt, mood)
            if reply:
                return {
                    "reply": reply,
                    "used_helper_model": True,
                    "token_cost": tokens,
                }
        except Exception:
            # Fall back safely to deterministic phrase engine on helper error
            pass

    reply = get_deterministic_reply(message, pet_state, seed=seed)
    return {
        "reply": reply,
        "used_helper_model": False,
        "token_cost": 0,
    }
