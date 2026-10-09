enum PrescriptionOcrStatus {
  uploaded,
  processing,
  ready,
  failed,
  confirmed,
  unknown;

  static PrescriptionOcrStatus fromValue(Object? value) {
    return switch (value?.toString().trim().toLowerCase()) {
      'uploaded' => PrescriptionOcrStatus.uploaded,
      'processing' => PrescriptionOcrStatus.processing,
      'ready' => PrescriptionOcrStatus.ready,
      'failed' => PrescriptionOcrStatus.failed,
      'confirmed' => PrescriptionOcrStatus.confirmed,
      _ => PrescriptionOcrStatus.unknown,
    };
  }

  String get apiValue => name;
}

enum MedicineCandidateConfidence {
  high,
  medium,
  low,
  unknown;

  static MedicineCandidateConfidence fromValue(Object? value) {
    return switch (value?.toString().trim().toLowerCase()) {
      'high' => MedicineCandidateConfidence.high,
      'medium' => MedicineCandidateConfidence.medium,
      'low' => MedicineCandidateConfidence.low,
      _ => MedicineCandidateConfidence.unknown,
    };
  }

  String get label => switch (this) {
    MedicineCandidateConfidence.high => 'High confidence',
    MedicineCandidateConfidence.medium => 'Medium confidence',
    MedicineCandidateConfidence.low => 'Low confidence',
    MedicineCandidateConfidence.unknown => 'Confidence not available',
  };
}

class PrescriptionMedicineCandidate {
  final String name;
  final String strength;
  final String dosage;
  final String frequency;
  final String duration;
  final String instructions;
  final String sourceLine;
  final MedicineCandidateConfidence confidence;
  final List<String> warnings;

  const PrescriptionMedicineCandidate({
    required this.name,
    this.strength = '',
    this.dosage = '',
    this.frequency = '',
    this.duration = '',
    this.instructions = '',
    this.sourceLine = '',
    this.confidence = MedicineCandidateConfidence.unknown,
    this.warnings = const [],
  });

  factory PrescriptionMedicineCandidate.fromJson(Map<Object?, Object?> json) {
    return PrescriptionMedicineCandidate(
      name: _stringValue(json['name']),
      strength: _stringValue(json['strength']),
      dosage: _stringValue(json['dosage']),
      frequency: _stringValue(json['frequency']),
      duration: _stringValue(json['duration']),
      instructions: _stringValue(json['instructions']),
      sourceLine: _stringValue(json['source_line']),
      confidence: MedicineCandidateConfidence.fromValue(json['confidence']),
      warnings: _stringList(json['warnings']),
    );
  }

  PrescriptionMedicineCandidate copyWith({
    String? name,
    String? strength,
    String? dosage,
    String? frequency,
    String? duration,
    String? instructions,
    String? sourceLine,
    MedicineCandidateConfidence? confidence,
    List<String>? warnings,
  }) {
    return PrescriptionMedicineCandidate(
      name: name ?? this.name,
      strength: strength ?? this.strength,
      dosage: dosage ?? this.dosage,
      frequency: frequency ?? this.frequency,
      duration: duration ?? this.duration,
      instructions: instructions ?? this.instructions,
      sourceLine: sourceLine ?? this.sourceLine,
      confidence: confidence ?? this.confidence,
      warnings: warnings ?? this.warnings,
    );
  }

  Map<String, Object?> toConfirmationJson() {
    return {
      'name': name.trim(),
      'strength': _nullableTrimmed(strength),
      'dosage': _nullableTrimmed(dosage),
      'frequency': _nullableTrimmed(frequency),
      'duration': _nullableTrimmed(duration),
      'instructions': _nullableTrimmed(instructions),
    };
  }
}

class PrescriptionExtractionResult {
  final int? prescriptionId;
  final PrescriptionOcrStatus status;
  final String? ocrEngine;
  final List<String> ocrLanguages;
  final String? ocrText;
  final List<PrescriptionMedicineCandidate> candidates;
  final List<String> warnings;
  final bool reused;

  const PrescriptionExtractionResult({
    required this.prescriptionId,
    required this.status,
    required this.ocrEngine,
    required this.ocrLanguages,
    required this.ocrText,
    required this.candidates,
    required this.warnings,
    required this.reused,
  });

  factory PrescriptionExtractionResult.fromJson(Map<Object?, Object?> json) {
    final rawCandidates = json['candidates'];
    final candidates = <PrescriptionMedicineCandidate>[];
    if (rawCandidates is List) {
      for (final value in rawCandidates) {
        if (value is Map) {
          candidates.add(PrescriptionMedicineCandidate.fromJson(value));
        }
      }
    }

    return PrescriptionExtractionResult(
      prescriptionId: _intValue(json['prescription_id']),
      status: PrescriptionOcrStatus.fromValue(json['ocr_status']),
      ocrEngine: _nullableString(json['ocr_engine']),
      ocrLanguages: _stringList(json['ocr_languages']),
      ocrText: _nullableString(json['ocr_text']),
      candidates: List.unmodifiable(candidates),
      warnings: List.unmodifiable(_stringList(json['warnings'])),
      reused: json['reused'] == true,
    );
  }
}

String _stringValue(Object? value) {
  if (value == null) return '';
  return value.toString().trim();
}

String? _nullableString(Object? value) {
  final result = _stringValue(value);
  return result.isEmpty ? null : result;
}

String? _nullableTrimmed(String value) {
  final result = value.trim();
  return result.isEmpty ? null : result;
}

int? _intValue(Object? value) {
  if (value is int) return value;
  return int.tryParse(value?.toString() ?? '');
}

List<String> _stringList(Object? value) {
  if (value is! List) return const [];
  return value
      .map(_stringValue)
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
}
