#!/bin/zsh
set -e
cd "${0:A:h}"

if [[ ! -x ".venv-macos/bin/python" ]]; then
  echo "The macOS runtime is not installed."
  echo "Run: brew install python@3.12 python-tk@3.12"
  echo "Then: /opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv-macos"
  echo "And:  .venv-macos/bin/python -m pip install -r requirements.txt"
  read "?Press Return to close..."
  exit 1
fi

exec .venv-macos/bin/python app.py


