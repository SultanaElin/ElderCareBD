import '../models/caregiver_verification.dart';
import '../services/text_structuring_service.dart';

class PatientInputValues {
  final String name;
  final int age;
  final String gender;

  const PatientInputValues({
    required this.name,
    required this.age,
    required this.gender,
  });
}

class PatientValidationResult {
  final PatientInputValues? values;
  final String? message;

  const PatientValidationResult._({this.values, this.message});

  const PatientValidationResult.valid(PatientInputValues values)
    : this._(values: values);

  const PatientValidationResult.invalid(String message)
    : this._(message: message);

  bool get isValid => values != null;
}

class AssessmentInputValues {
  final int age;
  final int glucose;
  final int systolicBp;
  final int diastolicBp;
  final double heightCm;
  final double weightKg;
  final double bmi;

  const AssessmentInputValues({
    required this.age,
    required this.glucose,
    required this.systolicBp,
    required this.diastolicBp,
    required this.heightCm,
    required this.weightKg,
    required this.bmi,
  });
}

class AssessmentValidationResult {
  final AssessmentInputValues? values;
  final String? message;

  const AssessmentValidationResult._({this.values, this.message});

  const AssessmentValidationResult.valid(AssessmentInputValues values)
    : this._(values: values);

  const AssessmentValidationResult.invalid(String message)
    : this._(message: message);

  bool get isValid => values != null;
}

class ExtractionValidationResult {
  final StructuredHealthData suggestions;
  final List<String> rejectedMessages;

  ExtractionValidationResult({
    required this.suggestions,
    required List<String> rejectedMessages,
  }) : rejectedMessages = List.unmodifiable(rejectedMessages);
}

/// Broad technical data-entry limits. These are deliberately separate from
/// prediction thresholds and are not diagnostic or treatment guidance.
class InputValidation {
  static const int minimumAge = 1;
  static const int maximumAge = 120;
  static const int minimumGlucose = 1;
  static const int maximumGlucose = 1000;
  static const double minimumGlucoseMmolL = 0.1;
  static const double maximumGlucoseMmolL = 55.5;
  static const double glucoseMgDlPerMmolL = 18.0;
  static const int minimumSystolicBp = 1;
  static const int maximumSystolicBp = 300;
  static const int minimumDiastolicBp = 1;
  static const int maximumDiastolicBp = 200;
  static const double minimumHeightCm = 30;
  static const double maximumHeightCm = 300;
  static const int minimumHeightFeet = 1;
  static const int maximumHeightFeet = 9;
  static const int minimumHeightInches = 0;
  static const int maximumHeightInches = 11;
  static const double minimumWeightKg = 1;
  static const double maximumWeightKg = 500;
  static const double minimumBmi = 1;
  static const double maximumBmi = 150;

  static const Set<String> supportedGenders = {'Male', 'Female', 'Other'};

  static String? validateCaregiverInputs({
    required bool isRegistration,
    required String name,
    required String phoneOrEmail,
    required String password,
    CaregiverVerificationChannel? verificationChannel,
  }) {
    if (phoneOrEmail.trim().isEmpty) {
      return 'Please enter a phone number or email.';
    }
    if (password.trim().isEmpty) {
      return 'Please enter a password.';
    }
    if (isRegistration && name.trim().isEmpty) {
      return 'Please enter caregiver name.';
    }
    if (isRegistration && verificationChannel == null) {
      return 'Please choose email or SMS verification.';
    }
    if (isRegistration &&
        verificationChannel == CaregiverVerificationChannel.email &&
        !_isValidEmail(phoneOrEmail.trim())) {
      return 'Please enter a valid email address.';
    }
    if (isRegistration &&
        verificationChannel == CaregiverVerificationChannel.sms &&
        !_isValidE164Phone(phoneOrEmail.trim())) {
      return 'Enter a phone number in international format, such as +8801712345678.';
    }
    return null;
  }

  static String? validateOtp(String value) {
    if (!RegExp(r'^\d{6}$').hasMatch(value.trim())) {
      return 'Enter the complete six-digit verification code.';
    }
    return null;
  }

  static bool _isValidEmail(String value) {
    return RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(value);
  }

