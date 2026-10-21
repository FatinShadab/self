"""Unit tests for pet_companion plugin."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
import tempfile
import shutil

plugin_dir = Path(__file__).resolve().parent.parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from habitat import HabitatSimulation
from phrase_engine import talk_with_pet, get_deterministic_reply
import plugin


class PetCompanionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.state_dir = self.temp_dir / "state"
        self.state_dir.mkdir(parents=True)
        plugin._CONTEXT = {"state_dir": str(self.state_dir)}
        plugin._CONFIG = {"use_helper_model": False, "seed": 42}
        plugin._HABITAT = HabitatSimulation(seed=42)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sensors_return_valid_telemetry(self) -> None:
        p_res = plugin.pet_status()
        self.assertTrue(p_res["ok"])
        self.assertEqual(p_res["pet"]["name"], "Pixel")
        self.assertIn("hunger", p_res["pet"])
        self.assertIn("energy", p_res["pet"])
        self.assertIn("mood", p_res["pet"])

        h_res = plugin.habitat_status()
        self.assertTrue(h_res["ok"])
        self.assertIn("cleanliness", h_res["habitat"])
        self.assertIn("food_bowl", h_res["habitat"])

    def test_actions_behave_deterministically_and_are_reversible(self) -> None:
        sim = HabitatSimulation(seed=42)
        initial_hunger = sim.pet.hunger
        initial_energy = sim.pet.energy

        # Feed
        f_res = sim.feed()
        self.assertTrue(f_res["ok"])
        self.assertLess(sim.pet.hunger, initial_hunger)

        # Undo feed
        self.assertTrue(sim.undo_last_action())
        self.assertEqual(sim.pet.hunger, initial_hunger)
        self.assertEqual(sim.pet.energy, initial_energy)

        # Play
        p_res = sim.play()
        self.assertTrue(p_res["ok"])
        self.assertLess(sim.pet.energy, initial_energy)

        # Undo play
        self.assertTrue(sim.undo_last_action())
        self.assertEqual(sim.pet.energy, initial_energy)

        # Rest
        sim.pet.energy = 20.0
        r_res = sim.rest_pet()
        self.assertTrue(r_res["ok"])
        self.assertGreater(sim.pet.energy, 20.0)

        # Release pet (irreversible)
        rel_res = sim.release_pet()
        self.assertTrue(rel_res["ok"])
        self.assertTrue(sim.pet.released)
        self.assertFalse(sim.undo_last_action(), "Release must be irreversible")

    def test_determinism_by_seed(self) -> None:
        sim1 = HabitatSimulation(seed=123)
        sim2 = HabitatSimulation(seed=123)

        sim1.advance_tick(new_tick=5)
        sim2.advance_tick(new_tick=5)

        self.assertEqual(sim1.to_dict(), sim2.to_dict())

        sim1.feed()
        sim2.feed()
        self.assertEqual(sim1.to_dict(), sim2.to_dict())

    def test_conversation_replies_change_with_pet_state(self) -> None:
        hungry_state = {"mood": "hungry", "hunger": 85.0, "energy": 50.0, "tick": 1}
        tired_state = {"mood": "tired", "hunger": 30.0, "energy": 15.0, "tick": 1}
        playful_state = {"mood": "playful", "hunger": 20.0, "energy": 90.0, "tick": 1}

        hungry_reply = talk_with_pet("hello", hungry_state)["reply"]
        tired_reply = talk_with_pet("hello", tired_state)["reply"]
        playful_reply = talk_with_pet("hello", playful_state)["reply"]

        self.assertTrue(any(w in hungry_reply.lower() for w in ["food", "bowl", "sniff", "whine"]))
        self.assertTrue(any(w in tired_reply.lower() for w in ["sleep", "yawn", "drowsy", "rest"]))
        self.assertTrue(any(w in playful_reply.lower() for w in ["play", "hop", "toy", "bounce", "spin"]))
        self.assertNotEqual(hungry_reply, tired_reply)
        self.assertNotEqual(hungry_reply, playful_reply)

    def test_slash_command_handler(self) -> None:
        reply = plugin.handle_pet_command("hello Pixel!")
        self.assertTrue(reply.startswith("[Pixel the Pet (mood: content)]:"))

    def test_unplug_archives_and_replug_restores_state(self) -> None:
        # 1. Modify state
        plugin._HABITAT.feed()
        saved_hunger = plugin._HABITAT.pet.hunger

        # 2. Disable / Unplug
        plugin.on_disable({"state_dir": str(self.state_dir)})
        archive_file = self.state_dir / "pet_state_archive.json"
        self.assertTrue(archive_file.exists())

        # 3. Simulate process restart / fresh habitat
        plugin._HABITAT = HabitatSimulation(seed=999)
        self.assertNotEqual(plugin._HABITAT.pet.hunger, saved_hunger)

        # 4. Enable / Replug
        plugin.on_enable({"state_dir": str(self.state_dir)})
        self.assertEqual(plugin._HABITAT.pet.hunger, saved_hunger)


if __name__ == "__main__":
    unittest.main()
