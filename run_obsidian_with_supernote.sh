#!/bin/zsh

# Open Supernote Partner first so it can sync
open -a "Supernote Partner"

# Give Supernote Partner time to start syncing
sleep 20

# Open Obsidian
open -a "Obsidian"

# Give Obsidian a few seconds to start
sleep 5

# Only start automation if it is not already running
if ! pgrep -f "supernote_obsidian_sync.py" > /dev/null; then
  cd ~/supernote-obsidian-sync || exit 1
  ~/supernote-obsidian-sync/.venv/bin/python ~/supernote-obsidian-sync/src/supernote_obsidian_sync.py &
fi