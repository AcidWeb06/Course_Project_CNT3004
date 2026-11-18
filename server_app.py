import os
import json
import socket
import threading
import hashlib
import hmac
import time
from NetworkAnalysis import networkStats

# username -> sha256 of the password
AUTHORIZED_USERS = {
    "user1": hashlib.sha256(b"password1").hexdigest(),
    "user2": hashlib.sha256(b"password2").hexdigest(),
    "user3": hashlib.sha256(b"password3").hexdigest(),
}

IP = "0.0.0.0"  # all interfaces (VPN is 10.200.102.149)
PORT = 4450
ADDR = (IP, PORT)
SIZE = 1024
FORMAT = "utf-8"
SERVER_PATH = "server"
ROOT = os.path.realpath(SERVER_PATH)
CLIENT_TIMEOUT = 300  # seconds
CHECK_TIMEOUT = 2     # seconds
CHUNK = 64 * 1024
COMMANDS = "UPLOAD, DOWNLOAD, DELETE, DIR, SUBFOLDER, LOGOUT"  # UPLOAD arrives as SEND_FILE

STATS_FILE = "network_stats.csv"
stats = None

# files sit on disk under: type letter + S for server + a number (TS001.txt, VS002.mp4)
# clients keep using the original name
INDEX_FILE = "server_index.json"
FILE_TYPES = {
    "T": (".txt", ".csv", ".log", ".md", ".json", ".xml", ".html"),
    "A": (".wav", ".mp3", ".flac", ".ogg", ".m4a"),
    "V": (".mp4", ".mkv", ".mov", ".avi", ".webm"),
    "I": (".png", ".jpg", ".jpeg", ".gif", ".bmp"),
}
OTHER_TYPE = "F"  # anything else

lock = threading.Lock()
active_files = {}  # path -> transfers using it
clients = {}       # addr -> user and connect time, everyone connected right now
file_index = {}    # "folder/name" -> {"id", "name", "stored", "sha256"}
counters = {}      # type letter -> last number handed out

def log(msg):
    with lock:
        print(msg.encode("ascii", "backslashreplace").decode())  # windows console chokes on some filenames

# transfers pass bytes
def record_stat(user, operation, filename="", nbytes=0, seconds=0.0, status="ok", response_ms=0.0, role="server"):
    try:
        stats.log(f"{role}:{user}", operation, filename, nbytes, seconds, response_ms, status)
    except (OSError, AttributeError):
        pass
    return round(nbytes / (1024 * 1024) / seconds, 3) if nbytes and seconds else 0


def record_client_report(user, report):
    fields = report.split("@", 6)
    if len(fields) < 7:
        record_stat(user, "REPORT", report.strip(), status="malformed", role="client")
        return ""
    _, cmd, target, nbytes, seconds, response_ms, rest = fields
    status = next((s for s in ("error", "ok") if rest.startswith(s)), "")
    try:
        nbytes, seconds, response_ms = int(float(nbytes)), float(seconds), float(response_ms)
    except ValueError:
        nbytes, seconds, response_ms, status = 0, 0.0, 0.0, ""
    record_stat(user, cmd, target, nbytes, seconds, status or "malformed", response_ms, role="client")
    return rest[len(status):]

# every command ends this
def reply(conn, text):
    data = f"OK@{text.replace('@', ' ')}".encode(FORMAT)[:SIZE - 1]
    conn.sendall(data.decode(FORMAT, errors="ignore").encode(FORMAT) + b"\n")

# one message from client
def receive(conn):
    data = conn.recv(SIZE)
    if not data:
        return None
    return data.decode(FORMAT, errors="replace").strip()

# recv() can return half a message or two stuck together
def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError
        buf += chunk
    return buf

# None if it points outside folder 
def safe_path(rel):
    path = os.path.realpath(os.path.join(ROOT, rel.strip().lstrip("/\\")))
    return path if path == ROOT or path.startswith(ROOT + os.sep) else None

def set_active(path, delta):
    with lock:
        active_files[path] = active_files.get(path, 0) + delta
        if not active_files[path]:
            del active_files[path]

# split up file into chunks
def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()

# what a file goes by in the index
def file_key(path):
    return os.path.normcase(os.path.relpath(path, ROOT)).replace("\\", "/")

def save_index():
    try:
        with open(INDEX_FILE + ".tmp", "w") as f:
            json.dump({"counters": counters, "files": file_index}, f, indent=1)
        os.replace(INDEX_FILE + ".tmp", INDEX_FILE)
    except OSError:
        pass

