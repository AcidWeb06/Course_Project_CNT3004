import socket
import struct
import json 
import time 
import csv 
import os
import threading

class networkStats:
    def __init__(self, filename):
        self.filename = filename
        self.lock = threading.Lock() #Used to prevent file corruption by having only one thread open at a time
        self.records = [] 
        if not os.path.exists(self.filename): #Checks to see if the network stats doesn't exists
            with open(self.filename, 'w', newline='') as file: #Opens a new file in 'write' mode with the alias 'file
                #Writes 'file' to a CSV file, and the names of each of the network statistics to be recorded
                writer = csv.writer(file) 
                writer.writerow(["timestamp", "source", "action", "filename", "file_size_bytes", "transfer_time_seconds", "data_rate_MB/s", "system_reponse_time_milliseconds", "status"])
    
    def log(self, source, action, filename="", file_size_bytes=0, transfer_time_seconds=0, system_reponse_time_milliseconds=0, status="OK"):
        data_rate = 0.0 #Intializes the data rate to 0.0
        if transfer_time_seconds > 0 and file_size_bytes > 0: #Checks if the transfer time of the file and the size of the file is greater than 0
            data_rate = (file_size_bytes / (1024 * 1024)) / transfer_time_seconds #Calculates the data rate of the file in megabytes per second (MB/s)
            
        #Stores the values of each of the network statistics for the current file into a dictionary called 'row'. 
        #'transfer_time_seconds', 'data_rate', and 'system_reponse_time_milliseconds' are rounded to 4 decimal places
        row = [
               time.strftime("%Y-%m-%d %H:%M:%S"),
               source,
               action,
               filename,
               file_size_bytes,
               round(transfer_time_seconds, 4),
               round(data_rate, 4),
               round(system_reponse_time_milliseconds, 3),
               status
            ]
        with self.lock:
            self.records.append(row) #Appends the row of values to the dictionary 'records'
            with open(self.filename, 'a', newline='') as file: #Opens up the file in append mode
                #Writes the file to a CSV and the row of values of the network stats for the current file into the CSV.
                writer =csv.writer(file)
                writer.writerow(row)
            

def send_json(sock, data_dict):
    payload = json.dumps(data_dict).encode('utf-8') #Serializes the dictionary into a JSON string and encodes it using UTF-8
    header = struct.pack("!I", len(payload)) #Converts the JSON string 'payload' into a 4-byte length unsigned integer header, done in network byte order
    sock.sendall(header + payload) #Sends the header and payload of the file into the socket using the sendall() function 

def recv_json(sock):
    raw_length = recv_exact(sock, 4) #Calls the recv_exact() function to retrieve the 4-byte length prefix, which is the header
    if not raw_length:
        return None
    msg_length = struct.unpack("!I", raw_length)[0] #Unpacks the prefix in order to retrieve the exact length of the TCP message
    payload = recv_exact(sock, msg_length) #Calls the recv_exact() function to retrieve the exact byte length of the JSON string
    if not payload: #The function returns None if the socket connection was disconnected before the 4-byte header was read by the function
        return None
    return json.loads(payload.decode('utf-8')) #Decodes the payload and parses it into a Python dictionary using json.loads()

def recv_exact(sock, num_bytes):
    buf = bytearray() #Creates a bytearray() object called buf
    while len(buf) < num_bytes: #Iterates as long as the length of the bytearray() buf is less than the number of bytes in the TCP header
        chunk = sock.recv(num_bytes - len(buf)) #Calculates the difference the number of bytes in the header and the length of 'buf'
        if not chunk: #Checks if the TCP chunk is an empty byte string
            return None
        buf.extend(chunk) #Adds chunk to the end of the bytearray() buf
    return bytes(buf) #Converts the bytearray() object buf into an immutable sequence of bytes
