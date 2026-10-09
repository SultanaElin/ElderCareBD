import 'package:eldercare_bd/utils/submission_guard.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('prevents a second concurrent submission', () {
    final guard = SubmissionGuard();

    expect(guard.tryStart(), isTrue);
    expect(guard.isInProgress, isTrue);
    expect(guard.tryStart(), isFalse);
  });

  test('allows a later submission after the first finishes', () {
    final guard = SubmissionGuard();

    expect(guard.tryStart(), isTrue);
    guard.finish();
    expect(guard.isInProgress, isFalse);
    expect(guard.tryStart(), isTrue);
  });
}
