import os
import socket
import hashlib
import math
import time
import getpass # Not Needed if using pwinput
import pwinput # Can acheive input mask with pwinput library (pip install pwinput)
from pathlib import Path

#School VPN IP (Ethernet): "10.200.102.149"

# IP = "192.168.1.101" #"localhost"
IP = "localhost"
PORT = 4450
ADDR = (IP,PORT)
SIZE = 1024 ## byte .. buffer size
FORMAT = "utf-8"
SERVER_DATA_PATH = "server_data"

#------------------------------------- NOTES -------------------------------------#
"""
# Look at function "main" to view the way to send network analysis data to server.
  Under each command if/elif statement

# Removed Command "TASK". It was unecessary. Update Server's list of commands

# Changed Command "SEND_FILE" to "UPLOAD" for formatting reasons. Update Server's
  list of commands. SEND_FILE still works!!! Just update the command list. 
"""
#---------------------------------------------------------------------------------#


#----Upload File Function----#                    # Using "@" to split strings       
def send_file(client, filename):
    try:
        # Extracting file path
        file_path = Path(filename).resolve()

        # Checking if file exist on client side
        if not file_path.exists():
            client.sendall("SEND_FILEFILE_NOT_FOUND_ON_CLIENT".encode(FORMAT)) # "Included "SEND_FILE" to make formating homogenous
            return None, None, None

        # Getting file size
        filesize = file_path.stat().st_size

        # Sending command and checking if file exist on server side
        check_cmd = f"SEND_FILECHECK_EXISTENCE_OF@{filename}" # "Included "SEND_FILE" to make formating homogenous
        client.sendall(check_cmd.encode(FORMAT))

        # Server's Response
        server_response = client.recv(SIZE).decode(FORMAT, errors="ignore").strip() # Will assume server response will be "FILE_EXIST" or "FILE_NOT_EXISTS"
        
        # Handling "FILE_EXIST" case
        if server_response == "FILE_EXISTS":
            # Asking user if they want to overwrite file
            choice = input(f"File '{filename}' already exist on the server. Overwrite? (y/n): ").strip().lower()

            # If No
            if choice != 'y':
                # Telling server to cancel upload
                client.sendall("CANCEL_UPLOAD".encode(FORMAT))
                print("Upload canceled by user.") 
                return None, None, None

            else:
                # Telling server to overwrite
                client.sendall("PROCEED_OVERWRITE".encode(FORMAT))

        # Handling "FILE_NOT_EXISTS" case
        elif server_response == "FILE_NOT_EXISTS":
            print(f"Uploading new file '{filename}' to server...")

        # Else
        else:
            print(f"[Error] Unexpected server response: {server_response}")
            return None, None, None

        # Continuing With Upload

        # Creating a 1024-byte header to identify file. filename | filesize
        header = f"{filename}@{filesize}" # "@" makes it easier to split string 
        header = header.ljust(SIZE)[:SIZE] # Padding Header

        # Sending file header
        client.sendall(header.encode(FORMAT))

        # Recording start time of file upload
        start_time = time.time()

        # Uploading file
        total_sent = 0
        with open(file_path, 'rb') as f:
            while chunk := f.read(SIZE):
                client.sendall(chunk)
                total_sent += len(chunk)

                # Printing progress
                progress = ((total_sent) / filesize) * 100
                print(f"\rProgress: {progress:.2f}%", end="", flush=True)

        # Recording end time of file upload
        end_time = time.time()

        # Other file information # May need to send to server
        transfer_time = end_time - start_time
        filesize_mb = filesize / 1000000
        average_speed = filesize_mb / transfer_time if transfer_time > 0 else 0

        print(f"\nSize: {round(filesize_mb)} MB")
        print(f"Transfer Time: {transfer_time:.2f} Seconds")
        print(f"Average Speed: {average_speed:.2f} Mbps")


        # Finished Uploading and returning values
        return transfer_time, filesize_mb, average_speed

    except (socket.error, ConnectionResetError) as e:
        print(f"\n[Error] Connection lost during file upload: {e}")
        return None, None, None
    
    except Exception as e:
        print(f"\n[Error] An unexpected error occurred while sending file: {e}")
        return None, None, None
    
