import 'dart:convert';

import 'package:eldercare_bd/models/caregiver_verification.dart';
import 'package:eldercare_bd/screens/splash_screen.dart';
import 'package:eldercare_bd/services/session_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

PendingVerificationContext _pending() {
  final now = DateTime.now().toUtc();
  return PendingVerificationContext(
    caregiverId: 41,
    channel: CaregiverVerificationChannel.email,
    destinationHint: 'c***@example.invalid',
    expiresAt: now.add(const Duration(minutes: 10)),
    resendAvailableAt: now.add(const Duration(seconds: 30)),
  );
}

Future<void> _disposeScreen(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('splash resumes a valid pending verification after restart', (
    tester,
  ) async {
    await SessionService.savePendingVerification(_pending());

    await tester.pumpWidget(const MaterialApp(home: SplashScreen()));
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();

    expect(find.text('Verify Caregiver Account'), findsOneWidget);
    expect(find.textContaining('c***@example.invalid'), findsOneWidget);
    expect(find.byKey(const Key('caregiver-otp-input')), findsOneWidget);
    await _disposeScreen(tester);
  });

  testWidgets('splash discards malformed pending state and shows role choice', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({
      'pending_caregiver_verification': jsonEncode({
        'caregiver_id': 41,
        'channel': 'email',
        'destination_hint': 'c***@example.invalid',
        'expires_at': 'malformed',
        'resend_available_at': '2026-09-12T10:01:00Z',
      }),
    });

    await tester.pumpWidget(const MaterialApp(home: SplashScreen()));
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();

    expect(find.text('Caregiver / Family Member'), findsOneWidget);
    expect(find.text('Verify Caregiver Account'), findsNothing);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.containsKey('pending_caregiver_verification'), isFalse);
  });
}
