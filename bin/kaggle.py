#!/usr/bin/env python3
"""Run the workspace's Kaggle CLI without exposing credentials in commands."""

import os
import re
from pathlib import Path
import subprocess
import sys


def main():
    home = Path(__file__).resolve().parents[1]
    config = home / ".godel" / "kaggle"
    binary = home / ".godel" / "tools" / "kaggle" / "bin" / "python"
    token_file = config / "access_token"
    if not binary.is_file() or not token_file.is_file():
        sys.exit("Kaggle setup is missing; see docs/kaggle.md.")
    token = token_file.read_text().strip()
    if not token or any(c.isspace() for c in token):
        sys.exit("The local Kaggle token must be one nonempty token.")
    env = {k: v for k, v in os.environ.items() if not k.startswith("KAGGLE_")}
    env.update(KAGGLE_API_TOKEN=token, KAGGLE_CONFIG_DIR=str(config))
    result = subprocess.run(
        [str(binary), "-I", "-m", "kaggle", *sys.argv[1:]],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for stream, output in ((sys.stdout, result.stdout), (sys.stderr, result.stderr)):
        text = output.decode(errors="replace").replace(token, "[REDACTED]")
        text = re.sub(r"(https?://)[^/@\s]+@", r"\1[REDACTED]@", text)
        # Download errors may include a signed storage URL, also a credential.
        text = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED]", text)
        stream.write(text)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
