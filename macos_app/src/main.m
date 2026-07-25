/*
 * main.m - XeFM macOS Application Launcher
 *
 * This is the main entry point for the XeFM native macOS application.
 * It initializes NSApplication and sets up the application delegate
 * that will handle Python embedding and XeFM window creation.
 *
 * Requirements: 1.1, 14.1
 */

#import <Cocoa/Cocoa.h>
#import "XeFMAppDelegate.h"

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        // Create the shared NSApplication instance
        // This is the singleton that manages the application lifecycle
        NSApplication *app = [NSApplication sharedApplication];
        
        // Create and set the application delegate
        // The delegate handles application lifecycle events and Python embedding
        XeFMAppDelegate *delegate = [[XeFMAppDelegate alloc] init];
        [app setDelegate:delegate];
        
        // Start the main event loop
        // This call blocks until the application terminates
        [app run];
    }
    return 0;
}
