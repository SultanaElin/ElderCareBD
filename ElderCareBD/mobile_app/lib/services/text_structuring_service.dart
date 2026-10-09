class ExtractionConflict {
  final String field;
  final String manualValue;
  final int extractedValue;

  const ExtractionConflict({
    required this.field,
    required this.manualValue,
    required this.extractedValue,
  });

  String get description =>
      '$field kept "$manualValue" (note suggested $extractedValue)';
}

class ExtractionApplicationResult {
  final String glucoseText;
  final String systolicBpText;
  final String diastolicBpText;
  final bool chestPain;
  final bool dizziness;
  final bool shortnessOfBreath;
  final bool excessiveThirst;
  final bool fatigue;
  final bool blurredVision;
  final List<ExtractionConflict> conflicts;

  ExtractionApplicationResult({
    required this.glucoseText,
    required this.systolicBpText,
    required this.diastolicBpText,
    required this.chestPain,
    required this.dizziness,
    required this.shortnessOfBreath,
    required this.excessiveThirst,
    required this.fatigue,
    required this.blurredVision,
    required List<ExtractionConflict> conflicts,
  }) : conflicts = List.unmodifiable(conflicts);
}

class StructuredHealthData {
  final int? glucose;
  final int? systolicBp;
  final int? diastolicBp;

  /// `true` means the symptom was mentioned. `null` means it was not detected.
  final bool? chestPain;
  final bool? dizziness;
  final bool? shortnessOfBreath;
  final bool? excessiveThirst;
  final bool? fatigue;
  final bool? blurredVision;

  const StructuredHealthData({
    this.glucose,
    this.systolicBp,
    this.diastolicBp,
    this.chestPain,
    this.dizziness,
    this.shortnessOfBreath,
    this.excessiveThirst,
    this.fatigue,
    this.blurredVision,
  });

  bool get hasSuggestions =>
      glucose != null ||
      systolicBp != null ||
      diastolicBp != null ||
      chestPain == true ||
      dizziness == true ||
      shortnessOfBreath == true ||
      excessiveThirst == true ||
      fatigue == true ||
      blurredVision == true;

  ExtractionApplicationResult applyPreservingManualValues({
    required String glucoseText,
    required String systolicBpText,
    required String diastolicBpText,
    required bool chestPain,
    required bool dizziness,
    required bool shortnessOfBreath,
    required bool excessiveThirst,
    required bool fatigue,
    required bool blurredVision,
    bool glucoseTextUsesMmolL = false,
  }) {
    final conflicts = <ExtractionConflict>[];

    return ExtractionApplicationResult(
      glucoseText: glucoseTextUsesMmolL
          ? _applyGlucoseSuggestionAsMmolL(
              currentText: glucoseText,
              suggestionMgDl: glucose,
              conflicts: conflicts,
            )
          : _applyNumericSuggestion(
              field: 'Glucose',
              currentText: glucoseText,
              suggestion: glucose,
              conflicts: conflicts,
            ),
      systolicBpText: _applyNumericSuggestion(
        field: 'Systolic BP',
        currentText: systolicBpText,
        suggestion: systolicBp,
        conflicts: conflicts,
      ),
      diastolicBpText: _applyNumericSuggestion(
        field: 'Diastolic BP',
        currentText: diastolicBpText,
        suggestion: diastolicBp,
        conflicts: conflicts,
      ),
      chestPain: chestPain || this.chestPain == true,
      dizziness: dizziness || this.dizziness == true,
      shortnessOfBreath: shortnessOfBreath || this.shortnessOfBreath == true,
      excessiveThirst: excessiveThirst || this.excessiveThirst == true,
      fatigue: fatigue || this.fatigue == true,
      blurredVision: blurredVision || this.blurredVision == true,
      conflicts: conflicts,
    );
  }

  String _applyNumericSuggestion({
    required String field,
    required String currentText,
    required int? suggestion,
    required List<ExtractionConflict> conflicts,
  }) {
    if (suggestion == null) return currentText;
    if (currentText.trim().isEmpty) return suggestion.toString();

    if (int.tryParse(currentText.trim()) != suggestion) {
      conflicts.add(
        ExtractionConflict(
          field: field,
          manualValue: currentText,
          extractedValue: suggestion,
        ),
      );
    }

    return currentText;
  }

