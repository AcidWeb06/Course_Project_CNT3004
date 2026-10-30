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
 
IP = "10.200.102.149"
PORT = 4450
ADDR = (IP, PORT)
SIZE = 1024
FORMAT = "utf-8"
SERVER_PATH = "server"
CLIENT_TIMEOUT = 300  # seconds
 
print_lock = threading.Lock()
 
 
# Thread-safe print so output from several clients doesn't interleave.
def log(msg):
    with print_lock:
        print(msg)
 
 
# Send an 'OK@...' message.
def reply(conn, text):
    text = text.replace("@", " ")
    conn.sendall(f"OK@{text}\n".encode(FORMAT))
 
 
# Read one message.
def receive(conn):
    data = conn.recv(SIZE)
    if not data:
        return None
    return data.decode(FORMAT, errors="replace").strip()
 
 
# Returns the username on success, or None on failure.
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
 
 
# Process one command. Returns False when the session should end.
def handle_command(conn, cmd):
    if cmd == "LOGOUT":
        return False
    elif cmd == "TASK":
        reply(conn, "Task received.")
    elif cmd == "":
        reply(conn, "ERROR: Empty command.")
    else:
        reply(conn, f"ERROR: Unknown command '{cmd[:30]}'. Valid commands: TASK, LOGOUT")
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
        reply(conn, "Welcome! Commands: TASK, LOGOUT")
 
        while True:
            raw = receive(conn)
            if raw is None:                       # client closed the connection
                log(f"[DISCONNECT] {addr} closed the connection.")
                break
            cmd = raw.split("@")[0].strip()
            if not handle_command(conn, cmd):     # LOGOUT
                break
 
    except socket.timeout:
        log(f"[TIMEOUT] {addr} was idle for {CLIENT_TIMEOUT}s, dropping.")
        try:
            conn.sendall("DISCONNECTED@Timed out due to inactivity.\n".encode(FORMAT))
        except OSError:
            pass
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        log(f"[DISCONNECT] {addr} dropped the connection unexpectedly.")
    except OSError as e:
        log(f"[SOCKET ERROR] {addr}: {e}")
    except Exception as e:
        # A bug in one client's handler must not affect other clients
        log(f"[UNEXPECTED ERROR] {addr}: {type(e).__name__}: {e}")
        try:
            reply(conn, "ERROR: Internal server error.")
        except OSError:
            pass
    finally:
        log(f"[CLOSED] {addr}")
        try:
            conn.close()
        except OSError:
            pass
 
 
def main():
    print("Starting the server")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # restart
 
    try:
        server.bind(ADDR)
    except OSError as e:
        print(f"Could not bind to {IP}:{PORT}: {e}")
        print("The port may already be in use, or the IP isn't on this machine (is the VPN on?).")
        return
 
    server.listen()
    log(f"server is listening on {IP}:{PORT}")
 
    try:
        while True:
            try:
                conn, addr = server.accept()
            except OSError as e:
                log(f"[ACCEPT ERROR] {e}")
                continue
            thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            thread.start()
    except KeyboardInterrupt:
        log("\nShutting down server.")
    finally:
        server.close()
 
 
if __name__ == "__main__":
    main()
 
