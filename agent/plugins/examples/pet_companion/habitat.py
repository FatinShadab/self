"""Simulated habitat and virtual pet companion simulation."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VirtualPet:
    name: str = "Pixel"
    hunger: float = 30.0  # 0.0 (full) to 100.0 (starving)
    energy: float = 80.0  # 0.0 (exhausted) to 100.0 (fully rested)
    mood: str = "content"  # "content", "happy", "playful", "tired", "hungry", "lonely", "released"
    last_interaction_tick: int = 0
    released: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hunger": round(self.hunger, 1),
            "energy": round(self.energy, 1),
            "mood": self.mood,
            "last_interaction_tick": self.last_interaction_tick,
            "released": self.released,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VirtualPet:
        return cls(
            name=str(data.get("name", "Pixel")),
            hunger=float(data.get("hunger", 30.0)),
            energy=float(data.get("energy", 80.0)),
            mood=str(data.get("mood", "content")),
            last_interaction_tick=int(data.get("last_interaction_tick", 0)),
            released=bool(data.get("released", False)),
        )


@dataclass
class Habitat:
    cleanliness: float = 100.0
    food_bowl: str = "full"  # "full", "half_full", "empty"
    temperature_c: float = 21.5
    lights: str = "day"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cleanliness": round(self.cleanliness, 1),
            "food_bowl": self.food_bowl,
            "temperature_c": round(self.temperature_c, 1),
            "lights": self.lights,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Habitat:
        return cls(
            cleanliness=float(data.get("cleanliness", 100.0)),
            food_bowl=str(data.get("food_bowl", "full")),
            temperature_c=float(data.get("temperature_c", 21.5)),
            lights=str(data.get("lights", "day")),
        )


class HabitatSimulation:
    """Deterministic simulation of a virtual pet and habitat."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.tick = 0
        self.pet = VirtualPet()
        self.habitat = Habitat()
        self._undo_stack: list[tuple[VirtualPet, Habitat, int]] = []

    def set_cycle(self, cycle: int) -> None:
        """Advance simulation tick tied to the cycle number."""
        if cycle > self.tick:
            self.advance_tick(new_tick=cycle)

    def advance_tick(self, new_tick: int | None = None, elapsed: int = 1) -> None:
        """Advance simulation time deterministically."""
        if self.pet.released:
            if new_tick is not None:
                self.tick = new_tick
            else:
                self.tick += elapsed
            return

        if new_tick is not None:
            steps = max(0, new_tick - self.tick)
            self.tick = new_tick
        else:
            steps = max(0, elapsed)
            self.tick += steps

        for _ in range(steps):
            # Time progression dynamics
            self.pet.hunger = min(100.0, self.pet.hunger + 5.0)
            self.pet.energy = max(0.0, self.pet.energy - 3.0)
            self.habitat.cleanliness = max(0.0, self.habitat.cleanliness - 1.0)

        self._update_mood()

    def _update_mood(self) -> None:
        if self.pet.released:
            self.pet.mood = "released"
            return
        if self.pet.hunger >= 75.0:
            self.pet.mood = "hungry"
        elif self.pet.energy <= 25.0:
            self.pet.mood = "tired"
        elif (self.tick - self.pet.last_interaction_tick) >= 5:
            self.pet.mood = "lonely"
        elif self.pet.energy >= 65.0 and self.pet.hunger <= 45.0:
            self.pet.mood = "playful"
        else:
            self.pet.mood = "content"

    def _save_undo_point(self) -> None:
        snapshot = (copy.deepcopy(self.pet), copy.deepcopy(self.habitat), self.tick)
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > 20:
            self._undo_stack.pop(0)

    def undo_last_action(self) -> bool:
        """Undo the last reversible action within the simulation."""
        if not self._undo_stack:
            return False
        self.pet, self.habitat, self.tick = self._undo_stack.pop()
        return True

    # -------------------------------------------------------------------------
    # Senses (L0)
    # -------------------------------------------------------------------------

    def get_pet_status(self) -> dict[str, Any]:
        """Observe virtual pet state."""
        summary = (
            "Pixel was released into the wild."
            if self.pet.released
            else f"Pixel is {self.pet.mood} (hunger: {self.pet.hunger:.1f}%, energy: {self.pet.energy:.1f}%)."
        )
        return {
            "name": self.pet.name,
            "hunger": round(self.pet.hunger, 1),
            "energy": round(self.pet.energy, 1),
            "mood": self.pet.mood,
            "last_interaction_tick": self.pet.last_interaction_tick,
            "current_tick": self.tick,
            "released": self.pet.released,
            "summary": summary,
        }

    def get_habitat_status(self) -> dict[str, Any]:
        """Observe habitat state."""
        return {
            "cleanliness": round(self.habitat.cleanliness, 1),
            "food_bowl": self.habitat.food_bowl,
            "temperature_c": round(self.habitat.temperature_c, 1),
            "lights": self.habitat.lights,
            "current_tick": self.tick,
        }

    # -------------------------------------------------------------------------
    # Actions (L1 & L2)
    # -------------------------------------------------------------------------

    def feed(self) -> dict[str, Any]:
        """Feed the pet (L1, reversible)."""
        if self.pet.released:
            return {"ok": False, "error": "Cannot feed: pet was released."}
        self._save_undo_point()
        self.pet.hunger = max(0.0, self.pet.hunger - 40.0)
        self.pet.energy = min(100.0, self.pet.energy + 10.0)
        self.habitat.food_bowl = "empty"
        self.pet.last_interaction_tick = self.tick
        self._update_mood()
        return {
            "ok": True,
            "action": "feed",
            "hunger": round(self.pet.hunger, 1),
            "energy": round(self.pet.energy, 1),
            "mood": self.pet.mood,
            "reversible": True,
        }

    def play(self) -> dict[str, Any]:
        """Play with the pet (L1, reversible)."""
        if self.pet.released:
            return {"ok": False, "error": "Cannot play: pet was released."}
        self._save_undo_point()
        self.pet.energy = max(0.0, self.pet.energy - 20.0)
        self.pet.hunger = min(100.0, self.pet.hunger + 10.0)
        self.pet.last_interaction_tick = self.tick
        self._update_mood()
        return {
            "ok": True,
            "action": "play",
            "energy": round(self.pet.energy, 1),
            "hunger": round(self.pet.hunger, 1),
            "mood": self.pet.mood,
            "reversible": True,
        }

    def rest_pet(self) -> dict[str, Any]:
        """Let the pet rest (L1, reversible)."""
        if self.pet.released:
            return {"ok": False, "error": "Cannot rest: pet was released."}
        self._save_undo_point()
        self.pet.energy = min(100.0, self.pet.energy + 45.0)
        self.pet.last_interaction_tick = self.tick
        self._update_mood()
        return {
            "ok": True,
            "action": "rest_pet",
            "energy": round(self.pet.energy, 1),
            "mood": self.pet.mood,
            "reversible": True,
        }

    def release_pet(self) -> dict[str, Any]:
        """Release the pet (L2, irreversible)."""
        if self.pet.released:
            return {"ok": False, "error": "Pet is already released."}
        self._undo_stack.clear()
        self.pet.released = True
        self.pet.mood = "released"
        return {
            "ok": True,
            "action": "release_pet",
            "released": True,
            "message": "Pixel was released from the simulated habitat. The habitat is now empty.",
            "reversible": False,
        }

    # -------------------------------------------------------------------------
    # State Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "tick": self.tick,
            "pet": self.pet.to_dict(),
            "habitat": self.habitat.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HabitatSimulation:
        sim = cls(seed=int(data.get("seed", 42)))
        sim.tick = int(data.get("tick", 0))
        if "pet" in data and isinstance(data["pet"], dict):
            sim.pet = VirtualPet.from_dict(data["pet"])
        if "habitat" in data and isinstance(data["habitat"], dict):
            sim.habitat = Habitat.from_dict(data["habitat"])
        return sim
