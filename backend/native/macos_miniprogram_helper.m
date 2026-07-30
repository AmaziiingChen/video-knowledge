#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <Foundation/Foundation.h>
#import <ImageIO/ImageIO.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#include <stdlib.h>
#include <unistd.h>

static void EmitJSON(id value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    NSString *json = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    printf("%s\n", json.UTF8String);
}

static BOOL AccessibilityTrusted(BOOL prompt) {
    NSDictionary *options = @{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @(prompt)};
    return AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
}

static BOOL ScreenCaptureTrusted(BOOL prompt) {
    if (@available(macOS 10.15, *)) {
        if (CGPreflightScreenCaptureAccess()) return YES;
        return prompt ? CGRequestScreenCaptureAccess() : NO;
    }
    return YES;
}

static NSArray *VisibleWindows(void) {
    CFArrayRef raw = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID
    );
    NSArray *windows = CFBridgingRelease(raw) ?: @[];
    NSMutableArray *result = [NSMutableArray array];
    for (NSDictionary *window in windows) {
        NSInteger layer = [window[(id)kCGWindowLayer] integerValue];
        if (layer != 0) continue;
        CGRect bounds = CGRectZero;
        if (!CGRectMakeWithDictionaryRepresentation(
                (__bridge CFDictionaryRef)window[(id)kCGWindowBounds], &bounds)) continue;
        if (bounds.size.width < 240 || bounds.size.height < 240) continue;
        NSString *owner = window[(id)kCGWindowOwnerName] ?: @"";
        NSString *name = window[(id)kCGWindowName] ?: @"";
        NSNumber *windowID = window[(id)kCGWindowNumber] ?: @0;
        NSNumber *pid = window[(id)kCGWindowOwnerPID] ?: @0;
        [result addObject:@{
            @"window_id": windowID,
            @"pid": pid,
            @"owner": owner,
            @"title": name,
            @"x": @(bounds.origin.x),
            @"y": @(bounds.origin.y),
            @"width": @(bounds.size.width),
            @"height": @(bounds.size.height),
        }];
    }
    return result;
}

static void PostMouse(CGEventType type, CGPoint point, CGMouseButton button) {
    CGEventRef event = CGEventCreateMouseEvent(NULL, type, point, button);
    if (event != NULL) {
        CGEventPost(kCGHIDEventTap, event);
        CFRelease(event);
    }
}

static int Click(double x, double y) {
    CGPoint point = CGPointMake(x, y);
    PostMouse(kCGEventMouseMoved, point, kCGMouseButtonLeft);
    usleep(30000);
    PostMouse(kCGEventLeftMouseDown, point, kCGMouseButtonLeft);
    usleep(50000);
    PostMouse(kCGEventLeftMouseUp, point, kCGMouseButtonLeft);
    return 0;
}

static int Scroll(double x, double y, int delta) {
    CGPoint point = CGPointMake(x, y);
    PostMouse(kCGEventMouseMoved, point, kCGMouseButtonLeft);
    usleep(30000);
    // Model a physical mouse wheel: a bounded series of non-continuous,
    // one-line notches. WeChat's mini-program webview ignores isolated pixel
    // gestures on some versions but accepts ordinary wheel events. Python
    // verifies the observed pixel displacement before taking another action.
    int logicalTicks = MIN(8, MAX(-8, delta));
    NSDictionary *globalDefaults = [[NSUserDefaults standardUserDefaults]
        persistentDomainForName:NSGlobalDomain];
    BOOL naturalScroll = [globalDefaults[@"com.apple.swipescrolldirection"] boolValue];
    int ticks = naturalScroll ? logicalTicks : -logicalTicks;
    if (ticks == 0) return 0;
    CGEventSourceRef source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState);
    if (source == NULL) return 3;
    int direction = ticks < 0 ? -1 : 1;
    for (int index = 0; index < abs(ticks); index += 1) {
        CGEventRef event = CGEventCreateScrollWheelEvent2(
            source, kCGScrollEventUnitLine, 1, direction, 0, 0
        );
        if (event == NULL) {
            CFRelease(source);
            return 3;
        }
        CGEventSetLocation(event, point);
        CGEventPost(kCGHIDEventTap, event);
        CFRelease(event);
        usleep(35000);
    }
    CFRelease(source);
    return 0;
}

static int PressKey(CGKeyCode code) {
    CGEventRef down = CGEventCreateKeyboardEvent(NULL, code, true);
    CGEventRef up = CGEventCreateKeyboardEvent(NULL, code, false);
    if (down == NULL || up == NULL) {
        if (down) CFRelease(down);
        if (up) CFRelease(up);
        return 3;
    }
    CGEventPost(kCGHIDEventTap, down);
    usleep(30000);
    CGEventPost(kCGHIDEventTap, up);
    CFRelease(down);
    CFRelease(up);
    return 0;
}

