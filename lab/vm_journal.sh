#!/bin/sh
# $1/$2 = epoch seconds. Single tokens on purpose: multipass re-splits arguments
# that contain spaces, which silently dropped the --since/--until bounds before.
journalctl -u fim-agent --since "@$1" --until "@$2" --no-pager 2>/dev/null
