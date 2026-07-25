//
//  XeFMAppDelegate.m
//  XeFM - Terminal File Manager
//
//  Application delegate implementation for XeFM macOS app bundle.
//  Handles Python embedding, window lifecycle, and Dock integration.
//

#import "XeFMAppDelegate.h"
#include <Python.h>

@implementation XeFMAppDelegate {
    BOOL pythonInitialized;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        pythonInitialized = NO;
    }
    return self;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    // Single-process, single-window architecture
    NSLog(@"Launching XeFM in single-process mode");
    
    // Initialize Python interpreter
    if (![self initializePython]) {
        // Display detailed error dialog
        NSString *errorMessage = @"Failed to initialize Python interpreter.\n\n"
                                 @"Possible causes:\n"
                                 @"• Python.framework is missing or corrupted\n"
                                 @"• XeFM source files are missing from the bundle\n"
                                 @"• Incompatible Python version\n\n"
                                 @"Please reinstall XeFM or check Console.app for detailed error logs.";
        [self showErrorDialog:errorMessage];
        
        // Terminate application gracefully
        [NSApp terminate:self];
        return;
    }
    
    // Launch XeFM window in current process
    [self launchXeFMWindow];
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    // Clean up Python interpreter
    [self shutdownPython];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    // Single-window mode: terminate when window closes
    return YES;
}

- (NSMenu *)applicationDockMenu:(NSApplication *)sender {
    // Single-window mode: no custom Dock menu needed
    return nil;
}

#pragma mark - Python Management

- (BOOL)initializePython {
    // Get bundle paths
    NSBundle *mainBundle = [NSBundle mainBundle];
    // Use "Current" symlink to support any Python version
    NSString *frameworksPath = [[mainBundle privateFrameworksPath] 
        stringByAppendingPathComponent:@"Python.framework/Versions/Current"];
    NSString *resourcesPath = [mainBundle resourcePath];
    
    // Verify Python.framework exists
    NSFileManager *fileManager = [NSFileManager defaultManager];
    if (![fileManager fileExistsAtPath:frameworksPath]) {
        NSLog(@"ERROR: Python.framework not found at path: %@", frameworksPath);
        return NO;
    }
    
    // Configure Python initialization
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    
    // Set Python home to embedded framework
    PyStatus homeStatus = PyConfig_SetBytesString(&config, &config.home, 
        [frameworksPath UTF8String]);
    if (PyStatus_Exception(homeStatus)) {
        NSLog(@"ERROR: Failed to set Python home: %s", homeStatus.err_msg);
        PyConfig_Clear(&config);
        return NO;
    }
    
    // Set program name
    PyStatus nameStatus = PyConfig_SetBytesString(&config, &config.program_name, 
        "XeFM");
    if (PyStatus_Exception(nameStatus)) {
        NSLog(@"ERROR: Failed to set program name: %s", nameStatus.err_msg);
        PyConfig_Clear(&config);
        return NO;
    }
    
    // Initialize Python
    PyStatus status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    
    // Check for initialization errors
    if (PyStatus_Exception(status)) {
        NSLog(@"ERROR: Python initialization failed: %s", status.err_msg);
        NSLog(@"ERROR: Python home was set to: %@", frameworksPath);
        return NO;
    }
    
    // Configure sys.path to include bundled modules
    // Add Resources directory to sys.path so Python can find xefm and puikit
    NSString *packagesPath = [resourcesPath
        stringByAppendingPathComponent:@"python_packages"];

    // Verify required files exist: the xefm package's entry module and the PuiKit
    // toolkit package (both live at the Resources root; see build.sh).
    NSString *xefmPath = [resourcesPath stringByAppendingPathComponent:@"xefm/app.py"];
    NSString *puikitPath = [resourcesPath stringByAppendingPathComponent:@"puikit"];

    if (![fileManager fileExistsAtPath:xefmPath]) {
        NSLog(@"ERROR: XeFM entry script not found at: %@", xefmPath);
        Py_Finalize();
        return NO;
    }
    if (![fileManager fileExistsAtPath:puikitPath]) {
        NSLog(@"ERROR: PuiKit library directory not found at: %@", puikitPath);
        Py_Finalize();
        return NO;
    }

    // Add paths to sys.path
    // Add Resources directory so Python can import xefm and puikit
    PyRun_SimpleString("import sys");
    
    NSString *resourcesPathCmd = [NSString stringWithFormat:@"sys.path.insert(0, '%@')", resourcesPath];
    PyRun_SimpleString([resourcesPathCmd UTF8String]);
    
    NSString *packagesPathCmd = [NSString stringWithFormat:@"sys.path.insert(0, '%@')", packagesPath];
    PyRun_SimpleString([packagesPathCmd UTF8String]);
    
    // Check for Python errors after sys.path configuration
    if (PyErr_Occurred()) {
        NSLog(@"ERROR: Python error occurred during sys.path configuration");
        PyErr_Print();
        Py_Finalize();
        return NO;
    }
    
    pythonInitialized = YES;
    NSLog(@"Python initialized successfully");
    return YES;
}

