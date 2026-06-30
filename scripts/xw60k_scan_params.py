#!/usr/bin/env python3
"""
XW60K Parameter Range Scanner
Reads holding registers 0x0300–0x0380 directly via ESPHome TCP bridge (port 8888)
and prints all non-zero values alongside known parameter names.

Usage:
  python3 xw60k_scan_params.py <esp-ip> [slave_id]
  python3 xw60k_scan_params.py 10.0.4.242 1
"""

import sys
import socket
import struct
import time
import csv

# Known addresses from register map PDF + empirical testing
KNOWN = {
    0x0108: ("Probe1",    "Probe 1 / Verdampfertemperatur",    "temp"),
    0x0100: ("ProbeR",    "Probe R / Raumtemperatur",          "temp"),
    0x035E: ("SEt",       "Set point (live operating value)",  "temp"),
}

# Likely parameter range — scan 0x0300 to 0x03FF
SCAN_START = 0x0300
SCAN_END   = 0x0400  # exclusive


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def read_holding(sock, slave: int, addr: int, qty: int = 16) -> list[int] | None:
    req = struct.pack('>BBHH', slave, 0x03, addr, qty)
    req += struct.pack('<H', crc16(req))
    try:
        sock.sendall(req)
        time.sleep(0.15)
        resp = b''
        deadline = time.time() + 1.0
        while len(resp) < 5 and time.time() < deadline:
            chunk = sock.recv(256)
            if chunk:
                resp += chunk
        if len(resp) < 5 or resp[1] != 0x03:
            return None
        n = resp[2]
        expected = 3 + n + 2
        while len(resp) < expected and time.time() < deadline:
            chunk = sock.recv(256)
            if chunk:
                resp += chunk
        if len(resp) < expected:
            return None
        return [struct.unpack('>H', resp[3 + i*2: 5 + i*2])[0] for i in range(n // 2)]
    except Exception as e:
        print(f"  [!] {e}", file=sys.stderr)
        return None


def signed16(v: int) -> int:
    return v if v < 0x8000 else v - 0x10000


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    ip    = sys.argv[1]
    slave = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    port  = 8888

    print(f"Connecting to {ip}:{port}  (Modbus slave {slave}) ...")
    sock = socket.create_connection((ip, port), timeout=5)
    print(f"Connected.  Scanning 0x{SCAN_START:04X}–0x{SCAN_END - 1:04X} ...\n")

    results = []
    addr = SCAN_START
    batch = 16

    while addr < SCAN_END:
        qty = min(batch, SCAN_END - addr)
        words = read_holding(sock, slave, addr, qty)
        if words is None:
            # Retry one-by-one on error
            words = []
            for i in range(qty):
                r = read_holding(sock, slave, addr + i, 1)
                words.append(r[0] if r else 0xFFFF)

        for i, raw in enumerate(words):
            a = addr + i
            s = signed16(raw)
            known = KNOWN.get(a, ('', ''))
            code, desc = known[0], known[1]
            scale = known[2] if len(known) > 2 else ''
            if scale == 'temp':
                disp = f"{s * 0.1:+.1f}°C"
            else:
                disp = f"{s:6d}  (0x{raw:04X})"

            marker = '  ←' if code else ''
            print(f"  0x{a:04X} ({a:4d}):  {disp:>12}  {code:>8}  {desc}{marker}")
            results.append({'addr_hex': f'0x{a:04X}', 'addr_dec': a,
                            'raw': raw, 'signed': s,
                            'code': code, 'description': desc})

        addr += qty
        time.sleep(0.05)

    sock.close()

    out = f'xw60k_scan_slave{slave}.csv'
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=results[0].keys())
        w.writeheader()
        w.writerows(results)
    print(f"\nSaved: {out}")


if __name__ == '__main__':
    main()