#--Downloading File Function--#
def download_file(client, filename):
    try:
        # Sending command and checking if file exist on server side
        check_cmd = f"DOWNLOAD@{filename}" # Server side needs to get filename from this string
        client.sendall(check_cmd.encode(FORMAT))

        # Server's Response
        header = client.recv(SIZE).decode(FORMAT, errors="ignore").strip() 
        if not header:
            print("[Error] Server closed connection during download check.")
            return None, None, None

        # Handles "FILE_NOT_FOUND"
        if "FILE_NOT_FOUND" in header:
            return None, None, None

        # Handles "FILE_FOUND"
        if "FILE_FOUND" in header:
            # Splitting header
            parts = header.split("@")
            if len(parts) < 4:
                print(f"[Error] Malformed server header: {header}")
                return None, None, None
            
            s_filename = parts[1]
            filesize = int(parts[2])
            offset = int(parts[3])

            print(f"Downloading '{s_filename}' (Size: {filesize} bytes)...")

            # Temporarily set a short timeout on the socket for the final chunk cleanup
            # so it never permanently hangs if a few bytes mismatch.
            client.settimeout(2.0)


            # Recording start time of file upload
            start_time = time.time()

            # Downloading file
            bytes_recieved = 0
            target_size = filesize - offset
            with open(s_filename, 'wb') as f:
                while bytes_recieved < target_size:
                    try:
                        to_read = min(SIZE, target_size - bytes_recieved)
                        chunk = client.recv(to_read)
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_recieved += len(chunk)

                        progress = (bytes_recieved / (filesize - offset)) * 100 if filesize > offset else 100
                        print(f"\rProgress: {progress:.2f}%", end="", flush=True)
                    
                    except socket.timeout:
                        break

            # Recording end time of file upload
            end_time = time.time()

            # Reset socket timeout back to normal (blocking)
            client.settimeout(None)

            # Other file information # May need to send to server
            transfer_time = end_time - start_time
            filesize_mb = filesize / 1000000
            average_speed = filesize_mb / transfer_time if transfer_time > 0 else 0

            print(f"\nSize: {round(filesize_mb)} MB")
            print(f"Transfer Time: {transfer_time:.2f} Seconds")
            print(f"Average Speed: {average_speed:.2f} Mbps")


            # Finished Downloading and returning values
            return transfer_time, filesize_mb, average_speed

        else:
            print(f"[Error] Unexpected server response: {header}")
            return None, None, None

    except (socket.error, ConnectionResetError) as e:
        print(f"\n[Error] Connection lost during download: {e}")
        return None, None, None
    
    except Exception as e:
        print(f"\n[Error] An unexpected error occurred during download: {e}")
        return None, None, None
        
#----Deleting File Function----#
def delete_file(client, filename):
    try:
        # Sending command and checking if file exist on server side
        exist_cmd = f"DELETE@{filename}"
        client.sendall(exist_cmd.encode(FORMAT))

    except socket.error as e:
        print(f"[Error] Network communication failed: {e}")

#------Viewing Directory------#
def view_dir(client, folder):
    try:
        # Sending command and checking if directory exist on server
        check_cmd = f"DIR@{folder}"
        client.sendall(check_cmd.encode(FORMAT))

    except socket.error as e:
        print(f"[Error] Network communication failed: {e}")

#---Create|Delete Subfolders---#
def subfolders(client, cmd ,folder):
    try:
        # Sending neccesary info to server
        info = f"SUBFOLDER@{cmd.lower()}@{folder}"
        client.sendall(info.encode(FORMAT))

    except socket.error as e:
        print(f"[Error] Network communication failed: {e}")

