import os
import socket

#School VPN IP (Ethernet): "10.200.102.149"

# IP = "192.168.1.101" #"localhost"
IP = "localhost"
PORT = 4450
ADDR = (IP,PORT)
SIZE = 1024 ## byte .. buffer size
FORMAT = "utf-8"
SERVER_DATA_PATH = "server_data"

def main():
    
    client = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    client.connect(ADDR)

    #---------------Authentification---------------#
    # Recieving username prompt and sending username
    user_msg = client.recv(SIZE).decode(FORMAT)
    username = input(user_msg)
    client.sendall(username.encode())

    # Recieving password prompt and sending hashed password
    pass_msg = client.recv(SIZE).decode(FORMAT)
    password = input(pass_msg)
    hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()
    client.sendall(hashed_password.encode())
    
    # Server response 
    login_response = client.recv(SIZE).decode()
    print(login_response.strip())

    #----------------------------------------------#
        
    while True:  ### multiple communications
        data = client.recv(SIZE).decode(FORMAT)
        cmd, msg = data.split("@")
        if cmd == "OK":
            print(f"{msg}")
        elif cmd == "DISCONNECTED":
            print(f"{msg}")
            break
        
        data = input("> ") 
        data = data.split(" ")
        cmd = data[0]

        if cmd == "TASK":
            client.send(cmd.encode(FORMAT))

        elif cmd == "LOGOUT":
            client.send(cmd.encode(FORMAT))
            break




    print("Disconnected from the server.")
    client.close() ## close the connection

if __name__ == "__main__":
    main()
