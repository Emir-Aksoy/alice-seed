#!/usr/bin/env python3
"""
Alice Seed CLI
Usage: seed.py <command> [options]
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alice Seed — AI agent backup & recovery tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  seed.py generate                              # generate seed (auto-detect agent)
  seed.py generate --encrypt --agent claude     # encrypted seed for Claude/openclaw
  seed.py generate --agent nanobot              # seed for nanobot
  seed.py verify   seed.zip --check-hash        # verify integrity
  seed.py restore  seed.zip --agent claude      # restore to Claude
  seed.py restore  seed.zip --decrypt           # restore encrypted seed
  seed.py restore  seed.zip --dry-run           # preview without writing
  seed.py export   seed.zip --format claude     # export to Claude format
  seed.py export   seed.zip --format langchain  # export to LangChain format
  seed.py incremental create -p parent.zip      # delta backup
  seed.py incremental apply  -b base.zip -i inc.zip
        """,
    )

    AGENT_CHOICES = ["nanobot", "claude"]

    sub = parser.add_subparsers(dest="command")

    # ── generate ──────────────────────────────────────────────────────────
    p_gen = sub.add_parser("generate", help="Generate a seed package")
    p_gen.add_argument("--encrypt", "-e", action="store_true",
                       help="Encrypt sensitive data with AES-256-GCM")
    p_gen.add_argument("--password", "-p", help="Encryption password")
    p_gen.add_argument("--agent",   "-a", choices=AGENT_CHOICES,
                       help="Agent profile (auto-detected if omitted)")
    p_gen.add_argument("--output",  "-o", help="Output directory")

    # ── verify ────────────────────────────────────────────────────────────
    p_ver = sub.add_parser("verify", help="Verify a seed file")
    p_ver.add_argument("seed_file")
    p_ver.add_argument("--check-hash", action="store_true",
                       help="Verify stored content hashes")

    # ── restore ───────────────────────────────────────────────────────────
    p_res = sub.add_parser("restore", help="Restore from a seed file")
    p_res.add_argument("seed_file")
    p_res.add_argument("--decrypt",  "-d", action="store_true",
                       help="Decrypt secrets from an encrypted seed")
    p_res.add_argument("--password", "-p", help="Decryption password")
    p_res.add_argument("--dry-run",  "-n", action="store_true",
                       help="Preview restore without writing any files")
    p_res.add_argument("--components", "-c", default="all",
                       help="Comma-separated: files,cron  (default: all)")
    p_res.add_argument("--agent",    "-a", choices=AGENT_CHOICES,
                       help="Target agent profile")

    # ── export ────────────────────────────────────────────────────────────
    p_exp = sub.add_parser("export", help="Export seed to a framework format")
    p_exp.add_argument("seed_file")
    p_exp.add_argument("--format", "-f", required=True,
                       choices=["langchain", "autogen", "crewai", "openai", "claude"],
                       help="Target format")
    p_exp.add_argument("--output", "-o", help="Output directory")

    # ── incremental ───────────────────────────────────────────────────────
    p_inc = sub.add_parser("incremental", help="Incremental (delta) backups")
    inc_sub = p_inc.add_subparsers(dest="subcommand")

    p_inc_create = inc_sub.add_parser("create", help="Create a delta backup")
    p_inc_create.add_argument("--parent", "-p", required=True,
                              help="Parent (base) seed file")
    p_inc_create.add_argument("--output", "-o", help="Output file path")
    p_inc_create.add_argument("--agent",  "-a", choices=AGENT_CHOICES)

    p_inc_apply = inc_sub.add_parser("apply", help="Merge delta into base seed")
    p_inc_apply.add_argument("--base",        "-b", required=True,
                             help="Base seed file")
    p_inc_apply.add_argument("--incremental", "-i", required=True,
                             help="Incremental seed file")
    p_inc_apply.add_argument("--output",      "-o", help="Output file path")

    # ── Dispatch ──────────────────────────────────────────────────────────
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "generate":
        from seed_generator import create_seed_package
        out = Path(args.output) if args.output else None
        create_seed_package(
            encrypt=args.encrypt,
            password=args.password,
            agent=args.agent,
            output_dir=out,
        )

    elif args.command == "verify":
        from seed_verify import verify_seed_file
        ok = verify_seed_file(args.seed_file, check_hash=args.check_hash)
        sys.exit(0 if ok else 1)

    elif args.command == "restore":
        from seed_resurrect import resurrect_seed
        ok = resurrect_seed(
            args.seed_file,
            decrypt=args.decrypt,
            password=args.password,
            dry_run=args.dry_run,
            components=args.components,
            agent=args.agent,
        )
        sys.exit(0 if ok else 1)

    elif args.command == "export":
        from seed_export import export_seed
        ok = export_seed(args.seed_file, args.format, args.output)
        sys.exit(0 if ok else 1)

    elif args.command == "incremental":
        if args.subcommand == "create":
            from seed_incremental import create_incremental_seed
            ok = create_incremental_seed(
                args.parent, args.output, getattr(args, "agent", None)
            )
        elif args.subcommand == "apply":
            from seed_incremental import apply_incremental_seed
            ok = apply_incremental_seed(args.base, args.incremental, args.output)
        else:
            p_inc.print_help()
            sys.exit(1)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
