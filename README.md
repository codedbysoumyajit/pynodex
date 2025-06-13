# Pynodex: CLI Process Manager  

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

## Quick Start  

### Start an Application  
```bash
pynodex start my-app "python -m http.server 8000" --port 8000
```  

### List Managed Processes  
```bash
pynodex list  
```  

### View Logs  
```bash
pynodex logs my-app  
```  

### Monitor Resources  
```bash
pynodex monitor  
```  

### Stop/Restart  
```bash
pynodex stop my-app  
pynodex restart all  
```  

### Cleanup  
```bash
pynodex clear my-app  # Remove a single app  
pynodex clear all     # Remove all apps (requires confirmation)  
```  

## Advanced (Conceptual)  
*Supports flags for auto-restart, memory limits, and file watching—requires a daemon for full functionality.*  

---  
**Storage**: Data is saved in your OS application directory (e.g., `~/.local/share/pynodex`).  
**Compatibility**: Works with any shell-executable language (Python, Node.js, Java, etc.).  

For detailed help: `pynodex <command> --help`
