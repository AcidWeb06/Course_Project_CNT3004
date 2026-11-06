import os
import socket
import hashlib
from pathlib import Path

#School VPN IP (Ethernet): "10.200.102.149"

# IP = "192.168.1.101" #"localhost"
IP = "localhost"
PORT = 4450
ADDR = (IP,PORT)
SIZE = 1024 ## byte .. buffer size
FORMAT = "utf-8"
SERVER_DATA_PATH = "server_data"


#----Sending file function----#                    # Using "@" to split strings       
def send_file(client, filename):
    # Extracting file path
    file_path = Path(filename).resolve()

    # Checking if file exist on client side
    if not file_path.exists():
        print(f"Error: File '{filename}' not found.")
        return False

    # Getting file size
    filesize = file_path.stat().st_size

    # Checking if file exist on server side
    check_cmd = f"CHECK_EXISTENCE_OF@{filename}" # Server side needs to get filename from this string
    client.sendall(check_cmd.encode(FORMAT))

    # Server's Response
    server_response = client.recv(SIZE).decode(FORMAT).strip() # WiLl assume server response will be "FILE_EXIST" or "FILE_NOT_EXISTS"
    
    # Handling "FILE_EXIST" case
    if server_response == "FILE_EXISTS":
        # Asking user if they want to overwrite file
        choice = input(f"File '{filename}' already exist on the server. Overwrite? (y/n): ").strip().lower()

        # If No
        if choice != 'y':
            # Telling server to cancel upload
            client.sendall("CANCEL_UPLOAD".encode(FORMAT))
            print("Upload canceled by user.") 
            return False

        else:
            # Telling server to overwrite
            client.sendall("PROCEED_OVERWRITE".encode(FORMAT))

    # Handling "FILE_NOT_EXISTS" case
    elif server_response == "FILE_NOT_EXISTS":
        pass

    # Else
    else:
        print("Error: Unexpected server response.")
        return False

    # Continuing With Upload

    # Creating a 1024-byte header to identify file. filename | filesize
    header = f"{filename}@{filesize}" # "@" makes it easier to split string 
    header = header.ljust(SIZE)[:SIZE] # Padding Header

    # Sending file header
    client.sendall(header.encode(FORMAT))

    # Uploading file
    with open(file_path, 'rb') as f:
        while chunk := f.read(SIZE):
            client.sendall(chunk)

    # Outputting Successful file send
    print(f"File '{filename}' uploaded successfully.\n")




def main():

    #---------------Inital Connection--------------#
    
    client = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    client.connect(ADDR)

    #---------------Authentification---------------#

    # Recieving username prompt and sending username
    user_msg = client.recv(SIZE).decode(FORMAT)
    username = input(user_msg)
    client.sendall(username.encode())

    # Recieving password prompt and sending hashed/encrypted password
    pass_msg = client.recv(SIZE).decode(FORMAT)
    password = input(pass_msg)
    hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()
    client.sendall(hashed_password.encode())

    # Server response | Is login successful?
    login_response = client.recv(SIZE).decode()
    print(login_response.strip())

    #----------------Command Center----------------#
    
    while True:  ### multiple communications

        # Server's message
        s_data = client.recv(SIZE).decode(FORMAT)
        s_cmd, msg = s_data.split("@")

        # Checking server's message 
        if s_cmd == "OK": # "OK" used to prompt welcome message and valid commands
            print(f"{msg}")
        elif s_cmd == "DISCONNECTED": # Used to prompt disconnection of client from server
            print(f"{msg}")
            break

        # Inputing command in terminal
        data = input("> ") 
        data = data.split(" ")
        cmd = data[0]

        # Checking what user inputted
        if cmd == "TASK":
            client.send(cmd.encode(FORMAT))

        elif cmd == "LOGOUT":
            client.send(cmd.encode(FORMAT))
            break

        elif cmd == "SEND_FILE": # Make sure files are stored in the same dir/folder as client.py script 
            # Input file name with extension (.mp3, .txt, .pdf, etc.)
            file_name = input("Enter the full file name: ")

            # Notifying server of command
            client.send(cmd.encode(FORMAT))

            # Running send file function            
            send_file(client, file_name)

    #---------------Connection Closed---------------#
    print("Disconnected from the server.")
    client.close() ## close the connection

if __name__ == "__main__":
    main()
