# Project Setup Guide

## Prerequisites

Ensure you have Python 3.8+ installed on your system. You can check your Python version by running:

```bash
python3 --version  # macOS/Linux
python --version   # Windows

```
---

## Getting Started

Follow these steps to isolate your dependencies and get the project running locally.

### 1. Create the Virtual Environment

Run the following command in the root directory of the project to create a hidden virtual environment folder named `.venv`:

**macOS / Linux:**

```bash
python3 -m venv .venv

```

**Windows:**

```bash
python -m venv .venv

```

### 2. Activate the Virtual Environment

Before installing dependencies or running code, you must activate the virtual environment.

**macOS / Linux (Bash/Zsh):**

```bash
source .venv/bin/activate

```

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1

```

**Windows (Command Prompt / CMD):**

```cmd
.venv\Scripts\activate.bat

```

> 💡 **Tip:** You will know it worked because your terminal prompt will now show `(.venv)` at the beginning of the line.

### 3. Upgrade pip & Install Requirements

Once the virtual environment is active, upgrade `pip` to the latest version and install the required packages listed in `requirements.txt`:

```bash
pip install --upgrade pip
pip install -r requirements.txt

```

---
## Run Webserver

```bash
python agent.py

```
---

## Deactivating the Environment

When you are done working on the project, you can exit the virtual environment safely by running:

```bash
deactivate

```

### Git Notice

Make sure your `.gitignore` file includes `.venv/` so you do not accidentally commit your local environment packages to GitHub!