  String _applyGlucoseSuggestionAsMmolL({
    required String currentText,
    required int? suggestionMgDl,
    required List<ExtractionConflict> conflicts,
  }) {
    if (suggestionMgDl == null) return currentText;

    final suggestionMmolL = suggestionMgDl / 18.0;
    final formattedSuggestion = suggestionMmolL
        .toStringAsFixed(2)
        .replaceFirst(RegExp(r'0+$'), '')
        .replaceFirst(RegExp(r'\.$'), '');
    if (currentText.trim().isEmpty) return formattedSuggestion;

    final manualMmolL = double.tryParse(currentText.trim());
    if (manualMmolL == null || (manualMmolL - suggestionMmolL).abs() > 0.01) {
      conflicts.add(
        ExtractionConflict(
          field: 'Glucose',
          manualValue: currentText,
          extractedValue: suggestionMgDl,
        ),
      );
    }

    return currentText;
  }
}

/// Deterministic, assistive extraction only. It does not diagnose symptoms or
/// interpret negation; caregivers must review suggestions before saving.
class TextStructuringService {
  static StructuredHealthData extract(String note) {
    final normalized = note.toLowerCase();
    final bloodPressure = _extractBloodPressure(normalized);

    return StructuredHealthData(
      glucose: _extractGlucose(normalized),
      systolicBp: bloodPressure?.$1,
      diastolicBp: bloodPressure?.$2,
      chestPain: _detectAny(normalized, const [
        'chest pain',
        'chest pressure',
        'chest discomfort',
        'বুকে ব্যথা',
        'বুক ব্যথা',
        'বুকে চাপ',
        'বুক চাপ',
      ]),
      dizziness: _detectAny(normalized, const [
        'dizziness',
        'dizzy',
        'মাথা ঘুর',
        'মাথা ঘোরা',
        'ঘুরছে',
      ]),
      shortnessOfBreath: _detectAny(normalized, const [
        'shortness of breath',
        'short of breath',
        'breathing problem',
        'difficulty breathing',
        'trouble breathing',
        'breathless',
        'শ্বাসকষ্ট',
        'শ্বাস কষ্ট',
        'শ্বাস নিতে কষ্ট',
      ]),
      excessiveThirst: _detectAny(normalized, const [
        'excessive thirst',
        'increased thirst',
        'very thirsty',
        'more thirst',
        'thirsty',
        'thirst',
        'বেশি পিপাসা',
        'অনেক পিপাসা',
        'পানি পিপাসা',
        'তৃষ্ণা',
      ]),
      fatigue: _detectAny(normalized, const [
        'fatigue',
        'weakness',
        'weak',
        'দুর্বল',
        'ক্লান্ত',
        'অবসাদ',
      ]),
      blurredVision: _detectAny(normalized, const [
        'blurred vision',
        'blurry vision',
        'blurred eyesight',
        'vision is blurry',
        'ঝাপসা',
        'চোখ ঝাপসা',
        'দেখতে সমস্যা',
      ]),
    );
  }

  static int? _extractGlucose(String text) {
    const keywords =
        r'(?:blood\s+sugar|sugar|suger|sugr|glucose|glukose|diabetes|diabetic|সুগার|গ্লুকোজ|ডায়াবেটিস|ডায়াবেটিস)';
    final afterKeyword = RegExp(
      '$keywords\\s*(?:is|was|level)?\\s*[:=]?\\s*(-?\\d+)',
      caseSensitive: false,
    ).firstMatch(text);
    if (afterKeyword != null) return int.tryParse(afterKeyword.group(1)!);

    final beforeKeyword = RegExp(
      r'(-?\d+)\s*(?:mg\s*/?\s*dl)?\s*' + keywords,
      caseSensitive: false,
    ).firstMatch(text);
    return beforeKeyword == null ? null : int.tryParse(beforeKeyword.group(1)!);
  }

  static (int, int)? _extractBloodPressure(String text) {
    final match = RegExp(
      r'(?:bp|b\.p\.?|blood pressure|pressure|presure|pressur|প্রেসার|রক্তচাপ)?\s*[:=]?\s*(-?\d+)\s*/\s*(-?\d+)',
      caseSensitive: false,
    ).firstMatch(text);
    if (match == null) return null;

    final systolic = int.tryParse(match.group(1)!);
    final diastolic = int.tryParse(match.group(2)!);
    if (systolic == null || diastolic == null) return null;
    return (systolic, diastolic);
  }

  static bool? _detectAny(String text, List<String> phrases) {
    return phrases.any(text.contains) ? true : null;
  }
}
