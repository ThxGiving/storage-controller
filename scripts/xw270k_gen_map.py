#!/usr/bin/env python3
"""
XW270K Parameter Map Generator
Parses XWEB EVO library files extracted from the XW270K package
and generates a parameter reference CSV + PDF.

Usage:
  python3 scripts/xw270k_gen_map.py [lib_dir] [output_dir]

  lib_dir    path containing models/ and partab/ subdirs (default: dixell/xw270k/v9.5)
  output_dir where to write CSV and PDF files          (default: dixell/xw270k)
"""

import sys
import os
import csv
import re
from pathlib import Path

# --------------------------------------------------------------------------- #
# Group names (from partab.en-GB header: G|N + numbered group names)
GROUP_NAMES = {
    "1": "Regulation",
    "2": "Display",
    "3": "Defrost",
    "4": "Fan",
    "5": "Alarm",
    "6": "Probes",
    "7": "Digital inputs",
    "8": "Configuration",
    "9": "Other",
}

# Data types for selected parameters (sign + scale)
PARAM_TYPE = {
    # temperatures: signed, ×0.1 °C
    "dtE": "signed ×0.1 °C", "dtS": "signed ×0.1 °C",
    "SdF": "signed ×0.1 °C",
    "ALU": "signed ×0.1 °C", "ALL": "signed ×0.1 °C",
    "AFH": "unsigned ×0.1 °C",
    "CSd": "signed ×0.1 °C", "AtH": "unsigned ×0.1 °C",
    "HES": "signed ×0.1 °C",
    "SAA": "signed ×0.1 °C", "SAH": "unsigned ×0.1 °C",
    "FSt": "signed ×0.1 °C",
    "SEt": "signed ×0.1 °C",
    # times / durations: unsigned integer (unit varies)
    "IdF": "unsigned (hours)", "MdF": "unsigned (min)",
    "MdS": "unsigned (min)", "ALd": "unsigned (min)",
    "doA": "unsigned (min)", "Ad2": "unsigned (min)",
    "Fnd": "unsigned (min)", "dSd": "unsigned (min)",
    "dAd": "unsigned (min)", "Fdt": "unsigned (min)",
    "Pdn": "unsigned (min)",
    "AC": "unsigned (min)", "AC1": "unsigned (sec/min)",
    "CCt": "unsigned (hours)",
    "did": "unsigned (min)",
    # booleans / enums: unsigned integer
    "CH": "enum (0=Cool, 1=Heat)",
    "CF": "enum (0=°C, 1=°F)",
    "rES": "enum (0=×0.1, 1=×1)",
    "P2P": "enum (0=Absent, 1=Present)",
    "P3P": "enum (0=Absent, 1=Present)",
    "P4P": "enum (0=Absent, 1=Present)",
    "i1P": "enum (0=NC oP, 1=NO CL)",
    "i2P": "enum (0=NC oP, 1=NO CL)",
    "ALC": "enum (0=Rel, 1=Abs)",
    "tdF": "enum (0=Electrical, 1=Gas-Hot)",
    "EdF": "enum (0=Temp, 1=Time, 2=Both)",
    "Fnc": "enum (0=F-C off, 1=F always, 2=F-C on)",
    "tbA": "enum (0=No, 1=Yes)",
}

# --------------------------------------------------------------------------- #

def parse_partab_english(path: Path) -> dict[str, str]:
    """Return {code: description} from partab.en-GB."""
    desc = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [l.rstrip() for l in f]

    in_params = False
    for line in lines:
        if line.startswith("D|"):
            in_params = True
            continue
        if not in_params:
            continue
        if line.startswith("L|"):
            break
        parts = line.split("|", 1)
        if len(parts) == 2:
            code, d = parts[0].strip(), parts[1].strip()
            if code and not code.startswith("l|"):
                desc[code] = d
    return desc


def parse_partab_wel(path: Path) -> list[tuple[str, int, str, int, int, int]]:
    """
    Parse parameter entries from partab.wel.
    Returns list of (code, group, access_level, word_addr, bit_offset, bit_width).
    """
    params = []
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [l.rstrip() for l in f]

    in_params = False
    current_code = None
    current_group = 0
    current_level = 0

    for line in lines:
        if line.startswith("P|"):
            in_params = True
            continue
        if not in_params:
            continue

        # Parameter header: CODE|group|access_level
        parts = line.split("|")
        if len(parts) == 3 and not parts[0].startswith("a") and not parts[0].startswith("v") \
                and not parts[0].startswith("e") and not parts[0].startswith("m") \
                and not parts[0].startswith("t") and not parts[0].startswith("l") \
                and not parts[0].startswith("u") and not parts[0].startswith("s") \
                and not parts[0].startswith("r") and not parts[0].startswith("A") \
                and not parts[0].startswith("n") and not parts[0].startswith("1") \
                and not parts[0].startswith("2") and not parts[0].startswith("3") \
                and not parts[0].startswith("4") and not parts[0].startswith("5"):
            try:
                g = int(parts[1])
                lvl = int(parts[2])
                current_code = parts[0].strip()
                current_group = g
                current_level = lvl
            except ValueError:
                pass
            continue

        # Address line: a|word_addr|bit_offset|bit_width|...
        if line.startswith("a|") and current_code:
            aparts = line.split("|")
            if len(aparts) >= 4:
                wa_str = aparts[1].strip()
                bo_str = aparts[2].strip()
                bw_str = aparts[3].strip()
                if wa_str not in ("L", "") and bo_str.lstrip("-").isdigit() and bw_str.isdigit():
                    try:
                        wa = int(wa_str)
                        bo = int(bo_str)
                        bw = int(bw_str)
                        params.append((current_code, current_group, current_level, wa, bo, bw))
                    except ValueError:
                        pass
            current_code = None  # reset until next header

    return params


