#!/usr/bin/env bash
set -euo pipefail

# Stream default PulseAudio microphone to the local RTMP ingest used by the stack.
# Requires ffmpeg installed on the host.

ffmpeg -f pulse -i default -ac 2 -ar 44100 -c:a aac -b:a 128k -f flv rtmp://localhost:1935/live/zoom
