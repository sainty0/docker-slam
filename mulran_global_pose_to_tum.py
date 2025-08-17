#!/usr/bin/env python3
"""
MulRan global_pose.csv → TUM trajectory

Input per row (13 numbers; delimiter can be commas, tabs, or spaces):
t  r11 r12 r13 tx  r21 r22 r23 ty  r31 r32 r33 tz
(where t is usually ns since epoch)

Output (TUM):
timestamp[s] tx ty tz qx qy qz qw
"""

import argparse
import math
import os
import re
import sys

# regex that finds floats like: 1, -2.3, 4.5e+06, 7E-3
NUM_RE = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')

def mat_to_quat(R):
    r00, r01, r02 = R[0]
    r10, r11, r12 = R[1]
    r20, r21, r22 = R[2]
    tr = r00 + r11 + r22
    if tr > 0.0:
        S = math.sqrt(tr + 1.0) * 2.0
        qw = 0.25 * S
        qx = (r21 - r12) / S
        qy = (r02 - r20) / S
        qz = (r10 - r01) / S
    elif (r00 > r11) and (r00 > r22):
        S = math.sqrt(1.0 + r00 - r11 - r22) * 2.0
        qw = (r21 - r12) / S
        qx = 0.25 * S
        qy = (r01 + r10) / S
        qz = (r02 + r20) / S
    elif r11 > r22:
        S = math.sqrt(1.0 + r11 - r00 - r22) * 2.0
        qw = (r02 - r20) / S
        qx = (r01 + r10) / S
        qy = 0.25 * S
        qz = (r12 + r21) / S
    else:
        S = math.sqrt(1.0 + r22 - r00 - r11) * 2.0
        qw = (r10 - r01) / S
        qx = (r02 + r20) / S
        qy = (r12 + r21) / S
        qz = 0.25 * S
    n = math.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
    return (qx/n, qy/n, qz/n, qw/n)

def polar_fix(R):
    # one-step polar decomposition fix for near-SO(3)
    RtR = [[sum(R[k][i]*R[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    M = [[(3.0 if i==j else 0.0) - RtR[i][j] for j in range(3)] for i in range(3)]
    Rn = [[sum(R[i][k]*M[k][j] for k in range(3)) / 2.0 for j in range(3)] for i in range(3)]
    det = (
        Rn[0][0]*(Rn[1][1]*Rn[2][2]-Rn[1][2]*Rn[2][1]) -
        Rn[0][1]*(Rn[1][0]*Rn[2][2]-Rn[1][2]*Rn[2][0]) +
        Rn[0][2]*(Rn[1][0]*Rn[2][1]-Rn[1][1]*Rn[2][0])
    )
    if det < 0:
        for i in range(3):
            Rn[i][2] = -Rn[i][2]
    return Rn

def convert(in_path, out_path, unit, offset_origin, enforce_orthonormal, prec):
    if not os.path.isfile(in_path):
        print(f"[ERROR] Input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    factor = {"ns": 1e-9, "ms": 1e-3, "s": 1.0}[unit]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    wrote = 0
    first_tvec = None
    with open(in_path, "r", encoding="utf-8", errors="ignore") as fin, \
         open(out_path, "w", encoding="utf-8") as fout:
        for line_no, raw in enumerate(fin, 1):
            nums = NUM_RE.findall(raw)
            if len(nums) < 13:
                # skip header/blank or malformed rows silently
                continue
            try:
                vals = list(map(float, nums[:13]))
            except ValueError:
                continue

            t_raw = vals[0]
            r11, r12, r13, tx = vals[1:5]
            r21, r22, r23, ty = vals[5:9]
            r31, r32, r33, tz = vals[9:13]

            ts = t_raw * factor
            R = [[r11, r12, r13],
                 [r21, r22, r23],
                 [r31, r32, r33]]
            if enforce_orthonormal:
                R = polar_fix(R)

            if offset_origin:
                if first_tvec is None:
                    first_tvec = (tx, ty, tz)
                tx -= first_tvec[0]
                ty -= first_tvec[1]
                tz -= first_tvec[2]

            qx, qy, qz, qw = mat_to_quat(R)
            fout.write(f"{ts:.{prec}f} {tx:.9f} {ty:.9f} {tz:.9f} {qx:.9f} {qy:.9f} {qz:.9f} {qw:.9f}\n")
            wrote += 1

    if wrote == 0:
        print("[WARN] Wrote 0 poses. Check delimiter/format (commas vs tabs/spaces) or timestamp unit.", file=sys.stderr)
    else:
        print(f"[OK] Wrote {wrote} poses to {out_path}")

def main():
    ap = argparse.ArgumentParser(description="Convert MulRan global_pose.csv to TUM")
    ap.add_argument("--in", dest="in_path", required=True, help="Path to MulRan global_pose.csv")
    ap.add_argument("--out", dest="out_path", required=True, help="Output TUM path")
    ap.add_argument("--timestamp-unit", choices=["ns","ms","s"], default="ns")
    ap.add_argument("--offset-origin", action="store_true")
    ap.add_argument("--enforce-orthonormal", action="store_true")
    ap.add_argument("--precision", type=int, default=9)
    args = ap.parse_args()

    convert(args.in_path, args.out_path, args.timestamp_unit,
            args.offset_origin, args.enforce_orthonormal, args.precision)

if __name__ == "__main__":
    main()
