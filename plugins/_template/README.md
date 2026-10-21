# Plugin Template Skeleton

This directory provides the canonical starter template for developing SELF plugins.

## Structure

```
plugins/<name>/
├── plugin.json         # Manifest declaring tools, sensors, actions, and metadata
├── plugin.py           # Python implementations of tools, sensors, actions, and hooks
├── tests/              # Plugin unit test suite
│   └── test_plugin.py  # Tests validating tools and functionality
└── state/              # Private runtime state directory (created at runtime)
```

## Scaffolding

To create a new plugin from this template:

```bash
python -m agent.plugins new <plugin_name>
```

This validates the plugin name, copies the template skeleton, and updates the manifest.

## Validating

To statically check your plugin:

```bash
python -m agent.plugins validate plugins/<plugin_name>
```

## Running Tests

To run your plugin's unit tests:

```bash
python -m unittest discover -s plugins/<plugin_name>/tests
```
