import 'package:eldercare_bd/services/prediction_service.dart';
import 'package:flutter_test/flutter_test.dart';

RiskPredictionResult _predict({
  int age = 59,
  int glucose = 109,
  int systolicBp = 129,
  int diastolicBp = 84,
  double bmi = 24.9,
  bool chestPain = false,
  bool dizziness = false,
  bool shortnessOfBreath = false,
  bool excessiveThirst = false,
  bool fatigue = false,
  bool blurredVision = false,
}) {
  return PredictionService.predict(
    RiskPredictionInput(
      age: age,
      glucose: glucose,
      systolicBp: systolicBp,
      diastolicBp: diastolicBp,
      bmi: bmi,
      chestPain: chestPain,
      dizziness: dizziness,
      shortnessOfBreath: shortnessOfBreath,
      excessiveThirst: excessiveThirst,
      fatigue: fatigue,
      blurredVision: blurredVision,
    ),
  );
}

void _expectScores(
  RiskPredictionResult result, {
  required int diabetes,
  required int heart,
}) {
  expect(result.diabetesScore, diabetes);
  expect(result.heartScore, heart);
}

void main() {
  group('age boundary', () {
    test('below 60 adds no age score', () {
      _expectScores(_predict(age: 59), diabetes: 0, heart: 0);
    });

    test('exactly 60 adds one point to both scores', () {
      _expectScores(_predict(age: 60), diabetes: 1, heart: 1);
    });
  });

  group('glucose boundaries', () {
    test('below 110 adds no diabetes score', () {
      _expectScores(_predict(glucose: 109), diabetes: 0, heart: 0);
    });

    test('exactly 110 adds one diabetes point', () {
      _expectScores(_predict(glucose: 110), diabetes: 1, heart: 0);
    });

    test('exactly 140 adds two diabetes points', () {
      _expectScores(_predict(glucose: 140), diabetes: 2, heart: 0);
    });

    test('exactly 180 adds three diabetes points', () {
      _expectScores(_predict(glucose: 180), diabetes: 3, heart: 0);
    });

    test('above 180 remains three diabetes points', () {
      _expectScores(_predict(glucose: 181), diabetes: 3, heart: 0);
    });
  });

  group('BMI boundaries', () {
    test('below 25 adds no BMI score', () {
      _expectScores(_predict(bmi: 24.9), diabetes: 0, heart: 0);
    });

    test('exactly 25 adds one point to both scores', () {
      _expectScores(_predict(bmi: 25), diabetes: 1, heart: 1);
    });

    test('exactly 30 adds two diabetes points and one heart point', () {
      _expectScores(_predict(bmi: 30), diabetes: 2, heart: 1);
    });

    test('above 30 keeps the highest BMI contribution', () {
      _expectScores(_predict(bmi: 30.1), diabetes: 2, heart: 1);
    });
  });

  group('blood-pressure boundaries', () {
    test('below 130 systolic and 85 diastolic adds no heart score', () {
      _expectScores(
        _predict(systolicBp: 129, diastolicBp: 84),
        diabetes: 0,
        heart: 0,
      );
    });

    test('exactly 130 systolic adds one heart point', () {
      _expectScores(
        _predict(systolicBp: 130, diastolicBp: 84),
        diabetes: 0,
        heart: 1,
      );
    });

    test('exactly 85 diastolic adds one heart point', () {
      _expectScores(
        _predict(systolicBp: 129, diastolicBp: 85),
        diabetes: 0,
        heart: 1,
      );
    });

    test('diastolic 80 alone remains below the live-screen boundary', () {
      _expectScores(
        _predict(systolicBp: 129, diastolicBp: 80),
        diabetes: 0,
        heart: 0,
      );
    });

    test('exactly 140 systolic adds two heart points', () {
      _expectScores(
        _predict(systolicBp: 140, diastolicBp: 84),
        diabetes: 0,
        heart: 2,
      );
    });

    test('exactly 90 diastolic adds two heart points', () {
      _expectScores(
        _predict(systolicBp: 129, diastolicBp: 90),
        diabetes: 0,
        heart: 2,
      );
    });

    test('exactly 160 systolic adds three heart points', () {
      _expectScores(
        _predict(systolicBp: 160, diastolicBp: 84),
        diabetes: 0,
        heart: 3,
      );
    });

    test('exactly 100 diastolic adds three heart points', () {
      _expectScores(
        _predict(systolicBp: 129, diastolicBp: 100),
        diabetes: 0,
        heart: 3,
      );
    });
  });

  group('individual symptom contributions', () {
    test('excessive thirst adds two diabetes points', () {
      _expectScores(_predict(excessiveThirst: true), diabetes: 2, heart: 0);
    });

    test('blurred vision adds one diabetes point', () {
      _expectScores(_predict(blurredVision: true), diabetes: 1, heart: 0);
    });

    test('fatigue adds one point to both scores', () {
      _expectScores(_predict(fatigue: true), diabetes: 1, heart: 1);
    });

    test('chest pain preserves the live contribution of two heart points', () {
      _expectScores(_predict(chestPain: true), diabetes: 0, heart: 2);
    });

    test('shortness of breath adds two heart points', () {
      _expectScores(_predict(shortnessOfBreath: true), diabetes: 0, heart: 2);
    });

    test('dizziness adds one heart point', () {
      _expectScores(_predict(dizziness: true), diabetes: 0, heart: 1);
    });
  });

  group('risk classification and recommendation compatibility', () {
    test('score below three is Low', () {
      final result = _predict(excessiveThirst: true);

      expect(result.diabetesScore, 2);
      expect(result.diabetesRisk, 'Low');
      expect(result.overallRisk, 'Low');
      expect(
        result.recommendation,
        'Low risk detected based on current inputs. Continue regular monitoring and healthy lifestyle habits.',
      );
    });

    test('score exactly three is Medium', () {
      final result = _predict(glucose: 180);

      expect(result.diabetesScore, 3);
      expect(result.diabetesRisk, 'Medium');
      expect(result.overallRisk, 'Medium');
      expect(
        result.recommendation,
        'Medium risk detected. Regular monitoring is recommended. Consider scheduling a medical checkup.',
      );
    });

    test('score exactly five is High', () {
      final result = _predict(glucose: 180, excessiveThirst: true);

      expect(result.diabetesScore, 5);
      expect(result.diabetesRisk, 'High');
      expect(result.overallRisk, 'High');
    });

    test('score above five remains High', () {
      final result = _predict(
        glucose: 180,
        excessiveThirst: true,
        blurredVision: true,
      );

      expect(result.diabetesScore, 6);
      expect(result.diabetesRisk, 'High');
      expect(result.overallRisk, 'High');
    });
  });

  test('known live assessment fixture remains identical', () {
    final result = _predict(
      age: 72,
      glucose: 165,
      systolicBp: 145,
      diastolicBp: 90,
      bmi: 25,
      chestPain: true,
      fatigue: true,
    );

    expect(result.diabetesScore, 5);
    expect(result.heartScore, 7);
    expect(result.diabetesRisk, 'High');
    expect(result.heartRisk, 'High');
    expect(result.overallRisk, 'High');
    expect(
      result.recommendation,
      'High risk detected. Please consult a doctor as soon as possible and monitor the patient closely.',
    );
  });
}
