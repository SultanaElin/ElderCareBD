import 'package:eldercare_bd/screens/caregiver_login_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('empty caregiver registration shows validation feedback', (
    tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: CaregiverLoginScreen()));

    await tester.ensureVisible(find.text('Register & Continue'));
    await tester.pumpAndSettle();
    expect(find.byType(ElevatedButton), findsOneWidget);
    await tester.tap(find.byType(ElevatedButton));
    await tester.pump(const Duration(milliseconds: 250));

    final snackBar = tester.widget<SnackBar>(
      find.byType(SnackBar, skipOffstage: false),
    );
    expect(
      (snackBar.content as Text).data,
      'Please enter a phone number or email.',
    );
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });
}
