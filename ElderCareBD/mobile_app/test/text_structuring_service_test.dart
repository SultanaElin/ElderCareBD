import 'package:eldercare_bd/services/text_structuring_service.dart';
import 'package:flutter_test/flutter_test.dart';

ExtractionApplicationResult _apply(
  StructuredHealthData extraction, {
  String glucose = '',
  String systolicBp = '',
  String diastolicBp = '',
  bool chestPain = false,
  bool dizziness = false,
  bool shortnessOfBreath = false,
  bool excessiveThirst = false,
  bool fatigue = false,
  bool blurredVision = false,
}) {
  return extraction.applyPreservingManualValues(
    glucoseText: glucose,
    systolicBpText: systolicBp,
    diastolicBpText: diastolicBp,
    chestPain: chestPain,
    dizziness: dizziness,
    shortnessOfBreath: shortnessOfBreath,
    excessiveThirst: excessiveThirst,
    fatigue: fatigue,
    blurredVision: blurredVision,
  );
}

void main() {
  group('symptom extraction', () {
    test('detects chest pain', () {
      final result = TextStructuringService.extract(
        'The patient reports chest pain today.',
      );

      expect(result.chestPain, isTrue);
    });

    test('detects dizziness', () {
      final result = TextStructuringService.extract(
        'The patient feels dizzy when standing.',
      );

      expect(result.dizziness, isTrue);
    });

    test('detects shortness of breath', () {
      final result = TextStructuringService.extract(
        'Shortness of breath after walking.',
      );

      expect(result.shortnessOfBreath, isTrue);
    });

    test('detects excessive thirst', () {
      final result = TextStructuringService.extract(
        'The patient has excessive thirst.',
      );

      expect(result.excessiveThirst, isTrue);
    });

    test('detects fatigue', () {
      final result = TextStructuringService.extract(
        'Persistent fatigue was reported.',
      );

      expect(result.fatigue, isTrue);
    });

    test('detects blurred vision', () {
      final result = TextStructuringService.extract(
        'The patient reports blurred vision.',
      );

      expect(result.blurredVision, isTrue);
    });

    test('detects multiple symptoms in one note', () {
      final result = TextStructuringService.extract(
        'Patient has chest pain, fatigue, and dizziness.',
      );

      expect(result.chestPain, isTrue);
      expect(result.fatigue, isTrue);
      expect(result.dizziness, isTrue);
      expect(result.shortnessOfBreath, isNull);
    });

    test('preserves the known chest pain and fatigue regression case', () {
      const rawNote = 'chest pain and fatigue';
      final result = TextStructuringService.extract(rawNote);

      expect(rawNote, 'chest pain and fatigue');
      expect(result.chestPain, isTrue);
      expect(result.fatigue, isTrue);
      expect(result.dizziness, isNull);
      expect(result.shortnessOfBreath, isNull);
      expect(result.excessiveThirst, isNull);
      expect(result.blurredVision, isNull);
    });

    test('supports established Bangla aliases', () {
      final result = TextStructuringService.extract(
        'রোগীর বুকে ব্যথা, মাথা ঘোরা এবং চোখ ঝাপসা।',
      );

      expect(result.chestPain, isTrue);
      expect(result.dizziness, isTrue);
      expect(result.blurredVision, isTrue);
    });
  });

  group('measurement extraction', () {
    test('extracts glucose after its label', () {
      final result = TextStructuringService.extract('Glucose is 165 mg/dL.');

      expect(result.glucose, 165);
    });

    test('extracts glucose before its label', () {
      final result = TextStructuringService.extract(
        'Reading was 165 blood sugar.',
      );

      expect(result.glucose, 165);
    });

    test('extracts systolic and diastolic blood pressure', () {
      final result = TextStructuringService.extract('BP 145/90.');

      expect(result.systolicBp, 145);
      expect(result.diastolicBp, 90);
    });

    test('extracts a mixed note through one contract', () {
      final result = TextStructuringService.extract(
        'TASK7_RUNTIME_20260818: Glucose 165, BP 145/90, chest pain and fatigue.',
      );

      expect(result.glucose, 165);
      expect(result.systolicBp, 145);
      expect(result.diastolicBp, 90);
      expect(result.chestPain, isTrue);
      expect(result.fatigue, isTrue);
      expect(result.dizziness, isNull);
    });
  });

  group('safe application', () {
    test('fills empty measurements and adds detected symptoms', () {
      final extraction = TextStructuringService.extract(
        'Glucose 165, BP 145/90, chest pain.',
      );
      final result = _apply(extraction);

      expect(result.glucoseText, '165');
      expect(result.systolicBpText, '145');
      expect(result.diastolicBpText, '90');
      expect(result.chestPain, isTrue);
      expect(result.conflicts, isEmpty);
    });

    test('converts extracted mg/dL glucose for a mmol/L form field', () {
      final extraction = TextStructuringService.extract('Glucose 126 mg/dL.');
      final result = extraction.applyPreservingManualValues(
        glucoseText: '',
        systolicBpText: '',
        diastolicBpText: '',
        chestPain: false,
        dizziness: false,
        shortnessOfBreath: false,
        excessiveThirst: false,
        fatigue: false,
        blurredVision: false,
        glucoseTextUsesMmolL: true,
      );

      expect(result.glucoseText, '7');
      expect(result.conflicts, isEmpty);
    });

    test('preserves conflicting manual measurements and reports them', () {
      final extraction = TextStructuringService.extract(
        'Glucose 165 and BP 145/90.',
      );
      final result = _apply(extraction, glucose: '150', diastolicBp: '80');

      expect(result.glucoseText, '150');
      expect(result.systolicBpText, '145');
      expect(result.diastolicBpText, '80');
      expect(result.conflicts, hasLength(2));
      expect(result.conflicts.map((conflict) => conflict.field), [
        'Glucose',
        'Diastolic BP',
      ]);
    });

    test('does not report matching manual measurements as conflicts', () {
      final extraction = TextStructuringService.extract(
        'Glucose 165 and BP 145/90.',
      );
      final result = _apply(
        extraction,
        glucose: '165',
        systolicBp: '145',
        diastolicBp: '90',
      );

      expect(result.conflicts, isEmpty);
    });

    test('never clears a manually selected symptom', () {
      final extraction = TextStructuringService.extract(
        'No supported symptom phrase is present.',
      );
      final result = _apply(extraction, dizziness: true);

      expect(result.dizziness, isTrue);
      expect(result.chestPain, isFalse);
    });
  });

  group('unsupported and irrelevant text', () {
    test('does not invent values when nothing supported is present', () {
      final result = TextStructuringService.extract(
        'Patient ate breakfast and took the morning medicine.',
      );

      expect(result.hasSuggestions, isFalse);
      expect(result.glucose, isNull);
      expect(result.systolicBp, isNull);
      expect(result.diastolicBp, isNull);
      expect(result.chestPain, isNull);
      expect(result.dizziness, isNull);
      expect(result.shortnessOfBreath, isNull);
      expect(result.excessiveThirst, isNull);
      expect(result.fatigue, isNull);
      expect(result.blurredVision, isNull);
    });

    test('generic pain and vision words do not imply specific symptoms', () {
      final result = TextStructuringService.extract(
        'Knee pain noted before a routine vision appointment.',
      );

      expect(result.chestPain, isNull);
      expect(result.blurredVision, isNull);
    });
  });
}
