"""
hotflash_client.py - laptop client for the ESP32 hot-flash LED test.

Usage:
    pip install pyserial
    python hotflash_client.py COM3            (Windows)
    python hotflash_client.py /dev/ttyUSB0    (Linux)
    python hotflash_client.py /dev/cu.usbserial-XXXX   (macOS)
    python hotflash_client.py                 (lists available ports)

Commands at the prompt:
    start     play the hot-flash sequence
    stop      stop immediately
    help      list these commands
    quit      exit (Ctrl+C does the same); does not send STOP

After 10 s without a command, the ESP32 closes the channel by itself (CUTOFF):
it stops the sequence and switches the LEDs off. When this client receives the
CUTOFF message, it closes the connection and exits. The timeout lives only on
the ESP32 (CUTOFF_MS in hotflash.ino).
"""


import os
import sys
import threading
import time

import serial
from serial.tools import list_ports

ESP32_COMMANDS = ("start", "stop")
COMMANDS = "start, stop, help, quit"


class Client:
    def __init__(self, port, baud=115200):
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate, self.ser.timeout = port, baud, 0.1
        # ESP32 boards wire DTR/RTS to their reset pin. Keeping both off means closing
        # the port (quit, Ctrl+C, closing the terminal) doesn't restart the ESP32,
        # so a running sequence is ended by the safety cutoff instead.
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        time.sleep(2)                    # some boards restart when the port opens anyway
        self.ser.reset_input_buffer()

        self.lock = threading.Lock()
        self.alive = True

        threading.Thread(target=self._reader, daemon=True).start()

    def send(self, line):
        with self.lock:
            self.ser.write((line + "\n").encode())

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
                if text.startswith("CUTOFF"):    # the ESP32 closed the channel: close the connection too
                    print(f"\n<< {text}\nConnection closed.", flush=True)
                    self.close()
                    os._exit(0)                  # the main thread is stuck waiting in input()
                if text:
                    self._print(f"<< {text}")

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
