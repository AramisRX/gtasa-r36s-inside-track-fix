#!/usr/bin/env python3
"""
GTA San Andreas (R36S / ArkOS-style port) - Inside Track betting fix.

Makes the Inside Track horse-betting screen usable with the gamepad on the
community "GTA SA ARKOS FIX v9" port binary (the `gtasa` executable).

Usage:
    python3 patch_itb.py <folder that contains gtasa>          apply the fix
    python3 patch_itb.py <folder that contains gtasa> --undo   restore the original

Examples:
    python3 patch_itb.py /roms/ports/gtasa        (on the console)
    python  patch_itb.py G:\\ports\\gtasa          (Windows, SD card in the PC)

The script only patches the exact binary it was written for (checked by SHA-256)
and keeps a backup of the original as `gtasa.orig`. No game files are touched.

Controls while the betting screen is open (R36S labels: A right, B bottom, X top, Y left):
    D-pad Up / Down    previous / next horse
    L1 / R1            bet amount buttons, row 1
    L2 / R2            bet amount buttons, row 2
    D-pad Left / Right bet amount buttons, row 3
    Y / B              bet amount buttons, row 4
    A                  place bet (start the race)
    X                  exit (the game's own mapping)

License: MIT (see LICENSE).
"""
import hashlib
import os
import shutil
import struct
import sys

ORIG_SHA256 = '3c7bcbda70b46603556f82e77a7a8e7d69e764e51aa53e9083ba0b41a5914415'
PATCHED_SHA256 = '159132f3071150782492cd9a199aa74623a9da2edb8e4af7aeeeea3bd2a8afed'

# Addresses inside the original binary (file offset == virtual address for these).
HOOK_SITE = 0x3b87c      # 'cbz x20, #0x3ba60' in gtasa_TouchInterface_IsReleased
CONT_NONNULL = 0x3b880   # original path when the widget has a texture name
GENERIC = 0x3ba60        # original "ask the real (touch) widget" path
RET_TRUE = 0x3bc28       # 'mov w0,#1 ; b epilogue'
HELD_MASK = 0xb0ba78     # held-button mask written by jni_gamepad_dispatch
CAVE = 0x1a1100          # zero padding after .gcc_except_table (RX segment)
STATE = 0xb3fc70         # just past the end of .bss (RW segment memsz is grown)

COND = dict(eq=0, ne=1, hs=2, lo=3, hi=8, ls=9)
WZR = 31


