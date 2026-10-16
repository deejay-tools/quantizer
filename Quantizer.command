#!/bin/zsh
# Doppio clic nel Finder per aprire l'interfaccia di Quantizer nel browser.
cd "$(dirname "$0")"
exec .venv/bin/python gui.py
