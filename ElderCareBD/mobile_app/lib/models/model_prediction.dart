class ModelFeatureContract {
  final String name;
  final String? type;
  final double? minimum;
  final double? maximum;
  final String? unit;
  final String? measurementContext;
  final List<Object> allowedValues;
  final Map<String, String> valueLabels;

  const ModelFeatureContract({
    required this.name,
    this.type,
    this.minimum,
    this.maximum,
    this.unit,
    this.measurementContext,
    this.allowedValues = const [],
    this.valueLabels = const {},
  });

  static ModelFeatureContract? tryParse(Object? raw) {
    final json = _stringKeyedMap(raw);
    final name = _nonEmptyString(json?['name']);
    if (json == null || name == null) return null;

    final rawAllowedValues = json['allowed_values'];
    final allowedValues = rawAllowedValues is List
        ? rawAllowedValues
              .where((value) => value is String || value is num)
              .cast<Object>()
              .toList(growable: false)
        : const <Object>[];

    final labels = <String, String>{};
    final rawLabels = _stringKeyedMap(json['value_labels']);
    if (rawLabels != null) {
      for (final entry in rawLabels.entries) {
        final label = _nonEmptyString(entry.value);
        if (label != null) labels[entry.key] = label;
      }
    }

    return ModelFeatureContract(
      name: name,
      type: _nonEmptyString(json['type']),
      minimum: _finiteDouble(json['minimum']),
      maximum: _finiteDouble(json['maximum']),
      unit: _nonEmptyString(json['unit']),
      measurementContext: _nonEmptyString(json['measurement_context']),
      allowedValues: allowedValues,
      valueLabels: Map.unmodifiable(labels),
    );
  }

  bool supportsNumber(num value) {
    final numericValue = value.toDouble();
    if (!numericValue.isFinite) return false;
    if (minimum != null && numericValue < minimum!) return false;
    if (maximum != null && numericValue > maximum!) return false;
    return true;
  }

  List<ModelCategoryOption> get categoryOptions {
    final options = <ModelCategoryOption>[];
    final seenLabels = <String>{};
    for (final value in allowedValues) {
      final label = valueLabels[_canonicalValueKey(value)]?.trim();
      if (label == null || label.isEmpty || !seenLabels.add(label)) {
        return const [];
      }
      options.add(ModelCategoryOption(metadataValue: value, label: label));
    }
    return List.unmodifiable(options);
  }

  bool supportsCategoryLabel(String? label) {
    if (label == null || label.trim().isEmpty) return false;
    return categoryOptions.any((option) => option.label == label);
  }
}

class ModelCategoryOption {
  final Object metadataValue;
  final String label;

  const ModelCategoryOption({required this.metadataValue, required this.label});
}

class DiseaseModelContract {
  final String disease;
  final bool available;
  final String? modelVersion;
  final String? modelName;
  final String? predictionSource;
  final double? threshold;
  final List<ModelFeatureContract> features;
  final String? unavailableReason;

  const DiseaseModelContract({
    required this.disease,
    required this.available,
    this.modelVersion,
    this.modelName,
    this.predictionSource,
    this.threshold,
    this.features = const [],
    this.unavailableReason,
  });

  static DiseaseModelContract? tryParse(Object? raw, {String? diseaseHint}) {
    final json = _stringKeyedMap(raw);
    if (json == null) return null;

    final disease = _nonEmptyString(json['disease']) ?? diseaseHint;
    if (disease == null) return null;

    Object? rawFeatures = json['features'];
    final featureContract = _stringKeyedMap(json['feature_contract']);
    rawFeatures ??= featureContract?['features'];

    final features = <ModelFeatureContract>[];
    if (rawFeatures is List) {
      for (final rawFeature in rawFeatures) {
        final feature = ModelFeatureContract.tryParse(rawFeature);
        if (feature != null) features.add(feature);
      }
    } else {
      final featureMap = _stringKeyedMap(rawFeatures);
      if (featureMap != null) {
        for (final entry in featureMap.entries) {
          final value = _stringKeyedMap(entry.value);
          if (value == null) continue;
          final feature = ModelFeatureContract.tryParse({
            'name': entry.key,
            ...value,
          });
          if (feature != null) features.add(feature);
        }
      }
    }

    final availableValue = json['available'];
    final available = availableValue is bool ? availableValue : false;

    return DiseaseModelContract(
      disease: disease,
      available: available,
      modelVersion: _nonEmptyString(json['model_version']),
      modelName: _nonEmptyString(json['model_name']),
      predictionSource: _nonEmptyString(json['prediction_source']),
      threshold: _finiteDouble(json['threshold']),
      features: List.unmodifiable(features),
      unavailableReason:
          _nonEmptyString(json['unavailable_reason']) ??
          _nonEmptyString(json['detail']) ??
          _nonEmptyString(json['message']),
    );
  }

  ModelFeatureContract? featureNamed(String name) {
    final normalizedName = _normalizeName(name);
    for (final feature in features) {
      if (_normalizeName(feature.name) == normalizedName) return feature;
    }
    return null;
  }
}

