# CTF Knowledge Packs

Compiled **tools + techniques + resources** for the six CTF/pentest categories,
as source content for a knowledge graph.

| Pack | Category |
|------|----------|
| [`packs/crypto`](packs/crypto)       | Cryptography — break/exploit a cipher to recover a secret |
| [`packs/pwn`](packs/pwn)             | Binary exploitation — abuse a memory bug to take control  |
| [`packs/rev`](packs/rev)             | Reverse engineering — read compiled logic for the answer  |
| [`packs/web`](packs/web)             | Web exploitation — attack a site/service through its flaws |
| [`packs/forensics`](packs/forensics) | Investigate files/dumps to recover hidden info            |
| [`packs/misc`](packs/misc)           | Mixed/unusual tasks (jails, encoding, PPC, OSINT)         |

## What's in each pack

- **`tools.json`** — structured manifest. Each tool has: `name`, `when` (what
  sub-task to reach for it), `install` (by package manager), `usage` (a one-line
  example), `docs` (link). Plus `summary`, `quick_triage` (first moves), and the
  `archetypes` it maps to. These fields map directly onto graph nodes/edges
  (Category → Technique → Tool → Install, Tool → Resource, etc.).
- **`playbook.md`** — the methodology: a triage decision-tree and concrete
  commands per attack family. The prose source for technique nodes/relationships.
- **`resources.md`** — curated reference links (HackTricks + specialized wikis,
  challenge archives, cheatsheets) the pack was compiled from.
- **`harvested/`** — raw source material fetched from the public references (see
  below), plus a `SOURCES.md` listing every URL pulled and its status. This is
  the unprocessed corpus the curated `tools.json`/`playbook.md` draw from; keep
  it as provenance and re-mine it when expanding the graph.

Tool counts: crypto 21, pwn 17, rev 18, web 19, forensics 22, misc 14 (**111 total**).
The curated `tools.json` sets were expanded with high-value tools found in the
harvested corpus (Awesome-CTF taxonomy, GTFOBins, etc.).

## Harvested corpus (`packs/<cat>/harvested/`)

Raw reference content fetched from public, open-source security resources
(~556 KB across 60 files). Each category folder has its own `SOURCES.md` with
the exact URLs. Fetched from:

- **All categories:** Awesome-CTF tool taxonomy (`apsdehal/awesome-ctf`)
- **crypto:** RsaCtfTool README, CryptoHack index, Cryptopals set index
- **pwn:** how2heap (+ glibc 2.23–2.43 dir listing), pwntools docs, ROPgadget, Nightmare TOC
- **rev:** radare2 book TOC, Ghidra cheatsheet, Malware Unicorn RE101, angr docs + examples list
- **web:** PayloadsAllTheThings — 17 vuln-class READMEs (SQLi, XSS, SSTI, SSRF, LFI, cmd-injection, XXE, deserialization, JWT, CORS, open-redirect, CRLF, LDAP, NoSQL, GraphQL, file-upload, path-traversal); OWASP WSTG structure
- **forensics:** Volatility3 plugin list, Wireshark display-filter reference, Sleuth Kit tool overview *(caesum stego handbook was unreachable — host offline)*
- **misc:** GTFOBins (478-entry index + 10 key entries), LOLBAS (136 Windows binaries), esolangs language list
