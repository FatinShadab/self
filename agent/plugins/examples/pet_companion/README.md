# Pet Companion Plugin (`pet_companion`)

The `pet_companion` plugin is a small, safe, deterministic specialization plugin demonstrating every plugin system capability. It ships disabled by default under `/opt/agent/plugins/examples/pet_companion` with zero token cost and no network dependencies.

## Capabilities

- **Simulated Habitat & Virtual Pet:** A simulated virtual pet named Pixel with hunger, energy, mood, and interaction tracking.
- **Sensors (L0):** `pet_companion.pet_status` and `pet_companion.habitat_status`.
- **Actions (L1 & L2):** Reversible actions `feed`, `play`, and `rest_pet` (L1), plus irreversible action `release_pet` (L2, denied by default without human permission grant).
- **Conversation & Slash Commands:** Deterministic state-dependent phrase engine via `pet_companion.talk_to_pet`, and direct human interaction via `/pet <message>`.
- **Autonomy & Identity:** The agent preserves its first-person voice and goals; the pet is an optional simulation and not a sentient creature.
- **State Persistence:** State saved in `workspace/plugins/pet_companion/state`, cleanly archived on unplug and restored on replug with stale facts flagged for re-verification.
