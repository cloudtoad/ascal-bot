import logging
import os
import sys
import tomllib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.toml")

try:
    with open(CONFIG_PATH, "rb") as f:
        config = tomllib.load(f)
except FileNotFoundError:
    print(f"Config file not found: {CONFIG_PATH}", file=sys.stderr)
    print("Copy config.example.toml to config.toml and fill in your details.", file=sys.stderr)
    sys.exit(1)

# Allow env var overrides
if os.environ.get("MATRIX_PASSWORD"):
    config.setdefault("matrix", {})["password"] = os.environ["MATRIX_PASSWORD"]
if os.environ.get("MATRIX_ACCESS_TOKEN"):
    config.setdefault("matrix", {})["access_token"] = os.environ["MATRIX_ACCESS_TOKEN"]

from bot.main import run_bot

run_bot(config)
