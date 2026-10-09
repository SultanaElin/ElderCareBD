import 'package:eldercare_bd/models/model_prediction.dart';
import 'package:eldercare_bd/services/model_screening_service.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _contractsJson() => {
  'models': {
    'diabetes': {
      'disease': 'diabetes',
      'available': true,
      'model_version': '3.0.0',
      'model_name': 'DiaBD Bangladesh diabetes status screening model',
      'prediction_source': 'task13b_diabd_v3_model',
      'threshold': 0.06,
      'features': [
        {'name': 'age', 'type': 'integer', 'minimum': 21, 'maximum': 80},
        {
          'name': 'gender',
          'type': 'integer',
          'allowed_values': [0, 1],
          'value_labels': {'0': 'Female', '1': 'Male'},
        },
        {
          'name': 'systolic_bp',
          'type': 'integer',
          'minimum': 62,
          'maximum': 231,
          'unit': 'mmHg',
        },
        {
          'name': 'diastolic_bp',
          'type': 'integer',
          'minimum': 45,
          'maximum': 119,
          'unit': 'mmHg',
        },
        {
          'name': 'glucose',
          'type': 'number',
          'minimum': 1.0,
          'maximum': 33.46,
          'unit': 'mmol/L',
          'measurement_context': 'random-session glucometer glucose',
        },
        {'name': 'bmi', 'type': 'number', 'minimum': 11.47, 'maximum': 54.08},
      ],
    },
    'heart': {
      'disease': 'heart',
      'available': true,
      'model_version': '2.0.0',
      'threshold': 0.53,
      'feature_contract': {
        'features': [
          {'name': 'age', 'type': 'integer', 'minimum': 29, 'maximum': 77},
          {
            'name': 'sex',
            'type': 'integer',
            'allowed_values': [0, 1],
            'value_labels': {'0': 'female', '1': 'male'},
          },
          {
            'name': 'cp',
            'type': 'integer',
            'allowed_values': [0, 1, 2, 3],
            'value_labels': {
              '0': 'typical angina',
              '1': 'atypical angina',
              '2': 'non-anginal pain',
              '3': 'asymptomatic',
            },
          },
          {
            'name': 'trestbps',
            'type': 'integer',
            'minimum': 94,
            'maximum': 200,
            'unit': 'mmHg',
            'measurement_context': 'resting_systolic',
          },
        ],
      },
    },
  },
};