  static bool _isValidE164Phone(String value) {
    return RegExp(r'^\+[1-9]\d{7,14}$').hasMatch(value);
  }

  static PatientValidationResult validatePatient({
    required String nameText,
    required String ageText,
    required String gender,
  }) {
    final name = nameText.trim();
    if (name.isEmpty) {
      return const PatientValidationResult.invalid(
        'Please enter patient name.',
      );
    }

    final age = int.tryParse(ageText.trim());
    if (!isValidAge(age)) {
      return const PatientValidationResult.invalid(
        'Please enter a valid age from 1 to 120.',
      );
    }

    if (!supportedGenders.contains(gender)) {
      return const PatientValidationResult.invalid(
        'Please select a valid gender.',
      );
    }

    return PatientValidationResult.valid(
      PatientInputValues(name: name, age: age!, gender: gender),
    );
  }

  static AssessmentValidationResult validateAssessment({
    required String ageText,
    required String glucoseText,
    required String systolicBpText,
    required String diastolicBpText,
    required String heightText,
    required String weightText,
  }) {
    final age = int.tryParse(ageText.trim());
    if (!isValidAge(age)) {
      return const AssessmentValidationResult.invalid(
        'Please enter a valid age from 1 to 120.',
      );
    }

    final glucoseMmolL = double.tryParse(glucoseText.trim());
    if (!isValidGlucoseMmolL(glucoseMmolL)) {
      return const AssessmentValidationResult.invalid(
        'Please enter glucose in mmol/L from 0.1 to 55.5, such as 6.1 or 7.00.',
      );
    }
    final glucose = convertGlucoseMmolLToMgDl(glucoseMmolL!);

    final systolicBp = int.tryParse(systolicBpText.trim());
    if (!isValidSystolicBp(systolicBp)) {
      return const AssessmentValidationResult.invalid(
        'Please enter a valid systolic BP from 1 to 300.',
      );
    }

    final diastolicBp = int.tryParse(diastolicBpText.trim());
    if (!isValidDiastolicBp(diastolicBp)) {
      return const AssessmentValidationResult.invalid(
        'Please enter a valid diastolic BP from 1 to 200.',
      );
    }

    if (diastolicBp! >= systolicBp!) {
      return const AssessmentValidationResult.invalid(
        'Diastolic BP must be lower than systolic BP.',
      );
    }

    final heightCm = double.tryParse(heightText.trim());
    if (!isValidHeight(heightCm)) {
      return const AssessmentValidationResult.invalid(
        'Please enter a valid height from 30 to 300 cm.',
      );
    }

    final weightKg = double.tryParse(weightText.trim());
    if (!isValidWeight(weightKg)) {
      return const AssessmentValidationResult.invalid(
        'Please enter a valid weight from 1 to 500 kg.',
      );
    }

    final bmi = _calculateBmi(heightCm!, weightKg!);
    if (!isValidBmi(bmi)) {
      return const AssessmentValidationResult.invalid(
        'Height and weight produce an invalid BMI. Please check both values.',
      );
    }

    return AssessmentValidationResult.valid(
      AssessmentInputValues(
        age: age!,
        glucose: glucose,
        systolicBp: systolicBp,
        diastolicBp: diastolicBp,
        heightCm: heightCm,
        weightKg: weightKg,
        bmi: double.parse(bmi.toStringAsFixed(1)),
      ),
    );
  }

  static double? tryCalculateBmi(String heightText, String weightText) {
    final heightCm = double.tryParse(heightText.trim());
    final weightKg = double.tryParse(weightText.trim());
    if (!isValidHeight(heightCm) || !isValidWeight(weightKg)) return null;

    final bmi = _calculateBmi(heightCm!, weightKg!);
    if (!isValidBmi(bmi)) return null;
    return double.parse(bmi.toStringAsFixed(1));
  }

  static double? tryConvertFeetAndInchesToCm(
    String feetText,
    String inchesText,
  ) {
    final feet = int.tryParse(feetText.trim());
    final inches = int.tryParse(inchesText.trim());
    if (feet == null ||
        feet < minimumHeightFeet ||
        feet > maximumHeightFeet ||
        inches == null ||
        inches < minimumHeightInches ||
        inches > maximumHeightInches) {
      return null;
    }

    final heightCm = ((feet * 12) + inches) * 2.54;
    if (!isValidHeight(heightCm)) return null;
    return double.parse(heightCm.toStringAsFixed(2));
  }

