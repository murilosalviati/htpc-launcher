#!/usr/bin/env bash
# Quick checks of the extension over D-Bus.
# Usage:
#   ./test.sh                      list open windows and the focused app
#   ./test.sh activate <appId>     raise the app
#   ./test.sh running <appId>      tell whether the app is running
#   ./test.sh close <appId>        ask the app to close
#   ./test.sh launcher             show the launcher
#   ./test.sh focus [seconds]      follow focus changes (stops by itself; 60 s by default)
set -euo pipefail

call() {
    gdbus call --session --dest org.htpc.Launcher \
        --object-path /org/htpc/Launcher \
        --method "org.htpc.Launcher.$1" "${@:2}"
}

case "${1:-list}" in
    list)
        call ListWindows
        echo "Focused: $(call FocusedApp)"
        ;;
    activate) call Activate "$2" ;;
    running)  call IsRunning "$2" ;;
    close)    call Close "$2" ;;
    launcher) call ShowLauncher ;;
    focus)
        # Stops after N seconds (60 by default) so it is not left running on the machine.
        timeout "${2:-60}" gdbus monitor --session --dest org.htpc.Launcher \
            --object-path /org/htpc/Launcher || true
        ;;
    *) echo "Unknown command: $1"; exit 1 ;;
esac
