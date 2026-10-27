# Forensics Playbook

**Goal:** recover hidden information from a file or data dump. The flag is hidden
by one of: appended/embedded data, metadata, steganography, a corrupted header,
or it lives inside a capture/memory/disk image. **Start cheap.**

## 0. Triage (run on everything)

```bash
file artifact
strings -n 6 artifact | grep -iE 'flag|ctf\{|key'
strings -n 6 -e l artifact | grep -i ctf        # UTF-16LE strings too
xxd artifact | head                              # magic bytes (is the header right?)
exiftool artifact                                # metadata / comments
binwalk -e artifact                              # embedded/appended files
```

Then route by type:

| Type | Tell | Go to |
|---|---|---|
| Image (PNG/JPG/BMP/GIF) | `file` says image | §1 Stego |
| PCAP / pcapng | `file` says capture | §2 Network |
| Memory dump | big `.raw`/`.mem`/`.vmem` | §3 Memory |
| Disk image | `.dd`/`.img`/`.e01`, partitions | §4 Disk |
| Archive / Office / PDF | zip/rar/docx/pdf | §5 Containers |
| Audio | `.wav`/`.mp3` | §6 Audio |

## 1. Image steganography

```bash
exiftool img            # comments/author/XMP often hold the flag
binwalk -e img          # appended zip/file after image data
pngcheck -vtp7 img.png  # extra chunks, wrong IHDR dims hiding rows
zsteg -a img.png        # PNG/BMP LSB (primary)
steghide info img.jpg ; steghide extract -sf img.jpg -p ''   # JPG/BMP/WAV
stegseek img.jpg rockyou.txt    # brute the steghide passphrase
```
Also: open bit-planes/channels (stegsolve or PIL) for LSB/visual stego; check for
data **after** the image's end marker (JPEG `FFD9`, PNG `IEND`); a too-small
image may have rows cropped via a wrong height field — fix and reopen.

## 2. Network (PCAP)

```bash
tshark -r cap.pcap -q -z io,phs                 # protocol hierarchy — what's in here
tshark -r cap.pcap -Y http.request -T fields -e http.host -e http.request.uri
tshark -r cap.pcap --export-objects http,out/   # pull transferred files
tshark -r cap.pcap -q -z follow,tcp,ascii,0     # follow a stream
```
Look for creds in HTTP/FTP/telnet, flags in payloads, DNS exfiltration
(data in subdomain labels), ICMP tunneling, USB HID captures (keystrokes),
and TLS (need a provided key to decrypt). `strings cap.pcap | grep ctf` first.

## 3. Memory (Volatility 3)

```bash
vol -f mem.raw windows.info          # confirm profile/OS
vol -f mem.raw windows.pslist
vol -f mem.raw windows.cmdline       # command lines (flags/args)
vol -f mem.raw windows.filescan | grep -i flag
vol -f mem.raw windows.dumpfiles --viraddr <addr>
vol -f mem.raw windows.hashdump      # creds
```
(Linux dumps: `linux.*` plugins.) Also `windows.clipboard`, `windows.netscan`,
`windows.malfind` (injected code).

## 4. Disk image

```bash
mmls disk.dd                          # partition offsets
fls -r -o <offset> disk.dd            # list files incl. deleted (*)
icat -o <offset> disk.dd <inode> > recovered
bulk_extractor -o out/ disk.dd        # sweep for strings/PII/URLs
foremost -i disk.dd -o carved/        # carve by signature
```
Check recently deleted files, user home dirs, browser artifacts, `.bash_history`.

## 5. Containers (archive / Office / PDF)

```bash
7z l file ; unzip -l file                     # list; docx/xlsx are zips
john <(zip2john secret.zip) --wordlist=rockyou.txt   # crack encrypted archive
olevba doc.docm                               # macros
pdf-parser.py --search flag file.pdf ; pdfdetach -saveall file.pdf
```
Office files are ZIPs — unzip and grep the XML/media parts. Nested archives
(zip-in-zip "matryoshka") → script the recursive unzip.

## 6. Audio

```bash
sox audio.wav -n spectrogram -o spec.png      # text drawn in the spectrogram
```
Also: DTMF tones (decode to digits), Morse, reversed/slowed playback, stereo
channel difference, LSB in WAV (steghide/zsteg-style).

## When stuck

Re-run binwalk with manual signature offsets; verify/repair magic bytes; try the
other stego tool for the format; consider layered hiding (stego → archive →
encoding). Search the artifact type + "CTF stego" in [`resources.md`](resources.md).
Report missing tools (volatility3/zsteg/tshark) as env gaps.