void main() {
  test('assessment copy distinguishes generic and model measurements', () {
    expect(
      ModelScreeningService.generalGlucoseLabel,
      'General glucose reading (mmol/L)',
    );
    expect(
      ModelScreeningService.randomGlucoseLabel,
      'Random-session glucometer glucose (mmol/L)',
    );
    expect(
      ModelScreeningService.randomGlucoseConfirmationLabel,
      'I confirm this is a random-session glucometer reading in mmol/L',
    );
    expect(
      ModelScreeningService.heartChestPainTypeLabel,
      'UCI-compatible chest-pain type',
    );
  });

  group('trusted prediction contract parsing', () {
    test('reads ranges and human labels from backend metadata', () {
      final contracts = PredictionContracts.tryParse(_contractsJson());

      expect(contracts, isNotNull);
      expect(contracts!.diabetes!.featureNamed('glucose')!.minimum, 1);
      expect(contracts.diabetes!.modelVersion, '3.0.0');
      expect(contracts.diabetes!.predictionSource, 'task13b_diabd_v3_model');
      expect(
        contracts.heart!
            .featureNamed('sex')!
            .categoryOptions
            .map((option) => option.label),
        ['female', 'male'],
      );
      expect(
        contracts.heart!
            .featureNamed('cp')!
            .categoryOptions
            .map((option) => option.label),
        [
          'typical angina',
          'atypical angina',
          'non-anginal pain',
          'asymptomatic',
        ],
      );
    });

    test('malformed or absent model data is null-safe', () {
      expect(PredictionContracts.tryParse(null), isNull);
      expect(PredictionContracts.tryParse({'models': []}), isNull);

      final partial = PredictionContracts.tryParse({
        'models': {
          'diabetes': {'available': false, 'disease': 'diabetes'},
        },
      });
      expect(partial?.diabetes?.available, isFalse);
      expect(partial?.heart, isNull);
    });

    test('categorical values without trusted labels are not exposed', () {
      final feature = ModelFeatureContract.tryParse({
        'name': 'cp',
        'allowed_values': [0, 1, 2, 3],
        'value_labels': {'0': 'typical angina'},
      });

      expect(feature?.categoryOptions, isEmpty);
      expect(feature?.supportsCategoryLabel('1'), isFalse);
    });
  });

  group('model-compatible input decisions', () {
    late PredictionContracts contracts;

    setUp(() {
      contracts = PredictionContracts.tryParse(_contractsJson())!;
    });

    test('unconfirmed random glucose never becomes a DiaBD input', () {
      final missing = ModelScreeningService.buildDiabetesInput(
        contracts: contracts,
        hasKnownDiabetes: false,
        patientGender: 'Female',
        randomGlucoseContextConfirmed: false,
        randomGlucoseText: '7.25',
        age: 72,
        systolicBp: 145,
        diastolicBp: 90,
        bmi: 25,
      );

      expect(missing.canPredict, isFalse);
      expect(missing.predictionStatus, 'skipped_missing_model_input');
    });

    test('confirmed DiaBD input sends the exact six-feature contract', () {
      final decision = ModelScreeningService.buildDiabetesInput(
        contracts: contracts,
        hasKnownDiabetes: false,
        patientGender: 'Female',
        randomGlucoseContextConfirmed: true,
        randomGlucoseText: '7.25',
        age: 72,
        systolicBp: 145,
        diastolicBp: 90,
        bmi: 25,
      );

      expect(decision.canPredict, isTrue);
      expect(decision.input!.toJson(), {
        'age': 72,
        'gender': 'Female',
        'systolic_bp': 145,
        'diastolic_bp': 90,
        'random_glucose_mmol_l': 7.25,
        'bmi': 25.0,
      });
    });

    test('known diabetes and Other gender bypass DiaBD safely', () {
      final known = ModelScreeningService.buildDiabetesInput(
        contracts: contracts,
        hasKnownDiabetes: true,
        patientGender: 'Female',
        randomGlucoseContextConfirmed: true,
        randomGlucoseText: '7.25',
        age: 72,
        systolicBp: 145,
        diastolicBp: 90,
        bmi: 25,
      );
      final other = ModelScreeningService.buildDiabetesInput(
        contracts: contracts,
        hasKnownDiabetes: false,
        patientGender: 'Other',
        randomGlucoseContextConfirmed: true,
        randomGlucoseText: '7.25',
        age: 72,
        systolicBp: 145,
        diastolicBp: 90,
        bmi: 25,
      );

      expect(known.canPredict, isFalse);
      expect(known.predictionStatus, 'not_applicable_known_diabetes');
      expect(other.canPredict, isFalse);
      expect(other.predictionStatus, 'unsupported_model_input');
    });

    test('Other and a missing chest-pain category cannot be fabricated', () {
      final other = ModelScreeningService.buildHeartInput(
        contracts: contracts,
        clinicalSex: 'Other',
        chestPainType: 'typical angina',
        restingSystolicConfirmed: true,
        age: 72,
        systolicBp: 145,
      );
      final missingCategory = ModelScreeningService.buildHeartInput(
        contracts: contracts,
        clinicalSex: 'female',
        chestPainType: null,
        restingSystolicConfirmed: true,
        age: 72,
        systolicBp: 145,
      );

      expect(other.canPredict, isFalse);
      expect(other.predictionStatus, 'unsupported_model_input');
      expect(missingCategory.canPredict, isFalse);
      expect(missingCategory.predictionStatus, 'skipped_missing_model_input');
    });

    test('heart request uses exact metadata labels and resting context', () {
      final decision = ModelScreeningService.buildHeartInput(
        contracts: contracts,
        clinicalSex: 'female',
        chestPainType: 'non-anginal pain',
        restingSystolicConfirmed: true,
        age: 72,
        systolicBp: 145,
      );

      expect(decision.input!.toJson(), {
        'age': 72,
        'clinical_sex': 'female',
        'chest_pain_type': 'non-anginal pain',
        'blood_pressure_context': 'resting_systolic',
        'resting_systolic_bp_mm_hg': 145,
      });
    });
  });

  group('prediction provenance parsing', () {
    test('uses threshold terminology without fabricating Medium', () {
      final prediction = DiseasePrediction.tryParse({
        'disease': 'diabetes',
        'prediction_source': 'task13b_diabd_v3_model',
        'model_version': '3.0.0',
        'risk_score': 0.64,
        'classification': 'at_or_above_model_threshold',
        'threshold': 0.06,
        'features_used': {
          'age': 72,
          'gender': 0,
          'systolic_bp': 145,
          'diastolic_bp': 90,
          'glucose': 7.25,
          'bmi': 25,
        },
        'disclaimer': 'Non-diagnostic research screening only.',
      }, standaloneResponse: true);

      expect(prediction?.isModelPrediction, isTrue);
      expect(
        prediction?.classificationLabel,
        'At/above screening-model threshold',
      );
      expect(prediction?.classificationLabel, isNot(contains('Medium')));
    });

    test('create response prefers canonical persisted predictions', () {
      final fallback = DiseasePrediction.fallback(
        disease: 'diabetes',
        predictionStatus: 'inference_failed',
        message: 'Fallback',
      );
      final results = AssessmentPredictions.fromCreateResponse(
        {
          'predictions': {
            'diabetes': {
              'disease': 'diabetes',
              'prediction_source': 'task13b_diabd_v3_model',
              'prediction_status': 'predicted',
              'model_version': '3.0.0',
              'risk_score': 0.02,
              'threshold': 0.06,
              'classification': 'below_model_threshold',
              'disclaimer': 'Non-diagnostic.',
            },
          },
        },
        diabetesFallback: fallback,
        heartFallback: fallback,
      );

      expect(results.diabetes.riskScore, 0.02);
      expect(
        results.diabetes.classificationLabel,
        'Below screening-model threshold',
      );
      expect(results.heart, same(fallback));
    });

    test('historical null provenance remains identifiable as legacy', () {
      expect(
        DiseasePrediction.fromAssessmentHistory({
          'diabetes_risk': 'Medium',
        }, 'diabetes'),
        isNull,
      );
    });

    test('rejects out-of-range and threshold-inconsistent model outputs', () {
      DiseasePrediction? parse(double score, String classification) {
        return DiseasePrediction.tryParse({
          'disease': 'diabetes',
          'prediction_source': 'task13b_diabd_v3_model',
          'model_version': '3.0.0',
          'risk_score': score,
          'threshold': 0.06,
          'classification': classification,
          'disclaimer': 'Non-diagnostic.',
        }, standaloneResponse: true);
      }

      expect(parse(5, 'at_or_above_model_threshold'), isNull);
      expect(parse(0.64, 'below_model_threshold'), isNull);
      expect(parse(0.64, 'medium'), isNull);
    });

    test('rejects a final model source paired with the wrong disease', () {
      final prediction = DiseasePrediction.tryParse({
        'disease': 'diabetes',
        'prediction_source': 'task13_heart_v2_model',
        'model_version': '2.0.0',
        'risk_score': 0.64,
        'threshold': 0.53,
        'classification': 'at_or_above_model_threshold',
        'disclaimer': 'Malformed fixture.',
      }, standaloneResponse: true);

      expect(prediction, isNull);
    });
  });
}
