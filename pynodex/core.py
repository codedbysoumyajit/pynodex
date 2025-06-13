# pynodex/core.py

import os
import sys
import subprocess
import json
import time
import psutil
import click
import socket # For IPC with daemon
import shutil
import datetime # For log timestamping in daemon (conceptual, but good for completeness)

# --- Configuration (Shared with Daemon) ---
APP_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "pynodex")
PROCESS_DB_FILE = os.path.join(APP_DIR, 'processes.json') # Now managed by daemon primarily
LOG_DIR = os.path.join(APP_DIR, 'process_logs')
DAEMON_SOCK_FILE = os.path.join(APP_DIR, 'pynodex_daemon.sock') # Socket for IPC


# --- IPC Client Function ---

def send_command_to_daemon(command_type, args=None):
    """Sends a command to the Pynodex daemon via Unix Domain Socket."""
    if not os.path.exists(DAEMON_SOCK_FILE):
        click.echo(click.style("Error: Pynodex daemon is not running.", fg="red"), err=True)
        click.echo(click.style(f"Please start it first: pynodex_daemon_cli start", fg="yellow"), err=True)
        sys.exit(1)

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(DAEMON_SOCK_FILE)
        
        command_data = {"type": command_type, "args": args if args else {}}
        sock.sendall(json.dumps(command_data).encode('utf-8') + b'\n') # Newline delimiter

        response_data = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            if b'\n' in response_data:
                break

        response = json.loads(response_data.decode('utf-8').strip())
        sock.close()
        return response
    except FileNotFoundError:
        click.echo(click.style("Error: Unix socket not found. Is daemon running and accessible?", fg="red"), err=True)
        sys.exit(1)
    except ConnectionRefusedError:
        click.echo(click.style("Error: Connection to daemon refused. Is daemon active and listening?", fg="red"), err=True)
        sys.exit(1)
    except json.JSONDecodeError:
        click.echo(click.style(f"Error: Invalid JSON response from daemon: {response_data.decode('utf-8')}", fg="red"), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"Error communicating with daemon: {e}", fg="red"), err=True)
        sys.exit(1)


# --- Helper Functions (used by CLI for display/local ops) ---

