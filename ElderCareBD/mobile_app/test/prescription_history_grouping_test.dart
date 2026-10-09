import 'dart:convert';

import 'package:eldercare_bd/screens/history_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<T> _withClient<T>(
  Future<http.Response> Function(http.Request request) handler,
  Future<T> Function() action,
) {
  return http.runWithClient(action, () => MockClient(handler));
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({
      'auth_token': 'history-test-token',
      'selected_patient_id': 73,
      'selected_patient_name': 'Synthetic Patient',
    });
  });

  testWidgets('history groups confirmed medicine fields under prescription', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await _withClient(
      (request) async {
        expect(request.headers['authorization'], 'Bearer history-test-token');
        if (request.url.path == '/assessments/patient/73') {
          return http.Response('[]', 200);
        }
        if (request.url.path == '/prescriptions/patient/73') {
          return http.Response(
            jsonEncode([
              {
                'id': 91,
                'patient_id': 73,
                'doctor_name': 'Dr Synthetic',
                'note': '',
                'has_image': false,
                'ocr_status': 'confirmed',
                'created_at': '2026-08-23T10:00:00Z',
                'medicines': [
                  {
                    'id': 201,
                    'name': 'Napa',
                    'strength': '500 mg',
                    'dosage': '1 tablet',
                    'frequency': 'Twice daily',
                    'duration': '5 days',
                    'instructions': 'After meals',
                  },
                ],
              },
            ]),
            200,
          );
        }
        if (request.url.path == '/medicines/patient/73') {
          return http.Response('[]', 200);
        }
        throw StateError('Unexpected request: ${request.url}');
      },
      () async {
        await tester.pumpWidget(const MaterialApp(home: HistoryScreen()));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(Tab, 'Prescriptions'));
        await tester.pumpAndSettle();

        expect(find.text('Confirmed medicines (1)'), findsOneWidget);
        expect(find.text('Napa'), findsOneWidget);
        expect(find.text('Strength: 500 mg'), findsOneWidget);
        expect(find.text('Dose amount: 1 tablet'), findsOneWidget);
        expect(find.text('Frequency: Twice daily'), findsOneWidget);
        expect(find.text('Duration: 5 days'), findsOneWidget);
        expect(find.text('Instructions: After meals'), findsOneWidget);
      },
    );
  });
}
