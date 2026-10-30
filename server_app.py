import os
import socket
import threading

AUTHORIZED_USERS = {
    "user": "password", 
    "client2": "encrypted_password_B",
    "prof": "encrypted_password_C"
}

IP = "10.200.102.149"
PORT = 4450
ADDR = (IP,PORT)
SIZE = 1024
FORMAT = "utf-8"
SERVER_PATH = "server"

def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected.")
    
    # Prompt for username
    conn.send("Enter username: ".encode(FORMAT))
    username = conn.recv(SIZE).decode(FORMAT)
    
    # Prompt for password
    conn.send("Enter password: ".encode(FORMAT))
    encrypted_pass = conn.recv(SIZE).decode(FORMAT)
    
    if username in AUTHORIZED_USERS and AUTHORIZED_USERS[username] == encrypted_pass:
        conn.send("Login successful.\n".encode(FORMAT))
    else: # invalid username or password
        conn.send("ERROR: Invalid username or password.\n".encode(FORMAT))
        conn.close()
        return

    while True:
        data =  conn.recv(SIZE).decode(FORMAT)
        data = data.split("@")
        cmd = data[0]
       
        send_data = "OK@"

        if cmd == "LOGOUT":
            break

        elif cmd == "TASK": 
            send_data += "LOGOUT from the server.\n"

            conn.send(send_data.encode(FORMAT))
        print(f"{addr} disconnected")
        conn.close()

def main():
    print("Starting the server")
    server = socket.socket(socket.AF_INET,socket.SOCK_STREAM) 
    server.bind(ADDR) 
    server.listen() 
    print(f"server is listening on {IP}: {PORT}")
    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target = handle_client, args = (conn, addr))
        thread.start()


if __name__ == "__main__":
    main()
