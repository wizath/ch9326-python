#!/usr/bin/env python3
"""
CH9326 HID-to-Serial bridge driver.

Usage as serial terminal:
    sudo python3 ch9326.py                        # default 9600 8N1
    sudo python3 ch9326.py -b 19200               # 19200 baud
    sudo python3 ch9326.py -b 115200 -s "hello"   # send string
    echo "data" | sudo python3 ch9326.py -b 9600   # pipe mode

Usage as library:
    from ch9326 import CH9326
    dev = CH9326()
    dev.open()
    dev.configure(baud=19200)
    dev.send(b"hello")
    data = dev.recv(timeout=1000)
    dev.close()
"""

import usb.core
import usb.util
import argparse
import select
import sys
import os

VID = 0x1A86
PID = 0xE010
EP_OUT = 0x02
EP_IN = 0x82
IFACE = 0
REPORT_SIZE = 32
MAX_PAYLOAD = 31

BAUD_RATES = {
    300:    (0x80, 0xD9),
    600:    (0x81, 0x64),
    1200:   (0x81, 0xB2),
    2400:   (0x81, 0xD9),
    4800:   (0x82, 0x64),
    9600:   (0x82, 0xB2),
    14400:  (0x82, 0xCC),
    19200:  (0x82, 0xD9),
    28800:  (0x83, 0x30),
    38400:  (0x83, 0x64),
    57600:  (0x83, 0x98),
    76800:  (0x83, 0xB2),
    115200: (0x83, 0xCC),
}

PARITY_NONE  = 0b000
PARITY_ODD   = 0b001
PARITY_EVEN  = 0b011
PARITY_SPACE = 0b111

DATABITS_5 = 0b00
DATABITS_6 = 0b01
DATABITS_7 = 0b10
DATABITS_8 = 0b11


class CH9326:
    def __init__(self):
        self.dev = None

    def open(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError("CH9326 not found")
        if self.dev.is_kernel_driver_active(IFACE):
            self.dev.detach_kernel_driver(IFACE)
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, IFACE)

    def close(self):
        if self.dev:
            try:
                usb.util.release_interface(self.dev, IFACE)
            except usb.core.USBError:
                pass
            usb.util.dispose_resources(self.dev)
            self.dev = None

    def configure(self, baud=9600, parity=PARITY_NONE, databits=DATABITS_8,
                  stopbits=1, interval=0x10):
        if baud not in BAUD_RATES:
            raise ValueError(f"unsupported baud rate: {baud}")
        b1, b2 = BAUD_RATES[baud]

        lcr = 0xC0  # required enable bits
        lcr |= databits & 0x03
        lcr |= 0x04 if stopbits == 1 else 0x00
        lcr |= (parity & 0x07) << 3

        buf = bytearray(REPORT_SIZE)
        buf[0] = 0xFF
        buf[1] = lcr
        buf[2] = b1
        buf[3] = b2
        buf[4] = interval
        self.dev.ctrl_transfer(0x21, 0x09, 0x0200, 0, buf, timeout=1000)

    def send(self, data):
        data = bytes(data)
        sent = 0
        while sent < len(data):
            chunk = data[sent:sent + MAX_PAYLOAD]
            report = bytearray(len(chunk) + 1)
            report[0] = len(chunk)
            report[1:] = chunk
            self.dev.write(EP_OUT, report, timeout=1000)
            sent += len(chunk)
        return sent

    def recv(self, timeout=1000):
        try:
            raw = self.dev.read(EP_IN, REPORT_SIZE, timeout=timeout)
        except usb.core.USBTimeoutError:
            return b""
        if len(raw) < 1:
            return b""
        length = raw[0]
        if length == 0 or length > MAX_PAYLOAD:
            return b""
        return bytes(raw[1:1 + length])

    def set_gpio_dir(self, direction):
        buf = bytearray(REPORT_SIZE)
        buf[0] = 0xC0
        buf[1] = direction & 0x03
        self.dev.ctrl_transfer(0x21, 0x09, 0x0200, 0, buf, timeout=1000)

    def set_gpio_data(self, data):
        buf = bytearray(REPORT_SIZE)
        buf[0] = 0xB0
        buf[1] = data & 0x03
        self.dev.ctrl_transfer(0x21, 0x09, 0x0200, 0, buf, timeout=1000)

    def get_gpio(self):
        ret = self.dev.ctrl_transfer(0xA1, 0x01, 0x0100, 0, REPORT_SIZE, timeout=2000)
        if len(ret) >= 1:
            return ret[0]
        return 0


def main():
    parser = argparse.ArgumentParser(description="CH9326 HID-to-Serial bridge")
    parser.add_argument("-b", "--baud", type=int, default=9600,
                        choices=sorted(BAUD_RATES.keys()),
                        help="baud rate (default: 9600)")
    parser.add_argument("-s", "--send", type=str, default=None,
                        help="send string and exit")
    parser.add_argument("--hex", action="store_true",
                        help="print received bytes as hex")
    args = parser.parse_args()

    dev = CH9326()
    dev.open()
    dev.configure(baud=args.baud)
    print(f"CH9326 opened at {args.baud} baud", file=sys.stderr)

    if args.send is not None:
        dev.send(args.send.encode())
        dev.close()
        return

    stdin_is_pipe = not os.isatty(sys.stdin.fileno())

    if stdin_is_pipe:
        data = sys.stdin.buffer.read()
        if data:
            dev.send(data)

    try:
        while True:
            data = dev.recv(timeout=500)
            if data:
                if args.hex:
                    print(" ".join(f"{b:02x}" for b in data), flush=True)
                else:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()


if __name__ == "__main__":
    main()
