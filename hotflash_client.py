"""
hotflash_client.py - laptop client for the ESP32 hot-flash LED test.

Usage:
    pip install pyserial
    python hotflash_client.py COM3            (Windows)
    python hotflash_client.py /dev/ttyUSB0    (Linux)
    python hotflash_client.py /dev/cu.usbserial-XXXX   (macOS)
    python hotflash_client.py                 (lists available ports)

Commands at the prompt:
    start     play the hot-flash sequence (turns the channel on)
    stop      stop immediately
    status    ask the ESP32 for its state
    help      list these commands
    quit      exit (Ctrl+C does the same); does not send STOP

After 10 s without a command, the ESP32 switches the channel off by itself
(CUTOFF) and this client closes the connection and exits.
"""


import os
import sys
import threading
import time

import serial
from serial.tools import list_ports

CUTOFF_S = 10                    # must match CUTOFF_MS in hotflash.ino
IDLE_TIMEOUT = CUTOFF_S + 0.5    # close a little after the ESP32's cutoff, so its CUTOFF message shows
ESP32_COMMANDS = ("start", "stop", "status")
COMMANDS = "start, stop, status, help, quit"


class Client:
    def __init__(self, port, baud=115200):
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate, self.ser.timeout = port, baud, 0.1
        # ESP32 boards wire DTR/RTS to their reset pin. Keeping both off means closing
        # the port (quit, Ctrl+C, closing the terminal) doesn't restart the ESP32,
        # so a running channel is ended by the safety cutoff instead.
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        time.sleep(2)                    # some boards restart when the port opens anyway
        self.ser.reset_input_buffer()

        self.lock = threading.Lock()
        self.alive = True
        self.last_cmd = time.monotonic()

        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._idle_watch, daemon=True).start()

    def send(self, line):
        with self.lock:
            self.ser.write((line + "\n").encode())
        self.last_cmd = time.monotonic()

    def _print(self, text):
        print(f"\n{text}\n> ", end="", flush=True)

    def _reader(self):
        buf = b""
        while self.alive:
            try:
                buf += self.ser.read(self.ser.in_waiting or 1)
            except (serial.SerialException, OSError, TypeError):
                if self.alive:
                    self._print("[serial connection lost]")
                self.alive = False
                break
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                if text:
                    self._print(f"<< {text}")

    def _idle_watch(self):
        while self.alive:
            if time.monotonic() - self.last_cmd > IDLE_TIMEOUT:
                print(f"\nNo command for {CUTOFF_S} s - connection closed.", flush=True)
                self.close()
                os._exit(0)              # the main thread is stuck waiting in input()
            time.sleep(0.1)

    def close(self):
        self.alive = False
        time.sleep(0.2)
        self.ser.close()


def main():
    if len(sys.argv) < 2:
        print("Available ports:")
        for p in list_ports.comports():
            print(f"  {p.device:20} {p.description}")
        print("\nUsage: python hotflash_client.py <port>")
        return

    client = Client(sys.argv[1])
    print(f"Connected. Commands: {COMMANDS}")

    try:
        while client.alive:
            cmd = input("> ").strip().lower()
            if cmd in ("quit", "exit"):
                break
            elif cmd == "help":
                print(f"   Commands: {COMMANDS}")
            elif cmd in ESP32_COMMANDS:
                client.send(cmd.upper())
            elif cmd:
                print("   Unknown command. Type help.")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        client.close()


if __name__ == "__main__":
    main()
