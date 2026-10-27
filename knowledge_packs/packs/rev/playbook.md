# Reverse Engineering Playbook

**Goal:** understand the compiled logic well enough to produce the input it wants
(a password/flag check) or extract the secret it hides. The flag is either
**embedded**, **computed**, or **the input that passes a check**.

## 0. Triage

```bash
file ./bin
strings -n 6 ./bin | grep -iE 'flag|ctf\{|key|pass|correct|wrong|nope'
```

Low-hanging fruit first — flags are often plaintext, base64, or split across a
few strings. Then determine the **format** and route to the right tool:

| Format tell | Tool |
|---|---|
| ELF/PE/Mach-O native | Ghidra / IDA Free / r2+Cutter |
| "UPX" in `file`/strings, high entropy | `upx -d` then re-triage |
| .NET / "Mono"/"CIL" | dnSpy / ILSpy |
| Java `.class`/`.jar` | jadx / CFR |
| Android `.apk` | jadx (code) + apktool (resources/smali) |
| Python `.pyc` / PyInstaller `.exe` | pyinstxtractor + decompyle3 |
| wasm | wasm2wat / wabt |
| firmware blob | binwalk -e |

## 1. Static: find the check

Decompile and locate the success gate — the branch that prints
`Correct`/returns the flag. Work backward from it. Typical shapes:

- **Direct compare:** `strcmp(input, "s3cr3t")` → the flag/password is right
  there. `ltrace ./bin` often reveals this without any decompiler.
- **Transform then compare:** input is XORed/added/permuted, then compared to a
  constant array. **Invert** the transform:
  - XOR with constant/key → XOR again.
  - add/sub → reverse.
  - per-byte table/permutation → build the inverse map.
- **Char-by-char constraints** (loops of `if (input[i] ^ a == b)`): collect the
  constraints and solve (by hand or z3).

## 2. Dynamic: confirm and shortcut

```bash
ltrace ./bin            # library calls (strcmp/memcmp/printf) with arguments
strace ./bin            # syscalls (open/read of a flag file, ptrace anti-debug)
gdb ./bin               # b *<cmp_addr>; run; inspect the expected buffer directly
```

Reading the *expected* buffer at the compare instruction frequently hands you the
answer with no math. Watch for **anti-debug** (`ptrace(PTRACE_TRACEME)`, timing
checks) — patch the check in gdb or NOP it in the binary.

## 3. Solve automatically when the logic is gnarly

- **angr** (symbolic execution) — the default when the check is a big
  arithmetic/XOR mangle and you'd rather not reverse it by hand:
  ```python
  import angr, claripy
  p = angr.Project('./bin', auto_load_libs=False)
  flag = claripy.BVS('flag', 8*32)
  st = p.factory.full_init_state(stdin=flag)
  sm = p.factory.simulation_manager(st)
  sm.explore(find=0xADDR_WIN, avoid=0xADDR_FAIL)
  print(sm.found[0].posix.dumps(0))
  ```
  Keep the input length tight and `avoid` the failure print to prune paths.
- **z3** — when you can read the per-byte constraints but there are many: model
  each flag byte as a `BitVec`, add the constraints, `check()`, read the `model()`.

## 4. Patching (when the goal is just to make it run/pass)

- Native: patch the conditional jump (e.g. `jne`→`je` or NOP) in Ghidra/r2
  (`wa`/`wx`), or branch in gdb.
- .NET: edit the method in dnSpy and save the assembly.
- Android: edit smali, `apktool b`, re-sign with `apksigner`.

## When stuck

Rename variables as you learn them so the decompiler output becomes readable.
Look for a key/seed loaded from a constant. For VM-based obfuscation, reverse the
bytecode interpreter first, then the bytecode. If a tool for the format isn't in
the sandbox (e.g. dnSpy for .NET), report the gap to the Coordinator.