def enc(ins, pc, labels):
    """Tiny AArch64 encoder for the handful of instructions used below."""
    op, *a = ins
    L = lambda x: labels[x] if isinstance(x, str) else x
    if op == 'b':
        return 0x14000000 | (((L(a[0]) - pc) >> 2) & 0x3ffffff)
    if op == 'b.':
        return 0x54000000 | ((((L(a[1]) - pc) >> 2) & 0x7ffff) << 5) | COND[a[0]]
    if op in ('cbz', 'cbnz'):
        sf, rt, t = a
        base = {('cbz', 0): 0x34000000, ('cbz', 1): 0xB4000000,
                ('cbnz', 0): 0x35000000, ('cbnz', 1): 0xB5000000}[(op, sf)]
        return base | ((((L(t) - pc) >> 2) & 0x7ffff) << 5) | rt
    if op == 'subwi':
        rd, rn, imm = a; return 0x51000000 | imm << 10 | rn << 5 | rd
    if op == 'addwi':
        rd, rn, imm = a; return 0x11000000 | imm << 10 | rn << 5 | rd
    if op == 'addxi':
        rd, rn, imm = a; return 0x91000000 | imm << 10 | rn << 5 | rd
    if op == 'cmpwi':
        rn, imm = a; return 0x7100001F | imm << 10 | rn << 5
    if op == 'cmpww':
        rn, rm = a; return 0x6B00001F | rm << 16 | rn << 5
    if op == 'adrp':
        rd, t = a; imm = ((L(t) & ~0xfff) - (pc & ~0xfff)) >> 12
        return 0x90000000 | (imm & 3) << 29 | ((imm >> 2) & 0x7ffff) << 5 | rd
    if op == 'adr':
        rd, t = a; imm = L(t) - pc
        return 0x10000000 | (imm & 3) << 29 | ((imm >> 2) & 0x7ffff) << 5 | rd
    if op == 'ldrx':
        rt, rn, off = a; return 0xF9400000 | (off // 8) << 10 | rn << 5 | rt
    if op == 'ldrb':
        rt, rn, off = a; return 0x39400000 | off << 10 | rn << 5 | rt
    if op == 'strb':
        rt, rn, off = a; return 0x39000000 | off << 10 | rn << 5 | rt
    if op == 'ldrh':
        rt, rn, off = a; return 0x79400000 | (off // 2) << 10 | rn << 5 | rt
    if op == 'addxx':
        rd, rn, rm = a; return 0x8B000000 | rm << 16 | rn << 5 | rd
    if op == 'tstxx':
        rn, rm = a; return 0xEA00001F | rm << 16 | rn << 5
    if op == 'csetne':
        rd, = a; return 0x1A9F07E0 | (COND['eq'] << 12) | rd
    if op == 'movw':
        rd, imm = a; return 0x52800000 | imm << 5 | rd
    raise ValueError(op)


# Code placed in the cave. Entered from HOOK_SITE with w19 = WidgetID, x20 = widget
# texture name (NULL for the Inside Track widgets 135..149).
PROG = [
    ('cbz', 1, 20, 'null'),
    ('b', CONT_NONNULL),
    'null',
    ('subwi', 9, 19, 135),                 # w9 = id - 135
    ('cmpwi', 9, 14),
    ('b.', 'hi', 'generic'),               # not an Inside Track widget
    ('adrp', 10, HELD_MASK),
    ('ldrx', 10, 10, HELD_MASK & 0xfff),   # x10 = held buttons
    ('adrp', 13, STATE),
    ('addxi', 13, 13, STATE & 0xfff),      # x13 = patch state
    ('cmpwi', 9, 4),
    ('b.', 'ls', 'horse'),
    # Bet amounts / place bet: one button each, fires on release. The betting script
    # queries widget 148 (place bet) twice per frame, so its release is reported twice.
    ('cmpwi', 9, 13),
    ('b.', 'ne', 'normal'),
    ('ldrb', 12, 13, 20),
    ('cbz', 0, 12, 'normal'),
    ('strb', WZR, 13, 20),
    ('b', 'true'),
    'normal',
    ('adr', 11, 'table'),
    ('addxx', 11, 11, 9),
    ('addxx', 11, 11, 9),                  # x11 = table + 2*idx
    ('ldrh', 11, 11, 0),
    ('cbz', 0, 11, 'generic'),
    ('tstxx', 10, 11),
    ('csetne', 15),                        # w15 = held now
    ('addxx', 12, 13, 9),
    ('ldrb', 14, 12, 0),                   # w14 = held at previous query
    ('strb', 15, 12, 0),
    ('cbz', 0, 14, 'generic'),
    ('cbnz', 0, 15, 'generic'),
    ('cmpwi', 9, 13),
    ('b.', 'ne', 'true'),
    ('movw', 12, 1),
    ('strb', 12, 13, 20),
    ('b', 'true'),
    'horse',                               # D-pad up/down cycles horse 1..5
    ('movw', 11, 0x2000),                  # up
    ('tstxx', 10, 11),
    ('csetne', 15),
    ('ldrb', 14, 13, 18),
    ('strb', 15, 13, 18),
    ('cbnz', 0, 14, 'chkdown'),
    ('cbz', 0, 15, 'chkdown'),
    ('ldrb', 12, 13, 16),
    ('cmpwi', 12, 1),
    ('b.', 'hi', 'updec'),
    ('movw', 12, 6),
    'updec',
    ('subwi', 12, 12, 1),
    ('strb', 12, 13, 16),
    ('movw', 14, 1),
    ('strb', 14, 13, 17),
    'chkdown',
    ('movw', 11, 0x8000),                  # down
    ('tstxx', 10, 11),
    ('csetne', 15),
    ('ldrb', 14, 13, 19),
    ('strb', 15, 13, 19),
    ('cbnz', 0, 14, 'emit'),
    ('cbz', 0, 15, 'emit'),
    ('ldrb', 12, 13, 16),
    ('cmpwi', 12, 5),
    ('b.', 'lo', 'dninc'),
    ('movw', 12, 0),
    'dninc',
    ('addwi', 12, 12, 1),
    ('strb', 12, 13, 16),
    ('movw', 14, 1),
    ('strb', 14, 13, 17),
    'emit',
    ('ldrb', 14, 13, 17),
    ('cbz', 0, 14, 'generic'),
    ('ldrb', 12, 13, 16),
    ('subwi', 12, 12, 1),
    ('cmpww', 12, 9),
    ('b.', 'ne', 'generic'),
    ('strb', WZR, 13, 17),
    'true',
    ('b', RET_TRUE),
    'generic',
    ('b', GENERIC),
    'table',
]
# Button bits in the port's internal mask (it swaps face buttons):
#   A(right)=0x2  B(bottom)=0x1  X(top)=0x8  Y(left)=0x4
#   L1=0x40 R1=0x80 L2=0x100 R2=0x200  Left=0x1000 Up=0x2000 Right=0x4000 Down=0x8000
# idx: 0-4 horses (D-pad, handled above) | 5 L1 | 6 R1 | 7 L2 | 8 R2 | 9 Left | 10 Right
#      | 11 Y | 12 B | 13 A (place bet) | 14 exit (left to the game: X)
TABLE = [0, 0, 0, 0, 0, 0x40, 0x80, 0x100, 0x200, 0x1000, 0x4000, 0x4, 0x1, 0x2, 0]


def build(orig: bytes) -> bytes:
    d = bytearray(orig)
    labels, pc = {}, CAVE
    for it in PROG:
        if isinstance(it, str):
            labels[it] = pc
        else:
            pc += 4
    code, pc = b'', CAVE
    for it in PROG:
        if isinstance(it, str):
            continue
        code += struct.pack('<I', enc(it, pc, labels))
        pc += 4
    code += struct.pack('<15H', *TABLE)
    end = CAVE + len(code)
    d[CAVE:end] = code
    d[HOOK_SITE:HOOK_SITE + 4] = struct.pack('<I', enc(('b', CAVE), HOOK_SITE, {}))

    # Program headers: grow RX filesz/memsz over the cave, grow RW memsz over STATE.
    phoff = struct.unpack_from('<Q', d, 0x20)[0]
    phentsize, phnum = struct.unpack_from('<HH', d, 0x36)
    loads = []
    for i in range(phnum):
        o = phoff + i * phentsize
        ptype, pflags, poff, pvaddr, _, pfilesz, pmemsz, _ = struct.unpack_from('<IIQQQQQQ', d, o)
        if ptype == 1:
            loads.append((o, pflags, poff, pvaddr, pfilesz, pmemsz))
    rx, rw = loads
    new_rx = (end + 0xff) & ~0xff
    struct.pack_into('<QQ', d, rx[0] + 32, new_rx, new_rx)
    struct.pack_into('<Q', d, rw[0] + 40, (STATE + 0x20) - rw[3])
    return bytes(d)


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    undo = '--undo' in sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 2
    folder = args[0]
    cur = os.path.join(folder, 'gtasa')
    bak = os.path.join(folder, 'gtasa.orig')
    if not os.path.isfile(cur):
        print(f'ERROR: {cur} not found. Pass the folder that contains the "gtasa" executable.')
        return 1

    if undo:
        if not os.path.isfile(bak) or sha256(bak) != ORIG_SHA256:
            print('ERROR: no valid gtasa.orig backup found; nothing to restore.')
            return 1
        shutil.copyfile(bak, cur)
        print('Restored the original gtasa from gtasa.orig.')
        return 0

    cur_hash = sha256(cur)
    if cur_hash == PATCHED_SHA256:
        print('Already patched. Nothing to do.')
        return 0
    if cur_hash == ORIG_SHA256:
        if not os.path.exists(bak):
            shutil.copy2(cur, bak)
            print('Backup written: gtasa.orig')
        src = cur
    elif os.path.isfile(bak) and sha256(bak) == ORIG_SHA256:
        src = bak
    else:
        print('ERROR: this gtasa binary is not the version this fix was made for.')
        print(f'  found    sha256 {cur_hash}')
        print(f'  expected sha256 {ORIG_SHA256}')
        print('Nothing was changed.')
        return 1

    with open(src, 'rb') as f:
        patched = build(f.read())
    if hashlib.sha256(patched).hexdigest() != PATCHED_SHA256:
        print('ERROR: internal check failed (unexpected result). Nothing was changed.')
        return 1
    with open(cur, 'r+b') as f:      # rewrite in place so the file keeps its permissions
        f.write(patched)
        f.truncate()
    print('Done: Inside Track betting fix applied. Undo with --undo.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
