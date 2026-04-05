To understand how **PyEnum** works, it’s best to look at it as an assembly line. You have a "bucket" of words (the Queue), "workers" (Threads) that grab words and check them against a website, and a "manager" (the Main class) that coordinates everything.

Here is a deep dive into the logic of the script.

---

## 1. The Core Engine: `class PyEnum`
This is the heart of the tool. When you initialize this class, it takes all your command-line arguments (URL, threads, wordlist) and sets up the environment.

### Thread Safety and Synchronization
Because multiple threads are running at once, the script uses **Locks**:
* `self.results_lock`: Ensures that if two threads find a hidden directory at the exact same millisecond, they don't "collide" when writing to the results list.
* `self.tested_lock`: Used to safely increment the counter for the progress bar.

### The Wordlist Loader (`load_wordlist`)
This function doesn't just read a file; it performs **Cartesian Product** logic. If your wordlist has `admin` and your extensions are `.php` and `.html`, it generates:
1. `admin`
2. `admin.php`
3. `admin.html`
All of these are pushed into `self.word_queue`, which is a **FIFO (First-In-First-Out)** queue.

---

## 2. Multi-Threading Logic
Python’s `threading` module is used to bypass the "wait time" of network requests.



### The `worker()` Method
This is what each thread executes. Its logic is a loop:
1. **Fetch:** Pull a word from the `word_queue`.
2. **Execute:** * If `mode == "dir"`, it calls `self.request()`.
    * If `mode == "dns"`, it calls `self.dns_lookup()`.
3. **Compare:** It checks if the HTTP status code (e.g., 200) matches your "allowed" list.
4. **Report:** If it's a match, it prints to the screen and saves to the results list.

### The Progress Printer
This is a **Daemon Thread**. It runs silently in the background and calculates:
$$\text{Progress \%} = \left( \frac{\text{Tested Words}}{\text{Total Words}} \right) \times 100$$
It uses `\r` (carriage return) to overwrite the same line in your terminal, creating a "live" updating feel.

---

## 3. Network Communication (`request`)
The script uses the `requests.Session()` object rather than simple `requests.get()`. 

**Why use a Session?**
* **Performance:** It reuses the underlying TCP connection (Keep-Alive), making the scan significantly faster.
* **Consistency:** It automatically handles the Headers and Cookies you provided for every single request in that thread.

It also includes an **Exception Handler** to catch common network errors (timeouts, dropped connections) so the entire tool doesn't crash if the website blips.

---

## 4. Input Handling: `argparse`
The `build_parser()` function defines the CLI (Command Line Interface). 

* **Type Casting:** It ensures `--threads` is an integer and `--timeout` is a float.
* **Defaults:** It sets the "standard" hacking status codes (200, 204, 301, etc.) so the user doesn't have to type them every time.
* **Pre-flight Check:** In the `if __name__ == "__main__":` block, the script validates that the URL starts with `http` or `https` before even starting the threads.

---

## 5. Visual Feedback: `class Color`
This is a simple helper class using **ANSI Escape Sequences**. 
* `\033[92m` tells the terminal to start printing in **Green**.
* `\033[0m` tells the terminal to **Reset** to default white text.
Without the Reset code, your entire terminal would stay green even after the script finishes!

---

### Summary of the Data Flow
1. **User** input → `argparse`
2. **Wordlist** file → `word_queue`
3. **Threads** → `worker()` loops
4. **Worker** → `requests.get()` → **Target Website**
5. **Response** → `Result` object → **Screen/File Output**
