import os
import socket
import threading

# Place this at the top of your file, near your PORT and IP variables
AUTHORIZED_USERS = {
    "client1": "encrypted_password_A", 
    "client2": "encrypted_password_B",
    "prof": "encrypted_password_C"
}

IP = "10.200.102.149"
PORT = 4450
ADDR = (IP,PORT)
SIZE = 1024
FORMAT = "utf-8"
SERVER_PATH = "server"

### to handle the clients
def handle_client (conn,addr):

    print(f"[NEW CONNECTION] {addr} connected.")

    initial_data = conn.recv(SIZE).decode(FORMAT)
    data_parts = initial_data.split("@")

    if len(data_parts) == 3 and data_parts[0] == "AUTH":
      username = data_parts[1]
      encrypted_pass = data_parts[2]
    else:
        conn.send("ERROR@Authentication required first".encode(FORMAT))
        conn.close()
        return

    if username in AUTHORIZED_USERS and AUTHORIZED_USERS[username] == encrypted_pass:
      conn.send("OK@Welcome to the server".encode(FORMAT))
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
  
    else:
      conn.send("ERROR@Invalid username or password".encode(FORMAT))
      conn.close()
      return

def main():
    print("Starting the server")
    server = socket.socket(socket.AF_INET,socket.SOCK_STREAM) ## used IPV4 and TCP connection
    server.bind(ADDR) # bind the address
    server.listen() ## start listening
    print(f"server is listening on {IP}: {PORT}")
    while True:
        conn, addr = server.accept() ### accept a connection from a client
        thread = threading.Thread(target = handle_client, args = (conn, addr)) ## assigning a thread for each client
        thread.start()


if __name__ == "__main__":
    main()