def main():

    #---------------Inital Connection--------------#

    client = socket.socket(socket.AF_INET,socket.SOCK_STREAM)

    try:
        client.connect(ADDR)

    except socket.error as e:
        print(f"[Error] Could not connect to server at {IP}:{PORT}. Details: {e}")
        return

    try:
        #---------------Authentification---------------#
        
        # Recieving username prompt and sending username
        user_msg = client.recv(SIZE).decode(FORMAT, errors="ignore")
        username = input(user_msg)
        client.sendall(username.encode(FORMAT))

        # Recieving password prompt and sending hashed/encrypted password
        pass_msg = client.recv(SIZE).decode(FORMAT, errors="ignore")
        # password = getpass.getpass(f"{pass_msg}")                             # If pwinput is not used
        password = pwinput.pwinput(f"{pass_msg}", mask="*")
        hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()
        client.sendall(hashed_password.encode(FORMAT))

        # Server response | Is login successful?
        login_response = client.recv(SIZE).decode(FORMAT, errors="ignore")
        print(login_response.strip())

        # If authentification failed, server sends error msg and disconnects
        if "ERROR" in login_response:
            return

        #----------------Command Center----------------#
        
        while True:  ### multiple communications

            # Server's  last message after functionS
            s_data = client.recv(SIZE).decode(FORMAT, errors="ignore")

            if not s_data:
                print("[Error] Server closed the connection.")
                break

            if "@" in s_data:
                s_cmd, msg = s_data.split("@", 1)
            else:
                s_cmd, msg = "OK", s_data

            # Checking server's message 
            if s_cmd == "OK": # "OK" used to prompt welcome message and valid commands
                print(f"\n{msg.strip()}")

            elif s_cmd == "DISCONNECTED": # Used to prompt disconnection of client from server
                print(f"\n[Disconnected] {msg.strip()}")
                break

            else:
                print(f"\n{s_data.strip()}")

            # Inputing command in terminal
            data = input("> ").strip()
            if not data:
                continue

            parts = data.split(" ", 1)
            cmd = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""
            
            # Checking what user inputted
            if cmd == "LOGOUT":
                client.sendall(cmd.encode(FORMAT))
                print("Logging out...")
                break

            elif cmd == "UPLOAD":
                # Make sure files are stored in the same dir/folder as client.py script 
                # Input file name with extension (.mp3, .txt, .pdf, etc.)
                filename = arg if arg else input("Enter full file name: ")   
                start_time = time.time()        
                transfer_time_s, filesize_mb, average_speed_mbps = send_file(client, filename)
                end_time = time.time()

                server_response_time_s = end_time - start_time

                # Example message to send data for network analysis
                # client.sendall(f"NETWORK_ANALYSIS@{transfer_time_s}@{filesize_mb}@{average_speed_mbps}@{server_response_time_s}")

            elif cmd == "DOWNLOAD": 
                filename = arg if arg else input("Enter full file name: ")  
                start_time = time.time()   
                transfer_time_s, filesize_mb, average_speed_mbps = download_file(client, filename)
                end_time = time.time()

                server_response_time_s = end_time - start_time

                # Example message to send data for network analysis
                # client.sendall(f"NETWORK_ANALYSIS@{transfer_time_s}@{filesize_mb}@{average_speed_mbps}@{server_response_time_s}")

            elif cmd == "DELETE":
                filename = arg if arg else input("Enter full file name: ")
                start_time = time.time()
                delete_file(client, filename)
                end_time = time.time()

                server_response_time_s = end_time - start_time

                # Example message to send data for network analysis
                # client.sendall(f"NETWORK_ANALYSIS@{server_response_time_s}")                

            elif cmd == "DIR": # What is the main dir name?
                dirname = arg if arg else input("Enter folder name: ")
                start_time = time.time()
                view_dir(client, dirname)
                end_time = time.time()

                server_response_time_s = end_time - start_time

                # Example message to send data for network analysis
                # client.sendall(f"NETWORK_ANALYSIS@{server_response_time_s}")

            elif cmd == "SUBFOLDER":
                if not arg:
                    dirname = input("Enter folder name: ")
                    c_or_d = input(f"'{dirname}' (create/delete): ").strip().lower()
                
                else:
                    sub_parts = arg.split(" ", 1)
                    c_or_d = sub_parts[0].lower()
                    dirname = sub_parts[1] if len(sub_parts) > 1 else input("Enter folder name: ")

                start_time = time.time()
                subfolders(client, c_or_d, dirname)
                end_time = time.time()

                server_response_time_s = end_time - start_time

                # Example message to send data for network analysis
                # client.sendall(f"NETWORK_ANALYSIS@{server_response_time_s}") 

            else:
                client.sendall(f"cmd".encode(FORMAT))
                

    except socket.timeout:
        print("\n[Error] Connection timed out due to inactivity.")
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        print("\n[Error] Connection was reset or closed by the server.")
    except Exception as e:
        print(f"\n[Error] An unexpected error occurred: {e}")
    finally:
        # Connection Closed
        print("Disconnected from the server.")
        client.close() ## close the connection

if __name__ == "__main__":
    main()
