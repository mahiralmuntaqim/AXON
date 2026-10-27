# Misc Playbook

**Goal:** these don't fit the other five, so first **classify the sub-genre**,
then apply its standard trick. The prompt/source almost always telegraphs which.

## Sub-genre → approach

### Interactive service / PPC (programming puzzle, `nc host port`)
A service asks many rounds of questions on a timer. Automate with pwntools:
```python
from pwn import *
io = remote('host', port)
while True:
    line = io.recvline()
    expr = parse(line)              # e.g. "12 * 7 ="
    io.sendline(str(eval_safe(expr)).encode())
```
Variants: math chains, decode-this, "solve 500 of these in 10s", mazes, sorting.
Also **proof-of-work** gates: "find X where sha256(X).startswith('00000')" — brute
in a tight loop.

### pyjail / bash jail (restricted eval/exec)
You can run code but input is filtered. Enumerate the filter, then route around it:
- Blocked keywords → build them from parts: `__import__('os')` via
  `getattr`, `().__class__.__base__.__subclasses__()` to reach `os`/`subprocess`.
- No letters/digits → unicode homoglyphs, octal/hex escapes, `chr()` assembly.
- Builtins stripped → `__builtins__` recovery via object graph, or `breakpoint()`.
- Bash: filtered chars → `${IFS}`, brace expansion, `$'\x2f'`, `cat<flag`, globs.
Goal: read the flag file or get a shell. (See HackTricks "bypass python sandboxes".)

### Encoding / cipher-lite puzzle
Peel layers with CyberChef **Magic**, or identify by shape:
- base64/32/85/58/62, hex, URL, ROT13/47, Atbash, Morse, Baconian, Braille,
  decimal/octal charcodes, Vigenère (if keyed).
- Nested: decode repeatedly until printable. `file` the decoded bytes each layer.

### Esoteric language
Fingerprint by glyphs and run it:
- `+-<>[].,` → **Brainfuck**; spaces/tabs/newlines only → **Whitespace**;
  image → **Piet**; dense symbol soup → **Malbolge**/**JSFuck**.
- Use an interpreter (tio.run offline-equivalent, or a 20-line BF interpreter).

### Visual codes
`zbarimg image.png` for QR/barcodes. Grids/flags → Braille, semaphore,
flag-semaphore, or a bitmap you must render. Reassemble fragmented/rotated QRs.

### Logic / constraint puzzle
Model it in **z3** and solve — Sudoku-likes, SAT, "find inputs satisfying these
equations", scheduling.

### Light OSINT
Pivot from the given seed (handle/email/image): `sherlock <user>`,
`holehe <email>`, `exiftool` the image for GPS/device, reverse-image hints.
Stay within the provided scope — don't target real third parties beyond the
challenge's own artifacts.

## General tactic

When unsure, read the source/prompt again for the *exact* win condition, then
write the smallest script that produces it. Misc rewards quickly recognizing the
genre and reusing the known trick over inventing something new.

## When stuck

Reclassify — you may have the genre wrong. Check [`resources.md`](resources.md)
for the specific sub-genre. If a service needs persistent scripted interaction
and the sandbox lacks pwntools, report the gap.
