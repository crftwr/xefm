//
//  XeFMAppDelegate.h
//  XeFM - Terminal File Manager
//
//  Application delegate for XeFM macOS app bundle.
//  Manages Python embedding, window lifecycle, and Dock integration.
//

#import <Cocoa/Cocoa.h>

@interface XeFMAppDelegate : NSObject <NSApplicationDelegate>

// Python initialization and shutdown
- (BOOL)initializePython;
- (void)shutdownPython;

// Window management
- (void)launchXeFMWindow;

// Utility methods
- (NSString *)getBundleResourcePath;
- (void)showErrorDialog:(NSString *)message;

@end
