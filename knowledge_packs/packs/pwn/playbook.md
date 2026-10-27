# Pwn (Binary Exploitation) Playbook

**Goal:** turn a memory bug into control — usually a shell (`system("/bin/sh")`)
or a flag read (open/read/write when seccomp blocks `execve`). **Always build
and test locally against the provided binary + libc first**, then repoint
pwntools at the remote.

## 0. Triage

```bash
file ./chall
checksec --file=./chall      # Canary? NX? PIE? RELRO?
strings ./libc.so.6 | grep -m1 'GLIBC_'   # libc version, if provided
```

Decompile `main` and called functions (Ghidra / `r2 -A`, `pdf @ main`). Find how
user input reaches memory. Mitigation map:

| Protection | Meaning | Implication |
|---|---|---|
| No canary | stack return addr overwritable directly | classic overflow |
| Canary | stack cookie before saved RIP | must leak/avoid it |
| NX | stack not executable | no shellcode on stack → ROP/ret2libc |
| No PIE | fixed code addresses | gadgets/symbols are static |
| PIE | code base randomized | need a code/PIE leak first |
| Partial/Full RELRO | GOT writable? | Full RELRO ⇒ no GOT overwrite |

## 1. Find the offset (stack bugs)

```python
from pwn import *
p = process('./chall')
p.sendline(cyclic(200))
p.wait()
core = p.corefile
offset = cyclic_find(core.read(core.rsp, 8))   # or pwndbg: cyclic -l <rip>
```

## 2. Pick the technique by what you have

- **`win()`/backdoor function exists** → **ret2win**: overflow to its address.
  (64-bit: you may need a `ret` gadget first to fix stack alignment for movaps.)
- **NX, no win, no libc leak** → leak libc first: ROP `puts(puts@got)` →
  compute libc base → second stage `system("/bin/sh")` or `one_gadget`.
  ```python
  rop = ROP(elf)
  rop.raw(rop.find_gadget(['ret']))       # alignment
  rop.puts(elf.got['puts'])
  rop.main()                              # return to main for stage 2
  ```
- **Format string** (`printf(user)`): leak (`%p`/`%N$p`) stack/canary/libc, then
  **arbitrary write** with `%n` via pwntools `fmtstr_payload(offset, {addr:val})`.
  Target: GOT entry → `system`, or return address.
- **GOT overwrite** (no Full RELRO): overwrite e.g. `free@got` / `printf@got`
  with `system`, then trigger with a `"/bin/sh"` argument.
- **ret2dlresolve** (no leak, no libc) / **ret2csu** (need to set rdx/rsi):
  standard when gadgets are scarce — pwntools `Ret2dlresolvePayload`.
- **SROP** (`syscall; ret` + control of rax=15): forge a sigreturn frame
  (`SigreturnFrame()`), great when gadgets are minimal.

## 3. Heap (glibc)

Identify the allocator pattern (menu: alloc/free/edit/show). Common bugs → techniques:

- **Use-After-Free / double-free** → **tcache poisoning** (glibc ≥2.26): free into
  tcache, corrupt `fd` to return an arbitrary pointer from the next malloc.
  (glibc ≥2.32 mangles `fd` with `pos>>12 ^ ptr` — leak a heap addr first.)
- **Heap overflow** → corrupt adjacent chunk size / top chunk (**House of Force**,
  older), or overlap chunks.
- **Fastbin dup**, **unsorted-bin leak** (free a large chunk → libc main_arena
  pointer in `fd` → libc base).
- Target hijacks: `__free_hook`/`__malloc_hook` (glibc <2.34), `_IO_FILE`
  / `_IO_list_all` (FSOP) on newer glibc, or `__exit_funcs` (tls).

Reference: how2heap (per-glibc-version techniques) in [`resources.md`](resources.md).

## 4. Shellcode (only if stack/region is executable — rare with NX)

`shellcraft` from pwntools: `asm(shellcraft.sh())`. If seccomp blocks execve,
check the filter (`seccomp-tools dump`) and use **ORW** shellcode (open/read/write
the flag file).

## 5. Fire at remote

```python
io = remote('host', port)        # swap process()->remote()
# ... same payload ...
io.interactive()
```
If libc offsets differ, identify the remote libc with **libc-database** from a
leaked symbol's last 3 nibbles, then recompute base and `one_gadget`.

## When stuck

Re-check: correct offset? stack alignment (`movaps` crash ⇒ add a `ret`)? right
libc? Is the bug actually reachable with your input? Try **angr** to auto-solve a
constraint-style challenge. If a needed tool (gdb/one_gadget/libc-database) is
missing from the sandbox, report it as an environment gap.
