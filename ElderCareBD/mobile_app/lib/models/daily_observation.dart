class DailyObservationDraft {
  final double? systolicBp;
  final double? diastolicBp;
  final double? glucoseValue;
  final String? glucoseUnit;
  final String? glucoseContext;
  final double? pulseBpm;
  final double? spo2Percent;
  final double? temperatureValue;
  final String? temperatureUnit;
  final double? weightKg;
  final String? symptoms;
  final String? notes;

  const DailyObservationDraft({
    this.systolicBp,
    this.diastolicBp,
    this.glucoseValue,
    this.glucoseUnit,
    this.glucoseContext,
    this.pulseBpm,
    this.spo2Percent,
    this.temperatureValue,
    this.temperatureUnit,
    this.weightKg,
    this.symptoms,
    this.notes,
  });

  Map<String, Object?> toJson({bool includeNulls = false}) {
    final values = <String, Object?>{
      'systolic_bp': systolicBp,
      'diastolic_bp': diastolicBp,
      'glucose_value': glucoseValue,
      'glucose_unit': glucoseUnit,
      'glucose_context': glucoseContext,
      'pulse_bpm': pulseBpm,
      'spo2_percent': spo2Percent,
      'temperature_value': temperatureValue,
      'temperature_unit': temperatureUnit,
      'weight_kg': weightKg,
      'symptoms': symptoms,
      'notes': notes,
    };
    if (includeNulls) return values;
    values.removeWhere((_, value) => value == null);
    return values;
  }
}

class DailyObservation {
  final int id;
  final int patientId;
  final DateTime observationDate;
  final DateTime recordedAt;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DailyObservationDraft values;

  const DailyObservation({
    required this.id,
    required this.patientId,
    required this.observationDate,
    required this.recordedAt,
    required this.createdAt,
    required this.updatedAt,
    required this.values,
  });

  static DailyObservation? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final json = raw.map((key, value) => MapEntry(key.toString(), value));
    final id = _positiveInt(json['id']);
    final patientId = _positiveInt(json['patient_id']);
    final observationDate = DateTime.tryParse(
      json['observation_date']?.toString() ?? '',
    );
    final recordedAt = DateTime.tryParse(json['recorded_at']?.toString() ?? '');
    final createdAt = DateTime.tryParse(json['created_at']?.toString() ?? '');
    final updatedAt = DateTime.tryParse(json['updated_at']?.toString() ?? '');
    if (id == null ||
        patientId == null ||
        observationDate == null ||
        recordedAt == null ||
        createdAt == null ||
        updatedAt == null) {
      return null;
    }

    final glucoseUnit = _optionalString(json['glucose_unit']);
    final temperatureUnit = _optionalString(json['temperature_unit']);
    if (glucoseUnit != null &&
        glucoseUnit != 'mg/dL' &&
        glucoseUnit != 'mmol/L') {
      return null;
    }
    if (temperatureUnit != null &&
        temperatureUnit != 'C' &&
        temperatureUnit != 'F') {
      return null;
    }

    final numericValues = <String, double?>{};
    for (final name in const [
      'systolic_bp',
      'diastolic_bp',
      'glucose_value',
      'pulse_bpm',
      'spo2_percent',
      'temperature_value',
      'weight_kg',
    ]) {
      final parsed = _optionalFiniteDouble(json[name]);
      if (json[name] != null && parsed == null) return null;
      numericValues[name] = parsed;
    }

    return DailyObservation(
      id: id,
      patientId: patientId,
      observationDate: observationDate,
      recordedAt: recordedAt,
      createdAt: createdAt,
      updatedAt: updatedAt,
      values: DailyObservationDraft(
        systolicBp: numericValues['systolic_bp'],
        diastolicBp: numericValues['diastolic_bp'],
        glucoseValue: numericValues['glucose_value'],
        glucoseUnit: glucoseUnit,
        glucoseContext: _optionalString(json['glucose_context']),
        pulseBpm: numericValues['pulse_bpm'],
        spo2Percent: numericValues['spo2_percent'],
        temperatureValue: numericValues['temperature_value'],
        temperatureUnit: temperatureUnit,
        weightKg: numericValues['weight_kg'],
        symptoms: _optionalString(json['symptoms']),
        notes: _optionalString(json['notes']),
      ),
    );
  }
}

int? _positiveInt(Object? raw) {
  final value = raw is int ? raw : (raw is num ? raw.toInt() : null);
  return value != null && value > 0 ? value : null;
}

double? _optionalFiniteDouble(Object? raw) {
  if (raw == null) return null;
  final value = raw is num ? raw.toDouble() : null;
  return value != null && value.isFinite ? value : null;
}

String? _optionalString(Object? raw) {
  if (raw == null) return null;
  final value = raw.toString().trim();
  return value.isEmpty ? null : value;
}
