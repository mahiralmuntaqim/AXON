# Crypto Playbook

**Goal:** recover the secret (flag/plaintext/key). CTF crypto is almost always a
*known* weakness in hand-rolled code — read the source first; the bug is usually
right there.

## 0. Triage (first 2 minutes)

1. **Read every provided file.** The `chall.py` / `server.py` shows the exact
   scheme and parameters. The flaw is in how it was built, not in the math of
   the primitive.
2. **Identify the primitive:**
   - `n, e, c` or a `.pub` key → **RSA**
   - `key`, `iv`, `AES`, a block size of 16 → **AES** (which mode?)
   - key shorter than data, reused → **XOR / stream reuse**
   - letters-only, shifts, substitution → **classical**
   - curve params, `G`, points → **ECC**
   - `p, g, y` → **Diffie-Hellman / DLP**
   - a `sign()`/`mac()` of `hash(secret || msg)` → **length extension**
   - repeated calls to `random`/LCG → **PRNG prediction**
3. **Is there a live oracle** (a service you can query repeatedly)? If yes the
   attack is interactive (padding oracle, LSB oracle, MAC forgery) — script it.

## 1. RSA

Order of attempts, cheapest first:

```bash
# a) Is n already factored publicly?
python3 -c "from factordb.factordb import FactorDB as F;x=F($n);x.connect();print(x.get_factor_list())"

# b) Throw the whole toolbox at it
python3 RsaCtfTool.py --publickey key.pub --uncipherfile cipher.bin --attack all
```

Specific textbook attacks and their tells:

- **Small e (e=3) + no padding:** `c` is a perfect cube → `m = iroot(c,3)`.
- **Håstad broadcast:** same `m`, small `e`, `e` different moduli → CRT then root.
- **Fermat (close primes):** `p≈q` → factor by trial around `isqrt(n)`.
- **Wiener (small d):** continued-fraction attack (RsaCtfTool `--attack wiener`).
- **Common modulus:** same `n`, two coprime `e` on same `m` → extended GCD.
- **Partial key / stereotyped message:** **Coppersmith** via Sage
  (`small_roots`). Also LSB/parity **decryption oracle** → binary search `m`.
- **Multi-prime / smooth p-1:** Pollard p−1 (`--attack pollard_p_1`).

```python
# small-e cube root
from gmpy2 import iroot; from Crypto.Util.number import long_to_bytes
m,ok = iroot(c,3); print(long_to_bytes(int(m)))
```

## 2. AES (mode is everything)

- **ECB** (`ECB`, identical blocks repeat): byte-at-a-time **ECB decryption** if
  you control a prefix; **cut-and-paste** to forge structured plaintext.
- **CBC + padding error leaks** → **padding oracle**: decrypt/encrypt arbitrary
  data. Use a scripted oracle loop (pwntools/requests).
- **CBC bit-flipping:** flip a ciphertext byte to flip the next plaintext block's
  byte — tamper with role=user→admin style data.
- **CTR / stream nonce reuse:** same keystream twice → XOR ciphertexts, crib-drag.
- **GCM nonce reuse:** forge tags (recover auth key H).

## 3. XOR / stream

```bash
xortool -x -c 20 cipher.hex          # guess key length + key by char frequency
```
Single-byte XOR → brute 0..255, score by English frequency / printability.
Known-plaintext (e.g. `flag{` or `CTF{`) → recover key bytes directly by XOR.

## 4. Classical

Shift/Caesar, Vigenère (find key len via Kasiski/IC), substitution
(frequency analysis / quipqiup), rail-fence, Playfair, affine, Bacon, Morse,
base-N. Use **CyberChef Magic** to auto-detect encoding chains.

## 5. Hashes & MACs

- Identify: `hashid <hash>`. Crack: `john`/`hashcat` with `rockyou.txt`.
- **Length extension** (`MAC = H(secret||msg)`, you know `msg`,`MAC`,`len(secret)`):
  `hashpumpy.hashpump(sig, msg, append, keylen)` → forged `(msg', sig')`.
- Encrypted file/key → `*2john` (`ssh2john`, `zip2john`, `pdf2john`) then crack.

## 6. ECC / DLP

- Small/weak curve or smooth order → **Pohlig–Hellman** (Sage `discrete_log`).
- Singular/anomalous curve, invalid-curve, or small subgroup → Sage.

## 7. PRNG

- Python `random` / MT19937: collect 624 consecutive 32-bit outputs →
  `randcrack` reconstructs state → predict future values.
- LCG: solve `X_{n+1}=aX_n+c mod m` with a few outputs (z3 or algebra).

## When stuck

Re-read the source for an *unused* check, an off-by-one in parameter generation,
or a constant that should have been random. Search the exact scheme name +
"CTF" in [`resources.md`](resources.md). If it needs lattices/Coppersmith and
Sage isn't in the sandbox, flag that to the Coordinator — it's an environment
gap, not a dead end.
