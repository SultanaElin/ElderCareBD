class RiskPredictionInput {
  final int age;
  final int glucose;
  final int systolicBp;
  final int diastolicBp;
  final double bmi;
  final bool chestPain;
  final bool dizziness;
  final bool shortnessOfBreath;
  final bool excessiveThirst;
  final bool fatigue;
  final bool blurredVision;

  const RiskPredictionInput({
    required this.age,
    required this.glucose,
    required this.systolicBp,
    required this.diastolicBp,
    required this.bmi,
    required this.chestPain,
    required this.dizziness,
    required this.shortnessOfBreath,
    required this.excessiveThirst,
    required this.fatigue,
    required this.blurredVision,
  });
}

class RiskPredictionResult {
  final int diabetesScore;
  final int heartScore;
  final String diabetesRisk;
  final String heartRisk;
  final String overallRisk;
  final String recommendation;

  const RiskPredictionResult({
    required this.diabetesScore,
    required this.heartScore,
    required this.diabetesRisk,
    required this.heartRisk,
    required this.overallRisk,
    required this.recommendation,
  });
}

class PredictionService {
  /// Non-diagnostic demonstration screening logic preserved from the live UI.
  /// It remains pending replacement by a validated final prediction approach.
  static RiskPredictionResult predict(RiskPredictionInput input) {
    int diabetesScore = 0;
    int heartScore = 0;

    if (input.age >= 60) {
      diabetesScore += 1;
      heartScore += 1;
    }

    if (input.glucose >= 180) {
      diabetesScore += 3;
    } else if (input.glucose >= 140) {
      diabetesScore += 2;
    } else if (input.glucose >= 110) {
      diabetesScore += 1;
    }

    if (input.bmi >= 30) {
      diabetesScore += 2;
      heartScore += 1;
    } else if (input.bmi >= 25) {
      diabetesScore += 1;
      heartScore += 1;
    }

    if (input.systolicBp >= 160 || input.diastolicBp >= 100) {
      heartScore += 3;
    } else if (input.systolicBp >= 140 || input.diastolicBp >= 90) {
      heartScore += 2;
    } else if (input.systolicBp >= 130 || input.diastolicBp >= 85) {
      heartScore += 1;
    }

    if (input.excessiveThirst) diabetesScore += 2;
    if (input.blurredVision) diabetesScore += 1;
    if (input.fatigue) diabetesScore += 1;

    if (input.chestPain) heartScore += 2;
    if (input.shortnessOfBreath) heartScore += 2;
    if (input.dizziness) heartScore += 1;
    if (input.fatigue) heartScore += 1;

    final diabetesRisk = _riskFromScore(diabetesScore);
    final heartRisk = _riskFromScore(heartScore);

    final overallRisk = diabetesRisk == 'High' || heartRisk == 'High'
        ? 'High'
        : diabetesRisk == 'Medium' || heartRisk == 'Medium'
        ? 'Medium'
        : 'Low';

    return RiskPredictionResult(
      diabetesScore: diabetesScore,
      heartScore: heartScore,
      diabetesRisk: diabetesRisk,
      heartRisk: heartRisk,
      overallRisk: overallRisk,
      recommendation: _recommendation(overallRisk),
    );
  }

  static String _riskFromScore(int score) {
    if (score >= 5) return 'High';
    if (score >= 3) return 'Medium';
    return 'Low';
  }

  static String _recommendation(String risk) {
    switch (risk) {
      case 'High':
        return 'High risk detected. Please consult a doctor as soon as possible and monitor the patient closely.';
      case 'Medium':
        return 'Medium risk detected. Regular monitoring is recommended. Consider scheduling a medical checkup.';
      default:
        return 'Low risk detected based on current inputs. Continue regular monitoring and healthy lifestyle habits.';
    }
  }
}
