import 'dart:convert';

import 'package:eldercare_bd/models/daily_observation.dart';
import 'package:eldercare_bd/services/api_service.dart';
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

Map<String, Object?> _response({int id = 9}) => {
  'id': id,
  'patient_id': 73,
  'observation_date': '2026-10-09',
  'recorded_at': '2026-10-09T08:00:00',
  'systolic_bp': 128.0,
  'diastolic_bp': 78.0,
  'glucose_value': null,
  'glucose_unit': null,
  'glucose_context': null,
  'pulse_bpm': 71.0,
  'spo2_percent': null,
  'temperature_value': null,
  'temperature_unit': null,
  'weight_kg': null,
  'symptoms': null,
  'notes': 'Morning reading',
  'created_at': '2026-10-09T08:00:00',
  'updated_at': '2026-10-09T08:00:00',
};

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({'auth_token': 'test-token'});
  });

  test(
    'GET today uses authenticated patient route and parses response',
    () async {
      final result = await _withClient((request) async {
        expect(request.method, 'GET');
        expect(
          request.url.toString(),
          '${ApiService.baseUrl}/patients/73/observations/today',
        );
        expect(request.headers['authorization'], 'Bearer test-token');
        return http.Response(jsonEncode(_response()), 200);
      }, () => ApiService.getTodayObservation(patientId: 73));
      expect(result!.id, 9);
      expect(result.values.notes, 'Morning reading');
    },
  );

  test('GET today maps 404 to an empty form state', () async {
    final result = await _withClient(
      (_) async =>
          http.Response(jsonEncode({'detail': 'Resource not found.'}), 404),
      () => ApiService.getTodayObservation(patientId: 73),
    );
    expect(result, isNull);
  });

  test('POST today omits missing optional values', () async {
    final result = await _withClient(
      (request) async {
        expect(request.method, 'POST');
        expect(request.headers['authorization'], 'Bearer test-token');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body, {'pulse_bpm': 71.0});
        return http.Response(jsonEncode(_response()), 201);
      },
      () {
        return ApiService.createTodayObservation(
          patientId: 73,
          observation: const DailyObservationDraft(pulseBpm: 71),
        );
      },
    );
    expect(result.patientId, 73);
  });

  test('PATCH sends explicit nulls so cleared values remain missing', () async {
    await _withClient(
      (request) async {
        expect(request.method, 'PATCH');
        expect(
          request.url.toString(),
          '${ApiService.baseUrl}/patients/73/observations/9',
        );
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['notes'], 'Updated');
        expect(body.containsKey('glucose_value'), isTrue);
        expect(body['glucose_value'], isNull);
        return http.Response(jsonEncode(_response()), 200);
      },
      () {
        return ApiService.updateObservation(
          patientId: 73,
          observationId: 9,
          observation: const DailyObservationDraft(notes: 'Updated'),
        );
      },
    );
  });

  test('backend status and validation detail remain available to UI', () async {
    await expectLater(
      _withClient(
        (_) async => http.Response(
          jsonEncode({
            'detail': [
              {'msg': 'SpO2 must be at most 100'},
            ],
          }),
          422,
        ),
        () => ApiService.createTodayObservation(
          patientId: 73,
          observation: const DailyObservationDraft(spo2Percent: 101),
        ),
      ),
      throwsA(
        isA<ApiException>()
            .having((error) => error.statusCode, 'status', 422)
            .having((error) => error.message, 'message', contains('SpO2')),
      ),
    );
  });
}
