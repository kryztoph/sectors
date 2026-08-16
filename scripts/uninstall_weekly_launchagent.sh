#!/bin/sh
set -eu

LABEL="com.fox.sectors.cotpy.weekly"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

if launchctl print "$GUI_DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$GUI_DOMAIN/$LABEL"
fi

rm -f "$TARGET_PLIST"
echo "$LABEL uninstalled."
