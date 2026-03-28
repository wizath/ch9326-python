# ch9326-hid2serial

Open-source Python driver for the WCH CH9326 HID-to-Serial bridge chip.

## Requirements

- Python 3
- [pyusb](https://pypi.org/project/pyusb/) (`pip install pyusb`)
- libusb 1.x backend

## Usage

### CLI -- serial terminal

```bash
# read at 9600 baud (default), raw bytes to stdout
sudo python3 ch9326.py

# read at 19200 baud, print hex
sudo python3 ch9326.py -b 19200 --hex

# send a string and exit
sudo python3 ch9326.py -b 115200 -s "AT\r\n"

# pipe data in
echo -ne "\x1e\x00\x00\x00\x00\x00\x00\x1e" | sudo python3 ch9326.py -b 19200
```

### Library

```python
from ch9326 import CH9326

dev = CH9326()
dev.open()
dev.configure(baud=19200)

dev.send(b"hello")
data = dev.recv(timeout=1000)

dev.set_gpio_dir(0x03)    # IO1 and IO2 as output
dev.set_gpio_data(0x01)   # IO1 high, IO2 low
gpio = dev.get_gpio()     # read GPIO input state

dev.close()
```

## Permissions

The script requires root or a udev rule. To run without sudo, create
`/etc/udev/rules.d/99-ch9326.rules`:

```
SUBSYSTEM=="usb", ATTR{idVendor}=="1a86", ATTR{idProduct}=="e010", MODE="0666"
```

Then reload: `sudo udevadm control --reload-rules && sudo udevadm trigger`

---

## Protocol Reference

Reverse-engineered from `libch9326.so` (x86-64) via Ghidra decompilation.

### USB Device

| Field | Value |
|---|---|
| VID | 0x1A86 (WCH / QinHeng Electronics) |
| PID | 0xE010 |
| Class | HID |
| Interface | 0 |
| OUT endpoint | 0x02 (interrupt) |
| IN endpoint | 0x82 (interrupt) |
| Report size | 32 bytes |
| Max payload | 31 bytes per report |

HID report descriptor uses vendor-defined Usage Page (0xFFA0), report count 32,
report size 8 bits.

### Serial Configuration

Sent as a 32-byte USB HID SET_REPORT control transfer:

```
bmRequestType: 0x21 (class, host-to-device, interface)
bRequest:      0x09 (SET_REPORT)
wValue:        0x0200 (output report, ID 0)
wIndex:        0
wLength:       32
```

#### Config buffer layout

| Byte | Description |
|---|---|
| 0 | Always 0xFF |
| 1 | Line Control Register (LCR) |
| 2 | Baud rate high byte |
| 3 | Baud rate low byte |
| 4 | Polling interval |
| 5-31 | 0x00 |

#### Line Control Register (byte 1)

```
Bit 7:6  MUST be set (0xC0) -- enables the serial transceiver
Bit 5:3  Parity
Bit 2    Stop bits
Bit 1:0  Data bits
```

**Bits 7:6 are critical.** Without 0xC0 set, the CH9326 will not transmit or
receive any serial data. This is the most common integration pitfall.

Data bits (bits 1:0):

| Value | Bits |
|---|---|
| 0b00 | 5 |
| 0b01 | 6 |
| 0b10 | 7 |
| 0b11 | 8 |

Stop bits (bit 2):

| Value | Stop |
|---|---|
| 1 | 1 stop bit |
| 0 | 2 stop bits |

Parity (bits 5:3):

| Value | Parity |
|---|---|
| 0b000 | None |
| 0b001 | Odd |
| 0b011 | Even |
| 0b111 | Space |

Common LCR values:

| Config | LCR |
|---|---|
| 8N1 | 0xC7 |
| 8E1 | 0xDF |
| 8O1 | 0xCF |
| 7E1 | 0xDE |

#### Baud rate divisors (bytes 2-3)

| Baud | Byte 2 | Byte 3 |
|---|---|---|
| 300 | 0x80 | 0xD9 |
| 600 | 0x81 | 0x64 |
| 1200 | 0x81 | 0xB2 |
| 2400 | 0x81 | 0xD9 |
| 4800 | 0x82 | 0x64 |
| 9600 | 0x82 | 0xB2 |
| 14400 | 0x82 | 0xCC |
| 19200 | 0x82 | 0xD9 |
| 28800 | 0x83 | 0x30 |
| 38400 | 0x83 | 0x64 |
| 57600 | 0x83 | 0x98 |
| 76800 | 0x83 | 0xB2 |
| 115200 | 0x83 | 0xCC |

#### Polling interval (byte 4)

| Value | Interval |
|---|---|
| 0x10 | 3 ms (default) |
| 0x20 | 6 ms |
| 0x30 | 9 ms |

### Data Transfer

Both send and receive use the same HID report framing on their respective
endpoints:

```
Byte 0:     payload length (1-31)
Byte 1..N:  serial data bytes
```

**Send (host -> serial):** Written to OUT endpoint 0x02 as interrupt transfers.
Data longer than 31 bytes is split across multiple reports. Each full report
carries 31 bytes (byte 0 = 0x1F), the final report carries the remainder.

**Receive (serial -> host):** Read from IN endpoint 0x82 as interrupt transfers.
Same framing -- byte 0 is the count of valid data bytes following it.

The vendor library uses an 8192-byte circular ring buffer for receive data,
fed by a background thread doing continuous interrupt reads.

### GPIO

The CH9326 has two GPIO pins (IO1 and IO2), controlled via SET_REPORT / GET_REPORT.

#### Set direction (command 0xC0)

```
Byte 0:   0xC0
Byte 1:   direction mask (bit 0=IO1, bit 1=IO2; 0=input, 1=output)
Byte 2-31: 0x00
```

Sent via SET_REPORT (0x21, 0x09, 0x0200).

#### Set output level (command 0xB0)

```
Byte 0:   0xB0
Byte 1:   level mask (bit 0=IO1, bit 1=IO2; 0=low, 1=high)
Byte 2-31: 0x00
```

Sent via SET_REPORT (0x21, 0x09, 0x0200).

#### Read input level

```
bmRequestType: 0xA1 (class, device-to-host, interface)
bRequest:      0x01 (GET_REPORT)
wValue:        0x0100 (input report)
```

Returns 2 bytes. First byte contains:
- Bit 5: IO1 level (1=high, 0=low)
- Bit 3: IO2 level (1=high, 0=low)

### Vendor Library Internals

The original `libch9326.so` maintains an array of up to 16 device structs, each
88 (0x58) bytes:

| Offset | Size | Field |
|---|---|---|
| 0x00 | 8 | libusb device pointer |
| 0x08 | 8 | libusb device handle |
| 0x10 | 8 | ring buffer read position |
| 0x18 | 8 | ring buffer write position |
| 0x20 | 8 | ring buffer size (0x2000) |
| 0x28 | 8 | ring buffer pointer (malloc) |
| 0x30 | 4 | control transfer timeout (1000 ms) |
| 0x34 | 4 | interrupt read timeout (2000 ms) |
| 0x38 | 4 | OUT endpoint (0x02) |
| 0x3C | 4 | IN endpoint (0x82) |
| 0x40 | 4 | device index |
| 0x44 | 4 | opened flag |
| 0x48 | 4 | close/stop flag |
| 0x50 | 8 | recv thread (pthread_t) |

## License

MIT
