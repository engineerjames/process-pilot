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

To start the Process Pilot, run:

```sh
poetry run python -m process_pilot.process
```

## Configuration

### Process Manifest

The process manifest defines the processes to be managed. It can be written in JSON or YAML format.

#### Example JSON Manifest

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
      }
    }
  ]
}
```

#### Example YAML Manifest

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
```

## Process Lifecycle

The following Mermaid diagram illustrates the process lifecycle and when various hook functions are called:

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

## Development

### Running Tests

To run the tests, use:

```sh
poetry run pytest
```

### Linting and Formatting

### Ready Strategies

Process Pilot supports three different strategies to determine if a process is ready:

1. TCP Port Listening
2. Named Pipe Signal
3. File Presence

The following diagrams illustrate how each strategy works:

#### TCP Ready Strategy

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

#### Named Pipe Ready Strategy

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

#### File Ready Strategy

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

To lint and format the code, use:

```sh
poetry run ruff check .
poetry run autopep8 --in-place --recursive .
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Contact

For any inquiries, please contact James Armes at jamesleearmes@gmail.com.