- (void)shutdownPython {
    if (pythonInitialized) {
        Py_Finalize();
        pythonInitialized = NO;
        NSLog(@"Python finalized");
    }
}

- (void)dealloc {
    // Clean up if needed
    [super dealloc];
}

#pragma mark - Window Management

- (void)launchXeFMWindow {
    // Launch XeFM window in current process (single-window mode)
    
    if (!pythonInitialized) {
        NSLog(@"ERROR: Cannot launch XeFM window - Python not initialized");
        exit(1);
        return;
    }
    
    // Set up environment PATH to include common binary locations
    // This ensures SSH ProxyCommand can find tools like 'aws', 'gcloud', etc.
    [self setupEnvironmentPath];
    
    // Set up sys.argv to launch in the native macOS GUI backend, before the
    // entry module runs. xefm.app.main() parses these via argparse.
    PyRun_SimpleString("import sys");
    PyRun_SimpleString("sys.argv = ['XeFM', '--backend', 'gui']");

    // Import the XeFM entry module (Resources/xefm/app.py). Resources/ is on
    // sys.path, so the whole xefm package — app plus its siblings — resolves
    // from there.
    PyObject *xefmModule = PyImport_ImportModule("xefm.app");
    if (!xefmModule) {
        NSLog(@"ERROR: Failed to import xefm.app module");
        PyErr_Print();
        exit(1);
        return;
    }

    // Get main function
    PyObject *mainFunc = PyObject_GetAttrString(xefmModule, "main");
    if (!mainFunc || !PyCallable_Check(mainFunc)) {
        NSLog(@"ERROR: main function not found or not callable");
        Py_XDECREF(mainFunc);
        Py_DECREF(xefmModule);
        exit(1);
        return;
    }

    // Call main() - this will block until the window is closed
    NSLog(@"Calling main()");
    PyObject *result = PyObject_CallObject(mainFunc, NULL);

    if (!result) {
        NSLog(@"ERROR: main() failed");
        PyErr_Print();
    }

    // Clean up
    Py_XDECREF(result);
    Py_DECREF(mainFunc);
    Py_DECREF(xefmModule);

    // When main() returns, the window was closed
    NSLog(@"main() returned, terminating application");
    
    // Use exit() instead of [NSApp terminate:self] to avoid issues
    // when running directly from command line
    exit(0);
}

- (void)setupEnvironmentPath {
    // Get current PATH
    NSString *currentPath = [[[NSProcessInfo processInfo] environment] objectForKey:@"PATH"];
    if (!currentPath) {
        currentPath = @"";
    }
    
    // Common locations for CLI tools (aws, gcloud, etc.)
    NSArray *additionalPaths = @[
        @"/usr/local/bin",           // Homebrew (Intel Mac)
        @"/usr/bin",                 // System binaries
        @"/bin",                     // Core system binaries
        [@"~/bin" stringByExpandingTildeInPath],                    // User binaries
        [@"~/.local/bin" stringByExpandingTildeInPath]              // Python user binaries
    ];
    
    // Build new PATH by prepending additional paths
    NSMutableArray *pathComponents = [NSMutableArray array];
    
    // Add additional paths first (higher priority)
    for (NSString *path in additionalPaths) {
        // Check if path exists before adding
        BOOL isDirectory;
        if ([[NSFileManager defaultManager] fileExistsAtPath:path isDirectory:&isDirectory] && isDirectory) {
            [pathComponents addObject:path];
        }
    }
    
    // Add current PATH components
    if ([currentPath length] > 0) {
        [pathComponents addObjectsFromArray:[currentPath componentsSeparatedByString:@":"]];
    }
    
    // Remove duplicates while preserving order
    NSMutableArray *uniquePaths = [NSMutableArray array];
    NSMutableSet *seenPaths = [NSMutableSet set];
    for (NSString *path in pathComponents) {
        if (![seenPaths containsObject:path]) {
            [uniquePaths addObject:path];
            [seenPaths addObject:path];
        }
    }
    
    // Join into PATH string
    NSString *newPath = [uniquePaths componentsJoinedByString:@":"];
    
    // Set environment variable for current process
    setenv("PATH", [newPath UTF8String], 1);
    
    NSLog(@"Updated PATH: %@", newPath);
    
    // Also update Python's os.environ so subprocess calls see the new PATH
    NSString *pythonCmd = [NSString stringWithFormat:@"import os; os.environ['PATH'] = '%@'", 
                          [newPath stringByReplacingOccurrencesOfString:@"'" withString:@"\\'"]];
    PyRun_SimpleString([pythonCmd UTF8String]);
}

#pragma mark - Utility Methods

- (NSString *)getBundleResourcePath {
    NSBundle *mainBundle = [NSBundle mainBundle];
    return [mainBundle resourcePath];
}

- (void)showErrorDialog:(NSString *)message {
    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:@"XeFM Error"];
    [alert setInformativeText:message];
    [alert setAlertStyle:NSAlertStyleCritical];
    [alert addButtonWithTitle:@"OK"];
    [alert runModal];
}

@end
