import psutil

import json

import os

import sys

import platform



def get_gpu_stats():

    """

    Attempts to retrieve GPU information via nvidia-smi.

    Returns 'N/A/N/A' if tools are missing or fail.

    """

    try:

        import subprocess

        gpu_info = subprocess.check_output(

            ["nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,nounits,noheader"], 

            encoding='utf-8'

        )

        free, total = gpu_info.strip().split(',')

        return f"{free.strip()}MB/{total.strip()}MB"

    except Exception:

        return "N/A/N/A"



def main():

    # System Name

    system_name = platform.node()



    # RAM Stats

    vm = psutil.virtual_memory()

    ram_free = f"{vm.available / (1024**3):.1f}GB"

    ram_max = f"{vm.total / (1024**3):.1f}GB"

    

    # CPU Stats

    # 'Free' CPU is calculated as (100 - usage percentage)

    cpu_usage = psutil.cpu_percent(interval=0.1)

import psutil
import json
import os
import sys
import platform

def get_gpu_stats():
    """
    Attempts to retrieve GPU information via nvidia-smi.
    Returns 'N/A/N/A' if tools are missing or fail.
    """
    try:
        import subprocess
        gpu_info = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,nounits,noheader"], 
            encoding='utf-8'
        )
        free, total = gpu_info.strip().split(',')
        return f"{free.strip()}MB/{total.strip()}MB"
    except Exception:
        return "N/A/N/A"

def main():
    # System Name
    system_name = platform.node()

    # RAM Stats
    vm = psutil.virtual_memory()
    ram_free = f"{vm.available / (1024**3):.1f}GB"
    ram_max = f"{vm.total / (1024**3):.1f}GB"
    
    # CPU Stats
    # 'Free' CPU is calculated as (100 - usage percentage)
    cpu_usage = psutil.cpu_percent(interval=0.1)
    cpu_free = f"{100 - cpu_usage:.1f}%"
    cpu_max = "100%"
    
    # GPU Stats
    gpu_string = get_gpu_stats()
    
    # OS Info
    os_info = f"{platform.system()} {platform.release()}"
    
    # Prompt Hint for AI
    if platform.system() == "Windows":
        path_hint = "Make sure to use Windows style paths (or forward slashes which Python accepts). Use PowerShell syntax for commands."
    else:
        path_hint = "Use Linux/Unix style paths and Bash syntax."

    # Format the updated output string
    result_string = f"[IMPORTANT: {path_hint}]\nSystem: {system_name}  OS: {os_info}  RAM: {ram_free}/{ram_max}  CPU: {cpu_free}/{cpu_max}  GPU: {gpu_string}"
    
    # Genesis Action protocol: Return Plain Text via stdout
    print(result_string)

if __name__ == "__main__":
    main()