def build_table(params, descriptions):
    """Combine parsed data into list of dicts."""
    rows = []
    for i, (code, group, level, word, bit_off, bit_width) in enumerate(params):
        group_name = GROUP_NAMES.get(str(group), f"Group {group}")
        desc = descriptions.get(code, "")
        dtype = PARAM_TYPE.get(code, "unsigned integer" if bit_width >= 8 else "bit flag")
        rw = "R/W" if level < 9 else "R"
        rows.append({
            "Index": i,
            "Code": code,
            "Group": group_name,
            "Description": desc,
            "EEPROM Word": word,
            "Bit Offset": bit_off,
            "Bit Width": bit_width,
            "Type": dtype,
            "R/W": rw,
        })
    return rows


def write_csv(rows, path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV written: {path}  ({len(rows)} parameters)")


def write_pdf(rows, path: Path, lib_dir: Path):
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        print("weasyprint not available — skipping PDF")
        return

    groups = {}
    for row in rows:
        g = row["Group"]
        groups.setdefault(g, []).append(row)

    # Build HTML
    html_parts = ["""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body { font-family: Arial, sans-serif; font-size: 9pt; margin: 15mm; }
  h1 { font-size: 16pt; margin-bottom: 4pt; }
  h2 { font-size: 11pt; margin-top: 14pt; margin-bottom: 4pt;
       border-bottom: 1px solid #999; color: #333; }
  .meta { font-size: 8pt; color: #666; margin-bottom: 12pt; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 10pt; }
  th { background: #2c5282; color: white; font-weight: bold; padding: 4pt 5pt;
       text-align: left; font-size: 8.5pt; }
  td { padding: 3pt 5pt; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
  tr:nth-child(even) { background: #f7fafc; }
  .code { font-family: monospace; font-weight: bold; font-size: 9pt; }
  .num  { text-align: center; }
  .rw   { text-align: center; font-size: 8pt; }
  .type { font-size: 7.5pt; color: #444; }
  @page { size: A4; margin: 15mm; }
  @media print { h2 { page-break-before: auto; } }
</style>
</head><body>"""]

    html_parts.append("<h1>Dixell XW270K — Parameter Reference</h1>")
    html_parts.append(
        f'<div class="meta">Source: XWEB EVO library · {lib_dir.name} · '
        f'Generated from models/partab files<br>'
        f'<b>Note:</b> EEPROM Word addresses are internal firmware offsets, '
        f'not Modbus register addresses. Modbus base: ~0x0502 (register 1282). '
        f'Exact Modbus addresses require the XW270K Modbus protocol manual '
        f'or empirical scanning.</div>'
    )

    for group_name, group_rows in groups.items():
        html_parts.append(f"<h2>{group_name}</h2>")
        html_parts.append("""<table>
  <tr>
    <th>#</th><th>Code</th><th>Description</th>
    <th>EEPROM Word</th><th>Bit Off.</th><th>Width</th>
    <th>Type / Unit</th><th>R/W</th>
  </tr>""")
        for row in group_rows:
            html_parts.append(
                f'<tr>'
                f'<td class="num">{row["Index"]}</td>'
                f'<td class="code">{row["Code"]}</td>'
                f'<td>{row["Description"]}</td>'
                f'<td class="num">{row["EEPROM Word"]}</td>'
                f'<td class="num">{row["Bit Offset"]}</td>'
                f'<td class="num">{row["Bit Width"]}</td>'
                f'<td class="type">{row["Type"]}</td>'
                f'<td class="rw">{row["R/W"]}</td>'
                f'</tr>'
            )
        html_parts.append("</table>")

    html_parts.append("</body></html>")

    HTML(string="\n".join(html_parts)).write_pdf(str(path))
    print(f"PDF written: {path}")


# --------------------------------------------------------------------------- #

def main():
    lib_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dixell/xw270k/v9.5")
    out_dir  = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("dixell/xw270k")

    # Locate partab files
    partab_root = lib_dir / "partab"
    en_files = list(partab_root.rglob("partab.en-GB"))
    wel_files = list(partab_root.rglob("partab.wel"))

    if not en_files or not wel_files:
        print(f"ERROR: could not find partab files under {partab_root}", file=sys.stderr)
        sys.exit(1)

    en_path  = en_files[0]
    wel_path = wel_files[0]
    print(f"Parsing: {en_path}")
    print(f"Parsing: {wel_path}")

    descriptions = parse_partab_english(en_path)
    params       = parse_partab_wel(wel_path)

    print(f"Found {len(descriptions)} descriptions, {len(params)} parameter entries")

    rows = build_table(params, descriptions)

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "XW270K_v9.5_Parameters.csv"
    pdf_path = out_dir / "XW270K_v9.5_Parameters.pdf"

    write_csv(rows, csv_path)
    write_pdf(rows, pdf_path, lib_dir)


if __name__ == "__main__":
    main()
