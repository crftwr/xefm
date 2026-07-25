# XeFM Application Overview

## Current Version: 0.99

XeFM (*Xenolith File Manager*) is a sophisticated dual-pane file manager that runs both as a native desktop app (Windows, macOS) and in the terminal (Windows, macOS, Linux), rendering through the external [PuiKit](https://github.com/crftwr/puikit) framework. It provides comprehensive file operations, cloud storage integration, and extensive customization capabilities.

## Core Architecture

```mermaid
flowchart TB
    subgraph APP["Application Layer"]
        XeFMApp["XeFMApp — xefm/app.py<br/>Controller · PuiKit event loop · key→action mapping · pane state"]
    end

    subgraph MGR["Manager Systems"]
        direction LR
        Pane["PaneManager<br/>xefm.pane_manager"]
        FileOps["FileOperationService<br/>xefm.file_operations"]
        Task["TaskManager<br/>xefm.task"]
        Progress["ProgressManager<br/>xefm.progress_manager"]
        State["StateManager<br/>xefm.state_manager"]
        Log["LogManager<br/>xefm.log_manager"]
    end

    subgraph UI["UI Components — XeFM widgets built on PuiKit"]
        direction LR
        Panes["Panes &amp; Status<br/>PaneHeader · PaneFooter · StatusBar · LayoutView"]
        Viewers["Viewers<br/>Text · Diff · DirectoryDiff · Image · JSON/CSV/Markdown"]
        Dialogs["Dialogs<br/>FilterList · Search · BatchRename · Conflict · Jump · Drives"]
    end

    subgraph STORE["Storage Abstraction — Path Polymorphism"]
        direction LR
        Path["Path facade + PathImpl ABC<br/>xefm.path"]
        Local["LocalPathImpl<br/>xefm.path"]
        SSH["SSHPathImpl<br/>xefm.ssh"]
        S3["S3PathImpl<br/>xefm.s3"]
        Archive["ArchivePathImpl<br/>xefm.archive"]
        Path --> Local & SSH & S3 & Archive
    end

    subgraph PUI["PuiKit Framework — external UI toolkit (../puikit)"]
        direction LR
        Events["Event system<br/>puikit.event"]
        Widgets["Widgets<br/>ListView · TextEdit · Menu · Splitter · message box"]
        TextEng["Text · Theme · Font · Layout<br/>puikit.text / theme / font / layout"]
    end

    subgraph BE["PuiKit Backends"]
        direction LR
        Curses["Curses<br/>terminal"]
        MacOS["macOS<br/>native"]
        Windows["Windows<br/>native"]
    end

    XeFMApp --> MGR
    XeFMApp --> UI
    MGR --> STORE
    UI --> STORE
    UI --> PUI
    PUI --> BE

    classDef app fill:#1a5490,stroke:#7fb3d5,color:#ffffff;
    classDef mgr fill:#8b2e24,stroke:#e0897f,color:#ffffff;
    classDef ui fill:#1e7e34,stroke:#7fd39b,color:#ffffff;
    classDef store fill:#9a6308,stroke:#e0b45f,color:#ffffff;
    classDef pui fill:#5e2d70,stroke:#b98fd0,color:#ffffff;
    classDef be fill:#0e7c66,stroke:#5fd0b4,color:#ffffff;

    class XeFMApp app;
    class Pane,FileOps,Task,Progress,State,Log mgr;
    class Panes,Viewers,Dialogs ui;
    class Path,Local,SSH,S3,Archive store;
    class Events,Widgets,TextEng pui;
    class Curses,MacOS,Windows be;
```

### Design principles

XeFM's UI is assembled from small, reusable components, each owning one aspect of
the interface. The principles that recur across them:

- **Modularity** — each feature lives in its own module (`xefm_*.py`).
- **Consistency** — uniform keyboard navigation and behavior across every dialog
  and pane.
- **Reusability** — the same component serves multiple contexts: the searchable
  list picker backs favorites, drives, programs, and the jump dialog; the same
  `FilePane` widget renders both real directories and virtual (search-results)
  listings.
- **Manager pattern** — specialized managers isolate concerns: `PaneManager`
  (dual-pane state and navigation), `FileOperationService` (copy / move / delete
  / rename), `TaskManager` (threaded work), `ProgressManager`, `StateManager`,
  and `LogManager`.
- **Extensibility** — new dialogs, viewers, and storage backends slot into the
  existing seams (the `Path` polymorphism and PuiKit widget layers shown above).

### Component groups

The architecture diagram above shows how the pieces fit together; the full
per-module inventory lives in [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md). The
major groups are:

- **Dual-pane model** — `PaneManager` tracks the active pane, per-pane selection,
  sort/filter state, and directory navigation, while `FilePane` renders one pane
  (real or virtual). Cross-pane copy/move and directory comparison fall out of
  this model naturally.
- **Reusable dialogs & bars** — a searchable list picker, scrollable text/info
  dialogs, a progressive (threaded) filename/content search dialog, batch rename,
  single-line input, and status-bar quick choices, all built on PuiKit widgets.
- **Viewers** — text (with syntax highlighting), diff, directory-diff, image, and
  structured (JSON/CSV/Markdown) content.
- **Storage abstraction** — a single `Path` facade over local, S3, SSH/SFTP, and
  archive backends, so every file operation works uniformly across them.
- **Integration & extensions** — external-program execution and archive
  create/extract (ZIP, TAR.GZ, TGZ).

## Key Features

### File Management
- **Dual Pane Interface**: Left and right panes for efficient file operations
- **Comprehensive Operations**: Copy, move, delete, rename, create files and directories
- **Batch Operations**: Multi-selection with space bar, regex-based batch renaming
- **Archive Support**: Create and extract ZIP, TAR.GZ, TGZ archives
- **Safety Features**: Confirmation dialogs, conflict resolution, permission checks

### Navigation and Search
- **Smart Navigation**: Arrow keys, Tab switching, directory history
- **Incremental Search**: Real-time filtering as you type
- **Threaded Search**: Non-blocking filename and content search
- **Pattern Filtering**: fnmatch patterns (*.py, test_*, etc.)
- **Jump Dialog**: Intelligent directory scanning with search
- **Favorite Directories**: Customizable bookmarks with quick access

### Text Handling
- **Built-in Text Viewer**: Syntax highlighting for 20+ file formats
- **External Editor Integration**: Configurable text editor support
- **Encoding Support**: UTF-8, Latin-1, CP1252 with automatic detection
- **Search in Files**: Find functionality within viewed text files

### Cloud Storage Integration
- **AWS S3 Support**: Full S3 integration with s3:// URI support
- **Seamless Operations**: All file operations work with S3 objects
- **Intelligent Caching**: TTL-based caching for optimal performance
- **Virtual Directories**: S3 prefix-based directory simulation
- **Mixed Operations**: Copy/move between local and S3 storage

### System Integration
- **Sub-shell Mode**: Environment variables for current state access
- **External Programs**: Configurable external command integration
- **VSCode Integration**: Direct directory and file opening
- **Beyond Compare Integration**: File and directory comparison

### Customization
- **Configuration System**: Comprehensive Python-based configuration
- **Key Bindings**: Fully customizable keyboard shortcuts
- **Color Schemes**: Dark/Light themes with runtime switching
- **Progress Animations**: Configurable animation patterns
- **Behavior Settings**: Confirmations, display options, performance tuning

## Command Line Interface

### Basic Usage
```bash
python3 -m xefm                    # Start with default settings
xefm                               # If installed via pip
```

### Directory Specification
```bash
python3 -m xefm --left /projects --right /documents
python3 -m xefm --left . --right ..
```

### Color Testing
XeFM includes comprehensive color support with multiple color schemes.

## Configuration System

### Configuration File
- **Location**: `~/.xefm/config.py`
- **Template**: `xefm/_config.py`
- **Auto-creation**: Generated from template on first run
- **Live Validation**: Error reporting with fallback to defaults

### Configurable Settings
- **Display**: Color schemes, pane ratios, hidden files
- **Behavior**: Confirmations, sorting, file operations
- **Performance**: Search limits, caching, animation speed
- **Key Bindings**: Complete keyboard customization
- **Directories**: Startup paths, favorites, history limits
- **Programs**: External command integration

## Development Architecture

### Modular Design
- **Component-based**: Each feature in separate module
- **Dialog System**: Reusable UI components
- **Manager Pattern**: Specialized managers for different concerns
- **Event-driven**: Key binding system with configurable actions

### Error Handling
- **Specific Exceptions**: Targeted exception handling
- **Graceful Degradation**: Fallback behavior for missing dependencies
- **User Feedback**: Clear error messages and recovery options

### Testing Framework
- **Unit Tests**: Component-level testing
- **Integration Tests**: Feature interaction testing
- **Demo Scripts**: Interactive feature demonstrations
- **Verification Scripts**: Quick feature validation

## Dependencies

### Required
- **Python 3.9+**: Core language requirement (3.13 supported)
- **curses**: Terminal UI library (built-in on Unix systems)

### Optional
- **pygments**: Enhanced syntax highlighting
- **boto3**: AWS S3 support
- **windows-curses**: Windows terminal support

## Platform Support
- **macOS**: Full support with native terminal
- **Linux**: Full support with standard terminals
- **Windows**: Supported with Windows Terminal or compatible terminals

## Performance Characteristics

### Optimizations
- **Threaded Operations**: Non-blocking search and file operations
- **Intelligent Caching**: S3 and remote operation caching
- **Lazy Loading**: On-demand resource loading
- **Memory Management**: Configurable limits for large operations

### Scalability
- **Large Directories**: Efficient handling of thousands of files
- **Remote Storage**: Optimized S3 operations with caching
- **Search Performance**: Configurable result limits and threading
- **Memory Usage**: Bounded memory consumption with cleanup

## Security Considerations

### File Operations
- **Permission Checks**: Validates file system permissions
- **Confirmation Dialogs**: User confirmation for destructive operations
- **Path Validation**: Prevents directory traversal attacks

### Cloud Integration
- **AWS Credentials**: Uses standard AWS credential chain
- **Secure Connections**: HTTPS for all S3 operations
- **Access Control**: Respects S3 bucket policies and IAM permissions

## Future Extensibility

### Plugin Architecture
- **External Programs**: Framework for custom tool integration
- **Dialog System**: Extensible UI component system
- **Path System**: Pluggable storage backend support

### Integration Points
- **Configuration**: Python-based configuration for flexibility
- **Key Bindings**: Programmable keyboard shortcuts
- **Color Schemes**: Customizable appearance system
- **Progress System**: Extensible progress tracking

This overview provides a comprehensive understanding of XeFM's current architecture, capabilities, and design principles as of version 0.99.