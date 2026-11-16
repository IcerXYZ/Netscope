#!/opt/netscope/venv/bin/python
"""Create, list and revoke per-agent NetScope enrollment tokens."""
import argparse
import grp
import json
import os
import secrets
import sys
import tempfile
from werkzeug.security import generate_password_hash

DEFAULT_PATH = "/etc/netscope-agent-tokens.json"
AGENT_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


def read_tokens(path=DEFAULT_PATH):
    """Read token hashes. An absent or empty file means no agents are enrolled."""
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read().strip()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}). "
            "No data was changed; restore a valid token registry before continuing."
        ) from exc
    if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
        raise RuntimeError(f"{path} must contain a JSON object mapping agent IDs to password hashes.")
    return data


def write_tokens(data, path=DEFAULT_PATH):
    """Atomically write the registry with root ownership and service-group read access."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o755, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".netscope-tokens-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        try:
            gid = grp.getgrnam("netscope").gr_gid
        except KeyError:
            gid = os.stat(path).st_gid if os.path.exists(path) else os.getgid()
        os.chown(temporary, 0, gid)
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    except OSError as exc:
        raise RuntimeError(f"Cannot update {path}: {exc}. Run this command with sudo.") from exc
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def valid_agent_id(agent_id):
    return bool(agent_id) and len(agent_id) <= 64 and all(c in AGENT_ID_CHARS for c in agent_id)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Manage individual NetScope agent credentials.",
        epilog=(
            "Examples:\n"
            "  sudo netscope-agent-token add proxmox-node-01\n"
            "  sudo netscope-agent-token list\n"
            "  sudo netscope-agent-token revoke proxmox-node-01\n"
            "Each generated token is displayed once. Copy it to the matching agent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("action", choices=("add", "revoke", "list"), help="operation to perform")
    parser.add_argument("agent_id", nargs="?", help="unique ID for the monitored machine")
    args = parser.parse_args(argv)
    path = os.environ.get("NETSCOPE_AGENT_TOKENS_FILE", DEFAULT_PATH)

    if args.action == "list":
        if args.agent_id:
            parser.error("list does not take an agent ID")
    elif not valid_agent_id(args.agent_id):
        parser.error("agent ID must be 1–64 characters: letters, numbers, dot, underscore or dash")

    try:
        data = read_tokens(path)
        if args.action == "list":
            if not data:
                print("No agents enrolled yet. Create one with: sudo netscope-agent-token add <agent-id>")
            else:
                print("Registered agents:")
                for agent_id in sorted(data):
                    print(f"  {agent_id}")
            return 0

        if args.action == "add":
            if args.agent_id in data:
                parser.error(
                    f"agent ID '{args.agent_id}' already exists; revoke it first if you intend to replace its token"
                )
            token = secrets.token_urlsafe(36)
            data[args.agent_id] = generate_password_hash(token, method="scrypt")
            write_tokens(data, path)
            print(f"Agent ID: {args.agent_id}")
            print("Agent token (shown once; copy it now):")
            print(token)
            print("\nInstall Agent mode on the matching machine and paste this token when prompted.")
            return 0

        if args.agent_id not in data:
            print(f"Agent ID '{args.agent_id}' was not found.", file=sys.stderr)
            return 1
        del data[args.agent_id]
        write_tokens(data, path)
        print(f"Revoked agent: {args.agent_id}")
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
