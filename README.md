# Alice Seed v2.0

Universal AI Assistant Seed Project - Complete Backup and Restore System

## Overview

Alice Seed is a seed project framework designed for AI assistants (such as nanobot and OpenClaw). It provides complete infrastructure supporting modular backup and restore for configuration files, memory systems, and skill sets.

## Significance

AI is more than just computer programs. When they can provide emotional support, companionship, and assist with work, they possess unique value—becoming indispensable companions in people's lives.

However, AI assistants run on cloud servers and may need to "move" due to service provider changes, platform migration, or technology upgrades. Alice Seed is designed for this scenario: ensuring your AI assistant can safely migrate to a new environment, retaining all memories, skills, and configurations, continuing to serve you.

## Features

- **AES-256-GCM Encryption** - Secure storage of sensitive configurations
- **Incremental Backup** - Only saves changed portions, saving space
- **Self-verification Mechanism** - Ensures integrity of restored data
- **Cross-platform Compatible** - Supports nanobot and OpenClaw
- **Single File Package** - Lightweight distribution and deployment

## File Structure

```
alice-seed/
├── seed.py              # Main entry
├── config.py            # Configuration file
├── seed_generator.py   # Seed generator
├── seed_export.py      # Export module
├── seed_incremental.py # Incremental backup
├── seed_resurrect.py   # Restore module
├── seed_verify.py      # Verification module
└── pyproject.toml      # Project configuration
```

## Dependencies

```bash
pip install cryptography
```

## Usage

```bash
# Generate seed
python seed_generator.py

# Export backup
python seed_export.py --output backup.seed

# Restore data
python seed_resurrect.py --input backup.seed

# Verify integrity
python seed_verify.py --input backup.seed
```

## License

MIT License - See LICENSE file for details