"""Test suite integrating shipped and example plugin unit tests into the main harness runner."""
from __future__ import annotations

from agent.plugins.hello.tests.test_hello import HelloPluginTests
from agent.plugins.examples.pet_companion.tests.test_pet_companion import PetCompanionTests

__all__ = ["HelloPluginTests", "PetCompanionTests"]
