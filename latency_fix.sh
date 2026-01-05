#!/bin/bash
# Script to optimize USB-Serial latency on Linux for Robot Control
# Usage: sudo ./latency_fix.sh

echo "--- Optimizing USB-Serial Latency ---"

# 1. Iterate over all direct USB-Serial devices in /sys/bus/usb-serial/devices/
FOUND=0

for dev in /sys/bus/usb-serial/devices/*; do
    if [ -d "$dev" ]; then
        LATENCY_FILE="$dev/latency_timer"
        if [ -f "$LATENCY_FILE" ]; then
            echo "Found device: $dev"
            
            OLD_VAL=$(cat "$LATENCY_FILE")
            echo "  Current Latency: ${OLD_VAL} ms"
            
            # Set to 1ms
            echo 1 > "$LATENCY_FILE"
            
            NEW_VAL=$(cat "$LATENCY_FILE")
            echo "  New Latency:     ${NEW_VAL} ms"
            
            if [ "$NEW_VAL" -eq 1 ]; then
                echo "  [OK] Success."
                FOUND=1
            else
                echo "  [FAIL] Could not set latency."
            fi
        fi
    fi
done

if [ $FOUND -eq 0 ]; then
    echo "No supported USB-Serial devices found yet."
    echo "Trying standard ttyUSB/ttyACM enumeration..."
    
    # Fallback/General method via setserial (if installed)
    if command -v setserial &> /dev/null; then
        for tty in /dev/ttyUSB* /dev/ttyACM*; do
            [ -e "$tty" ] || continue
            echo "Attempting low_latency on $tty via setserial..."
            setserial "$tty" low_latency
        done
    else
        echo "setserial tool not found (optional)."
    fi
fi

echo "--- Done ---"
echo "Note: This resets after reboot or unplugging."
echo "To make persistent, creates a udev rule:"
echo 'ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"'
