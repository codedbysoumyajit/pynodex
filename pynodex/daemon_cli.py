# pynodex/daemon_cli.py

import os
import sys
import click
from daemonize import Daemonize # Keep this import, but we'll bypass its usage for debugging
import subprocess
import psutil # For pid_exists
import signal # For os.kill
import time # For sleep in stop command

# Ensure this import path is correct
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
                # Clean up stale PID file if process doesn't exist
                click.echo(click.style(f"Warning: Old PID file found ({DAEMON_PID_FILE}) but no running process. Cleaning up.", fg="yellow"))
                os.remove(DAEMON_PID_FILE)
                # Also clean up stale socket file if it exists
                if os.path.exists(DAEMON_SOCK_FILE):
                    try:
                        os.remove(DAEMON_SOCK_FILE)
                    except OSError as e:
                        click.echo(click.style(f"Warning: Could not remove old socket file {DAEMON_SOCK_FILE}: {e}", fg="yellow"), err=True)

        except Exception as e:
            click.echo(click.style(f"Warning: Could not read or verify PID file: {e}", fg="yellow"), err=True)
            # Try to start anyway if pid_exists check failed

    # Ensure the APP_DIR exists and has correct permissions before starting daemon/logging
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        os.chmod(APP_DIR, 0o755) # Set sensible permissions
    except Exception as e:
        click.echo(click.style(f"CRITICAL ERROR: Could not create or set permissions for application directory '{APP_DIR}': {e}", fg="red", bold=True), err=True)
        sys.exit(1)


    click.echo(click.style("Starting Pynodex daemon (!!! RUNNING IN FOREGROUND FOR DEBUGGING !!!)", fg="red", bold=True))

    # --- THIS IS THE CRITICAL DEBUGGING CHANGE ---
    # We are calling start_daemon_process() directly, bypassing Daemonize library for now.
    try:
        start_daemon_process() # Directly call the daemon's main function
    except Exception as e:
        click.echo(click.style(f"CRITICAL ERROR IN DAEMON FOREGROUND START: {e}", fg="red", bold=True), err=True)
        # Print full traceback to stderr for debugging
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    # --- END CRITICAL DEBUGGING CHANGE ---

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
            if os.path.exists(DAEMON_SOCK_FILE): # Clean up socket if daemon already died
                try:
                    os.remove(DAEMON_SOCK_FILE)
                except OSError as e:
                    click.echo(click.style(f"Warning: Could not remove old socket file {DAEMON_SOCK_FILE}: {e}", fg="yellow"), err=True)
            sys.exit(0)

        click.echo(click.style(f"Stopping Pynodex daemon (PID: {pid})...", fg="cyan"))
        
        os.kill(pid, signal.SIGTERM) # Send terminate signal
        
        max_wait = 10 # seconds
        for _ in range(max_wait):
            if not psutil.pid_exists(pid):
                click.echo(click.style("Pynodex daemon stopped successfully.", fg="green"))
                # Clean up PID and socket files after successful stop
                if os.path.exists(DAEMON_PID_FILE):
                    os.remove(DAEMON_PID_FILE)
                if os.path.exists(DAEMON_SOCK_FILE):
                    try:
                        os.remove(DAEMON_SOCK_FILE)
                    except OSError as e:
                        click.echo(click.style(f"Warning: Could not remove old socket file {DAEMON_SOCK_FILE}: {e}", fg="yellow"), err=True)
                sys.exit(0)
            time.sleep(1) # Wait for 1 second

        # If loop finishes, daemon did not stop gracefully
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
