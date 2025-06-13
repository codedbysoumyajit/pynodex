# pynodex/cli.py

import os
import sys
import subprocess
import json
import time
import psutil
import signal
import click
import shutil # For deleting log directory contents

# --- Configuration and Global Variables ---
APP_DIR = click.get_app_dir("pynodex")
PROCESS_DB_FILE = os.path.join(APP_DIR, 'processes.json')
LOG_DIR = os.path.join(APP_DIR, 'process_logs')

# Ensure the application directory and log directory exist
os.makedirs(APP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# --- Helper Functions ---

def load_processes():
    """Loads managed processes from the JSON database file."""
    if os.path.exists(PROCESS_DB_FILE):
        with open(PROCESS_DB_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                click.echo(click.style(f"Warning: '{PROCESS_DB_FILE}' is empty or corrupted. Starting with an empty process list.", fg="yellow"), err=True)
                return {}
    return {}

def save_processes(processes):
    """Saves managed processes to the JSON database file."""
    os.makedirs(os.path.dirname(PROCESS_DB_FILE), exist_ok=True)
    with open(PROCESS_DB_FILE, 'w') as f:
        json.dump(processes, f, indent=4)

def get_process_info(pid):
    """
    Retrieves detailed information for a given PID using psutil.
    Returns a dictionary or None if process not found.
    """
    try:
        process = psutil.Process(pid)
        return {
            'pid': process.pid,
            'name': process.name(),
            'status': process.status(),
            'cpu_percent': process.cpu_percent(interval=None),
            'memory_percent': process.memory_percent(),
            'memory_info_rss_mb': process.memory_info().rss / (1024 * 1024),
            'cmdline': " ".join(process.cmdline()),
            'create_time': time.ctime(process.create_time())
        }
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied:
        return {'pid': pid, 'status': 'Access Denied', 'name': 'N/A', 'cpu_percent': 0, 'memory_percent': 0, 'memory_info_rss_mb': 0, 'cmdline': 'N/A', 'create_time': 'N/A'}

# --- CLI Commands (using Click) ---

@click.group(
    help=f"""
{click.style('Pynodex: A Simple CLI Process Manager', fg='bright_green', bold=True)}

{click.style('Manage your applications with ease, similar to pm2.', fg='white')}

{click.style('\nCommon Flags Overview (for "start" command):', fg='bright_blue', bold=True)}
\b
  --watch                     {click.style('[Daemon-Dependent]', fg='yellow')} Automatically restart app when files change.
  --max-memory-restart <MB>   {click.style('[Daemon-Dependent]', fg='yellow')} Restart if app exceeds memory (e.g., "200MB").
  --max-cpu-restart <%>       {click.style('[Daemon-Dependent]', fg='yellow')} Restart if app exceeds CPU (e.g., "90").
  --log <path>                Specify a custom log file for stdout/stderr.
  --no-daemon                 Print app output directly to console, no log file.
  --port <num>                Track port usage for the application.
  --env KEY=VALUE             Set environment variables for the app.
  --cwd <path>                Set working directory for the app.

{click.style('\nQuick Usage Examples:', fg='bright_blue', bold=True)}
\b
  {click.style('pynodex start <name> "<command>" [options]', fg='cyan')}
    {click.style('Example:', fg='white')} pynodex start my-web-app "python -m http.server 8000" --port 8000
    {click.style('Example:', fg='white')} pynodex start my-node-app "node app.js" --watch --max-memory-restart 250MB
    {click.style('Example:', fg='white')} pynodex start my-task "bash -c 'echo Hello; sleep 5'" --no-daemon

  {click.style('pynodex list', fg='cyan')}
    View all managed processes and their status.

  {click.style('pynodex logs <appname>', fg='cyan')}
    Display real-time logs for a specific application.

  {click.style('pynodex monitor', fg='cyan')}
    Show real-time system and process resource usage.

  {click.style('pynodex stop <appname>', fg='cyan')}
    Stop a specific managed process.

  {click.style('pynodex restart <appname> | all', fg='cyan')}
    Restart a specific managed process or all.

  {click.style('pynodex reload <appname> | all', fg='cyan')}
    Sequentially restart for code changes (minimal downtime).

  {click.style('pynodex save', fg='cyan')}
    Persist the current state of processes to disk.

  {click.style('pynodex clear [appname | all]', fg='cyan')}
    Stop and delete specific processes or all processes and their logs.
    {click.style('Example:', fg='white')} pynodex clear my-old-app
    {click.style('Example:', fg='white')} pynodex clear all

{click.style('\nFor detailed help on any command, use:', fg='yellow', bold=True)}
\b
  {click.style('pynodex <command> --help', fg='white')}
"""
)
def cli():
    """A simple process manager CLI for Pynodex."""
    pass # This function remains empty, Click uses its docstring/help parameter


@cli.command()
@click.argument('name')
@click.argument('command', nargs=-1, required=True)
@click.option('--cwd', type=click.Path(exists=True, file_okay=False, dir_okay=True), help='Working directory for the process.')
@click.option('--env', multiple=True, help='Environment variables (KEY=VALUE). Can be specified multiple times.')
@click.option('--port', type=int, help='Port number the process is expected to use.')
@click.option('--log', type=click.Path(file_okay=True, dir_okay=False, writable=True), help='Specify a custom log file path (stdout & stderr combined).')
@click.option('--no-daemon', is_flag=True, help='Do not redirect application output to a log file; print to current console.')
@click.option('--watch', is_flag=True, help='[Conceptual/Daemon-Dependent] Watch application files for changes and automatically restart. (Requires a daemon for full functionality).')
@click.option('--max-memory-restart', type=str, help='[Conceptual/Daemon-Dependent] Set memory threshold for app reload (e.g., "200MB"). (Requires a daemon for full functionality).')
@click.option('--max-cpu-restart', type=float, help='[Conceptual/Daemon-Dependent] Set CPU threshold for app reload (e.g., "90" for 90% CPU usage). (Requires a daemon for full functionality).')
@click.option('--restart-delay', type=int, help='[Conceptual/Daemon-Dependent] Delay between automatic restarts in milliseconds.')
@click.option('--no-autorestart', is_flag=True, help='[Conceptual/Daemon-Dependent] Do not auto-restart the application on crash/exit. (Requires a daemon for full functionality).')
@click.option('--cron', type=str, help='[Conceptual/Daemon-Dependent] Specify a cron pattern for forced restarts (e.g., "0 0 * * *"). (Requires a daemon for full functionality).')
@click.option('--time', is_flag=True, help='[Conceptual/Daemon-Dependent] Prefix logs with time. (Requires a daemon to intercept and format output).')
def start(name, command, cwd, env, port, log, no_daemon, watch, max_memory_restart, max_cpu_restart, restart_delay, no_autorestart, cron, time):
    """
    Starts a new process and adds it to the managed list.
    Arguments after '--' are passed directly to the command.

    Examples for Popular Language Supports:
    \b
      Python:
        pynodex start my-py-app "python my_script.py" --port 8000
        pynodex start flask-api "gunicorn app:app -b 0.0.0.0:5000" --cwd /srv/flask-app --port 5000

      Node.js:
        pynodex start my-node-app "node app.js" --env NODE_ENV=production --watch
        pynodex start express-server "npm start" --cwd /var/www/express-app --port 3000

      Java:
        pynodex start my-java-app "java -jar myapp.jar" --cwd /opt/myapp --max-memory-restart 512MB
        pynodex start spring-boot "java -jar target/app.jar" --port 8080

      Go:
        pynodex start my-go-binary "./my-go-app" --log /var/log/go_app.log --max-cpu-restart 70
        pynodex start go-daemon "./daemon_service"

      General Shell/Bash:
        pynodex start my-console-app "bash -c 'while true; do echo \"Hello $(date)\"; sleep 1; done'" --no-daemon
        pynodex start processing-script "sh process_data.sh" --cwd /data --no-autorestart
    """
    processes = load_processes()

    if name in processes:
        click.echo(click.style(f"Error: Process '{name}' already exists. Please stop it first or choose a different name.", fg="red"), err=True)
        return

    full_command = " ".join(command)
    if not full_command:
        click.echo(click.style("Error: Command to execute cannot be empty.", fg="red"), err=True)
        return

    if port:
        if not 1024 <= port <= 65535:
            click.echo(click.style("Error: Port number must be between 1024 and 65535.", fg="red"), err=True)
            return
        for proc_name, proc_info in processes.items():
            if proc_info.get('port') == port:
                click.echo(click.style(f"Error: Port {port} is already in use by process '{proc_name}'.", fg="red"), err=True)
                return
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                s.close()
        except OSError:
            click.echo(click.style(f"Error: Port {port} is already in use by another application or is reserved.", fg="red"), err=True)
            return
        except ImportError:
            click.echo(click.style("Warning: 'socket' module not available. Cannot check port availability.", fg="yellow"), err=True)

    click.echo(click.style(f"Starting process '{name}' with command: '{full_command}'...", fg="cyan"))

    process_env = os.environ.copy()
    for env_pair in env:
        parts = env_pair.split('=', 1)
        if len(parts) == 2:
            process_env[parts[0]] = parts[1]
        else:
            click.echo(click.style(f"Warning: Invalid environment variable format '{env_pair}'. Skipping.", fg="yellow"), err=True)

    stdout_target = None
    stderr_target = None
    stdout_log_path = None
    stderr_log_path = None

    if no_daemon:
        stdout_target = sys.stdout
        stderr_target = sys.stderr
        click.echo(click.style("Output will be printed directly to this console (no log file).", fg="blue"))
    else:
        if log:
            log_file_path = os.path.abspath(log)
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
            stdout_target = open(log_file_path, 'a')
            stderr_target = subprocess.STDOUT
            stdout_log_path = log_file_path
            stderr_log_path = log_file_path
            click.echo(click.style(f"Application output redirected to '{stdout_log_path}'", fg="blue"))
        else:
            stdout_log_path = os.path.join(LOG_DIR, f'{name}_stdout.log')
            stderr_log_path = os.path.join(LOG_DIR, f'{name}_stderr.log')
            stdout_target = open(stdout_log_path, 'a')
            stderr_target = open(stderr_log_path, 'a')
            click.echo(click.style(f"Application output redirected to '{stdout_log_path}' and '{stderr_log_path}'", fg="blue"))

    try:
        process = subprocess.Popen(
            full_command,
            shell=True,
            cwd=cwd,
            env=process_env,
            stdout=stdout_target,
            stderr=stderr_target,
        )
        pid = process.pid

        if not no_daemon and stdout_target and stdout_target != sys.stdout:
            stdout_target.close()
        if not no_daemon and stderr_target and stderr_target != sys.stderr and stderr_target != subprocess.STDOUT:
            stderr_target.close()

        processes[name] = {
            'pid': pid,
            'command': full_command,
            'cwd': cwd,
            'env': dict(process_env) if process_env else None,
            'status': 'running',
            'start_time': time.time(),
            'port': port,
            'stdout_log': os.path.abspath(stdout_log_path) if stdout_log_path else 'N/A (console)',
            'stderr_log': os.path.abspath(stderr_log_path) if stderr_log_path else 'N/A (console)',
            'watch': watch,
            'max_memory_restart': max_memory_restart,
            'max_cpu_restart': max_cpu_restart,
            'restart_delay_ms': restart_delay,
            'no_autorestart': no_autorestart,
            'cron': cron,
            'time_prefix_logs': time
        }
        save_processes(processes)
        click.echo(click.style(f"Process '{name}' started successfully with PID: {pid}.", fg="green"))

    except FileNotFoundError:
        click.echo(click.style(f"Error: Command '{full_command.split()[0]}' not found. Make sure it's in your system's PATH.", fg="red"), err=True)
    except Exception as e:
        click.echo(click.style(f"An unexpected error occurred while starting process '{name}': {e}", fg="red"), err=True)

@cli.command()
@click.argument('name')
def stop(name):
    """Stops a managed process."""
    processes = load_processes()
    if name not in processes:
        click.echo(click.style(f"Error: Process '{name}' not found in Pynodex registry.", fg="red"), err=True)
        return

    pid = processes[name].get('pid')
    if pid:
        try:
            proc = psutil.Process(pid)
            click.echo(click.style(f"Stopping process '{name}' with PID: {pid}...", fg="cyan"))
            proc.terminate()
            proc.wait(timeout=5)
            click.echo(click.style(f"Process '{name}' (PID: {pid}) stopped.", fg="green"))
        except psutil.NoSuchProcess:
            click.echo(click.style(f"Process '{name}' (PID: {pid}) not found or already dead. Removing from Pynodex registry.", fg="yellow"), err=True)
        except psutil.AccessDenied:
            click.echo(click.style(f"Access denied: Cannot terminate process '{name}' (PID: {pid}). You might need higher privileges.", fg="red"), err=True)
        except psutil.TimeoutExpired:
            click.echo(click.style(f"Process '{name}' (PID: {pid}) did not terminate gracefully. Attempting to kill...", fg="yellow"), err=True)
            try:
                proc.kill()
                proc.wait(timeout=2)
                click.echo(click.style(f"Process '{name}' (PID: {pid}) killed.", fg="green"))
            except psutil.NoSuchProcess:
                click.echo(click.style(f"Process '{name}' (PID: {pid}) was already gone after kill attempt.", fg="yellow"), err=True)
            except Exception as e:
                click.echo(click.style(f"Error killing process '{name}' (PID: {pid}): {e}", fg="red"), err=True)
        except Exception as e:
            click.echo(click.style(f"An unexpected error occurred while stopping process '{name}': {e}", fg="red"), err=True)
    else:
        click.echo(click.style(f"No PID recorded for process '{name}'. Removing from Pynodex registry.", fg="yellow"), err=True)

    del processes[name]
    save_processes(processes)

@cli.command(name='list')
def list_processes_cmd():
    """Lists all managed processes with their current status and resource usage."""
    processes = load_processes()
    if not processes:
        click.echo(click.style("No processes currently managed by Pynodex.", fg="blue"))
        return

    click.echo(click.style("\n--- Pynodex Managed Processes ---", fg="bright_cyan", bold=True))
    header_format = "{:<20} {:<10} {:<15} {:<8} {:<8} {:<10} {:<8} {:<8} {:<9} {:<30}"
    row_format = "{:<20} {:<10} {:<15} {:<8} {:<8} {:<10} {:<8} {:<8} {:<9} {:<30.30}"

    click.echo(click.style(header_format.format('NAME', 'PID', 'STATUS', 'CPU%', 'MEM%', 'RSS_MB', 'PORT', 'WATCH', 'CPU_LMT', 'COMMAND'), fg="bright_blue", bold=True))
    click.echo(click.style("-" * 150, fg="bright_blue"))

    for name, info in processes.items():
        pid = info.get('pid')
        status = info.get('status', 'unknown')
        cpu_percent = 'N/A'
        mem_percent = 'N/A'
        rss_mb = 'N/A'
        watch_status = 'Yes' if info.get('watch') else 'No'
        max_cpu_limit = f"{info.get('max_cpu_restart', 'N/A'):.0f}%" if info.get('max_cpu_restart') is not None else 'N/A'

        if pid:
            proc_info = get_process_info(pid)
            if proc_info:
                status = proc_info['status']
                cpu_percent = f"{proc_info['cpu_percent']:.1f}"
                mem_percent = f"{proc_info['memory_percent']:.1f}"
                rss_mb = f"{proc_info['memory_info_rss_mb']:.1f}"
                if info['status'] != status:
                    info['status'] = status
            else:
                status = 'dead/not_found'
                if info['status'] != status:
                    info['status'] = status
                    save_processes(processes)
        else:
            status = 'no_pid'
            if info['status'] != status:
                info['status'] = status
                save_processes(processes)
        
        status_color = "green" if status == "running" else "red" if status in ("dead/not_found", "stopped", "no_pid") else "yellow"
        
        click.echo(row_format.format(
            click.style(name, bold=True),
            str(pid) if pid else click.style('N/A', fg="red"),
            click.style(status, fg=status_color),
            cpu_percent,
            mem_percent,
            rss_mb,
            str(info.get('port', 'N/A')),
            watch_status,
            max_cpu_limit,
            info.get('command', 'N/A')
        ))

@cli.command()
@click.argument('name')
def logs(name):
    """
    Displays real-time logs for a specified application (like tail -f).
    """
    processes = load_processes()
    if name not in processes:
        click.echo(click.style(f"Error: Process '{name}' not found in Pynodex registry.", fg="red"), err=True)
        return

    app_info = processes[name]
    log_file_path = app_info.get('stdout_log')

    if log_file_path == 'N/A (console)':
        click.echo(click.style(f"Process '{name}' was started with '--no-daemon'. Its logs are printed directly to the console where it was started, not to a file.", fg="yellow"), err=True)
        return

    if not log_file_path or not os.path.exists(log_file_path):
        click.echo(click.style(f"Error: Log file not found for process '{name}'. Path: '{log_file_path}'", fg="red"), err=True)
        click.echo(click.style("Ensure the process was started correctly and has generated logs.", fg="red"), err=True)
        return

    click.echo(click.style(f"\n--- Displaying real-time logs for '{name}' (Press Ctrl+C to exit) ---", fg="bright_cyan", bold=True))
    click.echo(click.style(f"Log file: {log_file_path}", fg="blue"))

    try:
        with open(log_file_path, 'r') as f:
            f.seek(0, os.SEEK_END)

            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                click.echo(line.strip())

    except FileNotFoundError:
        click.echo(click.style(f"Error: Log file '{log_file_path}' disappeared.", fg="red"), err=True)
    except PermissionError:
        click.echo(click.style(f"Error: Permission denied to read log file '{log_file_path}'.", fg="red"), err=True)
    except Exception as e:
        click.echo(click.style(f"An unexpected error occurred while reading logs: {e}", fg="red"), err=True)
    except KeyboardInterrupt:
        click.echo(click.style("\nExiting log viewer.", fg="blue"))

@cli.command()
def monitor():
    """Displays real-time system hardware info and usage."""
    click.echo(click.style("--- Pynodex System Monitor (Press Ctrl+C to exit) ---", fg="bright_magenta", bold=True))
    try:
        while True:
            click.clear()

            click.echo(click.style("\n--- System Overview ---", fg="bright_blue", bold=True))
            cpu_usage = psutil.cpu_percent(interval=0.1)
            cpu_color = "green" if cpu_usage < 70 else "yellow" if cpu_usage < 90 else "red"
            click.echo(f"CPU Usage: {click.style(f'{cpu_usage}%', fg=cpu_color)}")
            
            mem = psutil.virtual_memory()
            mem_color = "green" if mem.percent < 70 else "yellow" if mem.percent < 90 else "red"
            click.echo(f"Memory Usage: {click.style(f'{mem.percent}%', fg=mem_color)} ({mem.used / (1024**3):.2f}GB / {mem.total / (1024**3):.2f}GB)")
            
            disk = psutil.disk_usage('/')
            disk_color = "green" if disk.percent < 70 else "yellow" if disk.percent < 90 else "red"
            click.echo(f"Disk Usage: {click.style(f'{disk.percent}%', fg=disk_color)} ({disk.used / (1024**3):.2f}GB / {disk.total / (1024**3):.2f}GB)")
            
            net = psutil.net_io_counters()
            click.echo(f"Network (Sent/Recv): {net.bytes_sent / (1024**2):.2f}MB / {net.bytes_recv / (1024**2):.2f}MB")
            click.echo(f"Boot Time: {click.style(time.ctime(psutil.boot_time()), fg='blue')}")
            click.echo(f"System Time: {click.style(time.ctime(), fg='blue')}")

            processes = load_processes()
            if processes:
                click.echo(click.style("\n--- Managed Processes ---", fg="bright_blue", bold=True))
                header_format = "{:<20} {:<10} {:<15} {:<8} {:<8} {:<10}"
                row_format = "{:<20} {:<10} {:<15} {:<8} {:<8} {:<10}"

                click.echo(click.style(header_format.format('NAME', 'PID', 'STATUS', 'CPU%', 'MEM%', 'RSS_MB'), fg="bright_blue", bold=True))
                click.echo(click.style("-" * 80, fg="bright_blue"))
                for name, info in processes.items():
                    pid = info.get('pid')
                    status = info.get('status', 'unknown')
                    cpu_percent = 'N/A'
                    mem_percent = 'N/A'
                    rss_mb = 'N/A'

                    if pid:
                        proc_info = get_process_info(pid)
                        if proc_info:
                            status = proc_info['status']
                            cpu_percent = f"{proc_info['cpu_percent']:.1f}"
                            mem_percent = f"{proc_info['memory_percent']:.1f}"
                            rss_mb = f"{proc_info['memory_info_rss_mb']:.1f}"
                            info['status'] = status
                        else:
                            status = 'dead/not_found'
                            if info['status'] != status:
                                info['status'] = status
                                save_processes(processes)
                    else:
                        status = 'no_pid'
                        if info['status'] != status:
                            info['status'] = status
                            save_processes(processes)
                    
                    status_color = "green" if status == "running" else "red" if status in ("dead/not_found", "stopped", "no_pid") else "yellow"

                    click.echo(row_format.format(
                        click.style(name, bold=True),
                        str(pid) if pid else click.style('N/A', fg="red"),
                        click.style(status, fg=status_color),
                        cpu_percent,
                        mem_percent,
                        rss_mb
                    ))
            else:
                click.echo(click.style("\nNo managed processes to display.", fg="blue"))

            time.sleep(1)
    except KeyboardInterrupt:
        click.echo(click.style("\nExiting Pynodex system monitor.", fg="blue"))
    except Exception as e:
        click.echo(click.style(f"An unexpected error occurred during monitoring: {e}", fg="red"), err=True)

@cli.command()
def save():
    """
    Saves the current state (metadata and live status) of all managed processes to disk.
    This ensures Pynodex's registry is up-to-date with actual process statuses.
    """
    processes = load_processes()
    if not processes:
        click.echo(click.style("No processes to save.", fg="blue"))
        return

    click.echo(click.style("Saving current state of managed processes...", fg="cyan"))
    updated_count = 0
    for name, info in list(processes.items()):
        pid = info.get('pid')
        
        if pid:
            proc_info = get_process_info(pid)
            if proc_info:
                if info['status'] != proc_info['status']:
                    info['status'] = proc_info['status']
                    updated_count += 1
            else:
                if info['status'] != 'dead/not_found':
                    info['status'] = 'dead/not_found'
                    updated_count += 1
        else:
            if info['status'] != 'no_pid':
                info['status'] = 'no_pid'
                updated_count += 1

    save_processes(processes)
    click.echo(click.style(f"Pynodex registry saved. {updated_count} processes had their status updated.", fg="green"))

@cli.command()
@click.argument('target', default='all', required=False)
def clear(target):
    """
    Stops and deletes specific managed process(es) and clears their logs.
    Usage: pynodex clear <appname> | pynodex clear all
    This action is irreversible.
    """
    processes = load_processes()
    if not processes and target != 'all':
        click.echo(click.style("No processes currently managed by Pynodex to clear.", fg="blue"), err=True)
        return

    if target == 'all':
        confirm_message = click.style("WARNING: This will stop ALL Pynodex managed processes and delete their logs. This action is irreversible. Do you want to continue?", fg="red", bold=True)
        
        click.confirm(confirm_message, abort=True)
        
        click.echo(click.style("Stopping all Pynodex managed processes...", fg="cyan"))
        
        logs_to_delete = set()
        for name, info in processes.items():
            if info.get('stdout_log') and info['stdout_log'] != 'N/A (console)':
                logs_to_delete.add(info['stdout_log'])
            if info.get('stderr_log') and info['stderr_log'] != 'N/A (console)' and info.get('stderr_log') != info.get('stdout_log'):
                logs_to_delete.add(info['stderr_log'])

        stopped_count = 0
        failed_to_stop_count = 0
        with click.progressbar(length=len(processes), label="Stopping processes") as bar:
            for name in list(processes.keys()):
                click.echo(f"Attempting to stop '{name}'...", nl=False)
                try:
                    stop_process(name) # This function already removes from registry and saves
                    stopped_count += 1
                    click.echo(click.style(" Done.", fg="green"))
                except Exception as e:
                    failed_to_stop_count += 1
                    click.echo(click.style(f" Failed: {e}", fg="red"), err=True)
                bar.update(1)

        save_processes({}) 
        click.echo(click.style("Pynodex registry cleared.", fg="green"))

        click.echo(click.style("Deleting all application log files...", fg="cyan"))
        deleted_log_count = 0
        with click.progressbar(length=len(logs_to_delete), label="Deleting logs") as bar:
            for log_path in logs_to_delete:
                try:
                    if os.path.exists(log_path):
                        os.remove(log_path)
                        deleted_log_count += 1
                except Exception as e:
                    click.echo(click.style(f"Error deleting log file '{log_path}': {e}", fg="red"), err=True)
                bar.update(1)
        
        try:
            if os.path.exists(LOG_DIR):
                shutil.rmtree(LOG_DIR)
            os.makedirs(LOG_DIR, exist_ok=True)
            click.echo(click.style(f"All logs in '{LOG_DIR}' cleaned up.", fg="green"))
        except Exception as e:
            click.echo(click.style(f"Error cleaning up log directory '{LOG_DIR}': {e}", fg="red"), err=True)


        click.echo(click.style(f"\n--- Pynodex Clear Summary ---", fg="bright_cyan", bold=True))
        click.echo(click.style(f"Stopped {stopped_count} processes.", fg="green"))
        if failed_to_stop_count > 0:
            click.echo(click.style(f"Failed to stop {failed_to_stop_count} processes.", fg="yellow"), err=True)
        click.echo(click.style(f"Deleted {deleted_log_count} log files.", fg="green"))
        click.echo(click.style("Pynodex is now in a clean state.", fg="green", bold=True))

    else: # Clearing a specific app
        app_name = target
        if app_name not in processes:
            click.echo(click.style(f"Error: Process '{app_name}' not found in Pynodex registry. Cannot clear.", fg="red"), err=True)
            return

        confirm_message = click.style(f"WARNING: This will stop process '{app_name}' and delete its logs. This action is irreversible. Do you want to continue?", fg="red", bold=True)
        click.confirm(confirm_message, abort=True)

        app_info = processes[app_name]
        log_paths_to_delete = set()
        if app_info.get('stdout_log') and app_info['stdout_log'] != 'N/A (console)':
            log_paths_to_delete.add(app_info['stdout_log'])
        if app_info.get('stderr_log') and app_info['stderr_log'] != 'N/A (console)' and app_info.get('stderr_log') != app_info.get('stdout_log'):
            log_paths_to_delete.add(app_info['stderr_log'])

        click.echo(click.style(f"Attempting to stop and clear process '{app_name}'...", fg="cyan"))
        try:
            stop_process(app_name)
            click.echo(click.style(f"Process '{app_name}' stopped and removed from registry.", fg="green"))
        except Exception as e:
            click.echo(click.style(f"Error stopping '{app_name}': {e}", fg="red"), err=True)

        click.echo(click.style(f"Deleting logs for '{app_name}'...", fg="cyan"))
        deleted_log_count = 0
        for log_path in log_paths_to_delete:
            try:
                if os.path.exists(log_path):
                    os.remove(log_path)
                    click.echo(click.style(f"Deleted: {log_path}", fg="green"))
                    deleted_log_count += 1
            except Exception as e:
                click.echo(click.style(f"Error deleting log file '{log_path}': {e}", fg="red"), err=True)
        
        click.echo(click.style(f"Process '{app_name}' and its logs have been cleared. Deleted {deleted_log_count} log files.", fg="green", bold=True))

@cli.command()
@click.argument('target', default='all', required=False)
def restart(target):
    """
    Restarts a specific managed process or all managed processes.
    This performs a stop then start sequence.
    Usage: pynodex restart <appname> | pynodex restart all
    """
    processes = load_processes()
    if not processes and target != 'all':
        click.echo(click.style("No processes currently managed by Pynodex to restart.", fg="blue"), err=True)
        return

    process_names = [target] if target != 'all' else list(processes.keys())
    if not process_names:
        click.echo(click.style("No processes found to restart.", fg="blue"))
        return

    click.echo(click.style(f"Initiating restart for {target} process(es)...", fg="cyan"))
    
    restarted_count = 0
    for name in process_names:
        if name not in processes:
            click.echo(click.style(f"Warning: Process '{name}' not found. Skipping restart.", fg="yellow"), err=True)
            continue
        
        app_info = processes[name] # Get original info before stop_process modifies it

        click.echo(click.style(f"\n--- Restarting '{name}' ---", fg="bright_blue", bold=True))
        
        # 1. Stop the process
        pid_before_stop = app_info.get('pid')
        if pid_before_stop:
            try:
                proc = psutil.Process(pid_before_stop)
                click.echo(click.style(f"Stopping '{name}' (PID: {pid_before_stop})...", fg="cyan"))
                proc.terminate()
                proc.wait(timeout=5)
                click.echo(click.style(f"'{name}' stopped.", fg="green"))
            except psutil.NoSuchProcess:
                click.echo(click.style(f"'{name}' (PID: {pid_before_stop}) already dead.", fg="yellow"))
            except Exception as e:
                click.echo(click.style(f"Error stopping '{name}': {e}", fg="red"), err=True)
                continue # Skip start if stop failed significantly
        else:
            click.echo(click.style(f"No active PID for '{name}' to stop. Attempting to start anew.", fg="yellow"))

        # Re-load processes after stop, as stop_process removed it from registry
        processes_after_stop = load_processes()
        if name in processes_after_stop: # This should not happen if stop_process worked
            del processes_after_stop[name]
            save_processes(processes_after_stop)

        # 2. Start the process using its original parameters
        try:
            # We need to re-call start_process with all original arguments
            # This is a bit awkward as start_process has many arguments.
            # A refactor would make start_process accept a dict of params.
            # For now, manually extract and pass:
            click.echo(click.style(f"Starting '{name}'...", fg="cyan"))
            _start_process_internal(
                name=name,
                command=app_info['command'].split(), # Split command string back into list
                cwd=app_info.get('cwd'),
                env=app_info.get('env'),
                port=app_info.get('port'),
                log=app_info.get('stdout_log') if app_info.get('stdout_log') != 'N/A (console)' else None, # Pass log path or None
                no_daemon=(app_info.get('stdout_log') == 'N/A (console)'),
                watch=app_info.get('watch', False),
                max_memory_restart=app_info.get('max_memory_restart'),
                max_cpu_restart=app_info.get('max_cpu_restart'),
                restart_delay=app_info.get('restart_delay_ms'),
                no_autorestart=app_info.get('no_autorestart', False),
                cron=app_info.get('cron'),
                time_prefix_logs=app_info.get('time_prefix_logs', False)
            )
            restarted_count += 1
            click.echo(click.style(f"'{name}' restarted successfully.", fg="green"))
        except Exception as e:
            click.echo(click.style(f"Error starting '{name}': {e}", fg="red"), err=True)
    
    click.echo(click.style(f"\nRestart process completed. Successfully restarted {restarted_count} process(es).", fg="bright_green", bold=True))

# Internal helper to abstract start_process logic for reuse in restart/reload
def _start_process_internal(name, command, cwd, env, port, log, no_daemon, watch, max_memory_restart, max_cpu_restart, restart_delay, no_autorestart, cron, time_prefix_logs):
    """Internal function to encapsulate the core process starting logic."""
    processes = load_processes() # Re-load to ensure latest registry state for checks

    # This internal function assumes 'name' is not already in processes or is about to be replaced.
    # We skip the 'name in processes' check here to allow re-registration during restart/reload.

    full_command = " ".join(command)
    
    # Port checking logic as in original start command
    if port:
        for proc_name, proc_info in processes.items():
            # Skip checking against itself if it's currently being restarted/reloaded
            if proc_name == name and proc_info.get('status') == 'running':
                continue # Don't check port if old process is still running and we're just about to replace it
            if proc_info.get('port') == port:
                raise ValueError(f"Port {port} already in use by process '{proc_name}'.")
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                s.close()
        except OSError:
            raise ValueError(f"Port {port} is already in use by another application or is reserved.")
    
    process_env = os.environ.copy()
    if env: # 'env' comes as a dict from saved info, so handle differently
        process_env.update(env) # Update with saved environment variables
    
    stdout_target = None
    stderr_target = None
    stdout_log_path = None
    stderr_log_path = None

    if no_daemon:
        stdout_target = sys.stdout
        stderr_target = sys.stderr
        stdout_log_path = 'N/A (console)'
        stderr_log_path = 'N/A (console)'
    else:
        if log: # 'log' comes as path string
            log_file_path = os.path.abspath(log)
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
            stdout_target = open(log_file_path, 'a')
            stderr_target = subprocess.STDOUT
            stdout_log_path = log_file_path
            stderr_log_path = log_file_path
        else: # Default logging path
            stdout_log_path = os.path.join(LOG_DIR, f'{name}_stdout.log')
            stderr_log_path = os.path.join(LOG_DIR, f'{name}_stderr.log')
            stdout_target = open(stdout_log_path, 'a')
            stderr_target = open(stderr_log_path, 'a')

    try:
        process = subprocess.Popen(
            full_command,
            shell=True,
            cwd=cwd,
            env=process_env,
            stdout=stdout_target,
            stderr=stderr_target,
        )
        pid = process.pid

        if not no_daemon and stdout_target and stdout_target != sys.stdout:
            stdout_target.close()
        if not no_daemon and stderr_target and stderr_target != sys.stderr and stderr_target != subprocess.STDOUT:
            stderr_target.close()
        
        # Update/Add process info
        processes[name] = {
            'pid': pid,
            'command': full_command,
            'cwd': cwd,
            'env': env, # Store original env dict
            'status': 'running',
            'start_time': time.time(),
            'port': port,
            'stdout_log': os.path.abspath(stdout_log_path),
            'stderr_log': os.path.abspath(stderr_log_path),
            'watch': watch,
            'max_memory_restart': max_memory_restart,
            'max_cpu_restart': max_cpu_restart,
            'restart_delay_ms': restart_delay,
            'no_autorestart': no_autorestart,
            'cron': cron,
            'time_prefix_logs': time_prefix_logs
        }
        save_processes(processes)
        return True
    except Exception as e:
        # Don't print click.echo here to allow caller to handle output
        raise e

@cli.command()
@click.argument('target', default='all', required=False)
def reload(target):
    """
    Performs a 'hot' reload (sequential restart) of a specific managed process or all.
    This attempts to minimize downtime by stopping the old process only after
    a new one has attempted to start. However, true zero-downtime hot reloading
    requires a dedicated daemon with health checks and potentially cluster management,
    which is beyond this CLI's current capabilities.
    Usage: pynodex reload <appname> | pynodex reload all
    """
    processes = load_processes()
    if not processes and target != 'all':
        click.echo(click.style("No processes currently managed by Pynodex to reload.", fg="blue"), err=True)
        return

    process_names = [target] if target != 'all' else list(processes.keys())
    if not process_names:
        click.echo(click.style("No processes found to reload.", fg="blue"))
        return

    click.echo(click.style(f"Initiating reload for {target} process(es) (sequential restart)...", fg="cyan"))
    
    reloaded_count = 0
    for name in process_names:
        if name not in processes:
            click.echo(click.style(f"Warning: Process '{name}' not found. Skipping reload.", fg="yellow"), err=True)
            continue
        
        app_info = processes[name] # Get original info before potential stop/start

        click.echo(click.style(f"\n--- Reloading '{name}' ---", fg="bright_blue", bold=True))
        
        old_pid = app_info.get('pid')

        # 1. Attempt to start the new process first
        try:
            click.echo(click.style(f"Attempting to start new instance of '{name}'...", fg="cyan"))
            _start_process_internal( # Use internal function
                name=name,
                command=app_info['command'].split(),
                cwd=app_info.get('cwd'),
                env=app_info.get('env'),
                port=app_info.get('port'),
                log=app_info.get('stdout_log') if app_info.get('stdout_log') != 'N/A (console)' else None,
                no_daemon=(app_info.get('stdout_log') == 'N/A (console)'),
                watch=app_info.get('watch', False),
                max_memory_restart=app_info.get('max_memory_restart'),
                max_cpu_restart=app_info.get('max_cpu_restart'),
                restart_delay=app_info.get('restart_delay_ms'),
                no_autorestart=app_info.get('no_autorestart', False),
                cron=app_info.get('cron'),
                time_prefix_logs=app_info.get('time_prefix_logs', False)
            )
            click.echo(click.style(f"New instance of '{name}' started (PID: {processes[name]['pid']}).", fg="green"))

            # 2. If new instance started successfully, then stop the old one
            if old_pid and psutil.pid_exists(old_pid):
                try:
                    old_proc = psutil.Process(old_pid)
                    click.echo(click.style(f"Stopping old instance of '{name}' (PID: {old_pid})...", fg="cyan"))
                    old_proc.terminate()
                    old_proc.wait(timeout=5)
                    click.echo(click.style(f"Old instance of '{name}' stopped.", fg="green"))
                except psutil.NoSuchProcess:
                    click.echo(click.style(f"Old instance of '{name}' (PID: {old_pid}) was already gone.", fg="yellow"))
                except Exception as e:
                    click.echo(click.style(f"Error stopping old instance of '{name}' (PID: {old_pid}): {e}", fg="red"), err=True)
            else:
                click.echo(click.style(f"No old instance of '{name}' (PID: {old_pid}) found to stop.", fg="yellow"))

            reloaded_count += 1

        except ValueError as ve: # Catch port conflicts specifically from internal start
            click.echo(click.style(f"Error reloading '{name}': {ve}. This might happen if the old process is still holding the port.", fg="red"), err=True)
            # If start fails due to port, then we must stop the old one and retry
            if old_pid and psutil.pid_exists(old_pid):
                click.echo(click.style(f"Attempting to stop old instance of '{name}' (PID: {old_pid}) and retry start...", fg="yellow"))
                try:
                    old_proc = psutil.Process(old_pid)
                    old_proc.terminate()
                    old_proc.wait(timeout=5)
                    click.echo(click.style(f"Old instance of '{name}' stopped. Retrying start...", fg="green"))
                    _start_process_internal( # Retry start
                        name=name,
                        command=app_info['command'].split(),
                        cwd=app_info.get('cwd'),
                        env=app_info.get('env'),
                        port=app_info.get('port'),
                        log=app_info.get('stdout_log') if app_info.get('stdout_log') != 'N/A (console)' else None,
                        no_daemon=(app_info.get('stdout_log') == 'N/A (console)'),
                        watch=app_info.get('watch', False),
                        max_memory_restart=app_info.get('max_memory_restart'),
                        max_cpu_restart=app_info.get('max_cpu_restart'),
                        restart_delay=app_info.get('restart_delay_ms'),
                        no_autorestart=app_info.get('no_autorestart', False),
                        cron=app_info.get('cron'),
                        time_prefix_logs=app_info.get('time_prefix_logs', False)
                    )
                    reloaded_count += 1
                    click.echo(click.style(f"'{name}' restarted successfully after retry.", fg="green"))
                except Exception as e_retry:
                    click.echo(click.style(f"Error restarting '{name}' even after retry: {e_retry}", fg="red"), err=True)
            else:
                click.echo(click.style(f"Cannot reload '{name}'. Old instance not found or port conflict persistent.", fg="red"), err=True)
        except Exception as e:
            click.echo(click.style(f"Error reloading '{name}': {e}", fg="red"), err=True)

    click.echo(click.style(f"\nReload process completed. Successfully reloaded {reloaded_count} process(es).", fg="bright_green", bold=True))


if __name__ == "__main__":
    cli()