class PredictionContracts {
  final DiseaseModelContract? diabetes;
  final DiseaseModelContract? heart;

  const PredictionContracts({this.diabetes, this.heart});

  static PredictionContracts? tryParse(Object? raw) {
    final root = _stringKeyedMap(raw);
    if (root == null) return null;

    final body = _stringKeyedMap(root['body']);
    final payload = body ?? root;
    final models =
        _stringKeyedMap(payload['models']) ??
        _stringKeyedMap(payload['contracts']) ??
        payload;

    final diabetes = DiseaseModelContract.tryParse(
      models['diabetes'],
      diseaseHint: 'diabetes',
    );
    final heart = DiseaseModelContract.tryParse(
      models['heart'],
      diseaseHint: 'heart',
    );
    if (diabetes == null && heart == null) return null;

    return PredictionContracts(diabetes: diabetes, heart: heart);
  }
}

class DiabetesModelInput {
  final int age;
  final String gender;
  final int systolicBp;
  final int diastolicBp;
  final double randomGlucoseMmolL;
  final double bmi;

  const DiabetesModelInput({
    required this.age,
    required this.gender,
    required this.systolicBp,
    required this.diastolicBp,
    required this.randomGlucoseMmolL,
    required this.bmi,
  });

  Map<String, Object> toJson({int? patientId}) => {
    'patient_id': ?patientId,
    'age': age,
    'gender': gender,
    'systolic_bp': systolicBp,
    'diastolic_bp': diastolicBp,
    'random_glucose_mmol_l': randomGlucoseMmolL,
    'bmi': bmi,
  };
}

class HeartModelInput {
  static const bloodPressureContext = 'resting_systolic';

  final int age;
  final String clinicalSex;
  final String chestPainType;
  final int restingSystolicBpMmHg;

  const HeartModelInput({
    required this.age,
    required this.clinicalSex,
    required this.chestPainType,
    required this.restingSystolicBpMmHg,
  });

  Map<String, Object> toJson({int? patientId}) => {
    'patient_id': ?patientId,
    'age': age,
    'clinical_sex': clinicalSex,
    'chest_pain_type': chestPainType,
    'blood_pressure_context': bloodPressureContext,
    'resting_systolic_bp_mm_hg': restingSystolicBpMmHg,
  };
}

class ModelInputDecision<T> {
  final T? input;
  final String predictionStatus;
  final String message;

  const ModelInputDecision._({
    this.input,
    required this.predictionStatus,
    required this.message,
  });

  const ModelInputDecision.ready(T input)
    : this._(input: input, predictionStatus: 'predicted', message: '');

  const ModelInputDecision.skipped({
    required String predictionStatus,
    required String message,
  }) : this._(predictionStatus: predictionStatus, message: message);

  bool get canPredict => input != null;
}

class DiseasePrediction {
  final String disease;
  final String predictionSource;
  final String predictionStatus;
  final String? modelVersion;
  final double? riskScore;
  final String? classification;
  final double? threshold;
  final Map<String, Object?> featuresUsed;
  final String disclaimer;

  const DiseasePrediction({
    required this.disease,
    required this.predictionSource,
    required this.predictionStatus,
    this.modelVersion,
    this.riskScore,
    this.classification,
    this.threshold,
    this.featuresUsed = const {},
    required this.disclaimer,
  });

  factory DiseasePrediction.fallback({
    required String disease,
    required String predictionStatus,
    required String message,
    String predictionSource = 'heuristic_demo_v1',
  }) {
    return DiseasePrediction(
      disease: disease,
      predictionSource: predictionSource,
      predictionStatus: predictionStatus,
      disclaimer: message,
    );
  }

  static DiseasePrediction? tryParse(
    Object? raw, {
    String? diseaseHint,
    bool standaloneResponse = false,
  }) {
    final json = _stringKeyedMap(raw);
    if (json == null) return null;

    final disease = _nonEmptyString(json['disease']) ?? diseaseHint;
    final source = _nonEmptyString(json['prediction_source']);
    if (disease == null || source == null) return null;
    if (!_predictionSourceMatchesDisease(disease, source)) return null;

    final score = _finiteDouble(json['risk_score']);
    final threshold = _finiteDouble(json['threshold']);
    final classification = _nonEmptyString(json['classification']);
    final status =
        _nonEmptyString(json['prediction_status']) ??
        (standaloneResponse ? 'predicted' : null) ??
        (_isModelSource(source) &&
                score != null &&
                threshold != null &&
                classification != null
            ? 'predicted'
            : 'model_unavailable');

    final rawFeatures = _stringKeyedMap(json['features_used']);
    final features = <String, Object?>{};
    if (rawFeatures != null) features.addAll(rawFeatures);

    final prediction = DiseasePrediction(
      disease: disease,
      predictionSource: source,
      predictionStatus: status,
      modelVersion: _nonEmptyString(json['model_version']),
      riskScore: score,
      classification: classification,
      threshold: threshold,
      featuresUsed: Map.unmodifiable(features),
      disclaimer:
          _nonEmptyString(json['disclaimer']) ??
          'This screening result is non-diagnostic.',
    );
    if (_isModelSource(source) &&
        status == 'predicted' &&
        !prediction.isModelPrediction) {
      return null;
    }
    return prediction;
  }