# next free name for a file
def new_entry(folder, name):
    ext = os.path.splitext(name)[1].lower()
    if not ext[1:].isalnum():
        ext = ""
    letter = next((t for t, exts in FILE_TYPES.items() if ext in exts), OTHER_TYPE)
    while True:
        counters[letter] = counters.get(letter, 0) + 1
        file_id = f"{letter}S{counters[letter]:03d}"
        if not os.path.exists(os.path.join(folder, file_id + ext)):  # skip it if something's already sitting there
            return {"id": file_id, "name": name, "stored": file_id + ext, "sha256": ""}

# stored name -> index entry
def stored_in(folder):
    key = "" if folder == ROOT else file_key(folder)
    with lock:
        return {e["stored"]: e for k, e in file_index.items() if k.rpartition("/")[0] == key}

def adopt(path):
    folder, name = os.path.split(path)
    try:
        digest = hash_file(path)
        with lock:
            entry = new_entry(folder, name)
            entry["sha256"] = digest
            os.rename(path, os.path.join(folder, entry["stored"]))
            file_index[file_key(path)] = entry
            save_index()
    except OSError:
        return None
    log(f"[INDEX] {name} stored as {entry['stored']}")
    return entry


# client path -> (path on disk, index key, index entry).
def locate(rel):
    path = safe_path(rel)
    if not path:
        return None, None, None
    key = file_key(path)
    folder, _, base = key.rpartition("/")
    with lock:
        entry = file_index.get(key)
        if not entry:
            for k, e in file_index.items():
                if k.rpartition("/")[0] == folder and base.lower() in (e["id"].lower(), e["stored"].lower()):
                    key, entry = k, e
                    break
    if not entry and os.path.isfile(path):
        entry = adopt(path)
    if entry:
        path = os.path.join(os.path.dirname(path), entry["stored"])
    return path, key, entry


# an upload that never finished shouldn't leave a name
def forget_if_missing(key, path):
    with lock:
        if key in file_index and not os.path.exists(path):
            del file_index[key]
            save_index()


# runs once: read index, drop missing files, pick up new
def load_index():
    try:
        with open(INDEX_FILE) as f:
            data = json.load(f)
        counters.update(data["counters"])
        file_index.update(data["files"])
    except (OSError, ValueError, KeyError):
        pass
    for key in list(file_index):
        if not os.path.isfile(os.path.join(ROOT, os.path.dirname(key), file_index[key]["stored"])):
            del file_index[key]
    for folder, _, names in os.walk(ROOT):
        known = stored_in(folder)
        for name in names:
            if name not in known and not name.endswith(".part"):
                adopt(os.path.join(folder, name))
    with lock:
        save_index()


# existence check -> overwrite decision -> 1024 byte header -> the data -> OK@
def handle_upload(conn, user, check):
    received = time.perf_counter()
    if not check:
        conn.settimeout(CHECK_TIMEOUT)
        try:
            check = receive(conn) or ""
        except socket.timeout:
            check = ""
        conn.settimeout(CLIENT_TIMEOUT)
    if not check.startswith("CHECK_EXISTENCE_OF@"):
        record_stat(user, "UPLOAD", status="not found on client", response_ms=(time.perf_counter() - received) * 1000)
        return reply(conn, "Upload aborted: file not found on client.")

    sent_name = check.split("@", 1)[1]
    filename = os.path.basename(sent_name.strip().replace("\\", "/"))  # client may send a whole windows path
    path, key, entry = (None, None, None) if filename in ("", ".", "..") else locate(filename)

    response_ms = (time.perf_counter() - received) * 1000
    if path and os.path.exists(path):
        conn.sendall(b"FILE_EXISTS")
        # exact length so we don't eat the header behind it
        first = recv_exact(conn, 1)
        if first == b"P":
            decision = first + recv_exact(conn, len("PROCEED_OVERWRITE") - 1)
        else:
            decision = first + recv_exact(conn, len("CANCEL_UPLOAD") - 1)
        if decision != b"PROCEED_OVERWRITE":
            record_stat(user, "UPLOAD", filename, status="canceled", response_ms=response_ms)
            return reply(conn, "Upload canceled.")
    else:
        conn.sendall(b"FILE_NOT_EXISTS")

    filesize = int(recv_exact(conn, SIZE).decode(FORMAT, errors="replace").rsplit("@", 1)[1])
    # header is padded by characters
    extra = len(f"{sent_name}@{filesize}".ljust(SIZE)[:SIZE].encode(FORMAT)) - SIZE
    if extra > 0:
        recv_exact(conn, extra)

    # new file
    if path and not entry:
        with lock:
            entry = file_index.setdefault(key, new_entry(ROOT, filename))
        path = os.path.join(ROOT, entry["stored"])

    # temp file
    tmp = f"{path}.{threading.get_ident()}.part"
    try:
        f = open(tmp, "wb") if path else None
    except OSError:
        f = None 

    start, remaining = time.perf_counter(), filesize
    digest = hashlib.sha256()  # hashed as it comes in, DOWNLOAD hands it back
    if path:
        set_active(path, 1)
    try:
        while remaining:
            chunk = conn.recv(min(CHUNK, remaining))
            if not chunk:
                raise ConnectionResetError
            if f:
                f.write(chunk)
                digest.update(chunk)
            remaining -= len(chunk)
    finally:
        if path:
            set_active(path, -1)
        if f:
            f.close()
        if remaining:
            record_stat(user, "UPLOAD", filename, filesize - remaining, time.perf_counter() - start, "interrupted", response_ms)
            if f:
                os.remove(tmp)
            if path:
                forget_if_missing(key, path)
    seconds = time.perf_counter() - start

    try:
        if not f:
            raise OSError
        os.replace(tmp, path)
    except OSError:  # couldn't write
        if f:
            os.remove(tmp)
        if path:
            forget_if_missing(key, path)
        record_stat(user, "UPLOAD", filename, filesize, seconds, "error", response_ms)
        return reply(conn, f"ERROR: Could not save '{filename}'.")
    with lock:
        entry["sha256"] = digest.hexdigest()
        save_index()
    mb_per_s = record_stat(user, "UPLOAD", filename, filesize, seconds, response_ms=response_ms)
    log(f"[UPLOAD] {user} {filename} -> {entry['stored']} ({filesize} bytes, {mb_per_s} MB/s)")
    reply(conn, f"Server received '{filename}' as {entry['id']} ({filesize} bytes).")


