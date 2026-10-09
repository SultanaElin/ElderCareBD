import 'dart:convert';
import 'dart:typed_data';

import 'package:eldercare_bd/screens/prescription_input_screen.dart';
import 'package:eldercare_bd/services/prescription_image_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

final Uint8List _imageBytes = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
);

class _ReviewPicker implements PrescriptionImagePicker {
  @override
  Future<PickedPrescriptionImage?> pick(PrescriptionImageSource source) async {
    return PickedPrescriptionImage(bytes: _imageBytes, name: 'synthetic.png');
  }

  @override
  Future<PickedPrescriptionImage?> recoverLostImage() async => null;
}

Future<T> _withClient<T>(
  Future<http.Response> Function(http.Request request) handler,
  Future<T> Function() action,
) {
  return http.runWithClient(action, () => MockClient(handler));
}

Future<void> _tapVisible(WidgetTester tester, Finder finder) async {
  ScaffoldMessenger.of(
    tester.element(find.byType(Scaffold).first),
  ).clearSnackBars();
  await tester.pumpAndSettle();
  await Scrollable.ensureVisible(tester.element(finder), alignment: 0.5);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

http.Response _uploadResponse() {
  return http.Response(
    jsonEncode({
      'prescription_id': 91,
      'patient_id': 73,
      'has_image': true,
      'ocr_status': 'uploaded',
    }),
    200,
  );
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({
      'auth_token': 'ocr-test-token',
      'selected_patient_id': 73,
      'selected_patient_name': 'Synthetic Patient',
    });
  });

  testWidgets(
    'OCR failure preserves manual fallback and never confirms automatically',
    (tester) async {
      var confirmationRequests = 0;

      await _withClient(
        (request) async {
          if (request.url.path == '/prescriptions/') return _uploadResponse();
          if (request.url.path == '/prescriptions/91/extract') {
            return http.Response(
              jsonEncode({
                'prescription_id': 91,
                'ocr_status': 'failed',
                'ocr_engine': 'tesseract',
                'ocr_languages': ['eng'],
                'ocr_text': null,
                'candidates': <Object>[],
                'warnings': ['The image could not be read.'],
                'reused': false,
              }),
              200,
            );
          }
          if (request.url.path == '/prescriptions/91/confirm') {
            confirmationRequests += 1;
            return http.Response('{}', 200);
          }
          throw StateError('Unexpected request: ${request.url}');
        },
        () async {
          await tester.pumpWidget(
            MaterialApp(
              home: PrescriptionInputScreen(imagePicker: _ReviewPicker()),
            ),
          );
          await tester.pumpAndSettle();

          await _tapVisible(tester, find.text('Choose from gallery'));
          await _tapVisible(tester, find.text('Upload Prescription'));
          expect(confirmationRequests, 0);

          await _tapVisible(tester, find.text('Extract Medicines'));
          expect(confirmationRequests, 0);
          expect(
            find.text('Extraction failed — manual entry available'),
            findsOneWidget,
          );
          expect(find.text('Add a missed medicine'), findsOneWidget);

          final name = find.byKey(const Key('manual-medicine-name'));
          await tester.ensureVisible(name);
          await tester.enterText(name, 'Manually reviewed medicine');
          await _tapVisible(
            tester,
            find.byKey(const Key('add-manual-medicine')),
          );
          expect(find.text('Manual entry'), findsOneWidget);
          expect(confirmationRequests, 0);
        },
      );
    },
  );

  testWidgets(
    'candidate editing/add/remove creates payload only after explicit confirm',
    (tester) async {
      Map<String, dynamic>? confirmationBody;
      var confirmationRequests = 0;

      await _withClient(
        (request) async {
          if (request.url.path == '/prescriptions/') return _uploadResponse();
          if (request.url.path == '/prescriptions/91/extract') {
            return http.Response(
              jsonEncode({
                'prescription_id': 91,
                'ocr_status': 'ready',
                'ocr_engine': 'tesseract',
                'ocr_languages': ['eng'],
                'ocr_text': 'Tab. Napa? 500 mg',
                'candidates': [
                  {
                    'name': 'Napa?',
                    'strength': '500 mg',
                    'dosage': null,
                    'frequency': null,
                    'duration': null,
                    'instructions': null,
                    'source_line': 'Tab. Napa? 500 mg',
                    'confidence': 'low',
                    'warnings': ['Medicine name uncertain'],
                  },
                ],
                'warnings': ['Review all OCR fields'],
                'reused': false,
              }),
              200,
            );
          }
          if (request.url.path == '/prescriptions/91/confirm') {
            confirmationRequests += 1;
            confirmationBody = jsonDecode(request.body) as Map<String, dynamic>;
            return http.Response(
              jsonEncode({
                'prescription_id': 91,
                'already_confirmed': false,
                'medicines': <Object>[],
              }),
              200,
            );
          }
          throw StateError('Unexpected request: ${request.url}');
        },
        () async {
          await tester.pumpWidget(
            MaterialApp(
              home: PrescriptionInputScreen(imagePicker: _ReviewPicker()),
            ),
          );
          await tester.pumpAndSettle();
          await _tapVisible(tester, find.text('Choose from gallery'));
          await _tapVisible(tester, find.text('Upload Prescription'));
          await _tapVisible(tester, find.text('Extract Medicines'));

          expect(confirmationRequests, 0);
          expect(find.text('Low confidence'), findsOneWidget);
          final candidateName = find.byKey(const ValueKey('medicine-1-name'));
          await tester.ensureVisible(candidateName);
          await tester.enterText(candidateName, 'Napa');
          await tester.pump();

          final manualName = find.byKey(const Key('manual-medicine-name'));
          await tester.ensureVisible(manualName);
          await tester.enterText(manualName, 'Missed Medicine');
          await _tapVisible(
            tester,
            find.byKey(const Key('add-manual-medicine')),
          );
          expect(find.text('Manual entry'), findsOneWidget);

          await _tapVisible(
            tester,
            find.byKey(const ValueKey('delete-medicine-2')),
          );
          expect(find.text('Manual entry'), findsNothing);
          expect(confirmationRequests, 0);

          await _tapVisible(tester, find.text('Confirm Reviewed Medicines'));
          expect(confirmationRequests, 1);
          expect(confirmationBody, {
            'medicines': [
              {
                'name': 'Napa',
                'strength': '500 mg',
                'dosage': null,
                'frequency': null,
                'duration': null,
                'instructions': null,
              },
            ],
          });
        },
      );
    },
  );
}
