# Process Pilot

Process Pilot is a Python-based tool for managing and monitoring processes defined in a manifest file. It supports JSON and YAML formats for defining processes and their configurations.

## Features

- Load process configurations from JSON or YAML files.
- Manage process lifecycles with customizable hooks.
- Monitor process resource usage.
- Define shutdown strategies for processes.
- Define ready strategies to determine when launched processes are deemed to be "running".

## Installation

To install the dependencies, use [Poetry](https://python-poetry.org/):

```sh
poetry install
```

## Usage

You can use the `ProcessPilot` class directly in your Python code to manage processes defined in a YAML or JSON file.

### Example Usage

#### Using a JSON Manifest

```python
from pathlib import Path
from process_pilot.process import ProcessPilot, ProcessManifest

# Load the process manifest from a JSON file
manifest_path = Path("path/to/your/manifest.json")
manifest = ProcessManifest.from_json(manifest_path)

# Create a ProcessPilot instance with the loaded manifest
pilot = ProcessPilot(manifest)

# Start managing the processes
pilot.start()
```

#### Using a YAML Manifest

```python
from pathlib import Path
from process_pilot.process import ProcessPilot, ProcessManifest

# Load the process manifest from a YAML file
manifest_path = Path("path/to/your/manifest.yaml")
manifest = ProcessManifest.from_yaml(manifest_path)

# Create a ProcessPilot instance with the loaded manifest
pilot = ProcessPilot(manifest)

# Start managing the processes
pilot.start()
```

## Configuration

### Process Manifest

The process manifest defines the processes to be managed. It can be written in JSON or YAML format.

#### Parameters

- `name`: The name of the process. This should be unique within the manifest.
- `path`: The path to the executable or script to be run.
- `args`: A list of arguments to be passed to the process.
- `timeout`: The maximum time (in seconds) to wait for the process to start or stop.
- `shutdown_strategy`: The strategy to use when shutting down the process. Possible values are:
  - `do_not_restart`: Do not restart the process after it stops.
  - `restart`: Restart the process after it stops. This is the default.
  - `shutdown_everything`: Stop all processes when this process stops.
- `ready_strategy`: The strategy to use to determine when the process is ready. Possible values are:
  - `tcp`: The process is ready when it starts listening on a specified TCP port.
  - `pipe`: The process is ready when it writes a specific signal to a named pipe.
  - `file`: The process is ready when a specific file is created.
- `ready_timeout_sec`: The maximum time (in seconds) to wait for the process to be ready.
- `ready_params`: Additional parameters for the ready strategy. These vary based on the strategy:
  - For `tcp`, specify the `port` to check.
  - For `pipe`, specify the `path` to the named pipe.
  - For `file`, specify the `path` to the file.
- `dependencies`: A list of other process names that must be started before this process can be started.
- `env`: A dictionary of environment variables to set for the process.

The following is an example of a JSON manifest:

```json
{
  "processes": [
    {
      "name": "example",
      "path": "sleep",
      "args": ["5"],
      "timeout": 3,
      "shutdown_strategy": "do_not_restart",
      "ready_strategy": "tcp",
      "ready_timeout_sec": 10.0,
      "ready_params": {
        "port": 8080
      },
      "dependencies": ["another_process"],
      "env": {
        "ENV_VAR": "value"
      }
    }
  ]
}
```

The following is an example of a YAML manifest:

```yaml
processes:
    - name: example
        path: sleep
        args: ["5"]
        timeout: 1.0
        shutdown_strategy: do_not_restart
        ready_strategy: tcp
        ready_timeout_sec: 10.0
        ready_params:
            port: 8080
        dependencies:
            - another_process
        env:
            ENV_VAR: value
```

## Plugin System

Process Pilot supports a plugin system that allows users to extend its functionality with custom hooks, ready strategies, and process statistics handlers.

### Creating a Plugin

To create a plugin, define a class that inherits from [`Plugin`](process_pilot/plugin.py) and implement the required methods:

```python
import time
from collections.abc import Callable
from pathlib import Path
from subprocess import Popen
from typing import TYPE_CHECKING

from process_pilot.plugin import Plugin
from process_pilot.types import ProcessHookType

if TYPE_CHECKING:
    from process_pilot.process import Process, ProcessStats

class ExamplePlugin(Plugin):
    def register_hooks(self) -> dict[ProcessHookType, list[Callable[["Process", Popen[str]], None]]]:
        return {
            "pre_start": self.pre_start_hook,
            "post_start": self.post_start_hook,
        }

    def register_strategies(self) -> dict[str, Callable[["Process", float], bool]]:
        return {
            "custom_strategy": self.custom_ready_strategy,
        }

    def register_stats_handlers(self) -> list[Callable[[list["ProcessStats"]], None]]:
        return [self.handle_stats]

    def handle_stats(self, stats: list["ProcessStats"]) -> None:
        for stat in stats:
            print(f"Process {stat.name} stats:")
            print(f"  Memory: {stat.memory_usage_mb:.2f}MB")
            print(f"  CPU: {stat.cpu_usage_percent:.1f}%")
```

When creating plugins it is important to keep in mind that you should always be checking readiness relative to
the start time--and always comparing the difference to the timeout value that is specified in the manifest. The
simplest example of this can be seen in the `FileReadyPlugin`:

```python
start_time = time.time()
while (time.time() - start_time) < process.ready_timeout_sec:
    if file_path.exists():
        return True
    time.sleep(ready_check_interval_secs)

# Timeout
return False
```

Be careful not to use readiness checks that block the threads ability to check for a timeout condition.

## Process Lifecycle

The following diagram illustrates the process lifecycle and when various hook functions are called:

```mermaid
graph TD
        A[Start Process Pilot] --> B[Initialize Processes]
        B --> C[Execute PRE_START Hooks]
        C --> D[Start Process]
        D --> E[Execute POST_START Hooks]
        E --> F[Monitor Process]
        F -->|Process Running| F
        F -->|Process Exits| G[Execute ON_SHUTDOWN Hooks]
        G --> H{Shutdown Strategy}
        H -->|restart| I[Restart Process]
        I --> J[Execute ON_RESTART Hooks]
        J --> F
        H -->|do_not_restart| K[Stop Monitoring]
        H -->|shutdown_everything| L[Stop All Processes]
```

## Ready Strategies

Process Pilot supports three different strategies to determine if a process is ready:

1. TCP Port Listening
2. Named Pipe Signal
3. File Presence

Each ready strategy is only relevant for determining when dependent processes should be started. That is, if a given process has no dependencies, then specifying a ready strategy isn't currently meaningful. The following diagrams illustrate how each strategy works:

### TCP Ready Strategy

```mermaid
sequenceDiagram
    participant PP as Process Pilot
    participant P as Process
    participant TCP as TCP Port
    PP->>P: Start Process
    activate P
    P->>TCP: Begin Listening
    loop Until Ready or Timeout
        PP->>TCP: Attempt Connection
        alt Port is Listening
            TCP-->>PP: Connection Success
            PP->>PP: Process Ready
        else Port not ready
            TCP-->>PP: Connection Failed
            Note over PP: Wait 0.1s
        end
    end
    deactivate P
```

### Named Pipe Ready Strategy

```mermaid
sequenceDiagram
    participant PP as Process Pilot
    participant P as Process
    participant Pipe as Named Pipe
    PP->>Pipe: Create Pipe
    PP->>P: Start Process
    activate P
    loop Until Ready or Timeout
        PP->>Pipe: Read Pipe
        alt Contains "ready"
            Pipe-->>PP: "ready"
            PP->>PP: Process Ready
        else Not Ready
            Pipe-->>PP: No Data/Error
            Note over PP: Wait 0.1s
        end
    end
    deactivate P
```

### File Ready Strategy

```mermaid
sequenceDiagram
    participant PP as Process Pilot
    participant P as Process
    participant FS as File System
    PP->>P: Start Process
    activate P
    loop Until Ready or Timeout
        PP->>FS: Check File
        alt File Exists
            FS-->>PP: File Found
            PP->>PP: Process Ready
        else No File
            FS-->>PP: No File
            Note over PP: Wait 0.1s
        end
    end
    deactivate P
```

Each strategy can be configured in the manifest:

```yaml
processes:
  - name: example
    path: myapp
    ready_strategy: tcp # or "pipe" or "file"
    ready_timeout_sec: 10.0
    ready_params:
      port: 8080 # for TCP
      path: "/tmp/ready.txt" # for File
```

## Development

### Running Tests

To run the tests, use:

```sh
poetry run pytest
```

### Linting and Formatting

To lint and format the code, use:

```sh
poetry run ruff check .
poetry run autopep8 --in-place --recursive .
```

## License

This project is licensed under the MIT License. See the [LICENSE](../LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Contact

For any inquiries, please contact James Armes at jamesleearmes@gmail.com.
