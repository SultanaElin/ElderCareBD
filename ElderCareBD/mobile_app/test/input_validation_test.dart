import 'package:eldercare_bd/models/caregiver_verification.dart';
import 'package:eldercare_bd/services/api_service.dart';
import 'package:eldercare_bd/services/text_structuring_service.dart';
import 'package:eldercare_bd/utils/input_validation.dart';
import 'package:flutter_test/flutter_test.dart';

AssessmentValidationResult _validateAssessment({
  String age = '72',
  String glucose = '9.17',
  String systolicBp = '145',
  String diastolicBp = '90',
  String height = '160',
  String weight = '64',
}) {
  return InputValidation.validateAssessment(
    ageText: age,
    glucoseText: glucose,
    systolicBpText: systolicBp,
    diastolicBpText: diastolicBp,
    heightText: height,
    weightText: weight,
  );
}

void main() {
  group('caregiver validation', () {
    test('rejects empty identifier and password separately', () {
      expect(
        InputValidation.validateCaregiverInputs(
          isRegistration: false,
          name: '',
          phoneOrEmail: '   ',
          password: 'secret',
        ),
        'Please enter a phone number or email.',
      );
      expect(
        InputValidation.validateCaregiverInputs(
          isRegistration: false,
          name: '',
          phoneOrEmail: 'caregiver@example.com',
          password: '   ',
        ),
        'Please enter a password.',
      );
    });

    test('registration requires a nonblank caregiver name', () {
      expect(
        InputValidation.validateCaregiverInputs(
          isRegistration: true,
          name: '   ',
          phoneOrEmail: 'caregiver@example.com',
          password: 'secret',
        ),
        'Please enter caregiver name.',
      );
    });

    test('registration validates the explicitly selected channel', () {
      expect(
        InputValidation.validateCaregiverInputs(
          isRegistration: true,
          name: 'Caregiver',
          phoneOrEmail: 'caregiver@example.com',
          password: 'secret',
          verificationChannel: CaregiverVerificationChannel.email,
        ),
        isNull,
      );
      expect(
        InputValidation.validateCaregiverInputs(
          isRegistration: true,
          name: 'Caregiver',
          phoneOrEmail: '+8801712345678',
          password: 'secret',
          verificationChannel: CaregiverVerificationChannel.sms,
        ),
        isNull,
      );
      expect(
        InputValidation.validateCaregiverInputs(
          isRegistration: true,
          name: 'Caregiver',
          phoneOrEmail: 'not-an-email',
          password: 'secret',
          verificationChannel: CaregiverVerificationChannel.email,
        ),
        'Please enter a valid email address.',
      );
      for (final phone in [
        '01712345678',
        '+0123456789',
        '+1234567',
        '+1234567890123456',
      ]) {
        expect(
          InputValidation.validateCaregiverInputs(
            isRegistration: true,
            name: 'Caregiver',
            phoneOrEmail: phone,
            password: 'secret',
            verificationChannel: CaregiverVerificationChannel.sms,
          ),
          'Enter a phone number in international format, such as +8801712345678.',
          reason: phone,
        );
      }
    });

    test('OTP is exactly six numeric digits and preserves leading zero', () {
      expect(InputValidation.validateOtp('042817'), isNull);
      for (final otp in ['42817', '0428170', '04a817', '  ']) {
        expect(
          InputValidation.validateOtp(otp),
          'Enter the complete six-digit verification code.',
          reason: otp,
        );
      }
    });
  });

  group('patient validation', () {
    test('rejects blank name', () {
      final result = InputValidation.validatePatient(
        nameText: '   ',
        ageText: '72',
        gender: 'Male',
      );

      expect(result.isValid, isFalse);
      expect(result.message, 'Please enter patient name.');
    });

    test('rejects nonnumeric and implausible ages', () {
      for (final age in ['abc', '0', '-1', '121']) {
        final result = InputValidation.validatePatient(
          nameText: 'Patient',
          ageText: age,
          gender: 'Female',
        );

        expect(result.isValid, isFalse, reason: 'age=$age');
      }
    });

    test('accepts current gender values and trims the name', () {
      final result = InputValidation.validatePatient(
        nameText: '  Patient Name  ',
        ageText: '72',
        gender: 'Other',
      );

      expect(result.isValid, isTrue);
      expect(result.values!.name, 'Patient Name');
      expect(result.values!.age, 72);
      expect(result.values!.gender, 'Other');
    });
  });

  group('assessment validation', () {
    test('converts whole feet and inches to centimetres', () {
      expect(InputValidation.tryConvertFeetAndInchesToCm('5', '7'), 170.18);
      expect(InputValidation.tryConvertFeetAndInchesToCm('5', '12'), isNull);
      expect(InputValidation.tryConvertFeetAndInchesToCm('', '7'), isNull);
    });

    test('rejects an empty required field', () {
      final result = _validateAssessment(age: '');

      expect(result.isValid, isFalse);
      expect(result.message, 'Please enter a valid age from 1 to 120.');
    });

    test('rejects nonnumeric input', () {
      final result = _validateAssessment(glucose: 'not-a-number');

      expect(result.isValid, isFalse);
      expect(
        result.message,
        'Please enter glucose in mmol/L from 0.1 to 55.5, such as 6.1 or 7.00.',
      );
    });

    test('rejects invalid ages', () {
      for (final age in ['0', '-1', '121']) {
        expect(_validateAssessment(age: age).isValid, isFalse, reason: age);
      }
    });

    test('rejects zero and negative height', () {
      for (final height in ['0', '-1']) {
        final result = _validateAssessment(height: height);

        expect(result.isValid, isFalse, reason: 'height=$height');
        expect(
          result.message,
          'Please enter a valid height from 30 to 300 cm.',
        );
      }
    });

    test('rejects zero and negative weight', () {
      for (final weight in ['0', '-1']) {
        final result = _validateAssessment(weight: weight);

        expect(result.isValid, isFalse, reason: 'weight=$weight');
        expect(result.message, 'Please enter a valid weight from 1 to 500 kg.');
      }
    });

    test('rejects negative measurements', () {
      expect(_validateAssessment(glucose: '-1').isValid, isFalse);
      expect(_validateAssessment(systolicBp: '-1').isValid, isFalse);
      expect(_validateAssessment(diastolicBp: '-1').isValid, isFalse);
    });

    test('rejects diastolic BP at or above systolic BP', () {
      final equal = _validateAssessment(systolicBp: '120', diastolicBp: '120');
      final reversed = _validateAssessment(
        systolicBp: '120',
        diastolicBp: '130',
      );

      expect(equal.isValid, isFalse);
      expect(reversed.isValid, isFalse);
      expect(equal.message, 'Diastolic BP must be lower than systolic BP.');
    });

    test('rejects nonfinite numeric input', () {
      expect(_validateAssessment(height: 'NaN').isValid, isFalse);
      expect(_validateAssessment(weight: 'Infinity').isValid, isFalse);
    });

    test('accepts an existing-style valid assessment', () {
      final result = _validateAssessment();

      expect(result.isValid, isTrue);
      expect(result.values!.age, 72);
      expect(result.values!.glucose, 165);
      expect(result.values!.bmi, 25.0);
    });

    test('accepts decimal mmol/L glucose and converts for the legacy API', () {
      expect(_validateAssessment(glucose: '6.1').values!.glucose, 110);
      expect(_validateAssessment(glucose: '7.00').values!.glucose, 126);
      expect(InputValidation.formatStoredGlucoseMmolL(110), '6.11 mmol/L');
      expect(InputValidation.formatStoredGlucoseMmolL(126), '7.00 mmol/L');
    });

    test('accepts broad valid boundaries without using risk thresholds', () {
      final result = _validateAssessment(
        age: '120',
        glucose: '55.5',
        systolicBp: '300',
        diastolicBp: '200',
        height: '200',
        weight: '500',
      );

      expect(result.isValid, isTrue);
      expect(result.values!.glucose, 999);
      expect(result.values!.bmi, 125.0);
    });
  });

  group('extracted measurement validation', () {
    test('rejects a long implausible glucose suggestion', () {
      const rawNote = 'Glucose 99999';
      final extraction = TextStructuringService.extract(rawNote);
      final validation = InputValidation.validateExtraction(extraction);

      expect(extraction.glucose, 99999);
      expect(validation.suggestions.glucose, isNull);
      expect(validation.rejectedMessages, hasLength(1));
      expect(validation.rejectedMessages.single, contains('was not applied'));
      expect(rawNote, 'Glucose 99999');
    });

    test(
      'preserves a manual value when an extracted suggestion is invalid',
      () {
        final extraction = TextStructuringService.extract('Glucose 99999');
        final validation = InputValidation.validateExtraction(extraction);
        final applied = validation.suggestions.applyPreservingManualValues(
          glucoseText: '150',
          systolicBpText: '',
          diastolicBpText: '',
          chestPain: false,
          dizziness: false,
          shortnessOfBreath: false,
          excessiveThirst: false,
          fatigue: false,
          blurredVision: false,
        );

        expect(applied.glucoseText, '150');
        expect(applied.conflicts, isEmpty);
      },
    );

    test('rejects an impossible extracted BP relationship as one pair', () {
      final extraction = TextStructuringService.extract('BP 90/145');
      final validation = InputValidation.validateExtraction(extraction);

      expect(validation.suggestions.systolicBp, isNull);
      expect(validation.suggestions.diastolicBp, isNull);
      expect(validation.rejectedMessages.single, contains('90/145'));
    });

    test('rejects negative extracted glucose and BP values', () {
      final glucose = InputValidation.validateExtraction(
        TextStructuringService.extract('Glucose -5'),
      );
      final systolic = InputValidation.validateExtraction(
        TextStructuringService.extract('BP -120/80'),
      );
      final diastolic = InputValidation.validateExtraction(
        TextStructuringService.extract('BP 120/-80'),
      );

      expect(glucose.suggestions.glucose, isNull);
      expect(systolic.suggestions.systolicBp, isNull);
      expect(systolic.suggestions.diastolicBp, isNull);
      expect(diastolic.suggestions.systolicBp, isNull);
      expect(diastolic.suggestions.diastolicBp, isNull);
    });
  });

  group('API response safety', () {
    test('normalizes empty and malformed response bodies', () {
      expect(
        ApiService.decodeResponseObject('')['detail'],
        'The server returned an empty response.',
      );
      expect(
        ApiService.decodeResponseObject('<html>error</html>')['detail'],
        'The server returned an invalid response.',
      );
      expect(
        ApiService.decodeResponseObject('[1, 2, 3]')['detail'],
        'The server returned an invalid response.',
      );
    });

    test('uses string backend detail but not malformed detail structures', () {
      expect(
        ApiService.errorMessage({
          'statusCode': 401,
          'body': {'detail': 'Invalid login credentials'},
        }, fallback: 'Login failed.'),
        'Invalid login credentials',
      );
      expect(
        ApiService.errorMessage({
          'statusCode': 422,
          'body': {'detail': <Object>[]},
        }, fallback: 'Please check the entered values.'),
        'Please check the entered values.',
      );
    });
  });
}
