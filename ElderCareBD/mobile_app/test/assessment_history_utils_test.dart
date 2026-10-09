import 'package:eldercare_bd/utils/assessment_history_utils.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('assessment timestamp parsing', () {
    test('preserves the instant from an explicit UTC timestamp', () {
      final localTimestamp = parseAssessmentTimestampToLocal(
        '2026-08-17T17:13:43.478309Z',
      );

      expect(
        localTimestamp?.toUtc(),
        DateTime.utc(2026, 8, 17, 17, 13, 43, 478, 309),
      );
    });

    test('treats a historical offset-free timestamp as UTC', () {
      final localTimestamp = parseAssessmentTimestampToLocal(
        '2026-08-17T17:13:43.478309',
      );

      expect(
        localTimestamp?.toUtc(),
        DateTime.utc(2026, 8, 17, 17, 13, 43, 478, 309),
      );
    });
  });

  group('active assessment symptom labels', () {
    test('returns labels only for true symptom flags', () {
      final labels = activeAssessmentSymptomLabels({
        'chest_pain': true,
        'dizziness': false,
        'shortness_of_breath': false,
        'excessive_thirst': false,
        'fatigue': true,
        'blurred_vision': true,
      });

      expect(labels, ['Chest pain', 'Fatigue', 'Blurred vision']);
    });

    test('returns an empty list when no symptoms are recorded', () {
      final labels = activeAssessmentSymptomLabels({
        'chest_pain': false,
        'dizziness': false,
        'shortness_of_breath': false,
        'excessive_thirst': false,
        'fatigue': false,
        'blurred_vision': false,
      });

      expect(labels, isEmpty);
    });
  });
}
