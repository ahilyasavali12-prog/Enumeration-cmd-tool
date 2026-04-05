#!/usr/bin/env python3
"""
PyEnum - A web directory/resource enumerator similar to Gobuster
Usage: python3 pyenum.py -u <url> -w <wordlist> [options]
"""

import argparse
import sys
import time
import threading
import queue
import signal
from urllib.parse import urljoin, urlparse
from datetime import datetime

try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except ImportError:
    print("[!] 'requests' library not found. Install it with: pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────
#  ANSI color codes for terminal output
# ─────────────────────────────────────────────
class Color:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"


# ─────────────────────────────────────────────
#  Result container
# ─────────────────────────────────────────────
class Result:
    def __init__(self, url, status_code, content_length, redirect=None):
        self.url            = url
        self.status_code    = status_code
        self.content_length = content_length
        self.redirect       = redirect

    def __str__(self):
        color = Color.GREEN if self.status_code in (200, 201) else Color.YELLOW
        base  = f"{color}[{self.status_code}]{Color.RESET} {self.url}  (Length: {self.content_length})"
        if self.redirect:
            base += f"  {Color.CYAN}→ {self.redirect}{Color.RESET}"
        return base


# ─────────────────────────────────────────────
#  Core enumerator
# ─────────────────────────────────────────────
class PyEnum:
    def __init__(self, args):
        self.base_url        = args.url.rstrip("/")
        self.wordlist_path   = args.wordlist
        self.extensions      = [f".{e.lstrip('.')}" for e in args.extensions] if args.extensions else [""]
        self.threads         = args.threads
        self.timeout         = args.timeout
        self.status_codes    = self._parse_status_codes(args.status_codes)
        self.user_agent      = args.user_agent
        self.follow_redirect = args.follow_redirects
        self.verify_ssl      = not args.no_verify_ssl
        self.delay           = args.delay
        self.output_file     = args.output
        self.verbose         = args.verbose
        self.cookies         = self._parse_cookies(args.cookies)
        self.headers         = self._parse_headers(args.headers)
        self.mode            = args.mode  # "dir" or "dns"
        self.proxy           = {"http": args.proxy, "https": args.proxy} if args.proxy else None

        self.results         = []
        self.results_lock    = threading.Lock()
        self.word_queue      = queue.Queue()
        self.stop_event      = threading.Event()
        self.total_words     = 0
        self.tested          = 0
        self.tested_lock     = threading.Lock()

        # Graceful shutdown on Ctrl+C
        signal.signal(signal.SIGINT, self._handle_interrupt)

    # ── helpers ────────────────────────────────
    def _parse_status_codes(self, raw):
        codes = set()
        for part in raw.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-")
                codes.update(range(int(lo), int(hi) + 1))
            else:
                codes.add(int(part))
        return codes

    def _parse_cookies(self, raw):
        if not raw:
            return {}
        cookies = {}
        for pair in raw.split(";"):
            if "=" in pair:
                k, v = pair.strip().split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    def _parse_headers(self, raw):
        if not raw:
            return {}
        headers = {}
        for pair in raw:
            if ":" in pair:
                k, v = pair.split(":", 1)
                headers[k.strip()] = v.strip()
        return headers

    def _handle_interrupt(self, sig, frame):
        print(f"\n{Color.YELLOW}[!] Interrupt received. Stopping...{Color.RESET}")
        self.stop_event.set()

    # ── banner ─────────────────────────────────
    def print_banner(self):
        print(f"""
{Color.CYAN}{Color.BOLD}
██████╗ ██╗   ██╗███████╗███╗   ██╗██╗   ██╗███╗   ███╗
██╔══██╗╚██╗ ██╔╝██╔════╝████╗  ██║██║   ██║████╗ ████║
██████╔╝ ╚████╔╝ █████╗  ██╔██╗ ██║██║   ██║██╔████╔██║
██╔═══╝   ╚██╔╝  ██╔══╝  ██║╚██╗██║██║   ██║██║╚██╔╝██║
██║        ██║   ███████╗██║ ╚████║╚██████╔╝██║ ╚═╝ ██║
╚═╝        ╚═╝   ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚═╝
{Color.RESET}{Color.BOLD}  Web Enumerator — Python Edition{Color.RESET}
""")
        print(f"  {Color.BOLD}Target  :{Color.RESET} {self.base_url}")
        print(f"  {Color.BOLD}Wordlist:{Color.RESET} {self.wordlist_path}")
        print(f"  {Color.BOLD}Mode    :{Color.RESET} {self.mode}")
        print(f"  {Color.BOLD}Threads :{Color.RESET} {self.threads}")
        print(f"  {Color.BOLD}Timeout :{Color.RESET} {self.timeout}s")
        if self.extensions != [""]:
            print(f"  {Color.BOLD}Ext     :{Color.RESET} {', '.join(self.extensions)}")
        print(f"  {Color.BOLD}Started :{Color.RESET} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("─" * 60)

    # ── wordlist loading ────────────────────────
    def load_wordlist(self):
        try:
            with open(self.wordlist_path, "r", encoding="utf-8", errors="ignore") as f:
                words = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            self.total_words = len(words) * len(self.extensions)
            for word in words:
                for ext in self.extensions:
                    self.word_queue.put(word + ext)
            print(f"  {Color.BOLD}Words   :{Color.RESET} {len(words)} ({self.total_words} requests with extensions)\n")
        except FileNotFoundError:
            print(f"{Color.RED}[!] Wordlist not found: {self.wordlist_path}{Color.RESET}")
            sys.exit(1)

    # ── HTTP request ────────────────────────────
    def request(self, url):
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            **self.headers
        })
        try:
            resp = session.get(
                url,
                timeout=self.timeout,
                verify=self.verify_ssl,
                allow_redirects=self.follow_redirect,
                cookies=self.cookies,
                proxies=self.proxy
            )
            redirect = resp.headers.get("Location") if resp.status_code in (301, 302, 307, 308) else None
            return Result(url, resp.status_code, len(resp.content), redirect)
        except requests.exceptions.ConnectionError:
            if self.verbose:
                print(f"{Color.RED}[-] Connection error: {url}{Color.RESET}")
        except requests.exceptions.Timeout:
            if self.verbose:
                print(f"{Color.YELLOW}[-] Timeout: {url}{Color.RESET}")
        except Exception as e:
            if self.verbose:
                print(f"{Color.RED}[-] Error ({url}): {e}{Color.RESET}")
        return None

    # ── DNS bruteforce ──────────────────────────
    def dns_lookup(self, subdomain):
        import socket
        domain = self.base_url.replace("http://", "").replace("https://", "").strip("/")
        fqdn   = f"{subdomain}.{domain}"
        try:
            ip = socket.gethostbyname(fqdn)
            return fqdn, ip
        except socket.gaierror:
            return fqdn, None

    # ── worker thread ───────────────────────────
    def worker(self):
        while not self.stop_event.is_set():
            try:
                word = self.word_queue.get(timeout=1)
            except queue.Empty:
                break

            if self.mode == "dns":
                fqdn, ip = self.dns_lookup(word)
                with self.tested_lock:
                    self.tested += 1
                if ip:
                    msg = f"{Color.GREEN}[FOUND]{Color.RESET} {fqdn}  → {ip}"
                    print(msg)
                    with self.results_lock:
                        self.results.append(f"FOUND: {fqdn} -> {ip}")
            else:
                url    = urljoin(self.base_url + "/", word)
                result = self.request(url)
                with self.tested_lock:
                    self.tested += 1
                if result and result.status_code in self.status_codes:
                    print(result)
                    with self.results_lock:
                        self.results.append(str(result))
                elif self.verbose and result:
                    print(f"  {Color.RED}[{result.status_code}]{Color.RESET} {url}")

            if self.delay:
                time.sleep(self.delay)

            self.word_queue.task_done()

    # ── progress printer ────────────────────────
    def progress_printer(self):
        while not self.stop_event.is_set():
            with self.tested_lock:
                done = self.tested
            pct = (done / self.total_words * 100) if self.total_words else 0
            print(f"\r  {Color.CYAN}Progress: {done}/{self.total_words} ({pct:.1f}%){Color.RESET}", end="", flush=True)
            time.sleep(0.5)
        print()  # newline after progress finishes

    # ── save results ────────────────────────────
    def save_results(self):
        if not self.output_file:
            return
        with open(self.output_file, "w") as f:
            f.write(f"PyEnum results — {datetime.now()}\n")
            f.write(f"Target: {self.base_url}\n")
            f.write("=" * 60 + "\n")
            for line in self.results:
                f.write(line + "\n")
        print(f"\n{Color.GREEN}[+] Results saved to: {self.output_file}{Color.RESET}")

    # ── main run ────────────────────────────────
    def run(self):
        self.print_banner()
        self.load_wordlist()

        threads = []

        # Start progress thread
        prog = threading.Thread(target=self.progress_printer, daemon=True)
        prog.start()

        # Start worker threads
        for _ in range(self.threads):
            t = threading.Thread(target=self.worker, daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        self.stop_event.set()
        prog.join()

        # Summary
        print(f"\n{'─' * 60}")
        print(f"{Color.BOLD}  Scan complete.{Color.RESET}")
        print(f"  Requests  : {self.tested}")
        print(f"  Found     : {Color.GREEN}{len(self.results)}{Color.RESET}")
        print(f"  Finished  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("─" * 60)

        self.save_results()


# ─────────────────────────────────────────────
#  CLI argument parser
# ─────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(
        prog="pyenum",
        description="PyEnum — A Python web enumerator (Gobuster-style)",
        formatter_class=argparse.RawTextHelpFormatter
    )
    p.add_argument("-u", "--url",       required=True,  help="Target URL  (e.g. http://example.com)")
    p.add_argument("-w", "--wordlist",  required=True,  help="Path to wordlist file")
    p.add_argument("-m", "--mode",      default="dir",  choices=["dir", "dns"],
                   help="Enumeration mode:\n  dir = directory/file bruteforce\n  dns = subdomain bruteforce\n(default: dir)")
    p.add_argument("-t", "--threads",   type=int, default=10, help="Number of threads (default: 10)")
    p.add_argument("-x", "--extensions", nargs="+",
                   help="File extensions to append  e.g. -x php txt html")
    p.add_argument("-s", "--status-codes", default="200,201,204,301,302,307,401,403",
                   help="Comma-separated status codes or ranges to report\n(default: 200,201,204,301,302,307,401,403)")
    p.add_argument("--timeout",         type=float, default=5, help="Request timeout in seconds (default: 5)")
    p.add_argument("--delay",           type=float, default=0, help="Delay between requests per thread (seconds)")
    p.add_argument("--user-agent",      default="PyEnum/1.0",  help="Custom User-Agent string")
    p.add_argument("--follow-redirects", action="store_true",  help="Follow HTTP redirects")
    p.add_argument("--no-verify-ssl",   action="store_true",   help="Disable SSL certificate verification")
    p.add_argument("--cookies",         help="Cookies  e.g. 'session=abc; token=xyz'")
    p.add_argument("--headers",         nargs="+",
                   help="Custom headers  e.g. --headers 'Authorization: Bearer TOKEN'")
    p.add_argument("--proxy",           help="Proxy URL  e.g. http://127.0.0.1:8080")
    p.add_argument("-o", "--output",    help="Save results to this file")
    p.add_argument("-v", "--verbose",   action="store_true", help="Show all responses (including non-matches)")
    return p


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
    args   = parser.parse_args()

    # Validate URL
    parsed = urlparse(args.url)
    if not parsed.scheme or not parsed.netloc:
        print(f"{Color.RED}[!] Invalid URL. Include scheme: http:// or https://{Color.RESET}")
        sys.exit(1)

    PyEnum(args).run()
write a explaination for this code in github formate
