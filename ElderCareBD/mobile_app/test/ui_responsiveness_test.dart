import 'package:eldercare_bd/models/caregiver_verification.dart';
import 'package:eldercare_bd/screens/caregiver_login_screen.dart';
import 'package:eldercare_bd/screens/caregiver_otp_verification_screen.dart';
import 'package:eldercare_bd/screens/role_selection_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _pumpAtPhoneSize(
  WidgetTester tester,
  Widget home, {
  double textScale = 1,
}) async {
  tester.view.physicalSize = const Size(320, 780);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    MaterialApp(
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
      home: home,
    ),
  );
  await tester.pump();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('role selection is exception-free on a narrow phone', (
    tester,
  ) async {
    await _pumpAtPhoneSize(tester, const RoleSelectionScreen());

    expect(find.text('Caregiver / Family Member'), findsOneWidget);
    expect(find.text('SPL-3 Healthcare Prototype'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('registration remains usable with enlarged phone text', (
    tester,
  ) async {
    await _pumpAtPhoneSize(
      tester,
      const CaregiverLoginScreen(),
      textScale: 1.8,
    );

    await tester.scrollUntilVisible(
      find.text('Register & Continue'),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pump();

    expect(find.byKey(const Key('caregiver-identity-input')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('OTP remains usable with enlarged phone text', (tester) async {
    final now = DateTime.now().toUtc();
    await _pumpAtPhoneSize(
      tester,
      CaregiverOtpVerificationScreen(
        pending: PendingVerificationContext(
          caregiverId: 41,
          channel: CaregiverVerificationChannel.email,
          destinationHint: 'c***@example.invalid',
          expiresAt: now.add(const Duration(minutes: 10)),
          resendAvailableAt: now.subtract(const Duration(seconds: 1)),
        ),
      ),
      textScale: 1.8,
    );

    await tester.scrollUntilVisible(
      find.text('Return to caregiver login'),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pump();

    expect(find.byKey(const Key('caregiver-otp-input')), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}