static int ActivateWindow(pid_t pid, NSString *targetTitle) {
    NSRunningApplication *app = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
    if (app == nil) return 3;
    [app unhide];
    BOOL activated = [app activateWithOptions:0];

    AXUIElementRef application = AXUIElementCreateApplication(pid);
    if (application == NULL) return activated ? 0 : 3;
    AXUIElementSetAttributeValue(application, kAXFrontmostAttribute, kCFBooleanTrue);

    BOOL raised = NO;
    if (targetTitle.length > 0) {
        CFTypeRef rawWindows = NULL;
        if (AXUIElementCopyAttributeValue(application, kAXWindowsAttribute, &rawWindows) == kAXErrorSuccess
                && rawWindows != NULL && CFGetTypeID(rawWindows) == CFArrayGetTypeID()) {
            NSArray *windows = CFBridgingRelease(rawWindows);
            for (id item in windows) {
                AXUIElementRef window = (__bridge AXUIElementRef)item;
                CFTypeRef rawTitle = NULL;
                if (AXUIElementCopyAttributeValue(window, kAXTitleAttribute, &rawTitle) != kAXErrorSuccess
                        || rawTitle == NULL) continue;
                NSString *title = CFBridgingRelease(rawTitle);
                if (![title isEqualToString:targetTitle]) continue;
                AXUIElementSetAttributeValue(application, kAXFocusedWindowAttribute, window);
                raised = AXUIElementPerformAction(window, kAXRaiseAction) == kAXErrorSuccess;
                break;
            }
        }
    }
    CFRelease(application);
    return (activated || raised) ? 0 : 3;
}

static int CaptureWindow(CGWindowID windowID, NSString *path) {
    if (@available(macOS 14.0, *)) {
        dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
        __block int result = 3;
        [SCShareableContent getShareableContentWithCompletionHandler:^(SCShareableContent *content, NSError *error) {
            if (error != nil || content == nil) {
                result = 4;
                dispatch_semaphore_signal(semaphore);
                return;
            }
            SCWindow *target = nil;
            for (SCWindow *window in content.windows) {
                if (window.windowID == windowID) {
                    target = window;
                    break;
                }
            }
            if (target == nil) {
                result = 5;
                dispatch_semaphore_signal(semaphore);
                return;
            }
            SCContentFilter *filter = [[SCContentFilter alloc] initWithDesktopIndependentWindow:target];
            SCStreamConfiguration *configuration = [[SCStreamConfiguration alloc] init];
            CGFloat scale = MAX(1.0, filter.pointPixelScale);
            configuration.width = MAX(1, (size_t)llround(filter.contentRect.size.width * scale));
            configuration.height = MAX(1, (size_t)llround(filter.contentRect.size.height * scale));
            configuration.showsCursor = NO;
            configuration.ignoreShadowsSingleWindow = YES;
            if (@available(macOS 14.2, *)) configuration.includeChildWindows = YES;
            [SCScreenshotManager captureImageWithFilter:filter configuration:configuration completionHandler:^(CGImageRef image, NSError *captureError) {
                if (captureError == nil && image != NULL) {
                    NSURL *url = [NSURL fileURLWithPath:path];
                    CGImageDestinationRef destination = CGImageDestinationCreateWithURL(
                        (__bridge CFURLRef)url, CFSTR("public.png"), 1, NULL
                    );
                    if (destination != NULL) {
                        CGImageDestinationAddImage(destination, image, NULL);
                        result = CGImageDestinationFinalize(destination) ? 0 : 7;
                        CFRelease(destination);
                    } else {
                        result = 6;
                    }
                } else {
                    result = 8;
                }
                dispatch_semaphore_signal(semaphore);
            }];
        }];
        long timedOut = dispatch_semaphore_wait(
            semaphore, dispatch_time(DISPATCH_TIME_NOW, 25 * NSEC_PER_SEC)
        );
        return timedOut == 0 ? result : 9;
    }
    return 10;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        if (argc < 2) {
            EmitJSON(@{@"error": @"missing_command"});
            return 2;
        }
        NSString *command = [NSString stringWithUTF8String:argv[1]];
        if ([command isEqualToString:@"status"]) {
            BOOL prompt = argc >= 3 && strcmp(argv[2], "--prompt") == 0;
            double idleSeconds = CGEventSourceSecondsSinceLastEventType(
                kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType
            );
            EmitJSON(@{
                @"available": @YES,
                @"accessibility_granted": @(AccessibilityTrusted(prompt)),
                @"screen_capture_granted": @(ScreenCaptureTrusted(prompt)),
                @"user_idle_seconds": @(MAX(0, idleSeconds)),
                @"windows": VisibleWindows(),
            });
            return 0;
        }
        if ([command isEqualToString:@"activate"] && argc >= 3) {
            pid_t pid = (pid_t)strtol(argv[2], NULL, 10);
            NSString *title = argc >= 4 ? [NSString stringWithUTF8String:argv[3]] : @"";
            int result = ActivateWindow(pid, title);
            EmitJSON(@{@"ok": @(result == 0)});
            return result;
        }
        if ([command isEqualToString:@"capture"] && argc == 4) {
            CGWindowID windowID = (CGWindowID)strtoul(argv[2], NULL, 10);
            NSString *path = [NSString stringWithUTF8String:argv[3]];
            return CaptureWindow(windowID, path);
        }
        if ([command isEqualToString:@"click"] && argc == 4) {
            return Click(strtod(argv[2], NULL), strtod(argv[3], NULL));
        }
        if ([command isEqualToString:@"scroll"] && argc == 5) {
            return Scroll(strtod(argv[2], NULL), strtod(argv[3], NULL), atoi(argv[4]));
        }
        if ([command isEqualToString:@"escape"]) {
            return PressKey((CGKeyCode)53);
        }
        EmitJSON(@{@"error": @"invalid_command"});
        return 2;
    }
}