# DOWNLOAD@path[@offset] -> header, data, OK@.
# header is FILE_FOUND@name@size@offset@sha256
def handle_download(conn, user, arg):
    received = time.perf_counter()
    name, offset = arg, 0
    if name.rsplit("@", 1)[-1].isdigit() and "@" in name:
        name, offset = name.rsplit("@", 1)
        offset = int(offset)
    path, _, entry = locate(name)
    if not path or not os.path.isfile(path):
        conn.sendall(f"FILE_NOT_FOUND@{name}".encode(FORMAT).ljust(SIZE))
        record_stat(user, "DOWNLOAD", name, status="error", response_ms=(time.perf_counter() - received) * 1000)
        return reply(conn, f"ERROR: File '{name}' does not exist on the server.")

    shown = entry["name"] if entry else os.path.basename(path)
    digest = entry["sha256"] if entry else ""
    filesize = os.path.getsize(path)
    offset = min(offset, filesize)
    conn.sendall(f"FILE_FOUND@{shown}@{filesize}@{offset}@{digest}".encode(FORMAT).ljust(SIZE)) # header
    start = time.perf_counter()
    response_ms = (start - received) * 1000
    set_active(path, 1)
    try:
        with open(path, "rb") as f: 
            f.seek(offset) # canceled bonus code
            while chunk := f.read(CHUNK):
                conn.sendall(chunk)
    finally:
        set_active(path, -1)
    mb_per_s = record_stat(user, "DOWNLOAD", name, filesize - offset, time.perf_counter() - start, response_ms=response_ms)
    log(f"[DOWNLOAD] {user} {name} <- {os.path.basename(path)} ({filesize - offset} bytes, {mb_per_s} MB/s)")
    reply(conn, f"Download of '{name}' complete.")

# returns (ok, text)
def handle_delete(arg):
    path, key, entry = locate(arg)
    if not path or not os.path.isfile(path):
        return False, f"ERROR: File '{arg}' does not exist."
    if path in active_files:
        return False, f"ERROR: File '{arg}' is currently being processed."
    try:
        os.remove(path)
    except OSError as e:
        return False, f"ERROR: {e.strerror}"
    if entry:
        with lock:
            file_index.pop(key, None)
            save_index()
    return True, f"Deleted '{arg}'."


# each file is id, original name, size
def handle_dir(arg):
    path = safe_path(arg)
    if not path or not os.path.isdir(path):
        return False, f"ERROR: Folder '{arg}' does not exist."
    known, lines = stored_in(path), []
    for e in sorted(os.scandir(path), key=lambda e: e.name):
        if e.name.endswith(".part"):
            continue
        if e.is_dir():
            lines.append(e.name + "/")
            continue
        size = e.stat().st_size
        entry = known.get(e.name) or adopt(e.path)
        lines.append(f"{entry['id']}  {entry['name']}  ({size} bytes)" if entry else f"{e.name}  ({size} bytes)")
    return True, f"Contents of /{arg}:\n" + ("\n".join(lines) or "(empty)")


