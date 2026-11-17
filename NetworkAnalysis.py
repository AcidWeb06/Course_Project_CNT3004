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
        self.lock = threading.Lock()
        self.records = []
        if not os.path.exists(self.filename):
            with open(self.filename, 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["timestamp", "role", "action", "filename", "file_size_bytes", "transfer_time_seconds", "data_rate_bps", "system_reponse_time_milliseconds", "status"])
    
    def log(self, role, action, filename="", file_size_bytes=0, transfer_time_seconds=0, system_reponse_time_milliseconds=0, status="OK"):
        data_rate = 0.0
        if transfer_time_seconds > 0 and file_size_bytes > 0:
            data_rate = (file_size_bytes / (1024 * 1024)) / transfer_time_seconds

        row = [
               time.strftime("%Y-%m-%d %H:%M:%S"),
               role,
               action,
               filename,
               file_size_bytes,
               round(transfer_time_seconds, 4),
               round(data_rate, 4),
               round(system_reponse_time_milliseconds, 3),
               status
            ]
        with self.lock:
            self.records.append(row)
            with open(self.filename, 'a', newline='') as file:
                writer =csv.writer(file)
                writer.writerow(row)
            

def send_json(sock, data_dict):
    payload = json.dumps(data_dict).encode('utf-8')
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)

def recv_json(sock):
    raw_length = recv_exact(sock, 4)
    if not raw_length:
        return None
    msg_length = struct.unpack("!I", raw_length)[0]
    payload = recv_exact(sock, msg_length)
    if not payload:
        return None
    return json.loads(payload.decode('utf-8'))

def recv_exact(sock, num_bytes):
    buf = bytearray()
    while len(buf) < num_bytes:
        chunk = sock.recv(num_bytes - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)
