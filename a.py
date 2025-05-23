import yaml
import os
import socket
import subprocess
import threading
import time
import json
from datetime import datetime
from netmiko import ConnectHandler
from netmiko.ssh_exception import NetMikoTimeoutException, NetMikoAuthenticationException
import paramiko
from termcolor import cprint

# Constants
NODES_FILE = "nodes.yaml"
LOG_FILE = "./dashboard/pi_cluster_log.jsonl"

COMMANDS = {
    "hostname": "hostname",
    "uptime": "uptime -p",
    "cpu_usage": "top -bn1 | grep '%Cpu' | awk '{print $2 + $4}'",
    "memory": "free -m | awk '/Mem:/ {print $2, $3}'",
    "disk": "df -h / | awk 'NR==2 {print $2, $3, $5}'",
    "ip_address": "hostname -I | awk '{print $1}'"
}

# Load nodes from YAML
def LOAD_NODES(file_path):
    if not os.path.exists(file_path):
        print(f"Error: Nodes file was not found at {file_path}")
        return []
    try:
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        return data.get("nodes", [])
    except yaml.YAMLError as e:
        print(f"YAML error in {file_path}: {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred while loading nodes: {e}")
        return []

# Live timer display with result
class TaskTimer:
    def __init__(self, label):
        self.label = label
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        print(f"[{self.label}] Running...", end='', flush=True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        elapsed = time.time() - self.start_time
        if exc_type is None:
            cprint(f" \u2705 {elapsed:.2f}s", "green")
        else:
            cprint(f" \u274C {elapsed:.2f}s", "red")

# Run SSH commands
def RUN_SSH_COMMANDS(node):
    with TaskTimer(node.get("HOST_NAME", "SSH Node")):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        stats = {"host": node.get("HOST_NAME", "unknown"), "timestamp": datetime.utcnow().isoformat() + "Z"}
        try:
            client.connect(node["HOST_NAME"], username=node["USER_NAME"], password=node["PASSWORD"])
            for cmd in node.get("COMMANDS", []):
                stdin, stdout, stderr = client.exec_command(cmd)
                stdout.channel.recv_exit_status()
            stats["status"] = "success"
        except Exception as e:
            stats["status"] = f"fail: {e}"
            raise
        finally:
            client.close()
        return stats

# Run Netmiko config

def RUN_NETMIKO_CONFIG(node):
    with TaskTimer(node.get("HOST_NAME", "Netmiko Node")):
        device = {
            'device_type': node.get("DEVICE_TYPE"),
            'host': node.get("HOST_NAME"),
            'username': node.get("USER_NAME"),
            'password': node.get("PASSWORD"),
        }
        stats = {"host": node.get("HOST_NAME", "unknown"), "timestamp": datetime.utcnow().isoformat() + "Z"}
        try:
            conn = ConnectHandler(**device)
            output = conn.send_config_set(node.get("CONFIG_COMMANDS", []))
            conn.save_config()
            conn.disconnect()
            stats["status"] = "success"
        except (NetMikoTimeoutException, NetMikoAuthenticationException, Exception) as e:
            stats["status"] = f"fail: {e}"
            raise
        return stats

# Run local commands
def RUN_LOCAL():
    with TaskTimer("Localhost"):
        stats = {"host": socket.gethostname(), "timestamp": datetime.utcnow().isoformat() + "Z"}
        for key, cmd in COMMANDS.items():
            try:
                output = subprocess.check_output(cmd, shell=True).decode().strip()
                stats[key] = output
            except Exception as e:
                stats[key] = f"Error: {e}"
        stats["status"] = "success"
        return stats

# Save log

def save_log(stats):
    with open(LOG_FILE, 'a') as f:
        f.write(json.dumps(stats) + '\n')

# Main

def main():
    nodes = LOAD_NODES(NODES_FILE)
    all_stats = []

    for node in nodes:
        try:
            if node.get("DEVICE_TYPE") == "local":
                stat = RUN_LOCAL()
            elif node.get("DEVICE_TYPE") == "ssh":
                stat = RUN_SSH_COMMANDS(node)
            else:
                stat = RUN_NETMIKO_CONFIG(node)
            save_log(stat)
            all_stats.append(stat)
        except Exception as e:
            cprint(f"Error processing {node.get('HOST_NAME')}: {e}", "red")

if __name__ == "__main__":
    main()