  static DiseasePrediction? fromAssessmentHistory(
    Map<String, dynamic> assessment,
    String disease,
  ) {
    final source = _nonEmptyString(assessment['${disease}_prediction_source']);
    if (source == null) return null;

    return DiseasePrediction.tryParse({
      'disease': disease,
      'prediction_source': source,
      'prediction_status': assessment['${disease}_prediction_status'],
      'model_version': assessment['${disease}_model_version'],
      'risk_score': assessment['${disease}_model_score'],
      'threshold': assessment['${disease}_model_threshold'],
      'classification': assessment['${disease}_model_classification'],
      'disclaimer': 'This saved screening result is non-diagnostic.',
    }, diseaseHint: disease);
  }

  bool get isModelPrediction =>
      _isModelSource(predictionSource) &&
      predictionStatus == 'predicted' &&
      modelVersion != null &&
      riskScore != null &&
      riskScore! >= 0 &&
      riskScore! <= 1 &&
      threshold != null &&
      threshold! >= 0 &&
      threshold! <= 1 &&
      (classification == 'below_model_threshold' ||
          classification == 'at_or_above_model_threshold') &&
      classification ==
          (riskScore! >= threshold!
              ? 'at_or_above_model_threshold'
              : 'below_model_threshold');

  String get classificationLabel => switch (classification) {
    'below_model_threshold' => 'Below screening-model threshold',
    'at_or_above_model_threshold' => 'At/above screening-model threshold',
    _ => 'Screening-model classification unavailable',
  };

  String get modelDisplayLabel => switch (predictionSource) {
    'task13b_diabd_v3_model' => 'DiaBD v3 research/demo screening model',
    'task13_heart_v2_model' =>
      'Cleveland Heart v2 research/demo screening model',
    'task13_v2_model' => 'Legacy Task 13 v2 research model',
    _ => 'Research screening model',
  };

  String get fallbackMessage {
    final explicitMessage = disclaimer.trim();
    if (explicitMessage.isNotEmpty &&
        explicitMessage != 'This screening result is non-diagnostic.') {
      return explicitMessage;
    }

    return switch (predictionStatus) {
      'skipped_missing_model_input' =>
        'Required model-compatible information was not provided.',
      'unsupported_model_input' =>
        'The model inputs were outside the trusted feature contract.',
      'model_unavailable' => 'The research model is currently unavailable.',
      'inference_failed' =>
        'The research model could not complete this screening.',
      'not_applicable_known_diabetes' =>
        'Diabetes screening was not run because diabetes is already recorded for this patient.',
      _ => 'The research model was not used for this assessment.',
    };
  }
}

class AssessmentPredictions {
  final DiseasePrediction diabetes;
  final DiseasePrediction heart;

  const AssessmentPredictions({required this.diabetes, required this.heart});

  factory AssessmentPredictions.fromCreateResponse(
    Object? raw, {
    required DiseasePrediction diabetesFallback,
    required DiseasePrediction heartFallback,
  }) {
    final body = _stringKeyedMap(raw);
    final predictions = _stringKeyedMap(body?['predictions']);

    return AssessmentPredictions(
      diabetes:
          DiseasePrediction.tryParse(
            predictions?['diabetes'],
            diseaseHint: 'diabetes',
          ) ??
          diabetesFallback,
      heart:
          DiseasePrediction.tryParse(
            predictions?['heart'],
            diseaseHint: 'heart',
          ) ??
          heartFallback,
    );
  }
}

Map<String, dynamic>? _stringKeyedMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) {
    return value.map((key, item) => MapEntry(key.toString(), item));
  }
  return null;
}

String? _nonEmptyString(Object? value) {
  if (value == null) return null;
  final text = value.toString().trim();
  if (text.isEmpty || text.toLowerCase() == 'null') return null;
  return text;
}

double? _finiteDouble(Object? value) {
  final parsed = value is num
      ? value.toDouble()
      : double.tryParse(value?.toString() ?? '');
  if (parsed == null || !parsed.isFinite) return null;
  return parsed;
}

String _canonicalValueKey(Object value) {
  if (value is num && value.toDouble() == value.toInt().toDouble()) {
    return value.toInt().toString();
  }
  return value.toString();
}

String _normalizeName(String value) =>
    value.trim().toLowerCase().replaceAll(RegExp(r'[^a-z0-9]'), '');

bool _isModelSource(String source) => const {
  'task13b_diabd_v3_model',
  'task13_heart_v2_model',
  // Retained only so already-saved partial Task 14/Pima-era rows remain readable.
  'task13_v2_model',
}.contains(source);

bool _predictionSourceMatchesDisease(String disease, String source) {
  return switch (source) {
    'task13b_diabd_v3_model' => disease == 'diabetes',
    'task13_heart_v2_model' => disease == 'heart',
    // The partial Task 14 source was shared by both historical model types.
    'task13_v2_model' => disease == 'diabetes' || disease == 'heart',
    _ => true,
  };
}