def load_processes_client(): # Client only loads for local display, daemon manages authoritative state
    if os.path.exists(PROCESS_DB_FILE):
        with open(PROCESS_DB_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                click.echo(click.style(f"Warning: '{PROCESS_DB_FILE}' is empty or corrupted. Displaying empty process list.", fg="yellow"), err=True)
                return {}
    return {}

def get_process_info_client(pid): # Client directly queries psutil for real-time monitor/list
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
    pass


@cli.command()
@click.argument('name')
@click.argument('command', nargs=-1, required=True)
@click.option('--cwd', type=click.Path(exists=True, file_okay=False, dir_okay=True), help='Working directory for the process.')
@click.option('--env', multiple=True, help='Environment variables (KEY=VALUE). Can be specified multiple times.')
@click.option('--port', type=int, help='Port number the process is expected to use.')
@click.option('--log', type=click.Path(file_okay=True, dir_okay=False, writable=True), help='Specify a custom log file path (stdout & stderr combined).')
@click.option('--no-daemon', is_flag=True, help='Do not redirect application output to a log file; print to current console.')
@click.option('--watch', is_flag=True, help='[Daemon-Dependent] Watch application files for changes and automatically restart. (Requires a daemon for full functionality).')
@click.option('--max-memory-restart', type=str, help='[Daemon-Dependent] Set memory threshold for app reload (e.g., "200MB"). (Requires a daemon for full functionality).')
@click.option('--max-cpu-restart', type=float, help='[Daemon-Dependent] Set CPU threshold for app reload (e.g., "90" for 90% CPU usage). (Requires a daemon for full functionality).')
@click.option('--restart-delay', type=int, help='[Daemon-Dependent] Delay between automatic restarts in milliseconds.')
@click.option('--no-autorestart', is_flag=True, help='[Daemon-Dependent] Do not auto-restart the application on crash/exit. (Requires a daemon for full functionality).')
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
    args = {
        'name': name,
        'command': list(command), # Convert tuple to list for JSON serialization
        'cwd': cwd,
        'env': dict(item.split('=', 1) for item in env) if env else None,
        'port': port,
        'log': log,
        'no_daemon': no_daemon,
        'watch': watch,
        'max_memory_restart': max_memory_restart,
        'max_cpu_restart': max_cpu_restart,
        'restart_delay_ms': restart_delay,
        'no_autorestart': no_autorestart,
        'cron': cron,
        'time_prefix_logs': time
    }
    response = send_command_to_daemon("start", args)
    if response['status'] == 'success':
        click.echo(click.style(response['message'], fg="green"))
    else:
        click.echo(click.style(f"Error starting process: {response['message']}", fg="red"), err=True)

@cli.command()
@click.argument('name')
def stop(name):
    """Stops a managed process."""
    response = send_command_to_daemon("stop", {'name': name})
    if response['status'] == 'success':
        click.echo(click.style(response['message'], fg="green"))
    else:
        click.echo(click.style(f"Error stopping process: {response['message']}", fg="red"), err=True)

@cli.command(name='list')
def list_processes_cmd():
    """Lists all managed processes with their current status and resource usage."""
    response = send_command_to_daemon("list")
    if response['status'] == 'success':
        processes = response['data']
    else:
        click.echo(click.style(f"Error retrieving process list from daemon: {response['message']}", fg="red"), err=True)
        return

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
        cpu_percent = f"{info.get('cpu_percent', 'N/A'):.1f}" if info.get('cpu_percent') is not None else 'N/A'
        mem_percent = f"{info.get('memory_percent', 'N/A'):.1f}" if info.get('memory_percent') is not None else 'N/A'
        rss_mb = f"{info.get('memory_info_rss_mb', 'N/A'):.1f}" if info.get('memory_info_rss_mb') is not None else 'N/A'
        watch_status = 'Yes' if info.get('watch') else 'No'
        max_cpu_limit = f"{info.get('max_cpu_restart', 'N/A'):.0f}%" if info.get('max_cpu_restart') is not None else 'N/A'
        
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
    # Logs command still reads directly from file for efficiency and simplicity
    # (Daemon could also relay logs, but direct tail-f is more robust if daemon crashes)
    processes = load_processes_client() # Client loads its own local view for log paths
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
    # Monitor command still directly queries psutil for real-time local system stats
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

            # Get managed processes data from daemon for their status/PIDs
            response = send_command_to_daemon("list")
            if response['status'] == 'success':
                processes = response['data']
            else:
                click.echo(click.style(f"\nError retrieving managed process data from daemon: {response['message']}", fg="red"), err=True)
                processes = {} # Fallback to empty if daemon communication fails

            if processes:
                click.echo(click.style("\n--- Managed Processes ---", fg="bright_blue", bold=True))
                header_format = "{:<20} {:<10} {:<15} {:<8} {:<8} {:<10}"
                row_format = "{:<20} {:<10} {:<15} {:<8} {:<8} {:<10}"

                click.echo(click.style(header_format.format('NAME', 'PID', 'STATUS', 'CPU%', 'MEM%', 'RSS_MB'), fg="bright_blue", bold=True))
                click.echo(click.style("-" * 80, fg="bright_blue"))
                for name, info in processes.items():
                    pid = info.get('pid')
                    status = info.get('status', 'unknown')
                    cpu_percent = f"{info.get('cpu_percent', 'N/A'):.1f}" if info.get('cpu_percent') is not None else 'N/A'
                    mem_percent = f"{info.get('memory_percent', 'N/A'):.1f}" if info.get('memory_percent') is not None else 'N/A'
                    rss_mb = f"{info.get('memory_info_rss_mb', 'N/A'):.1f}" if info.get('memory_info_rss_mb') is not None else 'N/A'
                    
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
    response = send_command_to_daemon("save")
    if response['status'] == 'success':
        click.echo(click.style(response['message'], fg="green"))
    else:
        click.echo(click.style(f"Error saving state: {response['message']}", fg="red"), err=True)

@cli.command()
@click.argument('target', default='all', required=False)
def clear(target):
    """
    Stops and deletes specific managed process(es) and clears their logs.
    Usage: pynodex clear <appname> | pynodex clear all
    This action is irreversible.
    """
    confirm_message_prefix = "WARNING: This will "
    if target == 'all':
        confirm_message_action = "stop ALL Pynodex managed processes and delete their logs."
    else:
        confirm_message_action = f"stop process '{target}' and delete its logs."
    
    confirm_message = click.style(confirm_message_prefix + confirm_message_action + " This action is irreversible. Do you want to continue?", fg="red", bold=True)
    click.confirm(confirm_message, abort=True)

    response = send_command_to_daemon("clear", {'name': target})
    if response['status'] == 'success':
        click.echo(click.style(response['message'], fg="green"))
    else:
        click.echo(click.style(f"Error clearing process(es): {response['message']}", fg="red"), err=True)

@cli.command()
@click.argument('target', default='all', required=False)
def restart(target):
    """
    Restarts a specific managed process or all managed processes.
    This performs a stop then start sequence.
    Usage: pynodex restart <appname> | pynodex restart all
    """
    response = send_command_to_daemon("restart", {'name': target})
    if response['status'] == 'success':
        click.echo(click.style(response['message'], fg="green"))
    else:
        click.echo(click.style(f"Error restarting process(es): {response['message']}", fg="red"), err=True)

@cli.command()
@click.argument('target', default='all', required=False)
def reload(target):
    """
    Performs a 'hot' reload (sequential restart) of a specific managed process or all.
    This attempts to minimize downtime by starting the new process before stopping the old.
    However, true zero-downtime hot reloading requires a dedicated daemon with health checks
    and potentially cluster management, which is beyond this CLI's current capabilities.
    Usage: pynodex reload <appname> | pynodex reload all
    """
    response = send_command_to_daemon("reload", {'name': target})
    if response['status'] == 'success':
        click.echo(click.style(response['message'], fg="green"))
    else:
        click.echo(click.style(f"Error reloading process(es): {response['message']}", fg="red"), err=True)

if __name__ == "__main__":
    cli()
