import 'dart:convert';
import 'dart:typed_data';

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

Map<String, dynamic> _requestJson(http.Request request) {
  return jsonDecode(request.body) as Map<String, dynamic>;
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({
      'auth_token': 'prescription-test-token',
    });
  });

  group('prescription transport contract', () {
    test(
      'upload uses bearer-authenticated multipart with its own boundary',
      () async {
        final result = await _withClient(
          (request) async {
            expect(request.method, 'POST');
            expect(
              request.url.toString(),
              '${ApiService.baseUrl}/prescriptions/',
            );
            expect(
              request.headers['authorization'],
              'Bearer prescription-test-token',
            );

            final contentType = request.headers['content-type'];
            expect(contentType, startsWith('multipart/form-data; boundary='));
            expect(contentType, isNot(contains('application/json')));
            expect(request.body, contains('name="patient_id"'));
            expect(request.body, contains('73'));
            expect(request.body, contains('filename="prescription.png"'));

            return http.Response(
              jsonEncode({
                'message': 'Prescription saved successfully',
                'prescription_id': 91,
                'patient_id': 73,
                'has_image': true,
                'ocr_status': 'uploaded',
              }),
              200,
            );
          },
          () => ApiService.createPrescription(
            patientId: 73,
            doctorName: 'Dr Test',
            note: 'Review in one week',
            imageBytes: Uint8List.fromList([1, 2, 3]),
            imageName: 'prescription.png',
          ),
        );

        expect(result['statusCode'], 200);
        expect((result['body'] as Map<String, dynamic>)['prescription_id'], 91);
        expect((result['body'] as Map<String, dynamic>)['has_image'], isTrue);
      },
    );

    test(
      'patient prescription history includes bearer authentication',
      () async {
        final prescriptions = await _withClient((request) async {
          expect(request.method, 'GET');
          expect(
            request.url.toString(),
            '${ApiService.baseUrl}/prescriptions/patient/73',
          );
          expect(
            request.headers['authorization'],
            'Bearer prescription-test-token',
          );
          expect(request.headers.containsKey('content-type'), isFalse);
          return http.Response(
            jsonEncode([
              {'id': 91, 'patient_id': 73, 'has_image': true},
            ]),
            200,
          );
        }, () => ApiService.getPatientPrescriptions(patientId: 73));

        expect(prescriptions, hasLength(1));
        expect((prescriptions.single as Map<String, dynamic>)['id'], 91);
      },
    );

    test('malformed prescription response is normalized safely', () async {
      final result = await _withClient(
        (_) async => http.Response('<html>invalid</html>', 200),
        () => ApiService.createPrescription(
          patientId: 73,
          doctorName: '',
          note: '',
        ),
      );

      expect(result['statusCode'], 200);
      expect(result['body'], {
        'detail': 'The server returned an invalid response.',
      });
    });

    test('prescription upload maps network failures safely', () async {
      await expectLater(
        _withClient(
          (request) async => throw http.ClientException('offline', request.url),
          () => ApiService.createPrescription(
            patientId: 73,
            doctorName: 'Dr Test',
            note: '',
          ),
        ),
        throwsA(
          isA<ApiException>().having(
            (error) => error.message,
            'message',
            'Could not connect to the server. Please try again.',
          ),
        ),
      );
    });
  });

  test(
    'manual medicines use the complete atomic confirmation payload',
    () async {
      final reviewedMedicines = <Map<String, Object?>>[
        {
          'name': 'Medicine A',
          'strength': '500 mg',
          'dosage': '1 tablet',
          'frequency': 'Twice daily',
          'duration': '7 days',
          'instructions': 'After meals',
        },
      ];

      final result = await _withClient(
        (request) async {
          expect(request.method, 'POST');
          expect(
            request.url.toString(),
            '${ApiService.baseUrl}/prescriptions/91/confirm',
          );
          expect(
            request.headers['authorization'],
            'Bearer prescription-test-token',
          );
          expect(request.headers['content-type'], contains('application/json'));
          expect(_requestJson(request), {'medicines': reviewedMedicines});

          return http.Response(
            jsonEncode({
              'message': 'Prescription medicines confirmed successfully',
              'prescription_id': 91,
              'patient_id': 73,
              'confirmed_at': '2026-08-22T12:00:00Z',
              'already_confirmed': false,
              'medicines': [
                {'id': 201, ...reviewedMedicines.first},
              ],
            }),
            200,
          );
        },
        () => ApiService.confirmPrescription(
          prescriptionId: 91,
          medicines: reviewedMedicines,
        ),
      );

      expect(result['statusCode'], 200);
      expect(
        (result['body'] as Map<String, dynamic>)['already_confirmed'],
        isFalse,
      );
    },
  );

  test(
    'standalone medicine creation sends bearer and structured fields',
    () async {
      final result = await _withClient(
        (request) async {
          expect(request.method, 'POST');
          expect(request.url.toString(), '${ApiService.baseUrl}/medicines/');
          expect(
            request.headers['authorization'],
            'Bearer prescription-test-token',
          );
          expect(_requestJson(request), {
            'patient_id': 73,
            'prescription_id': null,
            'name': 'Medicine B',
            'strength': '250 mg',
            'dosage': '2 tablets',
            'frequency': 'Once daily',
            'duration': '5 days',
            'instructions': 'With food',
            'quantity': 10,
            'daily_dose': 2,
            'start_date': '2026-08-22',
            'run_out_date': '2026-08-27',
            'alert_date': '2026-08-24',
            'note': 'Tracker-compatible entry',
          });
          return http.Response(
            jsonEncode({
              'message': 'Medicine record saved successfully',
              'medicine_id': 202,
              'name': 'Medicine B',
            }),
            200,
          );
        },
        () => ApiService.createMedicine(
          patientId: 73,
          name: 'Medicine B',
          strength: '250 mg',
          dosage: '2 tablets',
          frequency: 'Once daily',
          duration: '5 days',
          instructions: 'With food',
          quantity: 10,
          dailyDose: 2,
          startDate: '2026-08-22',
          runOutDate: '2026-08-27',
          alertDate: '2026-08-24',
          note: 'Tracker-compatible entry',
        ),
      );

      expect(result['statusCode'], 200);
      expect((result['body'] as Map<String, dynamic>)['medicine_id'], 202);
    },
  );

  test('protected prescription image sends bearer and returns bytes', () async {
    final expectedBytes = Uint8List.fromList([0x89, 0x50, 0x4e, 0x47]);

    final bytes = await _withClient((request) async {
      expect(request.method, 'GET');
      expect(
        request.url.toString(),
        '${ApiService.baseUrl}/prescriptions/91/image',
      );
      expect(
        request.headers['authorization'],
        'Bearer prescription-test-token',
      );
      expect(request.headers.containsKey('content-type'), isFalse);
      return http.Response.bytes(
        expectedBytes,
        200,
        headers: {'content-type': 'image/png'},
      );
    }, () => ApiService.getPrescriptionImage(prescriptionId: 91));

    expect(bytes, expectedBytes);
  });

  test('network failures map to a stable API exception', () async {
    await expectLater(
      _withClient(
        (request) async => throw http.ClientException('offline', request.url),
        () => ApiService.createMedicine(patientId: 73, name: 'Medicine C'),
      ),
      throwsA(
        isA<ApiException>().having(
          (error) => error.message,
          'message',
          'Could not connect to the server. Please try again.',
        ),
      ),
    );
  });

  test(
    'missing token blocks a sensitive request before network access',
    () async {
      SharedPreferences.setMockInitialValues({});
      var networkCalled = false;

      await expectLater(
        _withClient((_) async {
          networkCalled = true;
          return http.Response('[]', 200);
        }, () => ApiService.getPatientMedicines(patientId: 73)),
        throwsA(
          isA<ApiException>().having(
            (error) => error.message,
            'message',
            'Your session has expired. Please sign in again.',
          ),
        ),
      );
      expect(networkCalled, isFalse);
    },
  );

  test('bearer token is trimmed before it is sent', () async {
    SharedPreferences.setMockInitialValues({'auth_token': '  trimmed-token  '});

    await _withClient((request) async {
      expect(request.headers['authorization'], 'Bearer trimmed-token');
      return http.Response('[]', 200);
    }, () => ApiService.getPatientMedicines(patientId: 73));
  });
}
