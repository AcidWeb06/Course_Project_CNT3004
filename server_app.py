import os
import csv
import socket
import threading
import hashlib
import hmac
import time

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
COMMANDS = "TASK, SEND_FILE, DOWNLOAD, DELETE, DIR, SUBFOLDER, LOGOUT"

STATS_FILE = "server_stats.csv"
STATS_FIELDS = ["timestamp", "user", "operation", "filename", "bytes", "seconds", "mb_per_s", "status"]
STATS = []  # read by the analysis module

lock = threading.Lock()
active_files = {}  # path -> transfers using it, so DELETE knows what's busy


def log(msg):
    with lock:
        print(msg.encode("ascii", "backslashreplace").decode())  # windows console chokes on some filenames


# transfers pass bytes, everything else just logs response time
def record_stat(user, operation, filename="", nbytes=0, seconds=0.0, status="ok"):
    mb_per_s = 0
    if nbytes and seconds:
        mb_per_s = round(nbytes / (1024 * 1024) / seconds, 3)
    row = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user": user,
        "operation": operation,
        "filename": filename,
        "bytes": nbytes,
        "seconds": round(seconds, 6),
        "mb_per_s": mb_per_s,
        "status": status,
    }
    with lock:
        STATS.append(row)
        try:
            new = not os.path.exists(STATS_FILE)
            with open(STATS_FILE, "a", newline="") as f:
                writer = csv.DictWriter(f, STATS_FIELDS)
                if new:
                    writer.writeheader()
                writer.writerow(row)
        except OSError:
            pass
    return row


def reply(conn, text):
    data = f"OK@{text.replace('@', ' ')}".encode(FORMAT)[:SIZE - 1]
    conn.sendall(data.decode(FORMAT, errors="ignore").encode(FORMAT) + b"\n")


def receive(conn):
    data = conn.recv(SIZE)
    if not data:
        return None
    return data.decode(FORMAT, errors="replace").strip()


# recv() can return half a message, or two stuck together
def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError
        buf += chunk
    return buf


# None if it points outside the server folder (../ etc)
def safe_path(rel):
    path = os.path.realpath(os.path.join(ROOT, rel.strip().lstrip("/\\")))
    return path if path == ROOT or path.startswith(ROOT + os.sep) else None


def set_active(path, delta):
    with lock:
        active_files[path] = active_files.get(path, 0) + delta
        if not active_files[path]:
            del active_files[path]


def handle_upload(conn, user, check):
    if not check:
        conn.settimeout(CHECK_TIMEOUT)
        try:
            check = receive(conn) or ""
        except socket.timeout:
            check = ""
        conn.settimeout(CLIENT_TIMEOUT)
    if not check.startswith("CHECK_EXISTENCE_OF@"):
        return reply(conn, "Upload aborted: file not found on client.")

    sent_name = check.split("@", 1)[1]
    filename = os.path.basename(sent_name.strip())
    path = os.path.join(ROOT, filename)

    if os.path.exists(path):
        conn.sendall(b"FILE_EXISTS")
        # exact length so we don't eat the header behind it
        first = recv_exact(conn, 1)
        if first == b"P":
            decision = first + recv_exact(conn, len("PROCEED_OVERWRITE") - 1)
        else:
            decision = first + recv_exact(conn, len("CANCEL_UPLOAD") - 1)
        if decision != b"PROCEED_OVERWRITE":
            return reply(conn, "Upload canceled.")
    else:
        conn.sendall(b"FILE_NOT_EXISTS")

    filesize = int(recv_exact(conn, SIZE).decode(FORMAT, errors="replace").rsplit("@", 1)[1])
    # header is padded by characters, so non-ascii names run past SIZE bytes
    extra = len(f"{sent_name}@{filesize}".ljust(SIZE)[:SIZE].encode(FORMAT)) - SIZE
    if extra > 0:
        recv_exact(conn, extra)

    # temp file so a failed upload doesn't wreck the old copy
    tmp = f"{path}.{threading.get_ident()}.part"
    try:
        f = open(tmp, "wb")
    except OSError:
        f = None  # bad name, but the data's coming anyway so read and toss it

    start, remaining = time.perf_counter(), filesize
    set_active(path, 1)
    try:
        while remaining:
            chunk = conn.recv(min(CHUNK, remaining))
            if not chunk:
                raise ConnectionResetError
            if f:
                f.write(chunk)
            remaining -= len(chunk)
    finally:
        set_active(path, -1)
        if f:
            f.close()
        if remaining:
            record_stat(user, "UPLOAD", filename, filesize - remaining, time.perf_counter() - start, "interrupted")
            if f:
                os.remove(tmp)
    seconds = time.perf_counter() - start

    try:
        os.replace(tmp, path)
    except OSError:  # bad name, or windows won't replace a file someone's downloading
        if f:
            os.remove(tmp)
        return reply(conn, f"ERROR: Could not save '{filename}'.")
    row = record_stat(user, "UPLOAD", filename, filesize, seconds)
    log(f"[UPLOAD] {user} {filename} ({filesize} bytes, {row['mb_per_s']} MB/s)")
    reply(conn, f"Server received '{filename}' ({filesize} bytes).")


