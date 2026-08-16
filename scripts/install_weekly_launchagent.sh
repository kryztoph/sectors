#!/bin/sh
set -eu

LABEL="com.fox.sectors.cotpy.weekly"
PROJECT_DIR="/Users/fox/Private/Projects/sectors"
SOURCE_PLIST="$PROJECT_DIR/launchd/$LABEL.plist.template"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

mkdir -p "$PROJECT_DIR/logs" "$TARGET_DIR"
sed "s#__ROOT_DIR__#$PROJECT_DIR#g" "$SOURCE_PLIST" > "$TARGET_PLIST"
chmod 644 "$TARGET_PLIST"

if launchctl print "$GUI_DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$GUI_DOMAIN/$LABEL"
fi

launchctl bootstrap "$GUI_DOMAIN" "$TARGET_PLIST"
launchctl enable "$GUI_DOMAIN/$LABEL"

echo "$LABEL installed."
echo "Scheduled for Fridays at 5:45 PM local time."
echo "Run now with: launchctl kickstart -k $GUI_DOMAIN/$LABEL"
