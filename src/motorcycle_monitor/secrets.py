"""Credential loading shared by external-service adapters; never logs values."""

import os
import re
from pathlib import Path

FORMATS = {
    "DEEPSEEK_API_KEY": r"\bsk-[A-Za-z0-9_-]+",
    "GITHUB_TOKEN": r"\b(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9]+)",
}


def credential(environment_name: str, path: str) -> str:
    environment = os.environ.get(environment_name)
    text = environment if environment else Path(path).read_text().strip()
    matches = re.findall(FORMATS.get(environment_name, r"(?!)"), text)
    value = matches[0] if len(matches) == 1 else text
    if not value or len(value) > 4096 or any(char.isspace() for char in value):
        raise ValueError("Invalid API credential")
    if environment_name == "DEEPSEEK_API_KEY" and value.startswith(("gh", "github_")):
        raise ValueError("Incorrect API credential type")
    return value