# DOWNLOAD@path[@offset] -> header, data, OK@. offset is for resuming
def handle_download(conn, user, arg):
    name, offset = arg, 0
    if name.rsplit("@", 1)[-1].isdigit() and "@" in name:
        name, offset = name.rsplit("@", 1)
        offset = int(offset)
    path = safe_path(name)
    if not path or not os.path.isfile(path):
        conn.sendall(f"FILE_NOT_FOUND@{name}".encode(FORMAT).ljust(SIZE))
        return reply(conn, f"ERROR: File '{name}' does not exist on the server.")

    filesize = os.path.getsize(path)
    offset = min(offset, filesize)
    conn.sendall(f"FILE_FOUND@{os.path.basename(path)}@{filesize}@{offset}".encode(FORMAT).ljust(SIZE))
    start = time.perf_counter()
    set_active(path, 1)
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            while chunk := f.read(CHUNK):
                conn.sendall(chunk)
    finally:
        set_active(path, -1)
    row = record_stat(user, "DOWNLOAD", name, filesize - offset, time.perf_counter() - start)
    log(f"[DOWNLOAD] {user} {name} ({filesize - offset} bytes, {row['mb_per_s']} MB/s)")
    reply(conn, f"Download of '{name}' complete.")


# these return (ok, text)
def handle_delete(arg):
    path = safe_path(arg)
    if not path or not os.path.isfile(path):
        return False, f"ERROR: File '{arg}' does not exist."
    if path in active_files:
        return False, f"ERROR: File '{arg}' is currently being processed."
    try:
        os.remove(path)
    except OSError as e:
        return False, f"ERROR: {e.strerror}"
    return True, f"Deleted '{arg}'."


def handle_dir(arg):
    path = safe_path(arg)
    if not path or not os.path.isdir(path):
        return False, f"ERROR: Folder '{arg}' does not exist."
    lines = [e.name + "/" if e.is_dir() else f"{e.name}  ({e.stat().st_size} bytes)"
             for e in os.scandir(path) if not e.name.endswith(".part")]
    return True, f"Contents of /{arg}:\n" + ("\n".join(lines) or "(empty)")


# SUBFOLDER@create@path / SUBFOLDER@delete@path, delete only works on empty folders
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
        if cmd == "TASK":
            ok, text = True, "Task received."
        elif cmd == "DELETE":
            ok, text = handle_delete(arg)
        elif cmd == "DIR":
            ok, text = handle_dir(arg)
        elif cmd == "SUBFOLDER":
            ok, text = handle_subfolder(arg)
        else:
            ok, text = False, f"ERROR: Unknown command. Valid commands: {COMMANDS}"
        reply(conn, text)
        record_stat(user, cmd, arg, seconds=time.perf_counter() - start, status="ok" if ok else "error")
    return True


def handle_client(conn, addr):
    log(f"[NEW CONNECTION] {addr} connected.")
    conn.settimeout(CLIENT_TIMEOUT)
    try:
        username = authenticate(conn, addr)
        if username is None:
            conn.sendall("ERROR: Invalid username or password.\n".encode(FORMAT))
            time.sleep(0.1)  # keep the two messages in separate recv() calls
            conn.sendall("DISCONNECTED@Login failed.\n".encode(FORMAT))
            return

        log(f"[LOGIN] {addr} logged in as {username}")
        conn.sendall("Login successful.\n".encode(FORMAT))
        time.sleep(0.1)
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
        log(f"[CLOSED] {addr}")
        conn.close()


def main():
    print("Starting the server")
    os.makedirs(SERVER_PATH, exist_ok=True)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

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
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        log("\nShutting down server.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
