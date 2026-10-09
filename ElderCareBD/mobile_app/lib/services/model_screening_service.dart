import '../models/model_prediction.dart';

class ModelScreeningService {
  static const generalGlucoseLabel = 'General glucose reading (mmol/L)';
  static const randomGlucoseLabel =
      'Random-session glucometer glucose (mmol/L)';
  static const randomGlucoseConfirmationLabel =
      'I confirm this is a random-session glucometer reading in mmol/L';
  static const heartChestPainTypeLabel = 'UCI-compatible chest-pain type';

  static ModelInputDecision<DiabetesModelInput> buildDiabetesInput({
    required PredictionContracts? contracts,
    required bool hasKnownDiabetes,
    required String? patientGender,
    required bool randomGlucoseContextConfirmed,
    required String randomGlucoseText,
    required int age,
    required int systolicBp,
    required int diastolicBp,
    required double bmi,
  }) {
    if (hasKnownDiabetes) {
      return const ModelInputDecision.skipped(
        predictionStatus: 'not_applicable_known_diabetes',
        message:
            'Diabetes screening is not applicable because diabetes is already recorded for this patient.',
      );
    }

    final contract = contracts?.diabetes;
    if (contract == null || !contract.available) {
      return ModelInputDecision.skipped(
        predictionStatus: 'model_unavailable',
        message:
            contract?.unavailableReason ??
            'The diabetes research model contract is unavailable.',
      );
    }

    if (patientGender != 'Female' && patientGender != 'Male') {
      return const ModelInputDecision.skipped(
        predictionStatus: 'unsupported_model_input',
        message:
            'DiaBD supports only a recorded Female or Male profile. No gender value will be fabricated.',
      );
    }

    if (!randomGlucoseContextConfirmed || randomGlucoseText.trim().isEmpty) {
      return const ModelInputDecision.skipped(
        predictionStatus: 'skipped_missing_model_input',
        message:
            'A confirmed random-session glucometer glucose value in mmol/L is required for DiaBD screening.',
      );
    }

    final glucose = double.tryParse(randomGlucoseText.trim());
    final ageFeature = contract.featureNamed('age');
    final genderFeature = contract.featureNamed('gender');
    final systolicFeature = contract.featureNamed('systolic_bp');
    final diastolicFeature = contract.featureNamed('diastolic_bp');
    final glucoseFeature = contract.featureNamed('glucose');
    final bmiFeature = contract.featureNamed('bmi');
    if (glucose == null ||
        !glucose.isFinite ||
        ageFeature == null ||
        genderFeature == null ||
        systolicFeature == null ||
        diastolicFeature == null ||
        glucoseFeature == null ||
        bmiFeature == null ||
        !ageFeature.supportsNumber(age) ||
        !genderFeature.supportsCategoryLabel(patientGender) ||
        !systolicFeature.supportsNumber(systolicBp) ||
        !diastolicFeature.supportsNumber(diastolicBp) ||
        diastolicBp >= systolicBp ||
        !glucoseFeature.supportsNumber(glucose) ||
        !bmiFeature.supportsNumber(bmi)) {
      return const ModelInputDecision.skipped(
        predictionStatus: 'unsupported_model_input',
        message:
            'The diabetes model inputs are outside the supported research-model ranges.',
      );
    }

    return ModelInputDecision.ready(
      DiabetesModelInput(
        age: age,
        gender: patientGender!,
        systolicBp: systolicBp,
        diastolicBp: diastolicBp,
        randomGlucoseMmolL: glucose,
        bmi: bmi,
      ),
    );
  }

  static ModelInputDecision<HeartModelInput> buildHeartInput({
    required PredictionContracts? contracts,
    required String? clinicalSex,
    required String? chestPainType,
    required bool restingSystolicConfirmed,
    required int age,
    required int systolicBp,
  }) {
    final contract = contracts?.heart;
    if (contract == null || !contract.available) {
      return ModelInputDecision.skipped(
        predictionStatus: 'model_unavailable',
        message:
            contract?.unavailableReason ??
            'The heart research model contract is unavailable.',
      );
    }

    if (clinicalSex == null ||
        chestPainType == null ||
        !restingSystolicConfirmed) {
      return const ModelInputDecision.skipped(
        predictionStatus: 'skipped_missing_model_input',
        message:
            'Clinical sex, exact chest-pain type, and confirmed resting systolic blood pressure are required for the heart research model.',
      );
    }

    final ageFeature = contract.featureNamed('age');
    final sexFeature = contract.featureNamed('sex');
    final chestPainFeature = contract.featureNamed('cp');
    final bloodPressureFeature = contract.featureNamed('trestbps');
    if (ageFeature == null ||
        sexFeature == null ||
        chestPainFeature == null ||
        bloodPressureFeature == null ||
        !ageFeature.supportsNumber(age) ||
        !sexFeature.supportsCategoryLabel(clinicalSex) ||
        !chestPainFeature.supportsCategoryLabel(chestPainType) ||
        !bloodPressureFeature.supportsNumber(systolicBp)) {
      return const ModelInputDecision.skipped(
        predictionStatus: 'unsupported_model_input',
        message:
            'The heart model inputs are outside the supported research-model contract.',
      );
    }

    return ModelInputDecision.ready(
      HeartModelInput(
        age: age,
        clinicalSex: clinicalSex,
        chestPainType: chestPainType,
        restingSystolicBpMmHg: systolicBp,
      ),
    );
  }
}
