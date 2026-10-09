import 'dart:convert';

import 'package:eldercare_bd/models/caregiver_verification.dart';
import 'package:eldercare_bd/services/api_service.dart';
import 'package:eldercare_bd/services/session_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test(
    'caregiver session stores token and clears stale patient selection',
    () async {
      await SessionService.saveSelectedPatient(
        patientId: 99,
        patientName: 'Previous caregiver patient',
      );
      await SessionService.savePendingVerification(
        PendingVerificationContext(
          caregiverId: 41,
          channel: CaregiverVerificationChannel.email,
          destinationHint: 'c***@example.invalid',
          expiresAt: DateTime.utc(2026, 9, 12, 10, 10),
          resendAvailableAt: DateTime.utc(2026, 9, 12, 10, 1),
        ),
      );

      await SessionService.saveCaregiverSession(
        caregiverId: 7,
        caregiverName: 'Authenticated Caregiver',
        authToken: 'secure-session-token',
      );

      expect(await SessionService.getCaregiverId(), 7);
      expect(
        await SessionService.getCaregiverName(),
        'Authenticated Caregiver',
      );
      expect(await SessionService.getAuthToken(), 'secure-session-token');
      expect(await SessionService.getSelectedPatientId(), isNull);
      expect(await SessionService.getSelectedPatientName(), isNull);
      expect(await SessionService.getPendingVerification(), isNull);

      await SessionService.clearSession();

      expect(await SessionService.getCaregiverId(), isNull);
      expect(await SessionService.getCaregiverName(), isNull);
      expect(await SessionService.getAuthToken(), isNull);
    },
  );

  test('pending verification stores only minimum non-secret context', () async {
    await SessionService.saveCaregiverSession(
      caregiverId: 7,
      caregiverName: 'Previous Caregiver',
      authToken: 'previous-token',
    );
    await SessionService.saveSelectedPatient(
      patientId: 99,
      patientName: 'Previous Patient',
    );
    final pending = PendingVerificationContext(
      caregiverId: 41,
      channel: CaregiverVerificationChannel.sms,
      destinationHint: '+880******678',
      expiresAt: DateTime.utc(2026, 9, 12, 10, 10),
      resendAvailableAt: DateTime.utc(2026, 9, 12, 10, 1),
    );

    await SessionService.savePendingVerification(pending);
    final restored = await SessionService.getPendingVerification();
    final prefs = await SharedPreferences.getInstance();
    final serialized = prefs.getString('pending_caregiver_verification');

    expect(restored?.caregiverId, 41);
    expect(restored?.channel, CaregiverVerificationChannel.sms);
    expect(restored?.destinationHint, '+880******678');
    expect(restored?.expiresAt.isUtc, isTrue);
    expect(serialized, isNotNull);
    expect(serialized, isNot(contains('042817')));
    expect(serialized, isNot(contains('password')));
    expect(serialized, isNot(contains('+8801712345678')));
    expect(prefs.getKeys(), {'pending_caregiver_verification'});
    expect(await SessionService.getCaregiverId(), isNull);
    expect(await SessionService.getCaregiverName(), isNull);
    expect(await SessionService.getAuthToken(), isNull);
    expect(await SessionService.getSelectedPatientId(), isNull);
    expect(await SessionService.getSelectedPatientName(), isNull);

    await SessionService.clearSession();
    expect(await SessionService.getPendingVerification(), isNull);
  });

  test('malformed pending verification is discarded safely', () async {
    SharedPreferences.setMockInitialValues({
      'pending_caregiver_verification': jsonEncode({
        'caregiver_id': 41,
        'channel': 'email',
        'destination_hint': 'c***@example.invalid',
        'expires_at': 'not-a-date',
        'resend_available_at': '2026-09-12T10:01:00Z',
      }),
    });

    expect(await SessionService.getPendingVerification(), isNull);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.containsKey('pending_caregiver_verification'), isFalse);
  });

  test('protected core GET requests send the stored bearer token', () async {
    SharedPreferences.setMockInitialValues({
      'auth_token': 'stored-bearer-token',
    });

    final requestedPaths = <String>[];
    await http.runWithClient(
      () async {
        final patients = await ApiService.getPatientsByCaregiver(
          caregiverId: 7,
        );
        final patient = await ApiService.getPatientById(patientId: 73);
        final history = await ApiService.getPatientAssessments(patientId: 73);

        expect(patients, isEmpty);
        expect(patient?['id'], 73);
        expect(history, isEmpty);
      },
      () {
        return MockClient((request) async {
          expect(
            request.headers['authorization'],
            'Bearer stored-bearer-token',
          );
          requestedPaths.add(request.url.path);

          if (request.url.path == '/patients/73') {
            return http.Response(
              jsonEncode({'id': 73, 'name': 'Patient'}),
              200,
            );
          }
          return http.Response('[]', 200);
        });
      },
    );

    expect(requestedPaths, [
      '/patients/caregiver/7',
      '/patients/73',
      '/assessments/patient/73',
    ]);
  });

  test('missing local token does not fabricate authorization', () async {
    await http.runWithClient(
      () async {
        final patients = await ApiService.getPatientsByCaregiver(
          caregiverId: 7,
        );
        expect(patients, isEmpty);
      },
      () {
        return MockClient((request) async {
          expect(request.headers.containsKey('authorization'), isFalse);
          return http.Response(
            jsonEncode({'detail': 'Authentication required.'}),
            401,
          );
        });
      },
    );
  });
}
