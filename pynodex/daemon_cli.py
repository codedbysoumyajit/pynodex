# pynodex/daemon_cli.py (previously pynodex_daemon_cli.py)

import os
import sys
import click
from daemonize import Daemonize
import subprocess
import psutil # Ensure psutil is imported for pid_exists
import signal # Ensure signal is imported for os.kill

# Corrected import paths
from pynodex.daemon import start_daemon_process, DAEMON_PID_FILE, DAEMON_LOG_FILE, DAEMON_SOCK_FILE, APP_DIR

@click.group()
def daemon_cli():
    """Manages the Pynodex background daemon."""
    pass

@daemon_cli.command()
def start():
    """Starts the Pynodex daemon in the background."""
    if os.path.exists(DAEMON_PID_FILE):
        try:
            with open(DAEMON_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                click.echo(click.style(f"Error: Pynodex daemon is already running with PID {pid}.", fg="red"), err=True)
                sys.exit(1)
            else:
                click.echo(click.style(f"Warning: Old PID file found ({DAEMON_PID_FILE}) but no running process. Cleaning up.", fg="yellow"))
                os.remove(DAEMON_PID_FILE)
        except Exception as e:
            click.echo(click.style(f"Warning: Could not read or verify PID file: {e}", fg="yellow"), err=True)

    click.echo(click.style("Starting Pynodex daemon...", fg="cyan"))

    # Daemonize the process
    daemon = Daemonize(app="pynodex_daemon", pid=DAEMON_PID_FILE, action=start_daemon_process,
                        logger=DAEMON_LOG_FILE, chdir=APP_DIR)
    
    try:
        daemon.start()
        # Note: os.getpid() here will return the PID of the *cli process* not the daemon itself,
        # as daemonize library forks. The actual daemon PID is written to DAEMON_PID_FILE.
        # So we should inform the user to check the PID file or status.
        click.echo(click.style(f"Pynodex daemon initiated. Check its status with 'pynodex_daemon_cli status'.", fg="green"))
        click.echo(click.style(f"Daemon log file: {DAEMON_LOG_FILE}", fg="blue"))
    except Exception as e:
        click.echo(click.style(f"Error starting daemon: {e}", fg="red"), err=True)
        sys.exit(1)

@daemon_cli.command()
def stop():
    """Stops the Pynodex daemon."""
    if not os.path.exists(DAEMON_PID_FILE):
        click.echo(click.style("Error: Pynodex daemon PID file not found. Is it running?", fg="red"), err=True)
        sys.exit(1)

    try:
        with open(DAEMON_PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        if not psutil.pid_exists(pid):
            click.echo(click.style(f"Warning: Daemon PID {pid} found in file but process not running. Cleaning up PID file.", fg="yellow"))
            os.remove(DAEMON_PID_FILE)
            if os.path.exists(DAEMON_SOCK_FILE):
                os.remove(DAEMON_SOCK_FILE)
            sys.exit(0)

        click.echo(click.style(f"Stopping Pynodex daemon (PID: {pid})...", fg="cyan"))
        
        os.kill(pid, signal.SIGTERM)
        
        max_wait = 10 # seconds
        for _ in range(max_wait):
            if not psutil.pid_exists(pid):
                click.echo(click.style("Pynodex daemon stopped successfully.", fg="green"))
                if os.path.exists(DAEMON_PID_FILE):
                    os.remove(DAEMON_PID_FILE)
                if os.path.exists(DAEMON_SOCK_FILE):
                    os.remove(DAEMON_SOCK_FILE)
                sys.exit(0)
            time.sleep(1)
        
        click.echo(click.style(f"Error: Daemon (PID {pid}) did not stop gracefully after {max_wait} seconds. You may need to kill it manually.", fg="red"), err=True)
        sys.exit(1)

    except FileNotFoundError:
        click.echo(click.style("Error: PID file not found, daemon might not be running or already stopped.", fg="red"), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"Error stopping daemon: {e}", fg="red"), err=True)
        sys.exit(1)

@daemon_cli.command()
def status():
    """Checks the status of the Pynodex daemon."""
    if os.path.exists(DAEMON_PID_FILE):
        try:
            with open(DAEMON_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                click.echo(click.style(f"Pynodex daemon is RUNNING with PID: {pid}", fg="green"))
                click.echo(click.style(f"Daemon log: {DAEMON_LOG_FILE}", fg="blue"))
                click.echo(click.style(f"IPC Socket: {DAEMON_SOCK_FILE}", fg="blue"))
            else:
                click.echo(click.style(f"Pynodex daemon is NOT RUNNING (PID file found: {pid}, but process does not exist). Consider 'pynodex_daemon_cli stop' to clean up.", fg="yellow"))
        except Exception as e:
            click.echo(click.style(f"Pynodex daemon status UNKNOWN (Error reading PID file: {e})", fg="yellow"))
    else:
        click.echo(click.style("Pynodex daemon is NOT RUNNING (PID file not found).", fg="red"))


if __name__ == "__main__":
    daemon_cli()