  static ExtractionValidationResult validateExtraction(
    StructuredHealthData extraction,
  ) {
    final rejectedMessages = <String>[];
    var glucose = extraction.glucose;
    var systolicBp = extraction.systolicBp;
    var diastolicBp = extraction.diastolicBp;

    if (glucose != null && !isValidGlucose(glucose)) {
      rejectedMessages.add(
        'Glucose suggestion $glucose was not applied. Enter a value from 1 to 1000.',
      );
      glucose = null;
    }

    if (systolicBp != null || diastolicBp != null) {
      final systolicValid = isValidSystolicBp(systolicBp);
      final diastolicValid = isValidDiastolicBp(diastolicBp);
      final relationshipValid =
          systolicBp != null && diastolicBp != null && diastolicBp < systolicBp;

      if (!systolicValid || !diastolicValid || !relationshipValid) {
        final display = '${systolicBp ?? '?'}/${diastolicBp ?? '?'}';
        rejectedMessages.add(
          'Blood pressure suggestion $display was not applied. Check both BP values.',
        );
        systolicBp = null;
        diastolicBp = null;
      }
    }

    return ExtractionValidationResult(
      suggestions: StructuredHealthData(
        glucose: glucose,
        systolicBp: systolicBp,
        diastolicBp: diastolicBp,
        chestPain: extraction.chestPain,
        dizziness: extraction.dizziness,
        shortnessOfBreath: extraction.shortnessOfBreath,
        excessiveThirst: extraction.excessiveThirst,
        fatigue: extraction.fatigue,
        blurredVision: extraction.blurredVision,
      ),
      rejectedMessages: rejectedMessages,
    );
  }

  static bool isValidAge(int? value) =>
      value != null && value >= minimumAge && value <= maximumAge;

  static bool isValidGlucose(int? value) =>
      value != null && value >= minimumGlucose && value <= maximumGlucose;

  static bool isValidGlucoseMmolL(double? value) =>
      value != null &&
      value.isFinite &&
      value >= minimumGlucoseMmolL &&
      value <= maximumGlucoseMmolL;

  /// Converts the caregiver-facing mmol/L value into the existing assessment
  /// contract's integer mg/dL value. This keeps the persisted API and legacy
  /// heuristic stable while allowing familiar local glucometer entry units.
  static int convertGlucoseMmolLToMgDl(double value) =>
      (value * glucoseMgDlPerMmolL).round();

  static double? convertGlucoseMgDlToMmolL(num? value) {
    if (value == null || !value.isFinite) return null;
    return value / glucoseMgDlPerMmolL;
  }

  static String formatStoredGlucoseMmolL(Object? rawValue) {
    final mgDl = rawValue is num
        ? rawValue
        : num.tryParse(rawValue?.toString() ?? '');
    final mmolL = convertGlucoseMgDlToMmolL(mgDl);
    return mmolL == null ? 'N/A' : '${mmolL.toStringAsFixed(2)} mmol/L';
  }

  static bool isValidSystolicBp(int? value) =>
      value != null && value >= minimumSystolicBp && value <= maximumSystolicBp;

  static bool isValidDiastolicBp(int? value) =>
      value != null &&
      value >= minimumDiastolicBp &&
      value <= maximumDiastolicBp;

  static bool isValidHeight(double? value) =>
      value != null &&
      value.isFinite &&
      value >= minimumHeightCm &&
      value <= maximumHeightCm;

  static bool isValidWeight(double? value) =>
      value != null &&
      value.isFinite &&
      value >= minimumWeightKg &&
      value <= maximumWeightKg;

  static bool isValidBmi(double value) =>
      value.isFinite && value >= minimumBmi && value <= maximumBmi;

  static double _calculateBmi(double heightCm, double weightKg) {
    final heightMeter = heightCm / 100;
    return weightKg / (heightMeter * heightMeter);
  }
}