# SUBFOLDER@create@path / SUBFOLDER@delete@path
def handle_subfolder(arg):
    action, _, rel = arg.partition("@")
    path = safe_path(rel) if rel.strip() else None
    try:
        if action == "create" and path:
            os.makedirs(path)
        elif action == "delete" and path and path != ROOT:
            os.rmdir(path)
        else:
            return False, "ERROR: Use SUBFOLDER create <path> or SUBFOLDER delete <path>."
    except OSError as e:
        return False, f"ERROR: Could not {action} '{rel}': {e.strerror}"
    return True, f"Folder '{rel}' {action}d."


# username if the login is good, None if not
def authenticate(conn, addr):
    conn.sendall("Enter username: ".encode(FORMAT))
    username = receive(conn)
    if username is None:
        return None

    conn.sendall("Enter password: ".encode(FORMAT))
    hashed_pass = receive(conn)
    if hashed_pass is None:
        return None

    stored = AUTHORIZED_USERS.get(username)
    if stored and hmac.compare_digest(stored.encode(FORMAT), hashed_pass.encode(FORMAT)):
        return username

    log(f"[AUTH FAILED] {addr} tried username {username!r}")
    return None

# False = LOGOUT
def handle_command(conn, user, raw):
    raw, sep, report = raw.partition("NETWORK_ANALYSIS@")
    if sep:
        raw += record_client_report(user, report)
    raw = raw.strip()
    if not raw:
        return True
    cmd, _, arg = raw.partition("@")
    if raw.startswith("SEND_FILE"):
        handle_upload(conn, user, raw[len("SEND_FILE"):].strip())
    elif cmd == "DOWNLOAD":
        handle_download(conn, user, arg.strip())
    elif cmd == "LOGOUT":
        return False
    else:
        start = time.perf_counter()
        arg = arg.strip()
        if cmd == "DELETE":
            ok, text = handle_delete(arg)
        elif cmd == "DIR":
            ok, text = handle_dir(arg)
        elif cmd == "SUBFOLDER":
            ok, text = handle_subfolder(arg)
        else:
            ok, text = False, f"ERROR: Unknown command. Valid commands: {COMMANDS}"
        reply(conn, text)
        record_stat(user, cmd, arg, status="ok" if ok else "error", response_ms=(time.perf_counter() - start) * 1000)
    return True


# each client in its own thread
def handle_client(conn, addr):
    with lock:
        clients[addr] = {"user": None, "since": time.strftime("%H:%M:%S")}
    log(f"[NEW CONNECTION] {addr} connected. {len(clients)} active.")
    conn.settimeout(CLIENT_TIMEOUT)
    try:
        username = authenticate(conn, addr)
        if username is None:
            conn.sendall("ERROR: Invalid username or password.\n".encode(FORMAT))
            time.sleep(0.1)  # keep the two messages in separate recv() calls
            conn.sendall("DISCONNECTED@Login failed.\n".encode(FORMAT))
            return

        with lock:
            clients[addr]["user"] = username
        log(f"[LOGIN] {addr} logged in as {username}")
        conn.sendall("Login successful.\n".encode(FORMAT).ljust(SIZE))
        reply(conn, f"Welcome! Commands: {COMMANDS}")

        while True:
            raw = receive(conn)
            if raw is None:
                log(f"[DISCONNECT] {addr} closed the connection.")
                break
            if not handle_command(conn, username, raw):
                break

    except socket.timeout:
        log(f"[TIMEOUT] {addr} was idle for {CLIENT_TIMEOUT}s, dropping.")
        try:
            conn.sendall("DISCONNECTED@Timed out due to inactivity.\n".encode(FORMAT))
        except OSError:
            pass
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        log(f"[DISCONNECT] {addr} dropped the connection unexpectedly.")
    except Exception as e:
        # don't let one client take the server down
        log(f"[ERROR] {addr}: {type(e).__name__}: {e}")
        try:
            reply(conn, "ERROR: Internal server error.")
        except OSError:
            pass
    finally:
        with lock:
            clients.pop(addr, None)
        log(f"[CLOSED] {addr} {len(clients)} active.")
        conn.close()


def main():
    global stats
    print("Starting the server")
    stats = networkStats(STATS_FILE)
    os.makedirs(SERVER_PATH, exist_ok=True)
    load_index()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # AF_INET = IPv4, SOCK_STREAM = TCP
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # lets server restart on the same port without waiting

    try:
        server.bind(ADDR)
    except OSError as e:
        print(f"Could not bind to {IP}:{PORT}: {e}")
        return

    server.listen()
    log(f"server is listening on {IP}:{PORT}")

    try:
        while True:
            conn, addr = server.accept()
            # daemon so ctrl+c shuts down the threads aswell
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        log("\nShutting down server.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
