#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

static void EmitJSON(id value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    NSString *json = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    printf("%s\n", json.UTF8String);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) {
            EmitJSON(@{@"available": @NO, @"error": @"missing_image_path"});
            return 2;
        }
        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSImage *image = [[NSImage alloc] initWithContentsOfFile:path];
        CGImageRef cgImage = [image CGImageForProposedRect:NULL context:nil hints:nil];
        if (cgImage == NULL) {
            EmitJSON(@{@"available": @NO, @"error": @"image_unreadable"});
            return 3;
        }

        size_t pixelWidth = CGImageGetWidth(cgImage);
        size_t pixelHeight = CGImageGetHeight(cgImage);
        VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
        request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
        request.usesLanguageCorrection = YES;
        request.minimumTextHeight = 0.009;
        if (@available(macOS 13.0, *)) {
            request.automaticallyDetectsLanguage = YES;
        } else {
            request.recognitionLanguages = @[@"zh-Hans", @"en-US"];
        }

        VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:cgImage options:@{}];
        NSError *error = nil;
        if (![handler performRequests:@[request] error:&error]) {
            EmitJSON(@{@"available": @NO, @"error": @"vision_failed"});
            return 4;
        }

        NSMutableArray *lines = [NSMutableArray array];
        for (VNRecognizedTextObservation *observation in request.results ?: @[]) {
            VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
            if (candidate.string.length == 0) continue;
            CGRect box = observation.boundingBox;
            double x = box.origin.x * pixelWidth;
            double y = (1.0 - box.origin.y - box.size.height) * pixelHeight;
            [lines addObject:@{
                @"text": candidate.string,
                @"confidence": @(candidate.confidence),
                @"x": @(x),
                @"y": @(y),
                @"width": @(box.size.width * pixelWidth),
                @"height": @(box.size.height * pixelHeight),
            }];
        }
        [lines sortUsingComparator:^NSComparisonResult(NSDictionary *left, NSDictionary *right) {
            double ly = [left[@"y"] doubleValue];
            double ry = [right[@"y"] doubleValue];
            if (fabs(ly - ry) > 8.0) return ly < ry ? NSOrderedAscending : NSOrderedDescending;
            return [left[@"x"] doubleValue] < [right[@"x"] doubleValue]
                ? NSOrderedAscending : NSOrderedDescending;
        }];
        EmitJSON(@{
            @"available": @YES,
            @"width": @(pixelWidth),
            @"height": @(pixelHeight),
            @"lines": lines,
        });
        return 0;
    }
}
