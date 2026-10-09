import 'dart:convert';

import 'package:eldercare_bd/models/caregiver_verification.dart';
import 'package:eldercare_bd/screens/caregiver_login_screen.dart';
import 'package:eldercare_bd/screens/caregiver_otp_verification_screen.dart';
import 'package:eldercare_bd/services/session_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

PendingVerificationContext _pending({
  CaregiverVerificationChannel channel = CaregiverVerificationChannel.email,
  DateTime? resendAvailableAt,
}) {
  final now = DateTime.now().toUtc();
  return PendingVerificationContext(
    caregiverId: 41,
    channel: channel,
    destinationHint: channel == CaregiverVerificationChannel.email
        ? 'c***@example.invalid'
        : '+880******678',
    expiresAt: now.add(const Duration(minutes: 10)),
    resendAvailableAt:
        resendAvailableAt ?? now.subtract(const Duration(seconds: 1)),
  );
}

Map<String, dynamic> _requestJson(http.Request request) {
  return jsonDecode(request.body) as Map<String, dynamic>;
}

String _isoAfter(Duration duration) {
  return DateTime.now().toUtc().add(duration).toIso8601String();
}

void _configureLargeView(WidgetTester tester) {
  tester.view.physicalSize = const Size(900, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _disposeScreen(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('registration saves pending context and navigates to OTP', (
    tester,
  ) async {
    _configureLargeView(tester);

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          const MaterialApp(home: CaregiverLoginScreen()),
        );
        await tester.enterText(
          find.byKey(const Key('caregiver-name-input')),
          'Caregiver One',
        );
        await tester.enterText(
          find.byKey(const Key('caregiver-identity-input')),
          'caregiver@example.invalid',
        );
        await tester.enterText(
          find.byKey(const Key('caregiver-password-input')),
          'test-password',
        );
        await tester.tap(find.text('Register & Continue'));
        await tester.pumpAndSettle();

        expect(find.text('Verify Caregiver Account'), findsOneWidget);
        expect(find.textContaining('c***@example.invalid'), findsOneWidget);
        final pending = await SessionService.getPendingVerification();
        expect(pending?.caregiverId, 41);
        expect(pending?.channel, CaregiverVerificationChannel.email);
        expect(await SessionService.getAuthToken(), isNull);
        await _disposeScreen(tester);
      },
      () => MockClient((request) async {
        expect(request.url.path, '/auth/register-caregiver');
        expect(request.headers.containsKey('authorization'), isFalse);
        expect(_requestJson(request), {
          'name': 'Caregiver One',
          'phone_or_email': 'caregiver@example.invalid',
          'password': 'test-password',
          'channel': 'email',
        });
        return http.Response(
          jsonEncode({
            'message': 'Verification code sent.',
            'caregiver_id': 41,
            'verification_required': true,
            'channel': 'email',
            'destination_hint': 'c***@example.invalid',
            'expires_at': _isoAfter(const Duration(minutes: 10)),
            'resend_available_at': _isoAfter(const Duration(minutes: 1)),
          }),
          202,
        );
      }),
    );
  });

  testWidgets('pending login response resumes verification without a token', (
    tester,
  ) async {
    _configureLargeView(tester);

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          const MaterialApp(
            home: CaregiverLoginScreen(initialRegisterMode: false),
          ),
        );
        await tester.enterText(
          find.byKey(const Key('caregiver-identity-input')),
          '+8801712345678',
        );
        await tester.enterText(
          find.byKey(const Key('caregiver-password-input')),
          'test-password',
        );
        await tester.tap(find.text('Login & Continue'));
        await tester.pumpAndSettle();

        expect(find.text('Verify Caregiver Account'), findsOneWidget);
        expect(find.textContaining('+880******678'), findsOneWidget);
        expect(await SessionService.getAuthToken(), isNull);
        expect(
          (await SessionService.getPendingVerification())?.channel,
          CaregiverVerificationChannel.sms,
        );
        await _disposeScreen(tester);
      },
      () => MockClient((request) async {
        expect(request.url.path, '/auth/login-caregiver');
        return http.Response(
          jsonEncode({
            'detail': {
              'code': 'verification_required',
              'message': 'Verification required.',
              'caregiver_id': 41,
              'channel': 'sms',
              'destination_hint': '+880******678',
              'expires_at': _isoAfter(const Duration(minutes: 10)),
              'resend_available_at': _isoAfter(const Duration(minutes: 1)),
            },
          }),
          403,
        );
      }),
    );
  });

  testWidgets('OTP validation requires exactly six numeric digits', (
    tester,
  ) async {
    _configureLargeView(tester);
    await tester.pumpWidget(
      MaterialApp(home: CaregiverOtpVerificationScreen(pending: _pending())),
    );
    await tester.enterText(
      find.byKey(const Key('caregiver-otp-input')),
      '12345',
    );
    await tester.tap(find.text('Verify Code'));
    await tester.pump();

    expect(
      find.text('Enter the complete six-digit verification code.'),
      findsOneWidget,
    );
    await _disposeScreen(tester);
  });

  testWidgets('server OTP errors remain clear and attempt-aware', (
    tester,
  ) async {
    _configureLargeView(tester);
    var requestCount = 0;
    final responses = [
      {
        'code': 'invalid_otp',
        'message': 'unsafe backend detail',
        'attempts_remaining': 3,
      },
      {'code': 'otp_expired', 'message': 'unsafe backend detail'},
      {'code': 'otp_attempts_exhausted', 'message': 'unsafe backend detail'},
    ];

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          MaterialApp(
            home: CaregiverOtpVerificationScreen(pending: _pending()),
          ),
        );
        for (final expectedCode in [
          'invalid_otp',
          'otp_expired',
          'otp_attempts_exhausted',
        ]) {
          await tester.enterText(
            find.byKey(const Key('caregiver-otp-input')),
            '000001',
          );
          await tester.tap(find.text('Verify Code'));
          await tester.pumpAndSettle(const Duration(milliseconds: 50));
          expect(
            find.byKey(ValueKey('otp-feedback-$expectedCode')),
            findsOneWidget,
          );
        }
        expect(
          find.textContaining('Too many incorrect attempts'),
          findsOneWidget,
        );
        await _disposeScreen(tester);
      },
      () => MockClient((request) async {
        expect(request.url.path, '/auth/verify-otp');
        expect(_requestJson(request)['otp'], '000001');
        final detail = responses[requestCount++];
        return http.Response(jsonEncode({'detail': detail}), 400);
      }),
    );

    expect(requestCount, 3);
  });

  testWidgets('successful resend clears OTP and replaces pending timing', (
    tester,
  ) async {
    _configureLargeView(tester);

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          MaterialApp(
            home: CaregiverOtpVerificationScreen(pending: _pending()),
          ),
        );
        await tester.enterText(
          find.byKey(const Key('caregiver-otp-input')),
          '042817',
        );
        await tester.tap(find.byKey(const Key('resend-otp-button')));
        await tester.pumpAndSettle(const Duration(milliseconds: 50));

        final otpField = tester.widget<TextField>(
          find.byKey(const Key('caregiver-otp-input')),
        );
        expect(otpField.controller?.text, isEmpty);
        expect(
          find.byKey(const Key('otp-feedback-resend_success')),
          findsOneWidget,
        );
        final restored = await SessionService.getPendingVerification();
        expect(restored?.destinationHint, 'n***@example.invalid');
        final prefs = await SharedPreferences.getInstance();
        expect(
          prefs.getString('pending_caregiver_verification'),
          isNot(contains('042817')),
        );
        await _disposeScreen(tester);
      },
      () => MockClient((request) async {
        expect(request.url.path, '/auth/resend-otp');
        expect(_requestJson(request), {'caregiver_id': 41, 'channel': 'email'});
        return http.Response(
          jsonEncode({
            'message': 'New code sent.',
            'caregiver_id': 41,
            'verification_required': true,
            'channel': 'email',
            'destination_hint': 'n***@example.invalid',
            'expires_at': _isoAfter(const Duration(minutes: 10)),
            'resend_available_at': _isoAfter(const Duration(minutes: 1)),
          }),
          200,
        );
      }),
    );
  });

  testWidgets('resend cooldown disables request and displays countdown', (
    tester,
  ) async {
    _configureLargeView(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: CaregiverOtpVerificationScreen(
          pending: _pending(
            resendAvailableAt: DateTime.now().toUtc().add(
              const Duration(seconds: 30),
            ),
          ),
        ),
      ),
    );

    final button = tester.widget<TextButton>(
      find.byKey(const Key('resend-otp-button')),
    );
    expect(button.onPressed, isNull);
    expect(find.textContaining('Resend code in 00:'), findsOneWidget);
    await _disposeScreen(tester);
  });

  testWidgets(
    'verification success clears pending state and returns to login',
    (tester) async {
      _configureLargeView(tester);
      await SessionService.savePendingVerification(_pending());

      await http.runWithClient(
        () async {
          await tester.pumpWidget(
            MaterialApp(
              home: CaregiverOtpVerificationScreen(pending: _pending()),
            ),
          );
          await tester.enterText(
            find.byKey(const Key('caregiver-otp-input')),
            '042817',
          );
          await tester.tap(find.text('Verify Code'));
          await tester.pumpAndSettle();

          expect(find.text('Caregiver Login'), findsOneWidget);
          expect(find.text('Login & Continue'), findsOneWidget);
          expect(await SessionService.getPendingVerification(), isNull);
          expect(await SessionService.getAuthToken(), isNull);
        },
        () => MockClient((request) async {
          expect(request.url.path, '/auth/verify-otp');
          expect(_requestJson(request)['otp'], '042817');
          return http.Response(
            jsonEncode({
              'message': 'Caregiver verified.',
              'caregiver_id': 41,
              'verified': true,
              'verification_required': false,
            }),
            200,
          );
        }),
      );
    },
  );

  testWidgets('network failure shows a friendly message without raw details', (
    tester,
  ) async {
    _configureLargeView(tester);

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          MaterialApp(
            home: CaregiverOtpVerificationScreen(pending: _pending()),
          ),
        );
        await tester.enterText(
          find.byKey(const Key('caregiver-otp-input')),
          '042817',
        );
        await tester.tap(find.text('Verify Code'));
        await tester.pumpAndSettle(const Duration(milliseconds: 50));

        expect(
          find.text('Could not connect to the server. Please try again.'),
          findsOneWidget,
        );
        expect(find.textContaining('socket exploded'), findsNothing);
        await _disposeScreen(tester);
      },
      () => MockClient((request) async {
        throw http.ClientException('socket exploded', request.url);
      }),
    );
  });
}
