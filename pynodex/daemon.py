# pynodex/daemon.py

import os
import sys
import subprocess
import json
import time
import psutil
import socket
import logging
import signal
import fcntl # For non-blocking file locking (Unix-specific)

# External library for daemonization
from daemonize import Daemonize # A simpler alternative to python-daemon for basic daemonization

# --- Configuration (Shared with CLI) ---
# Using click.get_app_dir directly in daemon.py is not ideal as daemonize detaches.
# Instead, pass it or use a fixed path. For simplicity, we'll hardcode based on standard.
# In a real system, you'd configure this consistently.
APP_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "pynodex")
PROCESS_DB_FILE = os.path.join(APP_DIR, 'processes.json')
LOG_DIR = os.path.join(APP_DIR, 'process_logs')
DAEMON_PID_FILE = os.path.join(APP_DIR, 'pynodex_daemon.pid')
DAEMON_SOCK_FILE = os.path.join(APP_DIR, 'pynodex_daemon.sock')
DAEMON_LOG_FILE = os.path.join(APP_DIR, 'pynodex_daemon.log') # Daemon's own log

# Ensure directories exist
os.makedirs(APP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


# --- Daemon Logging ---
# Configure daemon's own logger
daemon_logger = logging.getLogger(__name__)
daemon_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# File handler
file_handler = logging.FileHandler(DAEMON_LOG_FILE)
file_handler.setFormatter(formatter)
daemon_logger.addHandler(file_handler)

# If running directly (not yet daemonized), also print to console
if not sys.argv[0].endswith('pynodex_daemon_cli.py'): # Simple check for direct execution
     stream_handler = logging.StreamHandler(sys.stdout)
     stream_handler.setFormatter(formatter)
     daemon_logger.addHandler(stream_handler)


# --- Shared Helper Functions (adapted for daemon context) ---

def load_processes_daemon():
    if os.path.exists(PROCESS_DB_FILE):
        try:
            with open(PROCESS_DB_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            daemon_logger.warning(f"'{PROCESS_DB_FILE}' is empty or corrupted. Starting with an empty process list for daemon.")
            return {}
    return {}

def save_processes_daemon(processes):
    os.makedirs(os.path.dirname(PROCESS_DB_FILE), exist_ok=True)
    with open(PROCESS_DB_FILE, 'w') as f:
        json.dump(processes, f, indent=4)

def get_process_info_daemon(pid):
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
        daemon_logger.warning(f"Access denied to process {pid}. Limited info available.")
        return {'pid': pid, 'status': 'Access Denied', 'name': 'N/A', 'cpu_percent': 0, 'memory_percent': 0, 'memory_info_rss_mb': 0, 'cmdline': 'N/A', 'create_time': 'N/A'}

def _start_process_internal_daemon(name, command, cwd, env, port, log, no_daemon, watch, max_memory_restart, max_cpu_restart, restart_delay, no_autorestart, cron, time_prefix_logs):
    """Internal function to encapsulate the core process starting logic for daemon."""
    processes = load_processes_daemon()

    full_command = " ".join(command)
    
    if port:
        # Daemon's own port checking. If it fails here, we raise error.
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                s.close()
        except OSError:
            raise ValueError(f"Port {port} is already in use by another application or is reserved.")
    
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    
    stdout_target = None
    stderr_target = None
    stdout_log_path = None
    stderr_log_path = None

    if no_daemon: # 'no_daemon' in the stored config means output goes to the actual process's console, not to daemon's files.
        # But for daemon-managed processes, we always want to capture logs.
        # So, if no_daemon was True from CLI, we still capture to our default logs.
        # This is a key difference: daemon always logs to file for background apps.
        stdout_log_path = os.path.join(LOG_DIR, f'{name}_stdout.log')
        stderr_log_path = os.path.join(LOG_DIR, f'{name}_stderr.log')
        stdout_target = open(stdout_log_path, 'a')
        stderr_target = open(stderr_log_path, 'a')
        daemon_logger.info(f"Process '{name}' configured with --no-daemon, but daemon will log to default files for persistence.")
    else:
        if log:
            log_file_path = os.path.abspath(log)
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
            stdout_target = open(log_file_path, 'a')
            stderr_target = subprocess.STDOUT
            stdout_log_path = log_file_path
            stderr_log_path = log_file_path
        else:
            stdout_log_path = os.path.join(LOG_DIR, f'{name}_stdout.log')
            stderr_log_path = os.path.join(LOG_DIR, f'{name}_stderr.log')
            stdout_target = open(stdout_log_path, 'a')
            stderr_target = open(stderr_log_path, 'a')

    try:
        # Use Popen to run the process independently and re-parent it to daemon
        process = subprocess.Popen(
            full_command,
            shell=True,
            cwd=cwd,
            env=process_env,
            stdout=stdout_target,
            stderr=stderr_target,
            preexec_fn=os.setsid if sys.platform != "win32" else None # Detach on Unix-like systems
        )
        pid = process.pid

        # The daemon closes its copies of the file handles immediately
        stdout_target.close()
        stderr_target.close()
        
        # Update/Add process info in daemon's view
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
            'time_prefix_logs': time_prefix_logs # Daemon will handle this now
        }
        save_processes_daemon(processes)
        daemon_logger.info(f"Started process '{name}' with PID: {pid}.")
        return {"status": "success", "message": f"Process '{name}' started with PID: {pid}."}
    except Exception as e:
        daemon_logger.error(f"Error starting process '{name}': {e}")
        return {"status": "error", "message": str(e)}


def _stop_process_internal_daemon(name):
    """Internal function to encapsulate the core process stopping logic for daemon."""
    processes = load_processes_daemon()
    if name not in processes:
        daemon_logger.warning(f"Attempted to stop '{name}' but not found in registry.")
        return {"status": "error", "message": f"Process '{name}' not found."}

    pid = processes[name].get('pid')
    if pid:
        try:
            proc = psutil.Process(pid)
            daemon_logger.info(f"Stopping process '{name}' (PID: {pid})...")
            proc.terminate()
            proc.wait(timeout=5)
            daemon_logger.info(f"Process '{name}' (PID: {pid}) stopped.")
        except psutil.NoSuchProcess:
            daemon_logger.warning(f"Process '{name}' (PID: {pid}) not found or already dead.")
        except psutil.AccessDenied:
            daemon_logger.error(f"Access denied to terminate process '{name}' (PID: {pid}).")
            return {"status": "error", "message": f"Access denied to PID {pid}."}
        except psutil.TimeoutExpired:
            daemon_logger.warning(f"Process '{name}' (PID: {pid}) did not terminate gracefully. Attempting to kill...")
            try:
                proc.kill()
                proc.wait(timeout=2)
                daemon_logger.info(f"Process '{name}' (PID: {pid}) killed.")
            except psutil.NoSuchProcess:
                daemon_logger.warning(f"Process '{name}' (PID: {pid}) was already gone after kill attempt.")
            except Exception as e:
                daemon_logger.error(f"Error killing process '{name}' (PID: {pid}): {e}")
                return {"status": "error", "message": f"Error killing PID {pid}: {e}"}
        except Exception as e:
            daemon_logger.error(f"An error occurred while stopping process '{name}': {e}")
            return {"status": "error", "message": str(e)}
    else:
        daemon_logger.warning(f"No PID recorded for process '{name}'.")

    del processes[name]
    save_processes_daemon(processes)
    daemon_logger.info(f"'{name}' removed from registry.")
    return {"status": "success", "message": f"Process '{name}' stopped and removed."}


# --- Daemon Core Logic ---

class PynodexDaemon:
    def __init__(self):
        self.managed_processes = load_processes_daemon()
        self.sock = None
        self.max_cpu_percent = psutil.cpu_count() * 100 # Max CPU usage for system

    def _monitor_running_processes(self):
        """
        Continuously monitor health and resources of running processes.
        This is where daemon-dependent features would be actively managed.
        """
        processes_to_check = list(self.managed_processes.keys()) # Copy keys as dict might change
        for name in processes_to_check:
            info = self.managed_processes.get(name)
            if not info: # Process might have been removed by another command
                continue

            pid = info.get('pid')
            
            if pid:
                proc_info = get_process_info_daemon(pid)
                if proc_info:
                    # Update live status
                    info['status'] = proc_info['status']
                    
                    # --- Implement Conceptual Features Here ---
                    # 1. CPU and Memory Limits
                    if info.get('max_cpu_restart') and proc_info['cpu_percent'] > info['max_cpu_restart']:
                        daemon_logger.warning(f"Process '{name}' (PID: {pid}) exceeded CPU limit ({proc_info['cpu_percent']}% > {info['max_cpu_restart']}%). Restarting...")
                        self._handle_restart(name, info)
                        continue # Move to next process after restart attempt

                    if info.get('max_memory_restart'):
                        # Convert '200MB', '1GB' to MB or Bytes for comparison
                        mem_limit_str = info['max_memory_restart'].lower()
                        mem_limit_mb = 0
                        if 'mb' in mem_limit_str:
                            mem_limit_mb = float(mem_limit_str.replace('mb', ''))
                        elif 'gb' in mem_limit_str:
                            mem_limit_mb = float(mem_limit_str.replace('gb', '')) * 1024
                        
                        if mem_limit_mb > 0 and proc_info['memory_info_rss_mb'] > mem_limit_mb:
                            daemon_logger.warning(f"Process '{name}' (PID: {pid}) exceeded Memory limit ({proc_info['memory_info_rss_mb']:.1f}MB > {mem_limit_mb:.1f}MB). Restarting...")
                            self._handle_restart(name, info)
                            continue # Move to next process after restart attempt
                    
                    # 2. File Watching (Needs a dedicated file watcher like watchdog)
                    # if info.get('watch'):
                    #    # daemon_logger.debug(f"Watching files for {name}...")
                    #    # In a real impl, integrate with a file system event loop
                    #    pass
                    
                    # 3. Cron Restarts (Needs a cron scheduler like APScheduler)
                    # if info.get('cron'):
                    #    # daemon_logger.debug(f"Checking cron for {name}...")
                    #    # In a real impl, schedule jobs with APScheduler
                    #    pass
                    
                    # 4. Log Timestamping (Daemon intercepts and writes logs)
                    # Our current Popen redirects directly to file. For timestamping,
                    # the daemon would need to open a PTY or use threads to read
                    # stdout/stderr, add timestamps, and then write to log file.
                    # This is complex and out of scope for a basic daemon example.
                    # if info.get('time_prefix_logs'):
                    #    # daemon_logger.debug(f"Timestamping logs for {name}...")
                    #    pass

                else: # Process not found by psutil
                    daemon_logger.info(f"Process '{name}' (PID: {pid}) is no longer running. Updating status.")
                    info['status'] = 'dead/not_found'
                    if not info.get('no_autorestart'): # Auto-restart unless disabled
                        daemon_logger.info(f"Auto-restarting '{name}' (no_autorestart is False).")
                        self._handle_restart(name, info) # Handle restart if crashed
                        continue # Move to next process after restart attempt

            elif info.get('status') == 'running': # Registry says running but no PID, likely crashed since last check
                daemon_logger.info(f"Process '{name}' has no active PID but is marked running. Assuming crash and updating status.")
                info['status'] = 'dead/not_found'
                if not info.get('no_autorestart'): # Auto-restart unless disabled
                    daemon_logger.info(f"Auto-restarting '{name}' (no_autorestart is False).")
                    self._handle_restart(name, info) # Handle restart if crashed
                    continue # Move to next process after restart attempt
            
            # Save managed_processes state periodically or when significant status changes occur
            save_processes_daemon(self.managed_processes)

    def _handle_restart(self, name, info):
        """Helper to handle process restart logic."""
        if info.get('restart_delay_ms'):
            delay_seconds = info['restart_delay_ms'] / 1000.0
            daemon_logger.info(f"Waiting {delay_seconds:.1f}s before restarting '{name}'.")
            time.sleep(delay_seconds)
        
        # Stop old instance explicitly before starting new one for clean restart
        _stop_process_internal_daemon(name) 
        
        try:
            # Re-start using stored original parameters
            _start_process_internal_daemon(
                name=name,
                command=info['command'].split(),
                cwd=info.get('cwd'),
                env=info.get('env'),
                port=info.get('port'),
                log=info.get('stdout_log') if info.get('stdout_log') != 'N/A (console)' else None,
                no_daemon=(info.get('stdout_log') == 'N/A (console)'), # Re-use original setting
                watch=info.get('watch', False),
                max_memory_restart=info.get('max_memory_restart'),
                max_cpu_restart=info.get('max_cpu_restart'),
                restart_delay=info.get('restart_delay_ms'),
                no_autorestart=info.get('no_autorestart', False),
                cron=info.get('cron'),
                time_prefix_logs=info.get('time_prefix_logs', False)
            )
            daemon_logger.info(f"Process '{name}' restarted by daemon.")
        except Exception as e:
            daemon_logger.error(f"Failed to restart '{name}': {e}")


    def _handle_client_command(self, conn, command_data):
        """Handles a command received from a CLI client."""
        command_type = command_data.get('type')
        args = command_data.get('args', {})
        
        response = {"status": "error", "message": "Unknown command or missing args."}

        if command_type == "start":
            response = _start_process_internal_daemon(
                name=args['name'],
                command=args['command'], # Passed as list
                cwd=args.get('cwd'),
                env=args.get('env'),
                port=args.get('port'),
                log=args.get('log'),
                no_daemon=args.get('no_daemon', False),
                watch=args.get('watch', False),
                max_memory_restart=args.get('max_memory_restart'),
                max_cpu_restart=args.get('max_cpu_restart'),
                restart_delay=args.get('restart_delay_ms'),
                no_autorestart=args.get('no_autorestart', False),
                cron=args.get('cron'),
                time_prefix_logs=args.get('time_prefix_logs', False)
            )
            self.managed_processes = load_processes_daemon() # Reload after change
        elif command_type == "stop":
            response = _stop_process_internal_daemon(args['name'])
            self.managed_processes = load_processes_daemon() # Reload after change
        elif command_type == "list":
            # For list, we return the daemon's current view of processes
            # Optionally, re-fetch live psutil data for each before sending
            current_processes = load_processes_daemon()
            for name, info in current_processes.items():
                pid = info.get('pid')
                if pid:
                    proc_info = get_process_info_daemon(pid)
                    if proc_info:
                        info.update(proc_info) # Add live data
                    else:
                        info['status'] = 'dead/not_found'
                        # Don't save here, list is read-only
            response = {"status": "success", "data": current_processes}
        elif command_type == "restart":
            name = args['name']
            # Replicate CLI's restart logic
            if name == 'all':
                names_to_restart = list(self.managed_processes.keys())
            else:
                names_to_restart = [name]
            
            restarted_count = 0
            for app_name in names_to_restart:
                info = self.managed_processes.get(app_name)
                if not info:
                    daemon_logger.warning(f"Daemon: Cannot restart '{app_name}', not found.")
                    continue
                
                daemon_logger.info(f"Daemon: Initiating restart for '{app_name}'.")
                
                # Stop the process
                stop_res = _stop_process_internal_daemon(app_name)
                if stop_res.get('status') == 'error' and not ("not found" in stop_res.get('message')):
                    daemon_logger.error(f"Daemon: Failed to stop '{app_name}' during restart: {stop_res.get('message')}")
                    continue
                
                # Re-load processes in daemon's memory to ensure state is clean after stop
                self.managed_processes = load_processes_daemon() 

                # Start the process
                try:
                    start_res = _start_process_internal_daemon(
                        name=app_name,
                        command=info['command'].split(),
                        cwd=info.get('cwd'),
                        env=info.get('env'),
                        port=info.get('port'),
                        log=info.get('stdout_log') if info.get('stdout_log') != 'N/A (console)' else None,
                        no_daemon=(info.get('stdout_log') == 'N/A (console)'),
                        watch=info.get('watch', False),
                        max_memory_restart=info.get('max_memory_restart'),
                        max_cpu_restart=info.get('max_cpu_restart'),
                        restart_delay=info.get('restart_delay_ms'),
                        no_autorestart=info.get('no_autorestart', False),
                        cron=info.get('cron'),
                        time_prefix_logs=info.get('time_prefix_logs', False)
                    )
                    if start_res.get('status') == 'success':
                        restarted_count += 1
                        daemon_logger.info(f"Daemon: Successfully restarted '{app_name}'.")
                    else:
                        daemon_logger.error(f"Daemon: Failed to start '{app_name}' during restart: {start_res.get('message')}")
                except Exception as e:
                    daemon_logger.error(f"Daemon: Exception during restart of '{app_name}': {e}")
            response = {"status": "success", "message": f"Restarted {restarted_count} process(es)."}
            self.managed_processes = load_processes_daemon() # Final reload

        elif command_type == "reload":
            name = args['name']
            if name == 'all':
                names_to_reload = list(self.managed_processes.keys())
            else:
                names_to_reload = [name]

            reloaded_count = 0
            for app_name in names_to_reload:
                info = self.managed_processes.get(app_name)
                if not info:
                    daemon_logger.warning(f"Daemon: Cannot reload '{app_name}', not found.")
                    continue
                
                daemon_logger.info(f"Daemon: Initiating reload for '{app_name}'.")
                
                old_pid = info.get('pid')
                start_successful = False
                
                # 1. Attempt to start new instance
                try:
                    start_res = _start_process_internal_daemon(
                        name=app_name,
                        command=info['command'].split(),
                        cwd=info.get('cwd'),
                        env=info.get('env'),
                        port=info.get('port'),
                        log=info.get('stdout_log') if info.get('stdout_log') != 'N/A (console)' else None,
                        no_daemon=(info.get('stdout_log') == 'N/A (console)'),
                        watch=info.get('watch', False),
                        max_memory_restart=info.get('max_memory_restart'),
                        max_cpu_restart=info.get('max_cpu_restart'),
                        restart_delay=info.get('restart_delay_ms'),
                        no_autorestart=info.get('no_autorestart', False),
                        cron=info.get('cron'),
                        time_prefix_logs=info.get('time_prefix_logs', False)
                    )
                    if start_res.get('status') == 'success':
                        start_successful = True
                        daemon_logger.info(f"Daemon: New instance of '{app_name}' started.")
                except Exception as e:
                    daemon_logger.error(f"Daemon: Failed to start new instance of '{app_name}': {e}")
                
                # 2. Stop old instance if new one started, or if port conflict
                if start_successful:
                    if old_pid and psutil.pid_exists(old_pid):
                        daemon_logger.info(f"Daemon: Stopping old instance of '{app_name}' (PID: {old_pid})...")
                        _stop_process_internal_daemon(app_name) # Call stop to remove old entry
                        daemon_logger.info(f"Daemon: Old instance of '{app_name}' stopped.")
                    reloaded_count += 1
                elif old_pid and psutil.pid_exists(old_pid): # Start failed, but old process exists
                    daemon_logger.warning(f"Daemon: New instance failed to start for '{app_name}'. Stopping old instance and retrying start.")
                    _stop_process_internal_daemon(app_name) # Stop the old one
                    
                    # Retry start (basic form of hot reload's resilience)
                    try:
                        start_res_retry = _start_process_internal_daemon(
                            name=app_name,
                            command=info['command'].split(),
                            cwd=info.get('cwd'),
                            env=info.get('env'),
                            port=info.get('port'),
                            log=info.get('stdout_log') if info.get('stdout_log') != 'N/A (console)' else None,
                            no_daemon=(info.get('stdout_log') == 'N/A (console)'),
                            watch=info.get('watch', False),
                            max_memory_restart=info.get('max_memory_restart'),
                            max_cpu_restart=info.get('max_cpu_restart'),
                            restart_delay=info.get('restart_delay_ms'),
                            no_autorestart=info.get('no_autorestart', False),
                            cron=info.get('cron'),
                            time_prefix_logs=info.get('time_prefix_logs', False)
                        )
                        if start_res_retry.get('status') == 'success':
                            reloaded_count += 1
                            daemon_logger.info(f"Daemon: Successfully reloaded '{app_name}' after retry.")
                        else:
                            daemon_logger.error(f"Daemon: Failed to reload '{app_name}' even after retry: {start_res_retry.get('message')}")
                    except Exception as e_retry:
                        daemon_logger.error(f"Daemon: Exception during reload retry of '{app_name}': {e_retry}")
                else:
                    daemon_logger.error(f"Daemon: Failed to reload '{app_name}'. No old instance to stop or new instance could not start.")

            response = {"status": "success", "message": f"Reloaded {reloaded_count} process(es)."}
            self.managed_processes = load_processes_daemon() # Final reload

        elif command_type == "save":
            # Daemon saves its current view of processes
            save_processes_daemon(self.managed_processes)
            daemon_logger.info("Daemon: Registry saved on explicit command.")
            response = {"status": "success", "message": "Pynodex registry saved by daemon."}
        elif command_type == "clear":
            names_to_clear = [args['name']] if args['name'] != 'all' else list(self.managed_processes.keys())
            
            logs_to_delete = set()
            for name in names_to_clear:
                info = self.managed_processes.get(name)
                if info:
                    if info.get('stdout_log') and info['stdout_log'] != 'N/A (console)':
                        logs_to_delete.add(info['stdout_log'])
                    if info.get('stderr_log') and info['stderr_log'] != 'N/A (console)' and info.get('stderr_log') != info.get('stdout_log'):
                        logs_to_delete.add(info['stderr_log'])
            
            cleared_count = 0
            for name in names_to_clear:
                res = _stop_process_internal_daemon(name)
                if res.get('status') == 'success':
                    cleared_count += 1
                daemon_logger.info(f"Daemon: Cleared '{name}' with result: {res.get('message')}")

            for log_path in logs_to_delete:
                try:
                    if os.path.exists(log_path):
                        os.remove(log_path)
                        daemon_logger.info(f"Daemon: Deleted log: {log_path}")
                except Exception as e:
                    daemon_logger.error(f"Daemon: Error deleting log {log_path}: {e}")

            if args['name'] == 'all':
                try:
                    if os.path.exists(LOG_DIR):
                        shutil.rmtree(LOG_DIR)
                    os.makedirs(LOG_DIR, exist_ok=True) # Recreate empty log directory
                    daemon_logger.info(f"Daemon: Cleaned up '{LOG_DIR}'.")
                except Exception as e:
                    daemon_logger.error(f"Daemon: Error cleaning up log directory '{LOG_DIR}': {e}")
                save_processes_daemon({}) # Ensure registry is empty
                response = {"status": "success", "message": f"Cleared all processes ({cleared_count} stopped) and logs."}
            else:
                response = {"status": "success", "message": f"Cleared process '{args['name']}' and its logs."}
            self.managed_processes = load_processes_daemon() # Final reload

        else:
            response = {"status": "error", "message": f"Daemon received unknown command: {command_type}"}
        
        conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
        conn.close()


    def run(self):
        daemon_logger.info("Pynodex Daemon starting up...")
        
        # Clean up old socket if it exists
        if os.path.exists(DAEMON_SOCK_FILE):
            os.remove(DAEMON_SOCK_FILE)

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(DAEMON_SOCK_FILE)
        self.sock.listen(1) # Listen for one connection at a time
        
        daemon_logger.info(f"Daemon listening on Unix socket: {DAEMON_SOCK_FILE}")

        # Ensure socket file has appropriate permissions (optional, but good for security)
        os.chmod(DAEMON_SOCK_FILE, 0o600)

        # Main daemon loop
        while True:
            try:
                # Set a timeout for accept so daemon can do other tasks (like monitoring)
                self.sock.settimeout(1.0) # Check for new connections every 1 second
                conn, addr = self.sock.accept()
                
                daemon_logger.info("Client connected.")
                data = b''
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if b'\n' in data: # Assume commands are newline-terminated
                        break
                
                try:
                    command_data = json.loads(data.decode('utf-8').strip())
                    daemon_logger.info(f"Received command: {command_data.get('type')}")
                    self._handle_client_command(conn, command_data)
                except json.JSONDecodeError as e:
                    daemon_logger.error(f"Invalid JSON received from client: {e}, Data: {data.decode('utf-8')}")
                    conn.sendall(json.dumps({"status": "error", "message": "Invalid JSON command."}).encode('utf-8') + b'\n')
                    conn.close()
                except Exception as e:
                    daemon_logger.error(f"Error handling client command: {e}")
                    conn.sendall(json.dumps({"status": "error", "message": f"Daemon internal error: {e}"}).encode('utf-8') + b'\n')
                    conn.close()
            except socket.timeout:
                # No client connection, continue with monitoring tasks
                self._monitor_running_processes()
            except KeyboardInterrupt: # For debugging if run directly
                daemon_logger.info("Daemon received KeyboardInterrupt. Shutting down.")
                break
            except Exception as e:
                daemon_logger.error(f"Unexpected error in daemon main loop: {e}")

        self.sock.close()
        daemon_logger.info("Pynodex Daemon shut down.")

def start_daemon_process():
    daemon = PynodexDaemon()
    daemon.run()

