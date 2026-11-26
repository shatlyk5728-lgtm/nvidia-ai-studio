# NVIDIA AI Studio

A native Windows desktop chat client for NVIDIA NIM models.

## Requirements
- Windows 10/11 (64-bit)
- Python 3.10+ only if running from source
- NVIDIA API key from https://build.nvidia.com/

## Run from source
1. Install Python 3.10 or newer.
2. Double-click `run.bat`.
3. Open Settings, paste your NVIDIA API key, and save it.
4. Select a model and start chatting.

## Build the Windows executable
Run `build.bat` on Windows. The executable is created at `dist\NVIDIA AI Studio.exe`.

Alternatively, push to GitHub and open **Actions → Build Windows EXE → Run workflow**. Download the `NVIDIA-AI-Studio-Windows` artifact when the workflow completes.

The API key is stored in the Windows Credential Manager through Python keyring. It is not written to source files or committed to Git.
