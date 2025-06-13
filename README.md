# Pynodex: Process Manager  

A lightweight, cross-platform process manager for monitoring and managing applications across multiple languages.  

## Features  

- **Process Management**: Start, stop, restart, and reload applications  
- **Real-time Monitoring**: Track CPU, memory, disk, and network usage  
- **Logging**: Stream logs directly to console or file  
- **Port Tracking**: Monitor application ports  
- **Persistence**: Automatically saves process states  

## Installation  

```bash
pip install .
# For development: pip install -e .
```

## Basic Commands  

### `pynodex start <name> "<command>" [options]`  
Launches a new application under Pynodex management.  

**Key Options:**  
* `--cwd <path>` - Set working directory  
* `--env KEY=VALUE` - Set environment variables  
* `--port <num>` - Track application port  
* `--log <path>` - Custom log file location  
* `--no-daemon` - Run without daemon logging (logs still saved)  

**Daemon-Enabled Features (Requires Daemon Process):**  
* `--watch` - Auto-restart on file changes  
* `--max-memory-restart <size>` - Restart if memory exceeded (e.g., "250MB")  
* `--max-cpu-restart <percent>` - Restart if CPU usage exceeded  
* `--restart-delay <ms>` - Delay between auto-restarts  
* `--no-autorestart` - Disable automatic restarts  
* `--cron <pattern>` - Schedule forced restarts  
* `--time` - Add timestamps to logs  

**Examples:**  
```bash
# Python server
pynodex start my-app "python -m http.server 8000" --port 8000

# Node.js app with monitoring
pynodex start node-app "node server.js" --watch --max-memory-restart 500MB

# Temporary script
pynodex start my-task "bash script.sh" --no-daemon
```

### Other Essential Commands  
```bash
pynodex list          # View managed processes
pynodex logs <app>    # Stream application logs
pynodex monitor       # Show system resource usage
pynodex stop <app>    # Stop an application
pynodex restart all   # Restart all applications
pynodex clear all     # Remove all apps (with confirmation)
```

---  
**Note**: Data is stored in your OS application directory (e.g., `~/.local/share/pynodex`).  
For detailed help: `pynodex <command> --help`